"""MoviePilot V2/V3 scheduled parking helper."""
from __future__ import annotations

from datetime import datetime
from threading import Event, Lock

from apscheduler.triggers.interval import IntervalTrigger
from app.plugins import _PluginBase
try:
    from app.db.oper.site import SiteOper
except ImportError:
    from app.db.site_oper import SiteOper
try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger

from .core import MAIN_HOSTS, ParkingClient, ParkingError, ParkingRunner, number, site_host


class QcwAutoPark(_PluginBase):
    plugin_name = "抢车位助手"
    plugin_desc = "复用 MP 主站认证，定时贴条、收车及按双重条件自动停车。"
    plugin_icon = "signin.png"
    plugin_version = "1.1.0"
    plugin_author = "tmzg0000"
    author_url = ""
    plugin_config_prefix = "qcwautopark_"
    plugin_order = 38
    auth_level = 2
    _lock = Lock()
    _enabled = False
    _site_id = ""
    _auto_ticket = True
    _ticket_threshold = 1000
    _request_interval = 10
    _interval_minutes = 5
    _threshold = 2000
    _max_level = 3
    _max_cash = 3000
    _run_once = False
    _invalid = False
    _stop = None

    def init_plugin(self, config=None):
        self.stop_service()
        self._stop = Event()
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._site_id = str(config.get("site_id") or "").strip()
        self._auto_ticket = bool(config.get("auto_ticket", True))
        self._invalid = False
        for name, default, minimum, maximum in (
            ("interval_minutes", 5, 1, 1440), ("threshold", 2000, 0, 1000000000),
            ("max_level", 3, 0, 1000000), ("max_cash", 3000, 0, 1000000000),
            ("ticket_threshold", 1000, 0, 1000000000), ("request_interval", 10, 10, 300),
        ):
            value = number(config.get(name, default))
            if value is None or value != int(value) or not minimum <= value <= maximum:
                self._invalid = True
                value = default
            setattr(self, "_" + name, int(value))
        if self._invalid:
            logger.error("抢车位助手：配置数值无效，请检查执行间隔、收益与筛选上限")
        self._run_once = bool(config.get("run_once", False))
        if self._run_once:
            self._run_once = False
            self.update_config(self._config())
            self.run_task()

    def _config(self):
        return {name: getattr(self, "_" + name) for name in (
            "enabled", "site_id", "interval_minutes", "threshold", "max_level", "max_cash", "run_once",
            "auto_ticket", "ticket_threshold", "request_interval")}

    @staticmethod
    def _sites():
        result = []
        for site in SiteOper().list_order_by_pri():
            try:
                host = site_host(getattr(site, "url", None) or getattr(site, "domain", None))
            except ValueError:
                continue
            if host in MAIN_HOSTS and getattr(site, "is_active", True):
                result.append(site)
        return result

    def _selected_site(self):
        sites = self._sites()
        if self._site_id:
            sites = [site for site in sites if str(site.id) == self._site_id]
        else:
            sites = [site for site in sites if getattr(site, "cookie", None)]
        if len(sites) != 1:
            raise ParkingError("请在插件中选择 MP 已配置 Cookie 的躺平 PT 主站")
        if not getattr(sites[0], "cookie", None):
            raise ParkingError("选中的 MP 主站没有 Cookie，请在站点管理中更新")
        return sites[0]

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
        return [{"id": "QcwAutoPark.Run", "name": "抢车位定时检查",
                 "trigger": IntervalTrigger(minutes=self._interval_minutes),
                 "func": self.run_task, "kwargs": {}}]

    def get_form(self):
        def field(model, label, **props):
            return {"component": "VTextField", "props": {"model": model, "label": label, **props}}
        options = [{"title": "自动匹配 MP 中的躺平主站", "value": ""}] + [
            {"title": site.name, "value": str(site.id)} for site in self._sites()]
        return [{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [
                    {"component": "VSwitch", "props": {"model": model, "label": label}}]}
                for model, label in (("enabled", "启用定时任务"), ("run_once", "保存后立即执行一次"), ("auto_ticket", "自己停车场自动贴条"))]},
            {"component": "VSelect", "props": {"model": "site_id", "label": "认证使用的 MP 主站",
                "items": options, "hint": "每轮读取站点管理中的最新 Cookie，经主站 parking.php 登录游戏，无需手填游戏 Cookie。",
                "persistent-hint": True}},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "interval_minutes", "检查间隔（分钟）", type="number", min=1, max=1440)]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "threshold", "收车收益阈值（严格大于）", type="number", min=0)]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "max_level", "停车场主人等级上限（≤）", type="number", min=0)]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "max_cash", "停车场主人金币上限（≤）", type="number", min=0)]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "ticket_threshold", "贴条预估收益阈值（≥）", type="number", min=0)]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field(
                    "request_interval", "请求间隔（秒，至少10）", type="number", min=10, max=300)]},
            ]},
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text":
                "默认每5分钟检查：自己私家车位上他人的车预估收益 ≥1000 且满足贴条时间后贴条；自己的车基础收益 >2000 后收车；空闲车仅停入主人等级 ≤3 且金币 ≤3000 的私家车位。所有 HTTP 请求完成后至少等待10秒再发送下一次；任务不重叠。"}},
        ]}], self._config()

    def run_task(self):
        if not self._lock.acquire(blocking=False):
            logger.info("抢车位助手：上轮仍在运行，跳过本轮")
            return
        client = runner = None
        try:
            if self._invalid:
                raise ParkingError("配置数值无效，请修正后重新保存")
            stop = self._stop or Event()
            site = self._selected_site()
            client = ParkingClient(site.cookie, site_url=getattr(site, "url", None) or getattr(site, "domain", None),
                                   user_agent=getattr(site, "ua", None), stop=stop, request_interval=self._request_interval)
            client.authenticate()
            runner = ParkingRunner(client, threshold=self._threshold, max_level=self._max_level,
                                   max_cash=self._max_cash, stop=stop, ticket_threshold=self._ticket_threshold,
                                   auto_ticket=self._auto_ticket)
            result = runner.run()
            self._finish("成功", "本轮检查完成" if not result["idle"] else "部分车辆空闲，等待符合双重条件的私家车位", result)
        except ParkingError as error:
            self._finish("停止", str(error), runner.report if runner else {})
        except Exception:
            # No traceback or response bodies: request objects can contain credentials.
            self._finish("失败", "执行出现未预期错误，请检查接口数据与插件版本", runner.report if runner else {})
        finally:
            try:
                if client:
                    client.close()
            finally:
                self._lock.release()

    def _finish(self, status, message, report):
        record = {"time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "status": status,
                  "message": message, "collected": report.get("collected", 0),
                  "parked": report.get("parked", 0), "earned": report.get("earned", 0),
                  "ticketed": report.get("ticketed", 0),
                  "idle": report.get("idle") if report.get("idle") is not None else "未知"}
        history = self.get_data("history") or []
        self.save_data("history", [record] + history[:19])
        logger.info("抢车位助手：%s，贴条 %s 次，收车 %s 辆，停车 %s 辆，%s", status, record["ticketed"], record["collected"], record["parked"], message)

    def get_page(self):
        records = self.get_data("history") or []
        if not records:
            return [{"component": "VAlert", "props": {"type": "info", "text": "暂无执行记录，选择 MP 主站后可勾选立即执行一次。"}}]
        return [{"component": "VTable", "props": {"density": "compact"}, "content": [
            {"component": "thead", "content": [{"component": "tr", "content": [
                {"component": "th", "text": label} for label in ("时间", "状态", "贴条", "收车", "停车", "到账金币", "剩余空闲", "结果")]}]},
            {"component": "tbody", "content": [{"component": "tr", "content": [
                {"component": "td", "text": str(row.get(key, "-"))}
                for key in ("time", "status", "ticketed", "collected", "parked", "earned", "idle", "message")]} for row in records]},
        ]}]

    def stop_service(self):
        if self._stop:
            self._stop.set()
