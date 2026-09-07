"""MoviePilot V2/V3 entrypoint for Browserless-backed PT check-ins."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger
from app.plugins import _PluginBase

try:  # MoviePilot V3
    from app.db.oper.site import SiteOper
except ImportError:  # MoviePilot V2
    from app.db.site_oper import SiteOper

try:  # MoviePilot V3 stable logging facade
    from app.sdk.logging import logger
except ImportError:  # MoviePilot V2
    from app.log import logger

from app.schemas import NotificationType

from .core import BrowserlessSigner, SignResult, parse_rules, resolve_rule


class CaptchaSignIn(_PluginBase):
    plugin_name = "验证码站点签到"
    plugin_desc = "复用 MoviePilot 站点 Cookie，通过 Browserless 完成 PT 图片验证码与 Cloudflare 签到。"
    plugin_icon = "signin.png"
    plugin_version = "1.0.2"
    plugin_author = "tmzg0000"
    author_url = ""
    plugin_config_prefix = "captchasignin_"
    plugin_order = 30
    auth_level = 2

    _enabled = False
    _notify = True
    _cron = "15 8 * * *"
    _site_ids: List[int] = []
    _concurrency = 2
    _browserless_url = ""
    _browserless_token = ""
    _site_rules = ""
    _run_once = False

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._notify = bool(config.get("notify", True))
        self._cron = str(config.get("cron") or "15 8 * * *")
        self._site_ids = [int(value) for value in config.get("site_ids", []) if str(value).isdigit()]
        self._concurrency = max(1, min(int(config.get("concurrency") or 2), 5))
        self._browserless_url = str(config.get("browserless_url") or "").strip()
        self._browserless_token = str(config.get("browserless_token") or "").strip()
        self._site_rules = str(config.get("site_rules") or "")
        self._run_once = bool(config.get("run_once", False))
        if self._run_once:
            self._run_once = False
            self.update_config(self._config())
            self.run_sign_in()

    def _config(self) -> Dict[str, Any]:
        return {"enabled": self._enabled, "notify": self._notify, "cron": self._cron,
                "site_ids": self._site_ids, "concurrency": self._concurrency,
                "browserless_url": self._browserless_url, "browserless_token": self._browserless_token,
                "site_rules": self._site_rules, "run_once": self._run_once}

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return []

    def get_api(self) -> List[Dict[str, Any]]:
        return []

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.error("验证码站点签到：Cron 表达式无效")
            return []
        return [{"id": "CaptchaSignIn.Run", "name": "验证码站点签到", "trigger": trigger,
                 "func": self.run_sign_in, "kwargs": {}}]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        sites = SiteOper().list_order_by_pri()
        options = [{"title": site.name, "value": site.id} for site in sites if getattr(site, "cookie", None)]
        fields = [
            ("enabled", "VSwitch", "启用插件"), ("notify", "VSwitch", "签到后发送通知"),
            ("run_once", "VSwitch", "保存后立即执行一次"), ("cron", "VTextField", "Cron（5 位）"),
            ("concurrency", "VTextField", "并发数（1-5）"),
            ("browserless_url", "VTextField", "Browserless 地址"),
            ("browserless_token", "VTextField", "Browserless Token"),
        ]
        content = [{"component": "VSelect", "props": {"model": "site_ids", "label": "签到站点", "items": options, "multiple": True, "chips": True}}]
        for model, component, label in fields:
            props: Dict[str, Any] = {"model": model, "label": label}
            if model == "browserless_token":
                props.update({"type": "password", "persistent-hint": True, "hint": "仅保存在 MoviePilot 插件配置中，不写入日志"})
            content.append({"component": component, "props": props})
        content.append({"component": "VTextarea", "props": {"model": "site_rules", "label": "自定义站点规则 JSON（可留空）", "rows": 10,
            "hint": "键使用域名或站点 ID；mode 为 image/cloudflare/open_page。OpenCD、包子和三类 CF 站点已内置。"}})
        return [{"component": "VForm", "content": content}], self._config()

    def get_page(self) -> List[dict]:
        records = self.get_data("latest") or []
        return [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "最近一次签到结果"}},
                {"component": "VTable", "content": [{"component": "tbody", "content": [
                    {"component": "tr", "content": [{"component": "td", "text": str(row.get("site", ""))},
                    {"component": "td", "text": str(row.get("status", ""))}, {"component": "td", "text": str(row.get("message", ""))}]} for row in records]}]}]

    def run_sign_in(self) -> None:
        if not self._browserless_url or not self._browserless_token:
            self._finish([{"site": "配置", "status": "failed", "message": "未配置 Browserless 地址或 Token"}])
            return
        try:
            rules = parse_rules(self._site_rules)
        except ValueError as error:
            self._finish([{"site": "配置", "status": "failed", "message": str(error)}])
            return
        all_sites = {site.id: site for site in SiteOper().list_order_by_pri()}
        selected = [all_sites[site_id] for site_id in self._site_ids if site_id in all_sites]
        if not selected:
            self._finish([{"site": "配置", "status": "failed", "message": "未选择可用的 MoviePilot 站点"}])
            return
        signer = BrowserlessSigner(self._browserless_url, self._browserless_token)
        with ThreadPoolExecutor(max_workers=min(self._concurrency, len(selected))) as executor:
            results = list(executor.map(lambda site: self._sign_one(site, rules, signer), selected))
        self._finish(results)

    @staticmethod
    def _site_dict(site: Any) -> Dict[str, Any]:
        return {key: getattr(site, key, None) for key in ("id", "name", "url", "cookie", "ua", "proxy")}

    def _sign_one(self, site: Any, rules: Dict[str, Dict[str, Any]], signer: BrowserlessSigner) -> Dict[str, str]:
        info = self._site_dict(site)
        try:
            outcome: SignResult = signer.sign(info, resolve_rule(info, rules))
        except ValueError as error:
            outcome = SignResult("failed", str(error))
        except Exception:
            logger.exception("验证码站点签到失败：%s", info.get("name"))
            outcome = SignResult("failed", "签到执行出现未预期错误")
        return {"site": str(info.get("name") or info.get("url") or "未知站点"), "status": outcome.status, "message": outcome.message}

    def _finish(self, results: List[Dict[str, str]]) -> None:
        self.save_data("latest", results)
        self.save_data("history_" + datetime.now().strftime("%Y%m%d"), results)
        if self._notify:
            summary = "\n".join("%s：%s - %s" % (item["site"], item["status"], item["message"]) for item in results)
            self.post_message(mtype=NotificationType.SiteMessage, title="验证码站点签到", text=summary)

    def stop_service(self) -> None:
        return None
