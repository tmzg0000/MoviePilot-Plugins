"""MoviePilot V2/V3 Tracker replacement; original plugin by honue, maintained by tmzg0000."""
from datetime import datetime, timedelta
from threading import Event, Lock
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

try:
    from app.sdk.plugin import _PluginBase
    from app.sdk.logging import logger
    from app.sdk.config import settings
    from app.sdk import scheduler as scheduler_sdk
    from app.schemas.types import MessageType as NotificationType
except ImportError:
    from app.plugins import _PluginBase
    from app.log import logger
    from app.core.config import settings
    from app.schemas import NotificationType
    scheduler_sdk = None

from .core import ConfigError, edit_torrent, open_client, parse_rules, torrent_list


class TrackerEditor(_PluginBase):
    """Replace matching Tracker URLs in one configured downloader."""

    plugin_name = "Tracker替换"
    plugin_desc = "批量替换 qBittorrent、Transmission 已有种子的 Tracker 文本。"
    plugin_icon = "https://raw.githubusercontent.com/tmzg0000/MoviePilot-Plugins/main/icons/trackereditor_A.png"
    plugin_version = "2.0.0"
    plugin_author = "tmzg0000"
    author_url = "https://github.com/tmzg0000/MoviePilot-Plugins"
    plugin_config_prefix = "trackereditor_"
    plugin_order = 30
    auth_level = 1

    def init_plugin(self, config=None):
        """Normalize historical config and queue a one-shot job through the host on V3."""
        if not hasattr(self, "_lock"):
            self._lock = Lock()
            self._stop = Event()
            self._scheduler = None
        self.stop_service()
        self._stop = Event()
        config = dict(config or {})
        self._config = {
            "onlyonce": False,
            "downloader_type": config.get("downloader_type") or "qbittorrent",
            "host": str(config.get("host") or "").strip(),
            "port": config.get("port", 8080),
            "username": str(config.get("username") or ""),
            "password": str(config.get("password") or ""),
            "tracker_config": str(config.get("tracker_config") or ""),
            # Upstream wrote run_cron* but read run_con*; accept both spellings.
            "run_con_enable": bool(config.get("run_con_enable", config.get("run_cron_enable", False))),
            "run_con": str(config.get("run_con", config.get("run_cron", "")) or "").strip(),
            "notify": bool(config.get("notify", True)),
        }
        if config.get("onlyonce"):
            self.update_config(self._config)
            self._queue_once()

    def _queue_once(self):
        """Avoid downloader network I/O on the configuration save request."""
        if scheduler_sdk is not None:
            if not scheduler_sdk.add_plugin_once_job(
                    "TrackerEditor", "trackereditor_once", self.task, "Tracker替换",
                    delay_seconds=3):
                self._finish({"status": "failed", "message": "宿主未能安排立即执行任务", "total": 0,
                              "updated": 0, "trackers": 0, "failed": 0})
            return
        from apscheduler.schedulers.background import BackgroundScheduler
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(self.task, trigger="date",
                                run_date=datetime.now(ZoneInfo(settings.TZ)) + timedelta(seconds=3),
                                misfire_grace_time=120)
        self._scheduler.start()

    def task(self):
        """Serialize scans and retain counts when one torrent fails partway through."""
        if not self._lock.acquire(blocking=False):
            logger.info("Tracker替换：已有任务运行，跳过本轮")
            return
        report = {"status": "success", "message": "替换完成", "total": 0,
                  "updated": 0, "trackers": 0, "failed": 0}
        client = None
        config = dict(self._config)
        stop = self._stop
        try:
            rules = parse_rules(config["tracker_config"])
            if not config["host"]:
                raise ConfigError("请填写下载器地址")
            if stop.is_set():
                report.update(status="stopped", message="任务已停止")
                return
            client = open_client(config)
            torrents = torrent_list(client, config["downloader_type"])
            report["total"] = len(torrents)
            for torrent in torrents:
                if stop.is_set():
                    report.update(status="stopped", message="任务已停止")
                    break
                changed = 0

                def record_change(count):
                    """Count only edits acknowledged by the downloader."""
                    nonlocal changed
                    changed += count
                    report["trackers"] += count

                try:
                    edit_torrent(client, config["downloader_type"], torrent, rules, record_change)
                except Exception:
                    # Exception strings can contain full Tracker URLs and passkeys.
                    report["failed"] += 1
                    logger.warning("Tracker替换：一个种子处理失败，请检查下载器状态与规则")
                if changed:
                    report["updated"] += 1
            if report["failed"] and report["status"] == "success":
                report.update(status="partial", message="部分种子处理失败，请检查下载器状态与规则")
        except ConfigError as error:
            report.update(status="failed", message=str(error))
        except Exception:
            report.update(status="failed", message="下载器连接或查询失败，请检查地址、认证和版本")
        finally:
            if client is not None:
                try:
                    client.__exit__(None, None, None)
                except Exception:
                    logger.warning("Tracker替换：关闭下载器会话失败")
            try:
                self._finish(report, notify=config["notify"])
            finally:
                self._lock.release()

    def _finish(self, report, notify=None):
        """Store and notify a summary without persisting Tracker URLs or passkeys."""
        report = dict(report, ran_at=datetime.now(ZoneInfo(settings.TZ)).strftime("%Y-%m-%d %H:%M:%S"))
        self.save_data("latest", report)
        text = (f"{report['message']}\n总种子数：{report['total']}\n已修改种子数：{report['updated']}"
                f"\n已修改 Tracker 数：{report['trackers']}\n失败种子数：{report['failed']}")
        logger.info(f"Tracker替换：{text}")
        if (self._config["notify"] if notify is None else notify):
            self.post_message(mtype=NotificationType.SiteMessage, title="Tracker替换", text=text)

    def get_state(self):
        """Report whether scheduled replacement is enabled."""
        return self._config["run_con_enable"]

    def get_service(self):
        """Register the schedule in MoviePilot's configured timezone."""
        if not self.get_state() or not self._config["run_con"]:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._config["run_con"], timezone=settings.TZ)
        except ValueError:
            logger.error("Tracker替换：Cron 表达式无效")
            return []
        return [{"id": "TrackerChangeRun", "name": "定时Tracker替换", "trigger": trigger,
                 "func": self.task, "kwargs": {}}]

    @staticmethod
    def get_command():
        """No remote commands are exposed."""
        return []

    def get_api(self):
        """No plugin API is exposed."""
        return []

    def get_form(self):
        """Keep the original connection fields and replacement syntax."""
        def field(component, model, label, **props):
            """Build one Vuetify field."""
            return {"component": component, "props": {"model": model, "label": label, **props}}

        def row(*fields):
            """Place related fields on the same row where space permits."""
            return {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 12 // len(fields)}, "content": [item]}
                for item in fields]}

        return [{"component": "VForm", "content": [
            row(field("VSwitch", "run_con_enable", "定时执行"),
                field("VSwitch", "onlyonce", "保存后立即运行一次"), field("VSwitch", "notify", "发送通知")),
            row(field("VCronField", "run_con", "执行周期"),
                field("VSelect", "downloader_type", "下载器类型", items=[
                    {"title": "qBittorrent", "value": "qbittorrent"},
                    {"title": "Transmission 4.0+", "value": "transmission"}])),
            row(field("VTextField", "host", "下载器地址", placeholder="http://192.168.2.100"),
                field("VTextField", "port", "下载器端口", type="number")),
            row(field("VTextField", "username", "用户名", autocomplete="off"),
                field("VTextField", "password", "密码", type="password", autocomplete="off")),
            row(field("VTextarea", "tracker_config", "Tracker 替换规则", rows=6,
                      placeholder="old.example.com|new.example.com",
                      hint="每行一条：旧文本|新文本。普通字符串替换，每个地址只应用第一条匹配规则。",
                      **{"persistent-hint": True})),
            {"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text":
                "扫描下载器中的所有种子。建议先用测试 Tracker 验证规则。"
                "仅修改匹配的 Tracker，保留其他地址及 Transmission 分组；不会修改下载器全局设置。"
                "原作者 honue，本仓库由 tmzg0000 维护。"}},
        ]}], dict(self._config)

    def get_page(self):
        """Display the most recent execution summary."""
        report = self.get_data("latest")
        if not report:
            return [{"component": "VAlert", "props": {"type": "info", "text": "暂无执行记录"}}]
        rows = [("执行时间", report["ran_at"]), ("结果", report["message"]),
                ("总种子数", report["total"]), ("已修改种子数", report["updated"]),
                ("已修改 Tracker 数", report["trackers"]), ("失败种子数", report["failed"])]
        return [{"component": "VTable", "content": [{"component": "tbody", "content": [
            {"component": "tr", "content": [{"component": "td", "text": str(value)} for value in row]}
            for row in rows]}]}]

    def stop_service(self):
        """Cancel pending one-shot work and stop a running scan between torrents."""
        self._stop.set()
        if scheduler_sdk is not None:
            scheduler_sdk.remove_plugin_once_job("TrackerEditor", "trackereditor_once")
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
