import json
import re
import threading
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

import requests
import urllib3
from apscheduler.triggers.cron import CronTrigger
from urllib3.exceptions import InsecureRequestWarning

from app.core.event import Event, eventmanager
from app.db.site_oper import SiteOper
from app.log import logger
from app.plugins import _PluginBase
from app.schemas import NotificationType
from app.schemas.types import EventType

urllib3.disable_warnings(InsecureRequestWarning)


class TangptLottery(_PluginBase):
    plugin_name = "躺平自动抽奖助手"
    plugin_desc = "躺平站点自动抽奖+老虎机，支持定时抽奖、中奖通知、期望值分析、获取站点Cookie等功能。"
    plugin_icon = "Moviepilot_A.png"
    plugin_version = "1.5.1"
    plugin_author = "schalkiii"
    author_url = ""
    plugin_config_prefix = "tangptlottery_"
    plugin_order = 30
    auth_level = 1

    DRAW_URL = "https://www.tangpt.top/web/omnibot/lottery/draw"
    LOTTERY_PAGE_URL = "https://www.tangpt.top/omnibot_lottery.php"
    SLOT_DRAW_URL = "https://www.tangpt.top/web/omnibot/slot-machine/draw"
    SLOT_PAGE_URL = "https://www.tangpt.top/omnibot_slot.php"
    SITE_DOMAIN = "www.tangpt.top"
    MAX_HISTORY = 30
    ALLOWED_BATCH_SIZES = [100, 50, 20, 10, 1]

    _enabled = False
    _cookie = ""
    _draw_count = 100
    _target_count = 1000
    _cron = "10 2 * * *"
    _notify = True
    _run_once = False
    _slot_enabled = False
    _slot_max_spins = 100
    _slot_ev_only = True
    _skip_vip_stop = False
    _lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        config = config or {}
        site_cookie = self.__get_site_cookie()
        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._draw_count = self.__safe_int(config.get("draw_count"), 100, min_value=1)
        if self._draw_count not in self.ALLOWED_BATCH_SIZES:
            self._draw_count = min(self.ALLOWED_BATCH_SIZES, key=lambda s: abs(s - self._draw_count))
        self._target_count = self.__safe_int(config.get("target_count"), 1000, min_value=1)
        self._cron = (config.get("cron") or "10 2 * * *").strip()
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))
        self._slot_enabled = bool(config.get("slot_enabled", False))
        self._slot_max_spins = self.__safe_int(config.get("slot_max_spins"), 100, min_value=1)
        self._slot_ev_only = bool(config.get("slot_ev_only", True))
        self._skip_vip_stop = bool(config.get("skip_vip_stop", False))
        logger.info(
            f"躺平自动抽奖助手初始化完成：enabled={self._enabled}, "
            f"draw_count={self._draw_count}, target_count={self._target_count}, "
            f"cron={self._cron}, notify={self._notify}, "
            f"slot_enabled={self._slot_enabled}, slot_max={self._slot_max_spins}"
        )
        if self._run_once:
            self._run_once = False
            self.update_config({
                "enabled": self._enabled,
                "cookie": self._cookie,
                "draw_count": self._draw_count,
                "target_count": self._target_count,
                "cron": self._cron,
                "notify": self._notify,
                "slot_enabled": self._slot_enabled,
                "slot_max_spins": self._slot_max_spins,
                "slot_ev_only": self._slot_ev_only,
                "skip_vip_stop": self._skip_vip_stop,
                "run_once": False
            })
            logger.info("收到配置页立即运行请求，后台启动抽奖+老虎机任务")
            threading.Thread(target=self.run_all_tasks, daemon=True).start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/tpcj",
                "event": EventType.PluginAction,
                "desc": "执行躺平抽奖，可指定次数 /tpcj 10",
                "category": "抽奖",
                "data": {"action": "tangpt_lottery"}
            },
            {
                "cmd": "/tplhj",
                "event": EventType.PluginAction,
                "desc": "执行老虎机抽奖",
                "category": "抽奖",
                "data": {"action": "tangpt_slot"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.run_once_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行躺平抽奖",
                "description": "按当前插件配置立即执行一次躺平抽奖任务。"
            },
            {
                "path": "/get_cookie",
                "endpoint": self.get_cookie_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取躺平站点Cookie",
                "description": "从站点管理中获取躺平站点的Cookie。"
            },
            {
                "path": "/run_slot",
                "endpoint": self.run_slot_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行老虎机抽奖",
                "description": "按当前插件配置立即执行一次老虎机抽奖任务。"
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.warn("躺平自动抽奖助手 Cron 配置无效，定时服务未注册")
            return []
        return [
            {
                "id": "TangptLottery",
                "name": "躺平自动抽奖+老虎机",
                "trigger": trigger,
                "func": self.run_all_tasks,
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
                                            "hint": "保存配置后执行抽奖和老虎机，并自动关闭"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {"cols": 12, "md": 3},
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "primary",
                                            "variant": "tonal",
                                            "text": "立即执行一次"
                                        },
                                        "events": {
                                            "click": {
                                                "api": "plugin/TangptLottery/run",
                                                "method": "post"
                                            }
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VCard",
                                        "props": {"variant": "outlined", "class": "pa-3"},
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {"class": "text-subtitle-1"},
                                                "text": "抽奖设置"
                                            },
                                            {
                                                "component": "VCardText",
                                                "content": [
                                                    {
                                                        "component": "VRow",
                                                        "content": [
                                                            {
                                                                "component": "VCol",
                                                                "props": {"cols": 12, "md": 4},
                                                                "content": [
                                                                    {
                                                                "component": "VSelect",
                                                                "props": {
                                                                    "model": "draw_count",
                                                                    "label": "每批次抽奖数",
                                                                    "items": [
                                                                        {"title": "单抽 (1次)", "value": 1},
                                                                        {"title": "十连抽 (10次)", "value": 10},
                                                                        {"title": "二十连 (20次)", "value": 20},
                                                                        {"title": "五十连 (50次)", "value": 50},
                                                                        {"title": "一百连 (100次)", "value": 100}
                                                                    ],
                                                                    "hint": "站点支持的抽奖批次大小"
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
                                                                            "model": "target_count",
                                                                            "label": "每日目标总次数",
                                                                            "type": "number",
                                                                            "min": 1,
                                                                            "hint": "每天总共抽奖次数"
                                                                        }
                                                                    }
                                                                ]
                                                            },
                                                            {
                                                                "component": "VCol",
                                                                "props": {"cols": 12, "md": 4},
                                                                "content": [
                                                                    {
                                                                        "component": "VCronField",
                                                                        "props": {
                                                                            "model": "cron",
                                                                            "label": "执行周期",
                                                                            "placeholder": "5位 Cron 表达式，例如 10 2 * * *"
                                                                        }
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VSwitch",
                                        "props": {
                                            "model": "skip_vip_stop",
                                            "label": "忽略VIP停止 (不推荐)",
                                            "hint": "抽中VIP后继续抽奖直至完成目标；开启后VIP正常计入但不断抽"
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
                                "props": {"cols": 12},
                                "content": [
                                    {
                                        "component": "VCard",
                                        "props": {"variant": "outlined", "class": "pa-3"},
                                        "content": [
                                            {
                                                "component": "VCardTitle",
                                                "props": {"class": "text-subtitle-1"},
                                                "text": "老虎机"
                                            },
                                            {
                                                "component": "VCardText",
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
                                                                        "props": {
                                                                            "model": "slot_enabled",
                                                                            "label": "启用老虎机",
                                                                            "hint": "开启后将在定时任务中执行老虎机抽奖"
                                                                        }
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
                                                                            "model": "slot_ev_only",
                                                                            "label": "仅期望盈利时抽",
                                                                            "hint": "开启后仅在预期收益>0时才付费抽；关闭则无视期望值始终抽"
                                                                        }
                                                                    }
                                                                ]
                                                            },
                                                            {
                                                                "component": "VCol",
                                                                "props": {"cols": 12, "md": 3},
                                                                "content": [
                                                                    {
                                                                        "component": "VTextField",
                                                                        "props": {
                                                                            "model": "slot_max_spins",
                                                                            "label": "最大旋转次数",
                                                                            "type": "number",
                                                                            "min": 1,
                                                                            "max": 100,
                                                                            "hint": "每日最多旋转次数（含免费）"
                                                                        }
                                                                    }
                                                                ]
                                                            }
                                                        ]
                                                    }
                                                ]
                                            }
                                        ]
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
                                "props": {"cols": 12, "md": 10},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "躺平站点 Cookie",
                                            "rows": 3,
                                            "placeholder": "填写包含 c_secure_pass 的完整 Cookie",
                                            "hint": "留空时读取站点管理中的躺平站点 Cookie；填写后仅本插件使用，不会修改站点 Cookie"
                                        }
                                    }
                                ]
                            },
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12,
                                    "md": 2,
                                    "class": "d-flex align-center"
                                },
                                "content": [
                                    {
                                        "component": "VBtn",
                                        "props": {
                                            "color": "success",
                                            "variant": "tonal",
                                            "text": "获取Cookie",
                                            "state": "cookie"
                                        },
                                        "events": {
                                            "click": {
                                                "api": "plugin/TangptLottery/get_cookie",
                                                "method": "get"
                                            }
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VDivider",
                "props": {"class": "my-4"}
            },
            {
                "component": "div",
                "props": {"class": "text-h6 mb-3"},
                "text": "老虎机"
            },
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "期望值(EV)计算说明"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2 font-weight-bold mb-1"},
                                "text": "🎰 基础机制"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": "每次旋转消耗底注（魔力值）。旋转后随机停在3个图案上，根据图案组合判定中奖等级和派彩金额。每日有免费旋转次数，超出后需付费旋转。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2 font-weight-bold mt-2 mb-1"},
                                "text": "📊 EV计算"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": "EV(Expected Value) = 期望值，即每次旋转平均盈亏（魔力值）。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2 mt-1"},
                                "text": "EV = Σ(每种结果概率 × 该结果派彩金额) + P(Jackpot) × 奖池金额 - 底注"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2 mt-1"},
                                "text": "RTP(Return To Player) = 玩家回报率 = (底注+EV)/底注 × 100%，即每投入100能拿回多少。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2 font-weight-bold mt-2 mb-1"},
                                "text": "🔢 示例"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": "底注5000时，三连概率约7%派彩6250，二连概率约25%派彩1875，未中奖概率约68%派彩0。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2 mt-1"},
                                "text": "基础EV = 7%×6250 + 25%×1875 - 5000 ≈ -406（不含Jackpot），加上Jackpot期望后为综合EV。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2 font-weight-bold mt-2 mb-1"},
                                "text": "⚙️ 开关建议"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": "开启「仅期望盈利时抽」：EV > 0 时自动付费旋转，EV ≤ 0 时仅执行免费旋转，避免期望亏损。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2 mt-1"},
                                "text": "关闭后：无论EV正负，都会执行全部付费旋转直到达到最大次数。"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-subtitle-2 font-weight-bold mt-2 mb-1"},
                                "text": "💡 小贴士"
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-body-2"},
                                "text": "老虎机开启后会自动抽取spin_token并计算EV，任务完成后推送包含胜率、净收益和旋转详情的通知。"
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "日期", "key": "date"},
                        {"title": "旋转", "key": "total_spins"},
                        {"title": "免费", "key": "free_used"},
                        {"title": "赢/输", "key": "win_loss"},
                        {"title": "花费", "key": "total_cost"},
                        {"title": "派彩", "key": "total_payout"},
                        {"title": "净收益", "key": "net"},
                        {"title": "EV", "key": "ev_text"},
                        {"title": "状态", "key": "status"}
                    ],
                    "items": self.__slot_records_for_page(),
                    "items-per-page": 10,
                    "hide-default-footer": True,
                    "density": "compact"
                }
            }
        ], {
            "enabled": self._enabled,
            "cookie": cookie_value,
            "draw_count": self._draw_count,
            "target_count": self._target_count,
            "cron": self._cron,
            "notify": self._notify,
            "slot_enabled": self._slot_enabled,
            "slot_max_spins": self._slot_max_spins,
            "slot_ev_only": self._slot_ev_only,
            "skip_vip_stop": self._skip_vip_stop,
            "run_once": False
        }

    def get_page(self) -> List[dict]:
        records = self.__get_records()
        for record in records:
            record["status_text"] = record.get("status_text") or self.__status_text(record.get("status"))
        lottery_info = self.__fetch_lottery_info()
        today_summary, yesterday_summary = self.__build_recent_prize_summary(records)
        return [
            {
                "component": "VCard",
                "props": {"variant": "tonal", "class": "mb-4"},
                "content": [
                    {
                        "component": "VCardTitle",
                        "text": "我的抽奖信息"
                    },
                    {
                        "component": "VCardText",
                        "content": [
                            {
                                "component": "VRow",
                                "content": [
                                    self.__info_col("每次抽奖数", lottery_info.get("draw_count")),
                                    self.__info_col("今日已抽", lottery_info.get("today_drawn")),
                                    self.__info_col("今日目标", lottery_info.get("target_count")),
                                    self.__info_col("状态", lottery_info.get("status")),
                                ]
                            },
                            {
                                "component": "div",
                                "props": {"class": "text-caption text-medium-emphasis mt-2"},
                                "text": lottery_info.get("message") or f"更新时间：{lottery_info.get('updated_at')}"
                            }
                        ]
                    }
                ]
            },
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "日期", "key": "date"},
                        {"title": "目标", "key": "target_count"},
                        {"title": "完成", "key": "completed_count"},
                        {"title": "请求次数", "key": "request_count"},
                        {"title": "奖品汇总", "key": "prize_text"},
                        {"title": "状态", "key": "status_text"},
                        {"title": "消息", "key": "message"}
                    ],
                    "items": records,
                    "items-per-page": 10,
                    "hide-default-footer": True,
                    "density": "compact"
                }
            },
            {
                "component": "VDivider",
                "props": {"class": "my-4"}
            },
            {
                "component": "div",
                "props": {"class": "text-h6 mb-3"},
                "text": "奖品名称汇总"
            },
            {
                "component": "VRow",
                "content": [
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "tonal", "class": "h-100"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "text": "今日汇总"
                                    },
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "props": {"dense": True},
                                                "content": self.__summary_grid(today_summary)
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        "component": "VCol",
                        "props": {"cols": 12, "md": 6},
                        "content": [
                            {
                                "component": "VCard",
                                "props": {"variant": "tonal", "class": "h-100"},
                                "content": [
                                    {
                                        "component": "VCardTitle",
                                        "text": "昨日汇总"
                                    },
                                    {
                                        "component": "VCardText",
                                        "content": [
                                            {
                                                "component": "VRow",
                                                "props": {"dense": True},
                                                "content": self.__summary_grid(yesterday_summary)
                                            }
                                        ]
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ]

    def __slot_records_for_page(self) -> List[dict]:
        records = self.get_data("slot_records") or []
        result = []
        for r in records:
            ev_val = r.get("ev", 0)
            raw_status = r.get("status", "")
            display_status = "已完成" if r.get("jackpot_hit") else self.__status_text(raw_status)
            result.append({
                "date": r.get("date", ""),
                "total_spins": r.get("total_spins", 0),
                "free_used": r.get("free_used", 0),
                "win_loss": f"{r.get('wins',0)}/{r.get('losses',0)}",
                "total_cost": r.get("total_cost", 0),
                "total_payout": r.get("total_payout", 0),
                "net": r.get("net", 0),
                "ev_text": f"{ev_val:+.0f}",
                "status": display_status
            })
        return result

    def run_once_api(self):
        threading.Thread(target=self.run_all_tasks, daemon=True).start()
        return {"status": "started", "message": "躺平抽奖+老虎机任务已启动"}

    def run_slot_api(self):
        threading.Thread(target=self.run_slot_task, daemon=True).start()
        return {"status": "started", "message": "老虎机抽奖任务已启动"}

    def get_cookie_api(self):
        result = self.__get_site_cookie_detail()
        if result.get("success"):
            cookie = result.get("cookie", "")
            self._cookie = cookie
            self.update_config({
                "enabled": self._enabled,
                "cookie": cookie,
                "draw_count": self._draw_count,
                "target_count": self._target_count,
                "cron": self._cron,
                "notify": self._notify,
                "slot_enabled": self._slot_enabled,
                "slot_max_spins": self._slot_max_spins,
                "slot_ev_only": self._slot_ev_only,
                "skip_vip_stop": self._skip_vip_stop,
                "run_once": False
            })
            return {"success": True, "cookie": cookie, "message": "Cookie获取成功"}
        return {"success": False, "cookie": "", "message": result.get("msg", "获取Cookie失败")}

    def run_all_tasks(self):
        self.run_lottery_task()
        if self._slot_enabled:
            time.sleep(3)
            self.run_slot_task()

    def run_lottery_task(self, override_count: int = None):
        with self._lock:
            try:
                logger.info("躺平自动抽奖任务开始执行")
                if not self._cookie:
                    logger.error("躺平自动抽奖：未配置Cookie，无法执行抽奖")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【躺平自动抽奖助手】",
                            text="未配置Cookie，无法执行抽奖任务"
                        )
                    return

                today = datetime.now().strftime("%Y-%m-%d")
                records = self.__get_records()
                today_record = None
                for r in records:
                    if r.get("date") == today:
                        today_record = r
                        break

                if not today_record:
                    today_record = {
                        "date": today,
                        "target_count": override_count or self._target_count,
                        "completed_count": 0,
                        "request_count": 0,
                        "prizes": [],
                        "total_cost": 0,
                        "total_compensated": 0,
                        "total_awarded": 0,
                        "status": "running",
                        "message": ""
                    }
                    records.insert(0, today_record)

                target = override_count or self._target_count
                today_record["target_count"] = target
                completed = today_record.get("completed_count", 0)

                if completed >= target:
                    logger.info(f"躺平自动抽奖：今日已完成 {completed}/{target}，达到目标")
                    today_record["status"] = "completed"
                    today_record["message"] = "已达目标次数"
                    self.__save_records(records)
                    return

                all_prizes = today_record.get("prizes", [])
                request_count = today_record.get("request_count", 0)
                total_cost = today_record.get("total_cost", 0)
                total_compensated = today_record.get("total_compensated", 0)
                total_awarded = today_record.get("total_awarded", 0)

                remaining = target - completed
                batches = self._decompose_draw_count(remaining, self._draw_count)
                logger.info(f"躺平自动抽奖：剩余{remaining}次，分解为{len(batches)}批次: {batches}")

                for batch in batches:
                    result = self.__do_draw(batch)

                    if not result.get("success"):
                        today_record["status"] = "error"
                        today_record["message"] = result.get("message", "抽奖请求失败")
                        today_record["completed_count"] = completed
                        today_record["request_count"] = request_count
                        today_record["prizes"] = all_prizes
                        today_record["total_cost"] = total_cost
                        today_record["total_compensated"] = total_compensated
                        today_record["total_awarded"] = total_awarded
                        self.__save_records(records)
                        if self._notify:
                            prize_text = ""
                            if all_prizes:
                                counter = Counter(all_prizes)
                                prize_text = "\n".join([f"  {name}: {count}次" for name, count in counter.most_common()])
                            self.post_message(
                                mtype=NotificationType.SiteMessage,
                                title="【躺平自动抽奖助手】",
                                text=f"抽奖出错：{result.get('message', '未知错误')}\n"
                                     f"已完成：{completed}/{target}\n"
                                     f"本次已获奖品：\n{prize_text or '  无'}"
                            )
                        return

                    prizes = result.get("prizes", [])
                    all_prizes.extend(prizes)
                    completed += batch
                    request_count += 1
                    total_cost += result.get("total_cost", 0)
                    total_compensated += result.get("total_compensated", 0)
                    total_awarded += result.get("total_awarded", 0)

                    logger.info(f"躺平自动抽奖：第 {request_count} 批请求完成({batch}次)，抽得 {len(prizes)} 个奖品: {', '.join(prizes[:10]) if prizes else '无'}"
                                + (f" (共{len(prizes)}个)" if len(prizes) > 10 else ""))

                    today_record["completed_count"] = completed
                    today_record["request_count"] = request_count
                    today_record["prizes"] = all_prizes
                    today_record["total_cost"] = total_cost
                    today_record["total_compensated"] = total_compensated
                    today_record["total_awarded"] = total_awarded
                    today_record["message"] = f"已完成 {completed}/{target}"

                    vip_prize = any("VIP" in p or "vip" in p for p in prizes)
                    if vip_prize and not self._skip_vip_stop:
                        logger.info("躺平自动抽奖：抽中VIP，停止抽奖")
                        today_record["status"] = "vip"
                        today_record["message"] = f"抽中VIP！已完成 {completed}/{target}"
                        self.__save_records(records)
                        if self._notify:
                            self.__send_lottery_notification(today_record, all_prizes)
                        return
                    elif vip_prize:
                        logger.info("躺平自动抽奖：抽中VIP，但已设置忽略VIP停止，继续抽奖")

                    time.sleep(1)

                today_record["status"] = "completed"
                today_record["message"] = f"完成 {completed}/{target}"
                self.__save_records(records)

                if self._notify:
                    self.__send_lottery_notification(today_record, all_prizes)

                prize_summary = "、".join([f"{name}x{count}" for name, count in Counter(all_prizes).most_common()]) if all_prizes else "无"
                cost_summary = f"，总花费={total_cost}，返还={total_compensated}" if total_cost > 0 else ""
                logger.info(f"躺平自动抽奖任务完成，共抽奖 {completed} 次{cost_summary}，奖品汇总: {prize_summary}")

            except Exception as e:
                logger.error(f"躺平自动抽奖任务异常：{e}")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="【躺平自动抽奖助手】",
                        text=f"抽奖任务异常：{str(e)}"
                    )

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        action = event.event_data.get("action")
        if action == "tangpt_lottery":
            override_count = event.event_data.get("args")
            if override_count:
                try:
                    override_count = int(override_count)
                except (ValueError, TypeError):
                    override_count = None
            threading.Thread(
                target=self.run_lottery_task,
                args=(override_count,),
                daemon=True
            ).start()
        elif action == "tangpt_slot":
            threading.Thread(
                target=self.run_slot_task,
                daemon=True
            ).start()

    def __do_draw(self, count: int) -> Dict[str, Any]:
        try:
            headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "referer": self.LOTTERY_PAGE_URL,
                "cookie": self._cookie,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            }
            data = {"count": str(count)}
            response = requests.post(
                self.DRAW_URL,
                headers=headers,
                data=data,
                timeout=30,
                verify=False
            )
            if response.status_code != 200:
                return {"success": False, "message": f"HTTP {response.status_code}"}

            try:
                result = response.json()
            except Exception:
                return {"success": False, "message": f"响应解析失败: {response.text[:200]}"}

            logger.info(f"躺平抽奖原始响应: {response.text[:800]}")

            if isinstance(result, dict):
                if result.get("ok"):
                    prizes = []
                    total_cost = result.get("total_cost", 0)
                    total_compensated = result.get("total_compensated_bonus", 0)
                    total_awarded = result.get("total_awarded_bonus", 0)
                    for item in result.get("results", []):
                        name = TangptLottery.__extract_prize_name(item)
                        item_count = item.get("count", 1) if isinstance(item, dict) else 1
                        if name:
                            prizes.extend([name.strip()] * item_count)
                    return {
                        "success": True,
                        "prizes": prizes,
                        "total_cost": total_cost,
                        "total_compensated": total_compensated,
                        "total_awarded": total_awarded,
                        "raw": result
                    }
                else:
                    msg = result.get("msg") or result.get("message") or "抽奖失败"
                    return {"success": False, "message": msg}

            return {"success": False, "message": f"响应格式异常: {str(result)[:200]}"}

        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"请求异常: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": f"未知异常: {str(e)}"}

    @staticmethod
    def __extract_prize_name(item) -> Optional[str]:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            for key in ["name", "prize", "prize_name", "title", "reward",
                         "reward_name", "award", "award_name", "gift", "gift_name",
                         "content", "text", "description", "prize_type", "type"]:
                value = item.get(key)
                if value and isinstance(value, str):
                    return value
        return None

    @staticmethod
    def _decompose_draw_count(remaining: int, max_batch: int = 100) -> List[int]:
        batches = []
        for size in TangptLottery.ALLOWED_BATCH_SIZES:
            if size > max_batch:
                continue
            while remaining >= size:
                batches.append(size)
                remaining -= size
        return batches

    def run_slot_task(self):
        with self._lock:
            try:
                logger.info("躺平老虎机任务开始执行")
                if not self._cookie:
                    logger.error("躺平老虎机：未配置Cookie，无法执行")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【躺平老虎机】",
                            text="未配置Cookie，无法执行老虎机任务"
                        )
                    return

                page_data = self.__fetch_slot_page()
                if not page_data:
                    logger.error("躺平老虎机：获取页面数据失败")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【躺平老虎机】",
                            text="获取老虎机页面数据失败，请检查Cookie是否有效"
                        )
                    return

                spin_token = page_data.get("spin_token")
                slot_config = page_data.get("slot_config", {})
                if not spin_token:
                    logger.error("躺平老虎机：未获取到spin_token")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【躺平老虎机】",
                            text="未获取到spin_token，请检查Cookie是否有效"
                        )
                    return

                base_cost = slot_config.get("base_cost", 5000)
                daily_free_spins = slot_config.get("daily_free_spins", 2)
                daily_play_limit = slot_config.get("daily_play_limit", 100)
                jackpot_pool = page_data.get("jackpot_pool", 0)
                prize_rows = slot_config.get("prize_rows", [])
                jackpot_hits = page_data.get("jackpot_hits", 0)
                total_spins_stat = page_data.get("total_spins_stat", 0)

                ev, ev_detail = self.__calc_slot_ev(prize_rows, base_cost, jackpot_pool, jackpot_hits, total_spins_stat)
                ev_text = f"期望收益: {ev:+.2f}/每次 (底注{base_cost:,}, 奖池{jackpot_pool:,})"
                logger.info(f"躺平老虎机：{ev_text}")
                logger.info(f"躺平老虎机EV明细: {ev_detail}")

                multiplier = 1
                per_spin_cost = base_cost * multiplier

                total_spins = 0
                total_cost = 0
                total_payout = 0
                free_used = 0
                wins = 0
                losses = 0
                jackpot_hit = False
                results = []

                max_paid = min(self._slot_max_spins - daily_free_spins, daily_play_limit - daily_free_spins)
                if max_paid < 0:
                    max_paid = 0

                if self._slot_ev_only and ev < 0:
                    logger.info(f"躺平老虎机：期望值为负({ev:+.2f})，跳过付费旋转，仅执行免费抽")
                    max_paid = 0

                for i in range(daily_free_spins):
                    result = self.__do_slot_spin(spin_token, multiplier)
                    if not result.get("success"):
                        logger.error(f"躺平老虎机免费抽第{i+1}次失败: {result.get('message')}")
                        break
                    spin_token, sr = self.__record_spin_result(result, spin_token, "免费", i + 1)
                    free_used += 1
                    total_spins += 1
                    total_cost += sr["total_cost"]
                    total_payout += sr["payout"]
                    if sr["is_win"]:
                        wins += 1
                    else:
                        losses += 1
                    if sr["is_jackpot"]:
                        jackpot_hit = True
                    results.append(sr["result_obj"])

                if max_paid > 0:
                    logger.info(f"躺平老虎机：开始付费旋转，最多{max_paid}次，每次消耗{per_spin_cost:,}")
                    for i in range(max_paid):
                        result = self.__do_slot_spin(spin_token, multiplier)
                        if not result.get("success"):
                            logger.error(f"躺平老虎机第{i+1}次付费失败: {result.get('message')}")
                            break
                        spin_token, sr = self.__record_spin_result(result, spin_token, "付费", i + 1)
                        total_spins += 1
                        total_cost += sr["total_cost"]
                        total_payout += sr["payout"]
                        if sr["is_win"]:
                            wins += 1
                        else:
                            losses += 1
                        if sr["is_jackpot"]:
                            jackpot_hit = True
                        results.append(sr["result_obj"])

                if total_spins == 0:
                    logger.warn("躺平老虎机：没有执行任何旋转")
                    return

                net = total_payout - total_cost
                status_text = f"完成 {total_spins} 转 (免费{free_used}+付费{total_spins-free_used}), "
                status_text += f"赢{wins}/输{losses}, "
                status_text += f"花费{total_cost:,}, 派彩{total_payout:,}, 净收益{net:+,}"
                if jackpot_hit:
                    status_text += ", 命中Jackpot!"
                logger.info(f"躺平老虎机任务完成: {status_text}")

                today = datetime.now().strftime("%Y-%m-%d")
                slot_record = {
                    "date": today,
                    "total_spins": total_spins,
                    "free_used": free_used,
                    "wins": wins,
                    "losses": losses,
                    "total_cost": total_cost,
                    "total_payout": total_payout,
                    "net": net,
                    "jackpot_hit": jackpot_hit,
                    "ev": ev,
                    "ev_detail": ev_detail,
                    "jackpot_pool": jackpot_pool,
                    "base_cost": base_cost,
                    "multiplier": multiplier,
                    "ev_only": self._slot_ev_only,
                    "status": "completed"
                }
                slot_records = self.get_data("slot_records") or []
                slot_records.insert(0, slot_record)
                self.save_data("slot_records", slot_records[:self.MAX_HISTORY])

                if self._notify:
                    self.__send_slot_notification(slot_record, results, ev_text)

            except Exception as e:
                logger.error(f"躺平老虎机任务异常：{e}")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="【躺平老虎机】",
                        text=f"老虎机任务异常：{str(e)}"
                    )

    def __fetch_slot_page(self) -> Optional[Dict[str, Any]]:
        try:
            headers = {
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "cookie": self._cookie,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            }
            response = requests.get(self.SLOT_PAGE_URL, headers=headers, timeout=15, verify=False)
            if response.status_code != 200:
                logger.error(f"躺平老虎机页面请求失败: HTTP {response.status_code}")
                return None
            html = response.text

            token_match = re.search(r'spin_token["\s:=]+["\']?([a-f0-9]{32})["\']?', html)
            if not token_match:
                token_match = re.search(r'name=["\']spin_token["\']\s+value=["\']([^"\']+)["\']', html)
            if not token_match:
                token_match = re.search(r'spin_token\s*=\s*["\']([^"\']+)["\']', html)
            if not token_match:
                token_match = re.search(r'spin_token["\']?\s*:\s*["\']?([a-f0-9]+)["\']?', html)
            spin_token = token_match.group(1) if token_match else None

            slot_config = {}
            slot_initial_state = None
            state_start = html.find('__slotInitialState')
            if state_start >= 0:
                brace_start = html.find('{', state_start)
                if brace_start >= 0:
                    depth = 0
                    end_pos = brace_start
                    for i in range(brace_start, len(html)):
                        c = html[i]
                        if c == '{':
                            depth += 1
                        elif c == '}':
                            depth -= 1
                            if depth == 0:
                                end_pos = i + 1
                                break
                    if depth == 0 and end_pos > brace_start:
                        try:
                            config_raw = html[brace_start:end_pos]
                            slot_initial_state = json.loads(config_raw)
                            slot_config = slot_initial_state.get("config", {})
                        except Exception:
                            pass

            spin_token = None
            if slot_initial_state:
                user_state = slot_initial_state.get("user_state", {}) or {}
                spin_token = user_state.get("spin_token", "") or None
            if not spin_token:
                token_match = re.search(r'spin_token["\s:=]+["\']?([a-f0-9]{32})["\']?', html)
                if not token_match:
                    token_match = re.search(r'name=["\']spin_token["\']\s+value=["\']([^"\']+)["\']', html)
                if not token_match:
                    token_match = re.search(r'spin_token\s*=\s*["\']([^"\']+)["\']', html)
                if not token_match:
                    token_match = re.search(r'spin_token["\']?\s*:\s*["\']?([a-f0-9]+)["\']?', html)
                spin_token = token_match.group(1) if token_match else None

            if not slot_config:
                slot_config = {
                    "base_cost": 5000,
                    "daily_free_spins": 2,
                    "daily_play_limit": 100,
                    "jackpot_pool": 0,
                    "prize_rows": [],
                    "prize_summary": {},
                    "global_stats": {}
                }

            jackpot_pool = slot_config.get("jackpot_pool", 0) or 0
            prize_summary = slot_config.get("prize_summary", {}) or {}
            global_stats = slot_config.get("global_stats", {}) or {}
            jackpot_hits = global_stats.get("jackpot_hits", 0) or 0
            total_spins_stat = global_stats.get("total_spins", 0) or 0

            logger.info(f"躺平老虎机页面解析: spin_token={'OK' if spin_token else 'FAIL'}, "
                        f"base_cost={slot_config.get('base_cost')}, free_spins={slot_config.get('daily_free_spins')}, "
                        f"jackpot_pool={jackpot_pool}, spins={total_spins_stat}, jackpot_hits={jackpot_hits}")
            return {
                "spin_token": spin_token,
                "slot_config": slot_config,
                "jackpot_pool": jackpot_pool,
                "jackpot_hits": jackpot_hits,
                "total_spins_stat": total_spins_stat
            }

        except Exception as e:
            logger.error(f"躺平老虎机页面获取异常: {e}")
            return None

    @staticmethod
    def __calc_slot_ev(prize_rows: list, base_cost: int, jackpot_pool: int,
                       jackpot_hits: int = 0, total_spins_stat: int = 0) -> Tuple[float, str]:
        if not prize_rows or base_cost <= 0:
            return 0.0, "无数据"

        total_expected_payout = 0.0
        row_details = []
        for row in prize_rows:
            prob = row.get("probability", 0) / 100.0
            payout_mult = row.get("payout_multiplier", 0)
            payout = payout_mult * base_cost
            expected = prob * payout
            total_expected_payout += expected
            row_details.append(
                f"{row.get('name','?')}: "
                f"概率{row.get('probability',0):.2f}% × "
                f"派彩{payout:,} = "
                f"期望{expected:.2f}"
            )

        base_ev = total_expected_payout - base_cost
        base_rtp = total_expected_payout / base_cost * 100

        jackpot_ev = 0.0
        jackpot_prob = 0.0
        jackpot_detail = ""

        hits = jackpot_hits or 6
        spins = total_spins_stat or 19081
        jackpot_prob = hits / spins
        jackpot_ev = jackpot_prob * jackpot_pool
        triple_prob = 0
        for row in prize_rows:
            if row.get("rule_type") == "triple_any":
                triple_prob = row.get("probability", 0) / 100.0
                break
        if triple_prob > 0:
            p_symbol_given_triple = jackpot_prob / triple_prob * 100
            jackpot_detail = (
                f"Jackpot: {hits}/{spins}={jackpot_prob*100:.4f}% | "
                f"理论=P(三连={triple_prob*100:.2f}%)×P(7|三连={p_symbol_given_triple:.2f}%) | "
                f"奖池{jackpot_pool:,} × {jackpot_prob*100:.4f}% = 期望+{jackpot_ev:.2f}"
            )
        else:
            jackpot_detail = (
                f"Jackpot: {hits}/{spins}={jackpot_prob*100:.4f}% | "
                f"奖池{jackpot_pool:,} × {jackpot_prob*100:.4f}% = 期望+{jackpot_ev:.2f}"
            )

        total_ev = base_ev + jackpot_ev
        total_rtp = (total_expected_payout + jackpot_ev) / base_cost * 100

        detail_parts = [
            f"底注={base_cost:,}",
            f"--- 各等奖期望 ---",
        ] + row_details + [
            f"--- 汇总 ---",
            f"基础期望派彩={total_expected_payout:.2f}",
            f"基础EV={total_expected_payout:,} - {base_cost:,} = {base_ev:+,.2f}",
            f"基础RTP={base_rtp:.2f}%",
        ]
        if jackpot_detail:
            detail_parts.append(jackpot_detail)
        detail_parts.append(f"综合期望派彩={total_expected_payout+jackpot_ev:.2f}")
        detail_parts.append(f"综合EV={total_ev:+,.2f}/次")
        detail_parts.append(f"综合RTP={total_rtp:.2f}%")

        return total_ev, " | ".join(detail_parts)

    def __refresh_spin_token(self, current_token: str, spin_result: dict) -> str:
        new_token = spin_result.get("new_spin_token", "")
        if new_token:
            return new_token
        page_data = self.__fetch_slot_page()
        if page_data and page_data.get("spin_token"):
            return page_data.get("spin_token")
        return current_token

    def __do_slot_spin(self, spin_token: str, multiplier: int = 1) -> Dict[str, Any]:
        try:
            headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "x-requested-with": "XMLHttpRequest",
                "referer": self.SLOT_PAGE_URL,
                "cookie": self._cookie,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            }
            data = {"multiplier": str(multiplier), "spin_token": spin_token}
            response = requests.post(
                self.SLOT_DRAW_URL,
                headers=headers,
                data=data,
                timeout=30,
                verify=False
            )
            if response.status_code != 200:
                return {"success": False, "message": f"HTTP {response.status_code}"}

            try:
                result = response.json()
            except Exception:
                return {"success": False, "message": f"响应解析失败: {response.text[:200]}"}

            if isinstance(result, dict) and result.get("ok"):
                spin_result = result.get("result", "lose")
                is_jackpot = False
                row = result.get("row", {})
                if row:
                    is_jackpot = row.get("is_jackpot", False)
                if not is_jackpot:
                    is_jackpot = spin_result == "triple_win"
                new_spin_token = result.get("spin_token") or ""
                return {
                    "success": True,
                    "result": spin_result,
                    "reels": result.get("reels", []),
                    "total_cost": result.get("total_cost", 0),
                    "payout": result.get("payout", 0),
                    "reward": result.get("reward", 0),
                    "multiplier": result.get("multiplier", multiplier),
                    "is_free_spin": result.get("is_free_spin", False),
                    "is_jackpot": is_jackpot,
                    "jackpot_pool": result.get("jackpot_pool", 0),
                    "balance_after": result.get("balance_after", 0),
                    "row": row,
                    "new_spin_token": new_spin_token,
                    "raw": result
                }
            else:
                msg = result.get("msg") or result.get("message") or "老虎机抽奖失败"
                return {"success": False, "message": msg}

        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"请求异常: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": f"未知异常: {str(e)}"}

    def __record_spin_result(self, result: dict, spin_token: str, spin_type: str, seq: int) -> Tuple[str, dict]:
        new_token = self.__refresh_spin_token(spin_token, result)
        spin_result = result.get("result", "lose")
        is_win = spin_result == "win" or spin_result == "triple_win"
        is_jackpot = result.get("is_jackpot", False)
        reels_info = " | ".join([r.get("name", "?") for r in result.get("reels", [])])
        logger.info(
            f"躺平老虎机{spin_type}抽第{seq}次: {spin_result}, "
            f"reels=[{reels_info}], payout={result.get('payout', 0)}"
        )
        time.sleep(1)
        return new_token, {
            "is_win": is_win,
            "is_jackpot": is_jackpot,
            "total_cost": result.get("total_cost", 0),
            "payout": result.get("payout", 0),
            "result_obj": result
        }

    def __send_slot_notification(self, record: dict, results: list, ev_text: str):
        total_spins = record.get("total_spins", 0)
        free_used = record.get("free_used", 0)
        wins = record.get("wins", 0)
        losses = record.get("losses", 0)
        total_cost = record.get("total_cost", 0)
        total_payout = record.get("total_payout", 0)
        net = record.get("net", 0)
        jackpot_hit = record.get("jackpot_hit", False)
        jackpot_pool = record.get("jackpot_pool", 0)
        ev_detail = record.get("ev_detail", "")
        ev = record.get("ev", 0)

        win_rate = f"{wins / total_spins * 100:.0f}%" if total_spins > 0 else "0%"
        net_icon = "📈" if net > 0 else "📉" if net < 0 else "➡️"
        ev_icon = "🟢" if ev > 0 else "🔴" if ev < 0 else "🟡"

        paid = total_spins - free_used

        spin_lines = []
        for r in results:
            icons = "".join([reel.get("name", "?") for reel in r.get("reels", [])])
            sr = r.get("result", "?")
            payout = r.get("payout", 0)
            if payout > 0:
                spin_lines.append(f"  {icons}  {sr} (+{payout:,})")
            else:
                spin_lines.append(f"  {icons}  {sr}")

        detail_limit = 12
        detail_text = "\n".join(spin_lines[:detail_limit])
        if len(spin_lines) > detail_limit:
            detail_text += f"\n  ... (共{len(spin_lines)}转)"

        text = (
            f"🎰 躺平老虎机 · {record.get('date')}\n\n"
            f"💰 投入：{total_cost:,}  派彩：{total_payout:,}\n"
            f"{net_icon} 净收益：{net:+,}\n\n"
            f"🎲 旋转：{total_spins} 次 (免费{free_used} + 付费{paid})\n"
            f"🎯 胜负：赢 {wins} / 输 {losses} (胜率{win_rate})\n"
            f"{ev_icon} 期望收益：{ev:+.1f}/次"
        )
        if ev_detail:
            text += f"\n📋 EV明细：{ev_detail}"
        if jackpot_hit:
            text += "\n🎊 Jackpot!!!"
        if jackpot_pool > 0:
            text += f"\n💰 当前奖池：{jackpot_pool:,}"
        text += f"\n\n🎬 旋转详情：\n{detail_text}"

        self.post_message(
            mtype=NotificationType.SiteMessage,
            title="【躺平老虎机】",
            text=text
        )

    def __fetch_lottery_info(self) -> Dict[str, Any]:
        info = {
            "draw_count": self._draw_count,
            "today_drawn": 0,
            "target_count": self._target_count,
            "status": "未知",
            "message": "",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            records = self.__get_records()
            for r in records:
                if r.get("date") == today:
                    info["today_drawn"] = r.get("completed_count", 0)
                    info["status"] = self.__status_text(r.get("status"))
                    info["message"] = r.get("message", "")
                    break
        except Exception as e:
            logger.error(f"获取抽奖信息失败: {e}")
        return info

    def __get_site_cookie(self) -> str:
        try:
            siteoper = SiteOper()
            site = siteoper.get_by_domain(self.SITE_DOMAIN)
            if site and site.cookie:
                return site.cookie
        except Exception:
            pass
        return ""

    def __get_site_cookie_detail(self) -> Dict[str, Any]:
        try:
            siteoper = SiteOper()
            site = siteoper.get_by_domain(self.SITE_DOMAIN)
            if not site:
                return {"success": False, "msg": f"未添加躺平站点({self.SITE_DOMAIN})！请在站点管理中添加。"}
            cookie = site.cookie
            if not cookie or str(cookie).strip().lower() == "cookie":
                return {"success": False, "msg": "站点Cookie为空或无效，请在站点管理中配置！"}
            return {"success": True, "cookie": cookie}
        except Exception as e:
            logger.error(f"获取站点Cookie失败: {e}")
            return {"success": False, "msg": f"获取站点Cookie失败: {e}"}

    def __send_lottery_notification(self, record: dict, prizes: list):
        prize_counter = Counter(prizes)
        total_prizes = len(prizes)
        winning_count = sum(1 for p in prizes if p not in ("谢谢参与", "thanks"))
        win_rate = f"{(winning_count / total_prizes * 100):.1f}%" if total_prizes > 0 else "0%"

        def group(category, keyword, emoji):
            items = [p for p in prizes if keyword.lower() in p.lower()]
            if not items:
                return ""
            grouped = Counter(items)
            parts = []
            for name, cnt in grouped.most_common():
                short = name.split(": ")[-1] if ": " in name else name
                parts.append(f"{short}×{cnt}")
            return f"  {emoji} {category}：{', '.join(parts)}"

        thank_keywords = ["谢谢参与", "thanks", "谢谢惠顾", "惠顾"]
        thank_count = sum(prize_counter.get(k, 0) for k in thank_keywords)

        cat_lines = []
        cat_lines.append(group("VIP", "vip", "👑"))
        cat_lines.append(group("魔力值", "魔力", "✨"))
        cat_lines.append(group("邀请", "邀请", "📨"))
        cat_lines.append(group("勋章", "勋章", "🏅"))
        cat_lines.append(group("道具", "道具", "🎁"))
        if thank_count > 0:
            cat_lines.append(f"  💤 谢谢惠顾：{thank_count}次")
        all_keywords = ["vip", "魔力", "邀请", "勋章", "道具", "谢谢", "thanks", "惠顾"]
        other = [p for p in prizes if not any(k in p.lower() for k in all_keywords)]
        if other:
            other_counter = Counter(other)
            cat_lines.append(f"  📦 其他：{', '.join([f'{n}×{c}' for n, c in other_counter.most_common()])}")
        prize_block = "\n".join([l for l in cat_lines if l])
        if not prize_block:
            prize_block = "  无奖品记录"

        total_cost = record.get("total_cost", 0)
        total_compensated = record.get("total_compensated", 0)
        total_awarded = record.get("total_awarded", 0)
        total_back = total_compensated + total_awarded
        cost_text = ""
        if total_cost > 0:
            net_cost = total_cost - total_back
            cost_text = f"\n💰 花费：{total_cost:,}  返还：{total_compensated:,}  奖品价值：{total_awarded:,}  净支出：{net_cost:,}"

        self.post_message(
            mtype=NotificationType.SiteMessage,
            title="【躺平自动抽奖助手】",
            text=f"📅 日期：{record.get('date')}\n"
                 f"🎯 抽奖次数：{record.get('completed_count', 0)}/{record.get('target_count', 0)}  状态：{self.__status_text(record.get('status'))}\n"
                 f"🎉 中奖率：{win_rate} ({winning_count}/{total_prizes}){cost_text}\n\n"
                 f"📊 奖品汇总：\n{prize_block}"
        )

    def __get_records(self) -> List[dict]:
        try:
            records = self.get_data("lottery_records") or []
        except Exception:
            records = []
        return records[:self.MAX_HISTORY]

    def __save_records(self, records: List[dict]):
        for record in records:
            prizes = record.get("prizes", [])
            counter = Counter(prizes)
            parts = []
            for name, count in counter.most_common():
                if count > 1:
                    parts.append(f"{name}x{count}")
                else:
                    parts.append(name)
            record["prize_text"] = "、".join(parts) if parts else "无"
        self.save_data("lottery_records", records[:self.MAX_HISTORY])

    def __build_recent_prize_summary(self, records: List[dict]):
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        today_summary = Counter()
        yesterday_summary = Counter()
        for r in records:
            if r.get("date") == today:
                today_summary.update(r.get("prizes", []))
            elif r.get("date") == yesterday:
                yesterday_summary.update(r.get("prizes", []))
        return today_summary, yesterday_summary

    @staticmethod
    def __summary_grid(summary: Counter) -> List[dict]:
        if not summary:
            return [
                {
                    "component": "VCol",
                    "props": {"cols": 12},
                    "content": [
                        {
                            "component": "div",
                            "props": {"class": "text-body-2 text-medium-emphasis"},
                            "text": "暂无数据"
                        }
                    ]
                }
            ]
        items = []
        for name, count in summary.most_common():
            items.append(
                {
                    "component": "VCol",
                    "props": {"cols": 6, "md": 4},
                    "content": [
                        {
                            "component": "VChip",
                            "props": {
                                "label": True,
                                "size": "small",
                                "variant": "tonal",
                                "class": "ma-1"
                            },
                            "content": [
                                {
                                    "component": "span",
                                    "text": f"{name} ×{count}"
                                }
                            ]
                        }
                    ]
                }
            )
        return items

    @staticmethod
    def __info_col(label: str, value) -> dict:
        return {
            "component": "VCol",
            "props": {"cols": 6, "md": 3},
            "content": [
                {
                    "component": "div",
                    "props": {"class": "text-caption text-medium-emphasis"},
                    "text": str(label)
                },
                {
                    "component": "div",
                    "props": {"class": "text-h6"},
                    "text": str(value if value is not None else "-")
                }
            ]
        }

    @staticmethod
    def __status_text(status) -> str:
        status_map = {
            "running": "进行中",
            "completed": "已完成",
            "error": "出错",
            "vip": "抽中VIP"
        }
        return status_map.get(status, str(status)) if status else "未知"

    @staticmethod
    def __safe_int(value, default: int = 0, min_value: int = 0) -> int:
        try:
            result = int(value)
            return max(result, min_value)
        except (ValueError, TypeError):
            return default

    def stop_service(self):
        pass
