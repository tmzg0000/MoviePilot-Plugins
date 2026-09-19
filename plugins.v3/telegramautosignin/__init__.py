"""MoviePilot Telegram automatic sign-in plugin."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from apscheduler.triggers.cron import CronTrigger
from app.core.config import settings
from app.plugins import _PluginBase
from app.schemas import NotificationType
try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger
from .core import moviepilot_proxy, parse_targets, submit_commands


class TelegramAutoSignIn(_PluginBase):
    plugin_name = "Telegram 自动签到"
    plugin_desc = "定时通过 Telegram 用户会话向指定机器人发送签到命令。"
    plugin_icon = "telegram.png"
    plugin_version = "1.0.0"
    plugin_author = "tmzg0000"
    author_url = ""
    plugin_config_prefix = "telegramautosignin_"
    plugin_order = 35
    auth_level = 2
    _enabled = False
    _notify = False
    _cron = "25 0,12,23 * *"
    _api_id = _api_hash = _session_string = _bot_config = ""
    _use_moviepilot_proxy = _run_once = False

    def init_plugin(self, config: Optional[dict] = None) -> None:
        config = config or {}
        self._enabled = bool(config.get("enabled", False))
        self._notify = bool(config.get("notify", False))
        self._cron = str(config.get("cron") or "25 0,12,23 * *")
        for key in ("api_id", "api_hash", "session_string", "bot_config"):
            setattr(self, "_" + key, str(config.get(key) or "").strip())
        self._use_moviepilot_proxy = bool(config.get("use_moviepilot_proxy", False))
        self._run_once = bool(config.get("run_once", False))
        if self._run_once:
            self._run_once = False
            self.update_config(self._config())
            self.run_checkin()

    def _config(self) -> Dict[str, Any]:
        return {"enabled": self._enabled, "notify": self._notify, "cron": self._cron,
                "api_id": self._api_id, "api_hash": self._api_hash,
                "session_string": self._session_string, "bot_config": self._bot_config,
                "use_moviepilot_proxy": self._use_moviepilot_proxy, "run_once": self._run_once}

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
            logger.error("Telegram 自动签到：Cron 表达式无效")
            return []
        return [{"id": "TelegramAutoSignIn.Run", "name": "Telegram 自动签到", "trigger": trigger, "func": self.run_checkin, "kwargs": {}}]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        field = lambda model, label, **props: {"component": "VTextField", "props": {"model": model, "label": label, **props}}
        return [{"component": "VForm", "content": [
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 3}, "content": [{"component": "VSwitch", "props": {"model": key, "label": label}}]}
                for key, label in (("enabled", "启用插件"), ("notify", "执行后发送通知"), ("use_moviepilot_proxy", "使用 MoviePilot 代理"), ("run_once", "保存后立即执行一次"))
            ]},
            {"component": "VRow", "content": [
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [{"component": "VCronField", "props": {"model": "cron", "label": "执行周期", "placeholder": "5 位 Cron；例如 25 0,12,23 * *"}}]},
                {"component": "VCol", "props": {"cols": 12, "md": 6}, "content": [field("api_id", "Telegram API ID", type="password")]},
            ]},
            field("api_hash", "Telegram API Hash", type="password"),
            {"component": "VTextarea", "props": {"model": "session_string", "label": "Telethon StringSession", "rows": 3}},
            {"component": "VTextarea", "props": {"model": "bot_config", "label": "机器人命令", "rows": 3, "hint": "格式：@bot1:/qd,@bot2:sign；省略命令时默认 /qd", "persistent-hint": True}},
        ]}], self._config()

    def get_page(self) -> List[dict]:
        records = self.get_data("latest") or []
        if not records:
            return [{"component": "VAlert", "props": {"type": "info", "variant": "tonal", "text": "暂无执行记录；保存配置后可使用“立即执行一次”。"}}]
        rows = [{"component": "tr", "content": [{"component": "td", "text": str(row.get(key) or "-")} for key in ("bot", "command", "status", "message", "ran_at")]} for row in records if isinstance(row, dict)]
        return [{"component": "VTable", "props": {"density": "compact"}, "content": [
            {"component": "thead", "content": [{"component": "tr", "content": [{"component": "th", "text": label} for label in ("机器人", "命令", "状态", "结果", "执行时间")]}]},
            {"component": "tbody", "content": rows},
        ]}]

    def run_checkin(self) -> None:
        try:
            api_id = int(self._api_id)
        except ValueError:
            self._finish([{"bot": "配置", "command": "", "status": "failed", "message": "Telegram API ID 无效"}]); return
        targets = parse_targets(self._bot_config)
        if not self._api_hash or not self._session_string or not targets:
            self._finish([{"bot": "配置", "command": "", "status": "failed", "message": "请填写 API Hash、StringSession 和至少一个机器人命令"}]); return
        try:
            proxy = moviepilot_proxy(settings.PROXY) if self._use_moviepilot_proxy else None
            result = asyncio.run(submit_commands(api_id=api_id, api_hash=self._api_hash, session_string=self._session_string, targets=targets, proxy=proxy))
            self._finish([item.as_dict() for item in result])
        except Exception:
            logger.exception("Telegram 自动签到：执行失败")
            self._finish([{"bot": "执行", "command": "", "status": "failed", "message": "执行出现未预期错误"}])

    def _finish(self, records: List[Dict[str, str]]) -> None:
        ran_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        records = [dict(row, ran_at=row.get("ran_at") or ran_at) for row in records]
        self.save_data("latest", records)
        for row in records:
            logger.info("Telegram 自动签到：%s %s（%s）", row.get("bot"), row.get("status"), row.get("message"))
        if self._notify:
            text = "\n".join("%s：%s - %s" % (row["bot"], row["status"], row["message"]) for row in records)
            self.post_message(mtype=NotificationType.SiteMessage, title="Telegram 自动签到", text=text)

    def stop_service(self) -> None:
        return None
