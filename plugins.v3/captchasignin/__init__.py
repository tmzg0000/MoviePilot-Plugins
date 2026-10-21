"""MoviePilot V2/V3 entrypoint for HTTP/OCR-first PT check-ins."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import time
import re
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

from .core import DEFAULT_BROWSERLESS_URL, BrowserlessSigner, HttpSigner, HybridSigner, LocalBrowserSigner, SignResult, parse_rules, resolve_rule, site_state_key, target_url


class CaptchaSignIn(_PluginBase):
    plugin_name = "验证码站点签到"
    plugin_desc = "图片验证码优先 MP OCR，失败后 Browserless 兜底；农场仅直连签到。"
    plugin_icon = "signin.png"
    plugin_version = "2.0.2"
    plugin_author = "tmzg0000"
    author_url = ""
    plugin_config_prefix = "captchasignin_"
    plugin_order = 30
    auth_level = 2
    token_group_slots = 5

    _enabled = False
    _notify = True
    _cron = "15 8 * * *"
    _site_ids: List[int] = []
    _browserless_tokens = ""
    _site_options: Dict[str, Any] = {}
    _concurrency = 2
    _retry_delay_minutes = 10
    _retry_count = 1
    _browserless_url = DEFAULT_BROWSERLESS_URL
    _site_tokens: Dict[int, str] = {}
    _site_rules = ""
    _run_once = False

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._notify = bool(config.get("notify", True))
        self._cron = str(config.get("cron") or "15 8 * * *")
        groups = []
        if config.get("config_layout") == "site" or "browserless_tokens" in config:
            self._site_ids = self._ids(config.get("site_ids", []))
            self._browserless_tokens = str(config.get("browserless_tokens") or "")
        else:
            groups = self._load_token_groups(config)
            self._site_ids = self._ids(list(config.get("direct_site_ids") or []) +
                                       [site_id for group in groups for site_id in group["site_ids"]])
            self._browserless_tokens = "\n".join(dict.fromkeys(group["token"] for group in groups if group["token"]))
        tokens = [line.strip() for line in self._browserless_tokens.splitlines() if line.strip()]
        self._browserless_tokens = "\n".join(tokens)
        self._site_options = {key: value for key, value in config.items()
                              if re.fullmatch(r"site_\d+_(mode|token|button_source|button_text|success_source|success_text)", key)}
        # Migrate old groups by the token value so their original assignment
        # survives compaction of empty slots and duplicate group tokens.
        for group in groups:
            number = tokens.index(group["token"]) + 1 if group["token"] in tokens else 0
            for site_id in group["site_ids"]:
                self._site_options.setdefault("site_%s_token" % site_id, number)
        self._site_tokens = {}
        for site_id in self._site_ids:
            raw = self._site_options.get("site_%s_token" % site_id, 0)
            number = int(raw) if str(raw).isdigit() else 0
            self._site_options["site_%s_token" % site_id] = number
            self._site_tokens[site_id] = tokens[number - 1] if 0 < number <= len(tokens) else ""
        self._concurrency = max(1, min(int(config.get("concurrency") or 2), 5))
        self._retry_delay_minutes = max(1, min(int(config.get("retry_delay_minutes") or 10), 1440))
        retry_count = config.get("retry_count")
        self._retry_count = max(0, min(int(1 if retry_count in (None, "") else retry_count), 5))
        self._browserless_url = str(config.get("browserless_url") or DEFAULT_BROWSERLESS_URL).strip()
        self._site_rules = str(config.get("site_rules") or "")
        self._run_once = bool(config.get("run_once", False))
        if self._run_once:
            self._run_once = False
            self.update_config(self._config())
            self.run_sign_in()

    @staticmethod
    def _ids(values: Any) -> List[int]:
        return list(dict.fromkeys(int(value) for value in (values or []) if str(value).isdigit()))

    def _config(self) -> Dict[str, Any]:
        return {"config_layout": "site", "config_version": self.plugin_version, "enabled": self._enabled, "notify": self._notify, "cron": self._cron,
                "site_ids": self._site_ids, "concurrency": self._concurrency,
                "retry_delay_minutes": self._retry_delay_minutes, "retry_count": self._retry_count,
                "browserless_url": self._browserless_url, "browserless_tokens": self._browserless_tokens,
                "site_rules": self._site_rules, "run_once": self._run_once, **self._site_options}

    @classmethod
    def _load_token_groups(cls, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Load fixed UI slots and transparently retain the pre-1.0.23 config."""
        groups = []
        has_slot_config = any(
            f"browserless_token_{index}" in config or f"site_ids_{index}" in config
            for index in range(1, cls.token_group_slots + 1)
        )
        if has_slot_config:
            for index in range(1, cls.token_group_slots + 1):
                token = str(config.get(f"browserless_token_{index}") or "").strip()
                site_ids = [int(value) for value in config.get(f"site_ids_{index}", []) if str(value).isdigit()]
                if token or site_ids:
                    groups.append({"token": token, "site_ids": site_ids})
        else:
            groups.append({
                "token": str(config.get("browserless_token") or "").strip(),
                "site_ids": [int(value) for value in config.get("site_ids", []) if str(value).isdigit()],
            })
        return groups

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
        sites = [site for site in SiteOper().list_order_by_pri() if getattr(site, "cookie", None)]
        options = [{"title": site.name, "value": site.id} for site in sites]
        defaults = self._config()
        try:
            rules = parse_rules(self._site_rules)
        except ValueError:
            rules = {}

        def field(component: str, model: str, label: str, **props: Any) -> dict:
            return {"component": component, "props": {"model": model, "label": label, **props}}

        def row(*fields: dict) -> dict:
            return {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 12 // len(fields)}, "content": [item]}
                for item in fields]}

        content = [
            row(field("VSwitch", "enabled", "启用插件"), field("VSwitch", "notify", "签到后发送通知"),
                field("VSwitch", "run_once", "保存后立即执行一次")),
            row(field("VCronField", "cron", "执行周期", placeholder="15 8 * * *"),
                field("VTextField", "concurrency", "并发数", type="number", min=1, max=5)),
            row(field("VTextField", "retry_delay_minutes", "失败后等待分钟数", type="number", min=1, max=1440),
                field("VTextField", "retry_count", "失败后重试次数", type="number", min=0, max=5,
                      hint="额外执行次数；0 为关闭", **{"persistent-hint": True})),
            row(field("VTextarea", "browserless_tokens", "Browserless Token（每行一个）", rows=3,
                      autocomplete="off", spellcheck=False, hint="明文显示，每行一个；在下方每个站点中单独选择 Token 编号。可留空；农场和本地浏览器模式不使用 Token。",
                      **{"persistent-hint": True})),
            {"component": "div", "props": {"class": "text-caption mb-4", "style": {"overflowWrap": "anywhere"}}, "content": [
                {"component": "a", "props": {"href": "https://www.browserless.io/signup/email?plan=free", "target": "_blank", "rel": "noopener noreferrer", "class": "font-weight-medium"},
                 "text": "注册 Browserless 账号【https://www.browserless.io/signup/email?plan=free】"},
                {"component": "span", "text": "，登录 "},
                {"component": "a", "props": {"href": "https://browserless.io/account/", "target": "_blank", "rel": "noopener noreferrer", "class": "font-weight-medium"},
                 "text": "账户控制台【https://browserless.io/account/】"},
                {"component": "span", "text": "，在 API Key 区域复制 Token 后填入。"},
            ]},
            row(field("VSelect", "site_ids", "签到站点", items=options, multiple=True, chips=True,
                      hint="选择后自动显示下方对应站点的设置；仅显示已保存 Cookie 的站点。", **{"persistent-hint": True})),
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "density": "compact",
             "text": "图片验证码优先使用 MP 系统 OCR，失败后 Browserless 兜底；天空支持专用 HTTP/OCR。农场仅直连；猪猪默认使用 MP 本地浏览器，不转交云端。按钮与成功确认选择默认时沿用内置或高级规则。"}},
            {"component": "VCardTitle", "text": "站点设置列表"},
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal",
             "show": "{{ !(site_ids || []).length }}", "text": "请先在上方选择签到站点。"}},
        ]
        mode_items = [
            {"title": "默认（内置规则）", "value": "default"},
            {"title": "点击确定", "value": "open_page"},
            {"title": "验证码", "value": "image"},
            {"title": "CF盾", "value": "cloudflare"},
            {"title": "弹窗验证码", "value": "trigger_image"},
            {"title": "Altcha 验证", "value": "altcha"},
            {"title": "农场直连", "value": "farm"},
            {"title": "本地浏览器", "value": "local_browser"},
        ]
        choice_items = [{"title": "默认", "value": "default"}, {"title": "自定义", "value": "custom"}]
        token_items = "{{ [{title: '不使用', value: 0}, ...(browserless_tokens || '').split(/\\r?\\n/).map(t => t.trim()).filter(Boolean).map((t, i) => ({title: 'Token ' + (i + 1), value: i + 1}))] }}"
        site_cards = []
        for site in sites:
            prefix = "site_%s_" % site.id
            try:
                rule = resolve_rule(self._site_dict(site), rules)
            except ValueError:
                rule = {"mode": "open_page"}
            farm = rule["mode"] == "farm"
            for suffix, value in {"mode": rule["mode"], "token": 0, "button_source": "default", "button_text": "",
                                  "success_source": "default", "success_text": ""}.items():
                defaults.setdefault(prefix + suffix, value)
            if farm:
                defaults[prefix + "mode"] = "farm"
                defaults[prefix + "token"] = 0
            compact = {"density": "compact", "variant": "outlined", "hide-details": True}
            main_row = {"component": "VRow", "props": {"dense": True, "align": "center"}, "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 2}, "content": [
                    {"component": "div", "props": {"class": "text-body-2 font-weight-medium text-truncate", "title": str(site.name)}, "text": str(site.name)}]},
                {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [
                    field("VSelect", prefix + "mode", "模式", items=mode_items, disabled=farm, **compact)]},
                {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [
                    field("VSelect", prefix + "token", "Token", items=token_items,
                          disabled="{{ ['farm', 'local_browser'].includes(%smode) }}" % prefix, **compact)]},
                {"component": "VCol", "props": {"cols": 6, "md": 2}, "content": [
                    field("VSelect", prefix + "button_source", "按钮文字", items=choice_items, disabled=farm, **compact)]},
                {"component": "VCol", "props": {"cols": 6, "md": 3}, "content": [
                    field("VSelect", prefix + "success_source", "成功文字确认", items=choice_items, **compact)]},
            ]}
            details = []
            if not farm:
                details.append({"component": "VRow", "props": {"dense": True, "show": "{{ %sbutton_source === 'custom' }}" % prefix},
                    "content": [{"component": "VCol", "props": {"cols": 12}, "content": [
                        field("VTextField", prefix + "button_text", "自定义按钮文字", placeholder="例如：立即签到", **compact)]}]})
            details.append({"component": "VRow", "props": {"dense": True, "show": "{{ %ssuccess_source === 'custom' }}" % prefix},
                "content": [{"component": "VCol", "props": {"cols": 12}, "content": [
                    field("VTextarea", prefix + "success_text", "自定义成功确认文字", rows=2, density="compact",
                          hint="每行一个，匹配任意一项即确认成功。", **{"persistent-hint": True})]}]})
            site_cards.append({"component": "div", "props": {"class": "py-2",
                            "style": "{{ ({order: (site_ids || []).map(String).indexOf('%s')}) }}" % site.id,
                            "show": "{{ (site_ids || []).map(String).includes('%s') }}" % site.id},
                            "content": [main_row, *details]})
        content.append({"component": "div", "props": {"style": {"display": "flex", "flexDirection": "column"}}, "content": site_cards})
        content.append({"component": "VExpansionPanels", "content": [
            {"component": "VExpansionPanel", "content": [
                {"component": "VExpansionPanelTitle", "text": "高级设置（可选）"},
                {"component": "VExpansionPanelText", "content": [
                    field("VTextField", "browserless_url", "Browserless 地址", placeholder=DEFAULT_BROWSERLESS_URL),
                    field("VTextarea", "site_rules", "自定义站点规则 JSON", rows=8,
                          hint="用于签到路径、验证码选择器等高级设置；上方每站点的自定义设置优先。", **{"persistent-hint": True})]},
            ]},
        ]})
        return [{"component": "VForm", "content": content}], defaults

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
        all_sites = {site.id: site for site in SiteOper().list_order_by_pri()}
        selected = [(all_sites[site_id], self._site_tokens.get(site_id, "")) for site_id in self._site_ids if site_id in all_sites]
        if not selected:
            self._finish([{"site": "配置", "status": "failed", "message": "未选择可用的 MoviePilot 站点"}])
            return
        today = datetime.now().strftime("%Y%m%d")
        daily_state = self.get_data("state_" + today) or {}
        daily_state = daily_state if isinstance(daily_state, dict) else {}
        if not daily_state:
            for result in self.get_data("history_" + today) or []:
                if not isinstance(result, dict):
                    continue
                state_key = str(result.get("state_key") or "id:" + str(result.get("site_id") or "").strip())
                if result.get("status") in {"success", "already"} and state_key not in {"", "id:"}:
                    daily_state[state_key] = result
        pending, results = [], []
        for site, token in selected:
            previous = daily_state.get(site_state_key(self._site_dict(site)))
            if isinstance(previous, dict) and previous.get("status") in {"success", "already"}:
                results.append(dict(previous, message="今日已成功签到，已跳过网络签到"))
            else:
                pending.append((site, token))
        if not pending:
            logger.info("验证码站点签到：%s 个站点今日已成功，跳过网络签到", len(results))
            self._finish(results)
            return
        try:
            rules = parse_rules(self._site_rules)
        except ValueError as error:
            self._finish(results + [{"site": "配置", "status": "failed", "message": str(error)}])
            return
        logger.info("验证码站点签到：%s 个站点今日已成功跳过，开始处理 %s 个站点", len(results), len(pending))
        attempted = self._run_sites(pending, rules)
        result_by_site_id = {getattr(site, "id", None): result for (site, _token), result in zip(pending, attempted)}
        for attempt in range(1, self._retry_count + 1):
            failed_sites = [assignment for assignment in pending if result_by_site_id.get(getattr(assignment[0], "id", None), {}).get("status") == "failed"]
            if not failed_sites:
                break
            logger.info("验证码站点签到：%s 个失败站点将在 %s 分钟后重试（第 %s/%s 次）", len(failed_sites), self._retry_delay_minutes, attempt, self._retry_count)
            time.sleep(self._retry_delay_minutes * 60)
            for (site, _token), result in zip(failed_sites, self._run_sites(failed_sites, rules)):
                result_by_site_id[getattr(site, "id", None)] = result
        results.extend(result_by_site_id[getattr(site, "id", None)] for site, _token in pending)
        self._finish(results)

    def _run_sites(self, sites: List[Tuple[Any, str]], rules: Dict[str, Dict[str, Any]]) -> List[Dict[str, str]]:
        with ThreadPoolExecutor(max_workers=min(self._concurrency, len(sites))) as executor:
            return list(executor.map(lambda item: self._sign_one(item[0], rules, self._make_signer(item[1])), sites))

    def _make_signer(self, token: str) -> HybridSigner:
        from app.core.config import settings
        direct = HttpSigner(self._recognize_captcha, proxies=getattr(settings, "PROXY", None))
        local = LocalBrowserSigner(proxies=getattr(settings, "PROXY", None))
        return HybridSigner(direct, lambda: BrowserlessSigner(self._browserless_url, token)
                            if token and self._browserless_url else None, local=local)

    @staticmethod
    def _recognize_captcha(image_b64: str) -> str:
        # Use the same endpoint and payload as MP OcrHelper. Read current settings
        # on every call so custom OCR_HOST changes take effect without reload.
        import requests
        from app.core.config import settings
        address = str(settings.OCR_HOST or "https://movie-pilot.org").rstrip("/")
        response = requests.post(address + "/captcha/base64", json={"base64_img": image_b64}, timeout=30)
        response.raise_for_status()
        return str(response.json().get("result") or "")

    @staticmethod
    def _site_dict(site: Any) -> Dict[str, Any]:
        return {key: getattr(site, key, None) for key in ("id", "name", "url", "cookie", "ua", "proxy")}

    def _sign_one(self, site: Any, rules: Dict[str, Dict[str, Any]], signer: HybridSigner) -> Dict[str, str]:
        info = self._site_dict(site)
        site_name = str(info.get("name") or info.get("url") or "未知站点")
        sign_url = str(info.get("url") or "")
        logger.info("验证码站点签到：开始 %s", site_name)
        try:
            rule = resolve_rule(info, rules, self._site_options)
            sign_url = target_url(sign_url, str(rule["path"]), rule.get("route_fragment"))
            outcome: SignResult = signer.sign(info, rule)
        except ValueError as error:
            outcome = SignResult("failed", str(error))
        except Exception:
            logger.error("验证码站点签到执行异常：%s", info.get("name"))
            outcome = SignResult("failed", "签到执行出现未预期错误")
        logger.info("验证码站点签到：完成 %s（%s）", site_name, outcome.status)
        return {"site": site_name, "site_id": str(info.get("id") or ""), "state_key": site_state_key(info), "url": sign_url, "status": outcome.status, "message": outcome.message,
                "ran_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

    def _finish(self, results: List[Dict[str, str]]) -> None:
        ran_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        results = [dict(item, ran_at=item.get("ran_at") or ran_at) for item in results]
        self.save_data("latest", results)
        today = datetime.now().strftime("%Y%m%d")
        self.save_data("history_" + today, results)
        daily_state = self.get_data("state_" + today) or {}
        daily_state = daily_state if isinstance(daily_state, dict) else {}
        for result in results:
            if not isinstance(result, dict):
                continue
            state_key = str(result.get("state_key") or "id:" + str(result.get("site_id") or "").strip())
            if result.get("status") in {"success", "already"} and state_key not in {"", "id:"}:
                daily_state[state_key] = result
        self.save_data("state_" + today, daily_state)
        if self._notify:
            summary = "\n".join("%s：%s - %s" % (item["site"], item["status"], item["message"]) for item in results)
            self.post_message(mtype=NotificationType.SiteMessage, title="验证码站点签到", text=summary)

    def stop_service(self) -> None:
        return None
