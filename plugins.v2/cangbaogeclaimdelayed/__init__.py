import threading
from datetime import datetime
from typing import Any, Dict, List, Tuple

import requests
import urllib3
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger  # 新增的 Interval 触发器
from urllib3.exceptions import InsecureRequestWarning

from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.scheduler import Scheduler
from app.schemas import NotificationType
from app.schemas.types import EventType

urllib3.disable_warnings(InsecureRequestWarning)


class CangbaoGeClaimDelayed(_PluginBase):
    plugin_name = "藏宝阁PT任务领取延时版"
    plugin_desc = "支持标准Cron或按固定间隔(如每3天)为藏宝阁PT领取任务，领取后推送消息通知。"
    plugin_icon = "signin.png"
    plugin_version = "1.1.0"
    plugin_author = "schalkiii"
    author_url = ""
    plugin_config_prefix = "cbgclaim_delayed_"
    plugin_order = 31
    auth_level = 1

    CLAIM_URL = "https://cangbao.ge/ajax.php"
    TASK_PAGE_URL = "https://cangbao.ge/task.php"
    SITE_DOMAIN = "cangbao.ge"

    _enabled = False
    _cookie = ""
    _exam_id = "11"
    _cron = "0 0 1 * *"
    _notify = True
    _run_once = False
    _lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        self.stop_service()
        config = config or {}
        site_cookie = self.__get_site_cookie()
        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._exam_id = (config.get("exam_id") or "11").strip()
        self._cron = (config.get("cron") or "0 0 1 * *").strip()
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))
        logger.info(
            f"{self.plugin_name}初始化完成：enabled={self._enabled}, "
            f"exam_id={self._exam_id}, cron={self._cron}, notify={self._notify}"
        )
        if self._run_once:
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "cookie": self._cookie,
                "exam_id": self._exam_id,
                "cron": self._cron,
                "notify": self._notify,
                "run_once": False
            })
            logger.info(f"收到{self.plugin_name}配置页立即运行请求，后台启动任务领取")
            threading.Thread(target=self.claim_task, daemon=True).start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/cbgclaim_delayed",
                "event": EventType.PluginAction,
                "desc": "执行藏宝阁PT任务领取延时版",
                "category": "站点",
                "data": {"action": "cangbaoge_claim_delayed"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.run_once_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行藏宝阁PT任务领取",
                "description": "按当前插件配置立即执行一次任务领取。"
            },
            {
                "path": "/get_cookie",
                "endpoint": self.get_cookie_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取藏宝阁PT站点Cookie",
                "description": "从站点管理中获取藏宝阁PT站点的Cookie。"
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
            
        schedule_str = str(self._cron).strip()
        trigger = None
        
        try:
            # 判断是否为自定义的 interval 格式 (例如 interval:d:3 或 interval:m:4320)
            if schedule_str.startswith("interval:"):
                parts = schedule_str.split(":")
                if len(parts) == 3:
                    unit = parts[1].lower()
                    val = int(parts[2])
                    if unit == 'd':
                        trigger = IntervalTrigger(days=val)
                    elif unit == 'h':
                        trigger = IntervalTrigger(hours=val)
                    elif unit == 'm':
                        trigger = IntervalTrigger(minutes=val)
                    elif unit == 's':
                        trigger = IntervalTrigger(seconds=val)
                    else:
                        raise ValueError(f"不支持的时间单位: {unit}")
                else:
                    raise ValueError("interval格式不正确，应为 interval:单位:数值")
            else:
                # 默认走标准 Cron 解析逻辑
                trigger = CronTrigger.from_crontab(schedule_str)
        except Exception as e:
            logger.warn(f"{self.plugin_name} 调度配置无效 [{schedule_str}]，定时服务未注册: {e}")
            return []

        return [
            {
                "id": "CangbaoGeClaimDelayed",
                "name": self.plugin_name,
                "trigger": trigger,
                "func": self.claim_task,
                "kwargs": {}
            }
        ]

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        site_cookie = self.__get_site_cookie()
        cookie_value = self._cookie or site_cookie or ""
        return [
            {
                "component": "VForm",
                "content": [
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "enabled", "label": "启用插件"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {"model": "notify", "label": "发送通知"}
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "run_once",
                                            "label": "立即运行一次",
                                            "hint": "保存配置后执行任务领取，并自动关闭"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "exam_id",
                                            "label": "任务ID (exam_id)",
                                            "placeholder": "11",
                                            "hint": "藏宝阁PT的任务ID，默认为11"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 4},
                                "content": [
                                    {
                                        "component": "VTextField",
                                        "props": {
                                            "model": "cron",
                                            "label": "执行周期",
                                            "placeholder": "支持Cron或间隔语法",
                                            "hint": "Cron: '0 0 1 * *' | 间隔: 'interval:d:3'(每3天) 或 'interval:m:4320'(每4320分)"
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VRow",
                        "content":
