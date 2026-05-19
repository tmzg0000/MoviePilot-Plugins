import threading
from datetime import datetime
from typing import Any, Dict, List, Tuple

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


class NovaHDClaim(_PluginBase):
    plugin_name = "NovaHD任务领取"
    plugin_desc = "每月定时为NovaHD领取任务，领取后推送飞书消息通知。"
    plugin_icon = "signin.png"
    plugin_version = "1.0.0"
    plugin_author = "schalkiii"
    author_url = ""
    plugin_config_prefix = "novahdclaim_"
    plugin_order = 32
    auth_level = 1

    CLAIM_URL = "https://pt.novahd.top/ajax.php"
    TASK_PAGE_URL = "https://pt.novahd.top/task.php"
    SITE_DOMAIN = "pt.novahd.top"

    _enabled = False
    _cookie = ""
    _exam_id = "3"
    _cron = "0 0 1 * *"
    _notify = True
    _run_once = False
    _lock = threading.Lock()

    def init_plugin(self, config: dict = None):
        config = config or {}
        site_cookie = self.__get_site_cookie()
        self._enabled = bool(config.get("enabled", False))
        self._cookie = (config.get("cookie") or site_cookie or "").strip()
        self._exam_id = (config.get("exam_id") or "3").strip()
        self._cron = (config.get("cron") or "0 0 1 * *").strip()
        self._notify = bool(config.get("notify", True))
        self._run_once = bool(config.get("run_once", False))
        logger.info(
            f"NovaHD任务领取初始化完成：enabled={self._enabled}, "
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
            logger.info("收到配置页立即运行请求，后台启动任务领取")
            threading.Thread(target=self.claim_task, daemon=True).start()

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        return [
            {
                "cmd": "/nhdclaim",
                "event": EventType.PluginAction,
                "desc": "执行NovaHD任务领取",
                "category": "站点",
                "data": {"action": "novahd_claim"}
            }
        ]

    def get_api(self) -> List[Dict[str, Any]]:
        return [
            {
                "path": "/run",
                "endpoint": self.run_once_api,
                "methods": ["POST"],
                "auth": "bear",
                "summary": "立即执行NovaHD任务领取",
                "description": "按当前插件配置立即执行一次任务领取。"
            },
            {
                "path": "/get_cookie",
                "endpoint": self.get_cookie_api,
                "methods": ["GET"],
                "auth": "bear",
                "summary": "获取NovaHD站点Cookie",
                "description": "从站点管理中获取NovaHD站点的Cookie。"
            }
        ]

    def get_service(self) -> List[Dict[str, Any]]:
        if not self._enabled or not self._cron:
            return []
        try:
            trigger = CronTrigger.from_crontab(self._cron)
        except ValueError:
            logger.warn("NovaHD任务领取 Cron 配置无效，定时服务未注册")
            return []
        return [
            {
                "id": "NovaHDClaim",
                "name": "NovaHD任务领取",
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
                                            "placeholder": "3",
                                            "hint": "NovaHD的任务ID，默认为3"
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
                                            "placeholder": "5位 Cron 表达式，例如 0 0 1 * *"
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
                                "props": {"cols": 12, "md": 10},
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "cookie",
                                            "label": "NovaHD Cookie",
                                            "rows": 3,
                                            "placeholder": "填写包含 c_secure_pass 的完整 Cookie",
                                            "hint": "留空时读取站点管理中的NovaHD站点 Cookie；填写后仅本插件使用，不会修改站点 Cookie"
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
                                            "text": "获取Cookie"
                                        },
                                        "events": {
                                            "click": {
                                                "api": "plugin/NovaHDClaim/get_cookie",
                                                "method": "get",
                                                "state": "cookie"
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
                                        "component": "VAlert",
                                        "props": {
                                            "type": "info",
                                            "variant": "tonal",
                                            "text": "执行周期默认为每月1日0点（0 0 1 * *），可自定义Cron表达式。"
                                                    "领取任务后会自动通过系统通知渠道发送飞书消息（需先配置飞书机器人消息通知插件）。"
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": self._enabled,
            "cookie": cookie_value,
            "exam_id": self._exam_id,
            "cron": self._cron,
            "notify": self._notify,
            "run_once": False
        }

    def get_page(self) -> List[dict]:
        records = self.__get_records()
        for record in records:
            record["status_text"] = self.__status_text(record.get("status"))
        return [
            {
                "component": "VDataTable",
                "props": {
                    "headers": [
                        {"title": "日期", "key": "date"},
                        {"title": "任务ID", "key": "exam_id"},
                        {"title": "结果", "key": "result"},
                        {"title": "状态", "key": "status_text"},
                        {"title": "消息", "key": "message"}
                    ],
                    "items": records,
                    "items-per-page": 10,
                    "hide-default-footer": True,
                    "density": "compact"
                }
            }
        ]

    def run_once_api(self):
        threading.Thread(target=self.claim_task, daemon=True).start()
        return {"status": "started", "message": "NovaHD任务领取已启动"}

    def get_cookie_api(self):
        result = self.__get_site_cookie_detail()
        if result.get("success"):
            cookie = result.get("cookie", "")
            self._cookie = cookie
            self.update_config({
                "enabled": self._enabled,
                "cookie": cookie,
                "exam_id": self._exam_id,
                "cron": self._cron,
                "notify": self._notify,
                "run_once": False
            })
            return {"success": True, "cookie": cookie, "message": "Cookie获取成功"}
        return {"success": False, "cookie": "", "message": result.get("msg", "获取Cookie失败")}

    @eventmanager.register(EventType.PluginAction)
    def handle_command(self, event: Event):
        action = event.event_data.get("action")
        if action == "novahd_claim":
            threading.Thread(
                target=self.claim_task,
                daemon=True
            ).start()

    def claim_task(self):
        with self._lock:
            try:
                logger.info("NovaHD任务领取开始执行")
                if not self._cookie:
                    logger.error("NovaHD任务领取：未配置Cookie，无法执行")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【NovaHD任务领取】",
                            text="未配置Cookie，无法执行任务领取"
                        )
                    return

                today = datetime.now().strftime("%Y-%m-%d")
                result = self.__do_claim()

                record = {
                    "date": today,
                    "exam_id": self._exam_id,
                    "result": "成功" if result.get("success") else "失败",
                    "status": "completed" if result.get("success") else "error",
                    "message": result.get("message", "")
                }
                self.__save_record(record)

                if result.get("success"):
                    logger.info(f"NovaHD任务领取成功：{result.get('message')}")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【NovaHD任务领取】",
                            text=f"任务领取成功！\n"
                                 f"日期：{today}\n"
                                 f"任务ID：{self._exam_id}\n"
                                 f"结果：{result.get('message')}"
                        )
                else:
                    logger.warn(f"NovaHD任务领取失败：{result.get('message')}")
                    if self._notify:
                        self.post_message(
                            mtype=NotificationType.SiteMessage,
                            title="【NovaHD任务领取】",
                            text=f"任务领取失败！\n"
                                 f"日期：{today}\n"
                                 f"任务ID：{self._exam_id}\n"
                                 f"原因：{result.get('message')}"
                        )

            except Exception as e:
                logger.error(f"NovaHD任务领取异常：{e}")
                if self._notify:
                    self.post_message(
                        mtype=NotificationType.SiteMessage,
                        title="【NovaHD任务领取】",
                        text=f"任务领取异常：{str(e)}"
                    )

    def __do_claim(self) -> Dict[str, Any]:
        try:
            headers = {
                "accept": "application/json, text/javascript, */*; q=0.01",
                "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.8",
                "cache-control": "no-cache",
                "content-type": "application/x-www-form-urlencoded; charset=UTF-8",
                "pragma": "no-cache",
                "priority": "u=1, i",
                "sec-ch-ua": "\"Microsoft Edge\";v=\"147\", \"Not.A/Brand\";v=\"8\", \"Chromium\";v=\"147\"",
                "sec-ch-ua-mobile": "?0",
                "sec-ch-ua-platform": "\"Windows\"",
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
                "x-requested-with": "XMLHttpRequest",
                "referer": self.TASK_PAGE_URL,
                "cookie": self._cookie,
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
            }
            data = {
                "action": "claimTask",
                "params[exam_id]": self._exam_id
            }
            logger.info(f"NovaHD任务领取请求：exam_id={self._exam_id}")
            response = requests.post(
                self.CLAIM_URL,
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

            logger.info(f"NovaHD任务领取响应: {response.text[:500]}")

            if isinstance(result, dict):
                if result.get("success") or result.get("state") or result.get("code") == 0:
                    msg = result.get("msg") or result.get("message") or "领取成功"
                    return {"success": True, "message": msg, "raw": result}
                else:
                    msg = result.get("msg") or result.get("message") or "领取失败"
                    return {"success": False, "message": msg, "raw": result}

            return {"success": False, "message": f"响应格式异常: {str(result)[:200]}"}

        except requests.exceptions.RequestException as e:
            return {"success": False, "message": f"请求异常: {str(e)}"}
        except Exception as e:
            return {"success": False, "message": f"未知异常: {str(e)}"}

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
                return {"success": False, "msg": f"未添加NovaHD站点({self.SITE_DOMAIN})！请在站点管理中添加。"}
            cookie = site.cookie
            if not cookie or str(cookie).strip().lower() == "cookie":
                return {"success": False, "msg": "站点Cookie为空或无效，请在站点管理中配置！"}
            return {"success": True, "cookie": cookie}
        except Exception as e:
            logger.error(f"获取站点Cookie失败: {e}")
            return {"success": False, "msg": f"获取站点Cookie失败: {e}"}

    def __get_records(self) -> List[dict]:
        try:
            records = self.get_data("claim_records") or []
        except Exception:
            records = []
        return records[:30]

    def __save_record(self, record: dict):
        records = self.__get_records()
        records.insert(0, record)
        self.save_data("claim_records", records[:30])

    @staticmethod
    def __status_text(status) -> str:
        status_map = {
            "running": "进行中",
            "completed": "已完成",
            "error": "出错"
        }
        return status_map.get(status, str(status)) if status else "未知"

    def stop_service(self):
        pass