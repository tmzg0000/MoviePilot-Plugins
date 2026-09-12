"""MoviePilot V2/V3 entrypoint for Browserless-backed PT check-ins."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time
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

from .core import DEFAULT_BROWSERLESS_URL, BrowserlessSigner, SignResult, parse_rules, resolve_rule, target_url


class CaptchaSignIn(_PluginBase):
    plugin_name = "验证码站点签到"
    plugin_desc = "复用 MoviePilot 站点 Cookie，通过 Browserless 完成 PT 图片验证码与 Cloudflare 签到。"
    plugin_icon = "signin.png"
    plugin_version = "1.0.21"
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
    _retry_delay_minutes = 10
    _retry_count = 1
    _browserless_url = DEFAULT_BROWSERLESS_URL
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
        self._retry_delay_minutes = max(1, min(int(config.get("retry_delay_minutes") or 10), 1440))
        retry_count = config.get("retry_count")
        self._retry_count = max(0, min(int(1 if retry_count in (None, "") else retry_count), 5))
        self._browserless_url = str(config.get("browserless_url") or DEFAULT_BROWSERLESS_URL).strip()
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
                "retry_delay_minutes": self._retry_delay_minutes, "retry_count": self._retry_count,
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
        return [{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "enabled", "label": "启用插件"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "notify", "label": "签到后发送通知"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": "run_once", "label": "保存后立即执行一次"}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VCronField", "props": {"model": "cron", "label": "执行周期", "placeholder": "5 位 Cron；例如 15 8 * * *"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "concurrency", "label": "并发数", "type": "number", "min": 1, "max": 5, "hint": "同时处理 1–5 个站点，建议 2", "persistent-hint": True}}]},
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "retry_delay_minutes", "label": "失败后等待分钟数", "type": "number", "min": 1, "max": 1440, "hint": "仅失败站点重试前等待；默认 10 分钟", "persistent-hint": True}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "retry_count", "label": "失败后重试次数", "type": "number", "min": 0, "max": 5, "hint": "额外执行次数；0 为关闭，默认 1 次", "persistent-hint": True}}]},
            ]},
            {"component": "VSelect", "props": {"model": "site_ids", "label": "签到站点", "items": options, "multiple": True, "chips": True, "hint": "仅显示已在 MoviePilot 保存 Cookie 的站点", "persistent-hint": True}},
            {"component": "VDivider", "props": {"class": "my-4"}},
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact", "text": "Browserless Token 仅保存在 MoviePilot 插件配置中，签到记录、日志和通知均不会包含 Token、Cookie 或验证码内容。"}},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "browserless_url", "label": "Browserless 地址", "placeholder": DEFAULT_BROWSERLESS_URL, "hint": "可填写服务根地址或完整 /stealth/bql 地址", "persistent-hint": True}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VTextField", "props": {"model": "browserless_token", "label": "Browserless Token", "type": "password", "persistent-hint": True, "hint": "必填；不会写入日志"}}]},
            ]},
                {"component": "VTextarea", "props": {"model": "site_rules", "label": "自定义站点规则 JSON（可留空）", "rows": 10, "hint": "键使用域名或站点 ID；mode 为 image、trigger_image、cloudflare、open_page 或 altcha。内置 OpenCD、包子、LuckPT、OshenPT、YemaPT、HDSky 与 Cloudflare 站点规则。", "persistent-hint": True}},
        ]}], self._config()

    def get_page(self) -> List[dict]:
        records = self.get_data("latest") or []
        total = len(records)
        success = sum(row.get("status") in {"success", "already"} for row in records)
        failed = total - success
        if not records:
            return [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "暂无签到记录；保存配置后使用“立即执行一次”开始签到。", "prepend-icon": "mdi-information"}}]
        rows = []
        for row in records:
            meta = self._status_meta(str(row.get("status") or ""))
            site_name = str(row.get("site") or "未知站点")
            site_url = str(row.get("url") or "").strip()
            if site_url:
                try:
                    stored_rule = resolve_rule({"url": site_url, "id": row.get("site_id")}, parse_rules(self._site_rules))
                    site_url = target_url(site_url, str(stored_rule["path"]), stored_rule.get("route_fragment"))
                except ValueError:
                    pass
            result = "签到成功" if row.get("status") in {"success", "already"} else str(row.get("message") or "-")
            rows.append({"component": "tr", "content": [
                {"component": "td", "content": [{"component": "a", "props": {"href": site_url, "target": "_blank", "rel": "noopener noreferrer", "class": "text-primary text-decoration-none"}, "text": site_name}]} if site_url else {"component": "td", "text": site_name},
                {"component": "td", "content": [{"component": "VChip", "props": {"size": "x-small", "variant": "tonal", "color": meta["color"], "prepend-icon": meta["icon"]}, "text": meta["label"]}]},
                {"component": "td", "text": str(row.get("ran_at") or "-")},
                {"component": "td", "text": result},
            ]})
        return [
            {"component": "style", "text": ".captchasignin-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px}.captchasignin-stat{padding:12px}.captchasignin-stat__label{color:rgba(var(--v-theme-on-surface),.62);font-size:.78rem}.captchasignin-stat__value{margin-top:6px;font-size:1.35rem;font-weight:700}.captchasignin-table-wrap{overflow-x:auto;border:1px solid rgba(var(--v-theme-on-surface),.08);border-radius:8px}.captchasignin-table{min-width:760px}.captchasignin-table th,.captchasignin-table td{padding:8px!important}"},
            {"component": "div", "props": {"class": "captchasignin-summary"}, "content": [
                self._stat("本次站点", str(total), "已选择并完成处理", "info", "mdi-web"),
                self._stat("成功或已签到", f"{success}/{total}", "无需重复签到", "success", "mdi-check-circle"),
                self._stat("需要处理", str(failed), "请查看失败原因或更新 Cookie", "error" if failed else "success", "mdi-alert-circle-outline"),
            ]},
            {"component": "div", "props": {"class": "captchasignin-table-wrap mt-3"}, "content": [{"component": "VTable", "props": {"density": "compact", "hover": True, "class": "captchasignin-table"}, "content": [
                {"component": "thead", "content": [{"component": "tr", "content": [{"component": "th", "text": "站点"}, {"component": "th", "text": "状态"}, {"component": "th", "text": "最后运行时间"}, {"component": "th", "text": "结果"}]}]},
                {"component": "tbody", "content": rows},
            ]}]},
        ]

    @staticmethod
    def _status_meta(status: str) -> Dict[str, str]:
        if status == "success":
            return {"label": "签到成功", "color": "success", "icon": "mdi-check-circle"}
        if status == "already":
            return {"label": "签到成功", "color": "success", "icon": "mdi-check-circle"}
        return {"label": "签到失败", "color": "error", "icon": "mdi-alert-circle"}

    @staticmethod
    def _stat(label: str, value: str, hint: str, color: str, icon: str) -> Dict[str, Any]:
        return {"component": "div", "props": {"class": "captchasignin-stat app-card-shell app-card-colorful", "style": f"--app-card-accent-rgb: var(--v-theme-{color});"}, "content": [
            {"component": "div", "props": {"class": "captchasignin-stat__label"}, "text": label},
            {"component": "div", "props": {"class": f"captchasignin-stat__value text-{color}"}, "text": value},
            {"component": "div", "props": {"class": "text-caption text-medium-emphasis mt-1"}, "text": hint},
        ]}

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
        logger.info("验证码站点签到：开始处理 %s 个站点", len(selected))
        signer = BrowserlessSigner(self._browserless_url, self._browserless_token)
        results = self._run_sites(selected, rules, signer)
        result_by_site_id = {getattr(site, "id", None): result for site, result in zip(selected, results)}
        for attempt in range(1, self._retry_count + 1):
            failed_sites = [site for site in selected if result_by_site_id.get(getattr(site, "id", None), {}).get("status") == "failed"]
            if not failed_sites:
                break
            logger.info("验证码站点签到：%s 个失败站点将在 %s 分钟后重试（第 %s/%s 次）", len(failed_sites), self._retry_delay_minutes, attempt, self._retry_count)
            time.sleep(self._retry_delay_minutes * 60)
            for site, result in zip(failed_sites, self._run_sites(failed_sites, rules, signer)):
                result_by_site_id[getattr(site, "id", None)] = result
        results = [result_by_site_id[getattr(site, "id", None)] for site in selected]
        self._finish(results)

    def _run_sites(self, sites: List[Any], rules: Dict[str, Dict[str, Any]], signer: BrowserlessSigner) -> List[Dict[str, str]]:
        with ThreadPoolExecutor(max_workers=min(self._concurrency, len(sites))) as executor:
            return list(executor.map(lambda site: self._sign_one(site, rules, signer), sites))

    @staticmethod
    def _site_dict(site: Any) -> Dict[str, Any]:
        return {key: getattr(site, key, None) for key in ("id", "name", "url", "cookie", "ua", "proxy")}

    def _sign_one(self, site: Any, rules: Dict[str, Dict[str, Any]], signer: BrowserlessSigner) -> Dict[str, str]:
        info = self._site_dict(site)
        site_name = str(info.get("name") or info.get("url") or "未知站点")
        sign_url = str(info.get("url") or "")
        logger.info("验证码站点签到：开始 %s", site_name)
        try:
            rule = resolve_rule(info, rules)
            sign_url = target_url(sign_url, str(rule["path"]), rule.get("route_fragment"))
            outcome: SignResult = signer.sign(info, rule)
        except ValueError as error:
            outcome = SignResult("failed", str(error))
        except Exception:
            logger.exception("验证码站点签到失败：%s", info.get("name"))
            outcome = SignResult("failed", "签到执行出现未预期错误")
        logger.info("验证码站点签到：完成 %s（%s）", site_name, outcome.status)
        return {"site": site_name, "site_id": str(info.get("id") or ""), "url": sign_url, "status": outcome.status, "message": outcome.message,
                "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def _finish(self, results: List[Dict[str, str]]) -> None:
        ran_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results = [dict(item, ran_at=item.get("ran_at") or ran_at) for item in results]
        self.save_data("latest", results)
        self.save_data("history_" + datetime.now().strftime("%Y%m%d"), results)
        if self._notify:
            summary = "\n".join("%s：%s - %s" % (item["site"], item["status"], item["message"]) for item in results)
            self.post_message(mtype=NotificationType.SiteMessage, title="验证码站点签到", text=summary)

    def stop_service(self) -> None:
        return None
