"""M-Team 邮箱验证与每日会话访问。基于 qingyukb 馒头保活二开，GPL-3.0。"""
from __future__ import annotations

from threading import Lock
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

# 官方 V3 规范：优先用稳定 SDK；V2 环境回退到旧路径
try:  # MoviePilot V3
    from app.sdk.plugin import _PluginBase  # type: ignore[no-redef]
except ImportError:  # V2
    from app.plugins import _PluginBase

try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

try:
    from app.sdk.config import settings
except ImportError:
    from app.core.config import settings

try:  # 一次性任务交给宿主调度器（V3）
    from app.sdk import scheduler as scheduler_sdk
except ImportError:
    scheduler_sdk = None

try:
    from app.sdk.events import Event, EventType, eventmanager
except ImportError:
    from app.core.event import Event, eventmanager
    from app.schemas.types import EventType

from app.schemas.types import NotificationType

from .mteam import (DEFAULT_API_BASE, DEFAULT_SITE, activity_minutes_ago, fetch_profile,
                    format_activity, keepalive_login, last_activity, parse_datetime,
                    parse_profile)

HISTORY_LIMIT = 30
PAGE_STYLE = (
    ".mteam-page{background:rgb(var(--v-theme-surface));border-radius:14px;padding:14px 14px 6px;"
    "box-sizing:border-box;max-width:100%;overflow-wrap:anywhere}"
    ".mteam-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}"
    ".mteam-stat{display:flex;flex-direction:column;gap:2px;padding:8px 10px;border-radius:10px;"
    "border:1px solid rgba(var(--v-theme-on-surface),.10);background:rgba(var(--v-theme-on-surface),.03)}"
    ".mteam-stat-num{font-size:1.05rem;font-weight:700;line-height:1.2;"
    "font-variant-numeric:tabular-nums}"
    ".mteam-stat-label{font-size:.72rem;color:rgba(var(--v-theme-on-surface),.6)}"
    ".mteam-num-ok{color:#4caf50}.mteam-num-warn{color:#fb8c00}.mteam-num-grey{color:"
    "rgba(var(--v-theme-on-surface),.38)}"
    ".mteam-line{margin:10px 0 4px;font-size:.78rem;color:rgba(var(--v-theme-on-surface),.62)}"
    ".mteam-section{display:flex;align-items:center;gap:8px;margin:14px 0 8px;font-weight:600}"
    ".mteam-row{display:flex;flex-wrap:wrap;align-items:center;gap:2px 10px;width:100%;"
    "box-sizing:border-box;margin-bottom:8px;padding:9px 12px;border-radius:10px;"
    "border:1px solid rgba(var(--v-theme-on-surface),.10);background:rgba(var(--v-theme-on-surface),.025)}"
    ".mteam-row-head{display:flex;align-items:center;gap:8px;width:100%;min-width:0}"
    ".mteam-row-time{flex:1 1 auto;min-width:0;font-weight:600;font-size:.9rem;white-space:nowrap;"
    "overflow:hidden;text-overflow:ellipsis}"
    ".mteam-row-status{flex:0 0 auto}"
    ".mteam-row-msg{width:100%;font-size:.8rem;line-height:1.45;word-break:break-word;"
    "color:rgba(var(--v-theme-on-surface),.7)}"
)


class MtAliver(_PluginBase):
    plugin_name = "馒头保活助手"
    plugin_desc = "手动邮箱验证后保存浏览器会话，每日访问 M-Team，失效时提醒重新验证。"
    plugin_icon = "signin.png"
    plugin_version = "1.4.2"
    plugin_author = "tmzg0000（原作者 qingyukb）"
    author_url = "https://blog.qyus.cn"
    plugin_config_prefix = "mtaliver_"
    plugin_order = 30
    auth_level = 2

    _enabled = False
    _notify = True
    _run_once = False
    _cron = "35 1,9,21 * * *"
    _site_url = DEFAULT_SITE
    _username = ""
    _password = ""
    _email = ""
    _email_code = ""
    _request_email = False
    _run_lock = Lock()
    _api_key = ""
    _api_base = DEFAULT_API_BASE
    _ratio_warn = 1.0
    _verify_minutes = 10
    _interval_days = 1
    _api_verify = True
    _scheduler: Optional[BackgroundScheduler] = None

    def init_plugin(self, config: dict = None):
        self.stop_service()
        if config:
            self._enabled = bool(config.get("enabled"))
            self._notify = bool(config.get("notify", True))
            self._run_once = bool(config.get("run_once"))
            self._cron = str(config.get("cron") or "35 1,9,21 * * *").strip()
            self._site_url = str(config.get("site_url") or DEFAULT_SITE).strip().rstrip("/")
            self._username = str(config.get("username") or "").strip()
            self._password = str(config.get("password") or "")
            self._email = str(config.get("email") or "").strip()
            self._email_code = str(config.get("email_code") or "").strip()
            self._request_email = bool(config.get("request_email"))
            self._api_key = str(config.get("api_key") or "").strip()
            self._api_base = str(config.get("api_base") or DEFAULT_API_BASE).strip().rstrip("/")
            try:
                self._ratio_warn = float(config.get("ratio_warn") or 1.0)
            except (TypeError, ValueError):
                self._ratio_warn = 1.0
            try:
                self._verify_minutes = int(config.get("verify_minutes") or 10)
            except (TypeError, ValueError):
                self._verify_minutes = 10
            try:
                self._interval_days = max(1, int(config.get("interval_days") or 1))
            except (TypeError, ValueError):
                self._interval_days = 1
            self._api_verify = bool(config.get("api_verify", True))
        if self._run_once or self._request_email or self._email_code:
            self._run_once = False
            self._save_config()
            self._save_execution("queued", "任务已排队，等待提交邮箱验证码" if self._email_code else "任务已排队，等待浏览器执行")
            # 官方规范：一次性任务交给宿主调度器，不自建 BackgroundScheduler
            add_once = getattr(scheduler_sdk, "add_plugin_once_job", None) if scheduler_sdk else None
            if callable(add_once):
                try:
                    add_once(self.__class__.__name__, "mtaliver_once", self.keepalive,
                             "馒头保活助手（立即执行）", delay_seconds=3)
                except Exception:
                    self._save_execution("failed", "一次性任务登记失败，请重新保存后重试")
                    logger.error("馒头保活助手：登记一次性任务失败")
            else:
                # 老版本没有该接口时退回本地调度器
                scheduler = BackgroundScheduler(timezone=settings.TZ)
                scheduler.add_job(func=self.keepalive, trigger="date",
                                  run_date=datetime.now(ZoneInfo(str(settings.TZ))) + timedelta(seconds=3),
                                  misfire_grace_time=120, name="馒头保活助手（立即执行）")
                scheduler.start()
                self._scheduler = scheduler

    def _save_execution(self, status: str, message: str) -> None:
        self.save_data("execution", {"status": status, "message": message,
                                   "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")})

    def _save_config(self) -> None:
        self.update_config({
            "enabled": self._enabled, "notify": self._notify, "run_once": False,
            "cron": self._cron, "site_url": self._site_url, "username": self._username,
            "password": self._password, "email": self._email,
            "email_code": "", "request_email": False,
            "api_key": self._api_key, "api_base": self._api_base,
            "ratio_warn": self._ratio_warn, "verify_minutes": self._verify_minutes,
            "api_verify": self._api_verify,
            "interval_days": self._interval_days,
        })

    @staticmethod
    def site_apikey() -> str:
        """从 MoviePilot 站点管理里找 M-Team 的 API Key（站点里填过就不用再单独配）。"""
        try:
            from app.db.site_oper import SiteOper
        except Exception:
            try:
                from app.db.oper.site import SiteOper  # 兼容旧路径
            except Exception:
                return ""
        try:
            sites = SiteOper().list_order_by_pri()
        except Exception:
            return ""
        for site in sites or []:
            domain = str(getattr(site, "domain", "") or getattr(site, "url", "") or "").lower()
            if "m-team" not in domain:
                continue
            # 只认「令牌（API Key）」；站点管理里的 Authorization 是网页 JWT，不能当 API Key 用
            for attr in ("apikey", "api_key"):
                value = str(getattr(site, attr, "") or "").strip()
                if value:
                    return value
        return ""

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        """注册远程命令：/mtaliver_keepalive 立即保活一次。"""
        return [{
            "cmd": "/mtaliver_keepalive",
            "event": EventType.PluginAction,
            "desc": "立即执行一次馒头保活助手",
            "category": "插件命令",
            "data": {"action": "mtaliver_keepalive"},
        }]

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event) -> None:
        """处理插件命令事件（只认自己的 action）。"""
        payload = (getattr(event, "event_data", None) or {})
        if str(payload.get("action") or "") != "mtaliver_keepalive":
            return
        record = self.keepalive()
        logger.info("馒头保活助手：命令执行完成，%s", record.get("message", ""))

    def get_api(self) -> List[Dict[str, Any]]:
        return [{
            "path": "/keepalive",
            "endpoint": self.api_keepalive,
            "methods": ["GET"],
            "summary": "立即执行馒头保活助手",
            "description": "使用浏览器访问 M-Team，并返回账号统计",
        }]

    def api_keepalive(self) -> Dict[str, Any]:
        record = self.keepalive()
        return {"success": bool(record.get("ok")), "message": record.get("message", "")}

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.error("馒头保活助手：Cron 表达式无效：%s", self._cron)
            return []
        return [{"id": "MtAliver.Keepalive", "name": "馒头保活助手",
                 "trigger": trigger, "func": self.scheduled_keepalive, "kwargs": {}}]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        def field(kind: str, model: str, label: str, md: int = 6, **props: Any) -> Dict[str, Any]:
            return {"component": "VCol", "props": {"cols": 12, "md": md},
                    "content": [{"component": kind,
                                 "props": {"model": model, "label": label, **props}}]}

        def hint(kind: str, model: str, label: str, text: str, md: int = 6,
                 **props: Any) -> Dict[str, Any]:
            return field(kind, model, label, md, hint=text,
                         **{"persistent-hint": True, **props})

        def row(*cols: Dict[str, Any]) -> Dict[str, Any]:
            return {"component": "VRow", "content": list(cols)}

        return [{"component": "VForm", "content": [
            # 总开关
            row(field("VSwitch", "enabled", "启用插件", 4),
                hint("VSwitch", "notify", "发送通知", "每次结果都会推送，含分享率与魔力", 4),
                hint("VSwitch", "run_once", "保存后立即执行一次",
                     "保存后马上登录一次，提交验证码登录，或使用已保存会话访问", 4)),
            # 账号与二次验证
            row(hint("VTextField", "username", "M-Team 账号", "站点登录账号", 4),
                hint("VTextField", "password", "密码", "站点登录密码", 4,
                     type="password"),
                hint("VTextField", "email", "绑定邮箱",
                     "填写 M-Team 账号绑定的邮箱，用于发送验证码", 4)),
            row(hint("VSwitch", "request_email", "发送邮箱验证码",
                     "勾选并保存后发送一次；收到邮件后填写验证码，不要再次勾选", 6),
                hint("VTextField", "email_code", "邮箱验证码（一次性）",
                     "填写邮件中的 6 位数字并保存即可登录，提交后自动清空", 6,
                     type="password", autocomplete="off")),
            # 站点地址
            row(hint("VTextField", "site_url", "站点地址",
                     "默认 https://kp.m-team.cc，也可填 m-team.io 镜像", 6,
                     placeholder=DEFAULT_SITE),
                hint("VTextField", "api_base", "API 地址",
                     "读统计用，默认 https://api.m-team.cc", 6,
                     placeholder=DEFAULT_API_BASE)),
            # 执行策略
            row(hint("VTextField", "interval_days", "执行间隔（天）",
                     "按成功日期间隔执行，默认 1 天；每天访问一次", 4,
                     type="number", min=1, max=60),
                hint("VCronField", "cron", "检查时间",
                     "默认每天 01:35、09:35、21:35 检查是否需要保活", 4,
                     placeholder="35 1,9,21 * * *"),
                hint("VTextField", "ratio_warn", "分享率提醒阈值",
                     "低于该值时通知里带提醒，默认 1.0", 4,
                     type="number", min=0, step=0.1)),
            row(hint("VTextField", "api_key", "API Key（可选）",
                     "留空则读取 MoviePilot 站点管理的 API Key；用于核对最近动向和账号统计", 12,
                     type="password")),
            # 校验
            row(hint("VSwitch", "api_verify", "用「最近动向」校验登录",
                     "有 API Key 时要求最近动向变新；关掉则仅确认网页会话有效", 4),
                hint("VTextField", "verify_minutes", "校验窗口（分钟）",
                     "登录后站点「最近动向」必须在这个时间内刷新，默认 10 分钟", 4,
                     type="number", min=1, max=180),
                {"component": "VCol", "props": {"cols": 12, "md": 4}, "content": []}),
            row({"component": "VCol", "props": {"cols": 12}, "content": [{
                "component": "VAlert", "props": {"type": "warning", "variant": "tonal",
                                                 "density": "compact"},
                "text": "首次发送邮箱验证码 → 填码并保存 → 每日复用浏览器会话访问。会话失效需重新验证。"
                        "需 MoviePilot 本地 Playwright；会话访问是否满足站点保号规则，请核对最近动向与站点规则。"}]}),
        ]}], {
            "enabled": self._enabled, "notify": self._notify, "run_once": False,
            "cron": self._cron, "site_url": self._site_url, "username": self._username,
            "password": self._password, "email": self._email,
            "email_code": "", "request_email": False,
            "api_key": self._api_key, "api_base": self._api_base,
            "ratio_warn": self._ratio_warn, "verify_minutes": self._verify_minutes,
            "api_verify": self._api_verify, "interval_days": self._interval_days,
        }

    # ------------------------------------------------------------------ 保活
    def scheduled_keepalive(self) -> Dict[str, Any]:
        """定时入口：距上次成功保活不足「执行间隔（天）」就跳过。"""
        last = self.get_data("last_success") or {}
        if last.get("ok") and last.get("time"):
            try:
                done_at = datetime.strptime(str(last["time"]), "%Y-%m-%d %H:%M:%S")
                gap = (datetime.now().date() - done_at.date()).days
                if gap < self._interval_days:
                    logger.info("馒头保活助手：距上次成功 %.1f 天，未满 %s 天，本次跳过",
                                gap, self._interval_days)
                    return dict(last)
            except ValueError:
                pass
        return self.keepalive()

    def keepalive(self) -> Dict[str, Any]:
        if not self._run_lock.acquire(blocking=False):
            return {"ok": False, "message": "已有保活任务正在执行"}
        try:
            self._save_execution("running", "正在提交邮箱验证码，请稍后重新打开结果页" if self._email_code else "浏览器任务执行中，请稍后重新打开结果页")
            record = self._keepalive()
            self._save_execution("finished", record.get("message") or "执行完成")
            return record
        except Exception:
            # Record unexpected failures without logging credentials or browser arguments.
            record = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                      "ok": False, "message": "任务执行异常，请检查 MoviePilot 浏览器和存储服务后重试"}
            self.save_data("last", record)
            history = list(self.get_data("history") or [])
            self.save_data("history", [record] + history[:HISTORY_LIMIT - 1])
            self._save_execution("failed", record["message"])
            logger.error("馒头保活助手：任务执行异常")
            self._notify_result(record, {})
            return record
        finally:
            self._run_lock.release()

    def _keepalive(self) -> Dict[str, Any]:
        """执行邮箱验证或会话访问，读取统计并记录结果。"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        logger.info("馒头保活助手：开始浏览器会话访问")
        api_key = self._api_key or self.site_apikey()
        before_profile: Dict[str, Any] = {}
        if api_key:
            before_profile, _ = fetch_profile(api_key, self._api_base)
            before_profile = before_profile or {}
        email_code, request_email = self._email_code, self._request_email
        self._email_code, self._request_email = "", False
        self._save_config()
        outcome = keepalive_login(
            self._username, self._password, email=self._email, email_code=email_code,
            request_email=request_email, state=self.get_data("browser_state"),
            site_url=self._site_url, logger=logger)
        ok, message = bool(outcome.get("ok")), str(outcome.get("message") or "")
        if outcome.get("state"):
            self.save_data("browser_state", outcome["state"])
        logger.info("馒头保活助手：浏览器登录结果 - %s", message)
        profile: Dict[str, Any] = {}
        if api_key:
            logger.info("馒头保活助手：使用 API Key 读取账号统计")
        else:
            logger.info("馒头保活助手：站点管理里没有 m-team 的 API Key，跳过统计与最近动向校验")
        if not self._api_verify:
            logger.info("馒头保活助手：已关闭 API 校验，仅按浏览器结果判定")
        if api_key:
            profile, error = fetch_profile(api_key, self._api_base)
            if error:
                logger.warning("馒头保活助手：读取统计失败 - %s", error)
                profile = {}
        # 浏览器先确认身份，API 仅补充核对活动时间，不能覆盖浏览器失败。
        if ok and profile and self._api_verify:
            minutes = activity_minutes_ago(profile)
            moment, label = last_activity(profile)
            shown = format_activity(profile) if moment else "未读到"
            browser_message = message
            before_time = parse_datetime(str(before_profile.get("last_browse")
                                            or before_profile.get("last_login") or ""))
            after_time = moment
            changed = (before_time is None and after_time is not None) or (
                before_time is not None and after_time is not None and after_time > before_time)
            if minutes is None:
                ok = False
                message = f"{browser_message}；读不到最近动向，无法二次确认"
            elif changed and minutes <= self._verify_minutes:
                ok = True
                message = f"访问成功（{label} {shown}）"
            elif not changed:
                # 站点时间没变 = 这次并没有真的产生新访问（可能被自己的手动浏览掩盖）
                earlier = before_time.strftime("%Y-%m-%d %H:%M:%S") if before_time else "（未知）"
                ok = False
                message = (f"浏览器侧：{browser_message}｜站点侧：{label}没有变新"
                           f"（执行前 {earlier}，执行后 {shown}），判定本次活动时间未确认更新")
            else:
                ok = False
                message = (f"浏览器侧：{browser_message}｜站点侧：{label}变成了 {shown}，"
                           f"但距现在 {minutes:.0f} 分钟，超过 {self._verify_minutes} 分钟窗口")
        if ok and api_key and self._api_verify and not profile:
            ok = False
            message += "；账号统计读取失败，未能确认最近动向"
        record = {"time": now, "ok": ok, "message": message,
                  "pending": bool(outcome.get("email_sent")),
                  "ratio": (profile or {}).get("ratio", ""),
                  "bonus": (profile or {}).get("bonus", "")}
        history = list(self.get_data("history") or [])
        history.insert(0, record)
        self.save_data("history", history[:HISTORY_LIMIT])
        if profile:
            self.save_data("profile", dict(profile, updated=now))
        self.save_data("last", record)
        if ok:
            self.save_data("last_success", record)
            logger.info("馒头保活助手：%s", message)
        else:
            logger.warning("馒头保活助手失败：%s", message)
        self._notify_result(record, profile)
        return record

    def _notify_result(self, record: Dict[str, Any], profile: Dict[str, Any]) -> None:
        if not self._notify:
            return
        lines = [("等待邮箱验证" if record.get("pending") else "保活成功" if record.get("ok") else "保活失败") + f" · {record.get('time', '')[5:16]}"]
        if profile:
            detail = []
            if profile.get("last_browse") or profile.get("last_login"):
                detail.append(f"最近动向 {format_activity(profile)}")
            if profile.get("ratio"):
                detail.append(f"分享率 {profile['ratio']}")
            if profile.get("bonus"):
                detail.append(f"魔力 {profile['bonus']}")
            if profile.get("uploaded"):
                detail.append(f"上传 {profile['uploaded']}")
            if profile.get("downloaded"):
                detail.append(f"下载 {profile['downloaded']}")
            if detail:
                lines.append(" · ".join(detail))
            ratio = profile.get("ratio_value")
            if ratio is not None and ratio < self._ratio_warn:
                lines.append(f"⚠ 分享率低于 {self._ratio_warn}，注意保号")
        if not record.get("ok"):
            lines.append("原因：" + str(record.get("message") or "未知"))
        self.post_message(mtype=NotificationType.Plugin,
                          title="馒头保活助手", text="\n".join(lines))

    # ------------------------------------------------------------------ 页面
    def get_page(self) -> List[dict]:
        history = list(self.get_data("history") or [])
        profile = self.get_data("profile") or {}
        last = self.get_data("last") or {}
        execution = self.get_data("execution") or {}
        status_panel = []
        if execution.get("status") in ("queued", "running", "failed"):
            status_panel = [{"component": "VAlert", "props": {
                "type": "error" if execution.get("status") == "failed" else "info",
                "variant": "tonal", "text": str(execution.get("time") or "") + " · " + str(execution.get("message") or "")}}]
        if not history:
            return status_panel + [{"component": "VAlert", "props": {"type": "info", "variant": "tonal",
                     "text": "还没有保活记录；保存配置后点「保存后立即执行一次」，或等 Cron 触发。"}}]

        def stat(label: str, value: str, tone: str = "") -> Dict[str, Any]:
            tone = tone or ("ok" if value and value != "—" else "grey")
            return {"component": "div", "props": {"class": "mteam-stat"}, "content": [
                {"component": "div",
                 "props": {"class": f"mteam-stat-num mteam-num-{tone}"}, "text": value or "—"},
                {"component": "div", "props": {"class": "mteam-stat-label"}, "text": label}]}

        ratio = str(profile.get("ratio") or "")
        ratio_value = profile.get("ratio_value")
        ratio_tone = "ok"
        if isinstance(ratio_value, (int, float)) and ratio_value < self._ratio_warn:
            ratio_tone = "warn"
        body: List[dict] = [{
            "component": "div", "props": {"class": "mteam-stats"}, "content": [
                stat("分享率", ratio, ratio_tone),
                stat("魔力", str(profile.get("bonus") or "")),
                stat("上传", str(profile.get("uploaded") or "")),
                stat("下载", str(profile.get("downloaded") or "")),
            ]}]
        info = []
        if not self._api_key and not profile:
            info.append("未读到账号统计（站点管理里也没有 m-team 的 API Key）")
        if profile.get("username"):
            info.append(f"账号 {profile['username']}")
        if profile.get("last_browse") or profile.get("last_login"):
            info.append(f"最近动向 {format_activity(profile)}")
        if profile.get("last_login"):
            info.append(f"上次登录 {profile['last_login']}")
        if profile.get("updated"):
            info.append(f"统计更新 {str(profile['updated'])[5:16]}")
        if info:
            body.append({"component": "div", "props": {"class": "mteam-line"},
                         "text": " · ".join(info)})
        body.append({"component": "div", "props": {"class": "mteam-section"},
                     "content": [{
                         "component": "VChip",
                         "props": {"size": "small", "variant": "tonal", "color": "primary",
                                   "prepend-icon": "mdi-shield-check-outline"},
                         "text": f"保活记录（{len(history)}）"}]})
        rows = [{"component": "div", "props": {"class": "mteam-row"}, "content": [
            {"component": "div", "props": {"class": "mteam-row-head"}, "content": [
                {"component": "div", "props": {"class": "mteam-row-time"},
                 "text": str(item.get("time") or "")},
                {"component": "div", "props": {"class": "mteam-row-status"}, "content": [{
                    "component": "VChip",
                    "props": {"size": "x-small", "variant": "tonal",
                              "color": "success" if item.get("ok") else "error",
                              "prepend-icon": "mdi-check-circle" if item.get("ok")
                              else "mdi-alert-circle"},
                    "text": "待验证" if item.get("pending") else "成功" if item.get("ok") else "失败"}]}]},
            {"component": "div", "props": {"class": "mteam-row-msg"},
             "text": str(item.get("message") or "")},
        ]} for item in history[:10]]
        body.extend(rows)
        if last.get("time"):
            body.append({"component": "div", "props": {"class": "mteam-line"},
                         "text": f"最近一次：{last.get('time')} · "
                                 f"{'待验证' if last.get('pending') else '成功' if last.get('ok') else '失败'}"})
        return status_panel + [{"component": "style", "text": PAGE_STYLE},
                {"component": "div", "props": {"class": "mteam-page"}, "content": body}]

    def stop_service(self):
        scheduler = getattr(self, "_scheduler", None)
        if scheduler is not None:
            try:
                scheduler.remove_all_jobs()
                scheduler.shutdown(wait=False)
            except Exception:
                pass
            self._scheduler = None
