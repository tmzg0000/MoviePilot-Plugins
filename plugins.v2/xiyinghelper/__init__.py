"""栖影签到助手 / xiyinghelper, for MoviePilot V2 and V3."""
from datetime import datetime
from threading import Event, Lock
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
try:
    from app.sdk.plugin import _PluginBase
    from app.sdk.config import settings
    from app.sdk.logging import logger
except ImportError:
    from app.plugins import _PluginBase
    from app.core.config import settings
    from app.log import logger
try:
    from app.sdk._legacy.cookiecloud import CookieCloudHelper
except ImportError:
    from app.helper.cookiecloud import CookieCloudHelper
try:
    from app.schemas.types import MessageType as NotificationType
except ImportError:
    from app.schemas import NotificationType

from .core import HOST, MODES, SigninError, sign


class XiyingHelper(_PluginBase):
    plugin_name = "栖影签到助手"
    plugin_desc = "复用 MP CookieCloud，通过网页 HTTP 请求定时签到，无需浏览器或 OpenAPI。"
    plugin_icon = "signin.png"
    plugin_version = "1.0.2"
    plugin_author = "tmzg0000"
    author_url = "https://github.com/tmzg0000/MoviePilot-Plugins"
    plugin_config_prefix = "xiyinghelper_"
    plugin_order = 40
    auth_level = 2
    _lock = Lock()
    _stop = None
    _enabled = False
    _notify = False
    _proxy = True
    _mode = "normal"
    _cron = "10 0 * * *"
    _run_once = False
    _invalid = False
    _check_login = False

    def init_plugin(self, config=None):
        self.stop_service()
        self._stop = Event()
        config = config or {}
        for key, default in (("enabled", False), ("notify", False), ("proxy", True), ("run_once", False), ("check_login", False)):
            setattr(self, "_" + key, bool(config.get(key, default)))
        self._mode = str(config.get("mode", "normal"))
        self._cron = str(config.get("cron") or "10 0 * * *").strip()
        self._invalid = self._mode not in MODES
        try:
            CronTrigger.from_crontab(self._cron, timezone="Asia/Shanghai")
        except (ValueError, TypeError):
            self._invalid = True
        if self._invalid:
            logger.error("栖影签到助手：签到模式或 Cron 配置无效")
        if self._check_login or self._run_once:
            check_only = self._check_login
            self._run_once = self._check_login = False
            self.update_config(self._config())
            self.run_signin(check_only=check_only)

    def _config(self):
        return {key: getattr(self, "_" + key) for key in
                ("enabled", "notify", "proxy", "mode", "cron", "run_once", "check_login")}

    def get_state(self):
        return self._enabled and not self._invalid

    @staticmethod
    def get_command():
        return []

    def get_api(self):
        return []

    def get_service(self):
        if not self.get_state():
            return []
        return [{"id": "XiyingHelper.Signin", "name": self.plugin_name,
                 "trigger": CronTrigger.from_crontab(self._cron, timezone="Asia/Shanghai"),
                 "func": self.run_signin, "kwargs": {}}]

    def run_signin(self, check_only=False):
        if not self._lock.acquire(blocking=False):
            return
        try:
            if self._invalid:
                raise SigninError("签到模式或 Cron 配置无效")
            # Read current MP settings and decrypt with its built-in helper every run.
            # Do not persist cookies, CookieCloud keys, or helper error strings.
            cookies, _ = CookieCloudHelper().download()
            cookie = (cookies or {}).get(HOST) or (cookies or {}).get("." + HOST)
            if not isinstance(cookie, str) or not cookie.strip():
                raise SigninError("未从 MP CookieCloud 获取栖影 Cookie；请检查 MP 同步配置及浏览器是否同步 hdhaven.com")
            proxy = getattr(settings, "PROXY", None) if self._proxy else None
            today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
            attempted = self.get_data("attempt_day") == today

            def before_submit():
                self.save_data("attempt_day", today)

            self._finish(sign(cookie, self._mode, proxy, before_submit, attempted=attempted, stop=self._stop, check_only=check_only))
        except SigninError as error:
            self._finish({"status": "停止", "message": str(error)})
        except Exception:
            self._finish({"status": "失败", "message": "执行异常，请检查 CookieCloud、代理及站点连通性"})
        finally:
            self._lock.release()

    def _finish(self, result):
        record = dict(result, mode=MODES.get(self._mode, "无效模式"),
                      time=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"))
        history = self.get_data("history") or []
        self.save_data("history", [record] + history[:29])
        logger.info("栖影签到助手：%s，%s", record["status"], record["message"])
        if self._notify:
            self.post_message(mtype=NotificationType.SiteMessage, title=self.plugin_name,
                              text=f"{record['mode']}：{record['status']}\n{record['message']}")

    def get_form(self):
        return [{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSwitch", "props": {"model": key, "label": label}}]}
                for key, label in (("enabled", "启用定时签到"), ("proxy", "使用 MP 设置的代理"),
                                   ("notify", "发送执行通知"), ("run_once", "保存后立即执行一次"),
                                   ("check_login", "保存后仅检测登录（不签到）"))]},
            {"component": "VSelect", "props": {"model": "mode", "label": "签到方式",
                "items": [{"title": label, "value": key} for key, label in MODES.items()]}},
            {"component": "VCronField", "props": {"model": "cron", "label": "签到计划（北京时间）",
                "placeholder": "10 0 * * *"}},
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text":
                "自动读取 MP 已配置的 CookieCloud，无需重复填写密钥；请先在浏览器登录 hdhaven.com 并同步 Cookie。默认普通签到，每天北京时间 00:10 执行；代理默认使用 MP 全局设置，未配置时直连。直接发送网页签到请求，无需浏览器或 OpenAPI 凭证。"}},
            {"component": "VAlert", "props": {"type": "warning", "variant": "tonal", "text":
                "赌狗签到按站点规则可能扣除积分，请自行选择。两种方式每天只能领取一次。账户确认已签到才记为成功；提交结果不明时当天不重复提交。"}},
        ]}], self._config()

    def get_page(self):
        history = self.get_data("history") or []
        if not history:
            return [{"component": "VAlert", "props": {"type": "info", "text": "暂无签到记录"}}]
        return [{"component": "VTable", "props": {"density": "compact"}, "content": [
            {"component": "thead", "content": [{"component": "tr", "content": [
                {"component": "th", "text": text} for text in ("时间（北京）", "方式", "状态", "结果")]}]},
            {"component": "tbody", "content": [{"component": "tr", "content": [
                {"component": "td", "text": str(row.get(key, "-"))}
                for key in ("time", "mode", "status", "message")]} for row in history]},
        ]}]

    def stop_service(self):
        if self._stop:
            self._stop.set()
