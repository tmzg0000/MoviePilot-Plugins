import datetime
import threading
from typing import List, Tuple, Dict, Any, Optional

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
try:
    from app.sdk.config import settings
except ImportError:
    from app.core.config import settings
try:
    from app.sdk.services import DownloaderHelper
except ImportError:
    from app.helper.downloader import DownloaderHelper
try:
    from app.sdk.logging import logger
except ImportError:
    from app.log import logger
try:
    from app.sdk.plugin import _PluginBase
except ImportError:
    from app.plugins import _PluginBase
try:
    from app.schemas.system import ServiceInfo
except ImportError:
    from app.schemas import ServiceInfo


class Limit(_PluginBase):
    # 插件名称
    plugin_name = "自动限速"
    # 插件描述
    plugin_desc = "给qb、tr的下载任务限速"
    # 插件图标
    plugin_icon = "Youtube-dl_A.png"
    # 插件版本
    plugin_version = "1.1.7"
    # 插件作者
    plugin_author = "tmzg0000"
    # 作者主页
    author_url = "https://github.com/tmzg0000"
    # 插件配置项ID前缀
    plugin_config_prefix = "Limit_"
    # 加载顺序
    plugin_order = 22
    # 可使用的用户级别
    auth_level = 2
    # 日志前缀
    LOG_TAG = "[Limit]"

    # 退出事件
    _event = threading.Event()
    _run_lock = threading.Lock()
    # 私有属性
    sites_helper = None
    downloader_helper = None
    _scheduler = None
    _enabled = False
    _onlyonce = False
    _cover = False
    _global = False
    _interval = "计划任务"
    _interval_cron = "0 13 * * *"
    _interval_time = 24
    _interval_unit = "小时"
    _downloaders = None
    _global_speed = 0
    _limit_mode = "标签"
    _torrent_speed = 1000
    _new_only = False
    _tag_map = ""

    def init_plugin(self, config: dict = None):
        self.downloader_helper = DownloaderHelper()
        # 读取配置
        if config:
            self._enabled = config.get("enabled")
            self._onlyonce = config.get("onlyonce")
            self._cover = config.get("cover")
            self._global = config.get("global")
            self._interval = config.get("interval") or "计划任务"
            self._interval_cron = config.get("interval_cron") or "0 13 * * *"
            self._interval_time = self.str_to_number(config.get("interval_time"), 24)
            self._interval_unit = config.get("interval_unit") or "小时"
            self._downloaders = config.get("downloaders")
            self._global_speed = self.str_to_number(config.get("global_speed"), 0)
            self._limit_mode = config.get("limit_mode") or "标签"
            self._torrent_speed = max(0, self.str_to_number(config.get("torrent_speed"), 1000))
            self._new_only = bool(config.get("new_only", False))
            self._tag_map = config.get("tag_map") or ""

        # 停止现有任务
        self.stop_service()

        if self._onlyonce:
            # 创建定时任务控制器
            self._scheduler = BackgroundScheduler(timezone=settings.TZ)
            # 执行一次, 关闭onlyonce
            self._onlyonce = False
            config.update({"onlyonce": self._onlyonce})
            self.update_config(config)
            # 执行自动限速
            self._scheduler.add_job(func=self._complete_limit, trigger='date',
                                    run_date=datetime.datetime.now(
                                        tz=pytz.timezone(settings.TZ)) + datetime.timedelta(seconds=3)
                                    )
            if self._scheduler and self._scheduler.get_jobs():
                # 启动服务
                self._scheduler.print_jobs()
                self._scheduler.start()

    @property
    def service_infos(self) -> Optional[Dict[str, ServiceInfo]]:
        if not self._downloaders:
            logger.warning("尚未配置下载器，请检查配置")
            return None

        services = self.downloader_helper.get_services(name_filters=self._downloaders)
        if not services:
            logger.warning("获取下载器实例失败，请检查配置")
            return None

        active_services = {}
        for service_name, service_info in services.items():
            if service_info.type not in ("qbittorrent", "transmission"):
                logger.warning(f"下载器 {service_name} 类型不支持，仅支持 qBittorrent 和 Transmission")
                continue
            if service_info.instance.is_inactive():
                logger.warning(f"下载器 {service_name} 未连接，请检查配置")
            else:
                active_services[service_name] = service_info

        if not active_services:
            logger.warning("没有已连接的下载器，请检查配置")
            return None

        return active_services

    def get_state(self) -> bool:
        return self._enabled

    @staticmethod
    def get_command() -> List[Dict[str, Any]]:
        pass

    def get_api(self) -> List[Dict[str, Any]]:
        pass

    def get_service(self) -> List[Dict[str, Any]]:
        """
        注册插件公共服务
        [{
            "id": "服务ID",
            "name": "服务名称",
            "trigger": "触发器：cron/interval/date/CronTrigger.from_crontab()",
            "func": self.xxx,
            "kwargs": {} # 定时器参数
        }]
        """
        if self._enabled:
            if self._interval == "计划任务" or self._interval == "固定间隔":
                if self._interval == "固定间隔":
                    if self._interval_unit == "小时":
                        return [{
                            "id": "Limit",
                            "name": "自动限速",
                            "trigger": "interval",
                            "func": self._complete_limit,
                            "kwargs": {
                                "hours": self._interval_time
                            }
                        }]
                    else:
                        if self._interval_time < 5:
                            self._interval_time = 5
                            logger.info(f"{self.LOG_TAG}启动定时服务: 最小不少于5分钟, 防止执行间隔太短任务冲突")
                        return [{
                            "id": "Limit",
                            "name": "自动限速",
                            "trigger": "interval",
                            "func": self._complete_limit,
                            "kwargs": {
                                "minutes": self._interval_time
                            }
                        }]
                else:
                    return [{
                        "id": "Limit",
                        "name": "自动限速",
                        "trigger": CronTrigger.from_crontab(self._interval_cron),
                        "func": self._complete_limit,
                        "kwargs": {}
                    }]
        return []

    @staticmethod
    def str_to_number(s: str, i: int) -> int:
        try:
            return int(s)
        except (TypeError, ValueError):
            return i

    def _complete_limit(self):
        if not self._run_lock.acquire(blocking=False):
            logger.info(f"{self.LOG_TAG}上次限速任务尚未结束，跳过本次执行")
            return
        try:
            self._run_limit()
        finally:
            self._run_lock.release()

    def _run_limit(self):
        services = self.service_infos
        if not services:
            return
        all_torrents = self._limit_mode == "所有种子"
        new_only = all_torrents and self._new_only
        seen_records = (self.get_data("seen_torrents") or {}) if all_torrents else {}
        logger.info(f"{self.LOG_TAG}开始执行 ...")
        for service in services.values():
            downloader = service.name
            downloader_obj = service.instance
            logger.info(f"{self.LOG_TAG}开始扫描下载器 {downloader} ...")
            if not downloader_obj:
                logger.error(f"{self.LOG_TAG} 获取下载器失败 {downloader}")
                continue
            # 全局限速
            if self._global and not all_torrents:
                # MoviePilot 的 qB 接口接收 KiB/s，内部已乘以 1024。
                global_speed = self._global_speed
                if service.type == "transmission":
                    global_speed = self._kib_to_transmission_limit(global_speed)
                downloader_obj.set_speed_limit(download_limit=0, upload_limit=global_speed)
            tag_map = {}
            # 所有种子模式无需标签规则，也不修改下载器全局限速。
            if not all_torrents:
                if not self._tag_map:
                    continue
                for item in self._tag_map.split("\n"):
                    i = item.split(":")
                    _tag = i[0]
                    if not i[1]:
                        continue
                    _speed = int(i[1])
                    tag_map[_tag] = _speed
            # 获取下载器中的种子
            try:
                torrents, error = downloader_obj.get_torrents()
            except Exception as e:
                logger.error(f"{self.LOG_TAG}下载器 {downloader} 获取种子失败: {e}")
                continue
            # 获取失败时保留已有记录；成功返回空列表时清空快照。
            if error:
                continue
            torrents = torrents or []
            record_key = f"{service.type}:{downloader}"
            current_hashes = {self._get_hash(t, service.type) for t in torrents}
            current_hashes.discard("")
            current_hashes.discard(None)
            if new_only and record_key not in seen_records:
                # 首次成功扫描建立基线，已有种子不算新增。
                seen_records[record_key] = sorted(current_hashes)
                self.save_data("seen_torrents", seen_records)
                logger.info(f"{self.LOG_TAG}下载器 {downloader} 已建立新增种子基线，记录 {len(current_hashes)} 个已有种子")
                continue
            seen_hashes = set(seen_records.get(record_key, [])) & current_hashes
            logger.info(f"{self.LOG_TAG}下载器 {downloader} 分析种子信息中 ...")
            for torrent in torrents:
                try:
                    if self._event.is_set():
                        if all_torrents:
                            seen_records[record_key] = sorted(seen_hashes)
                            self.save_data("seen_torrents", seen_records)
                        logger.info(f"{self.LOG_TAG}停止服务")
                        return
                    # 获取种子hash
                    hash = self._get_hash(torrent=torrent, dl_type=service.type)
                    if not hash:
                        continue
                    if new_only and hash in seen_hashes:
                        continue
                    if all_torrents:
                        seen_hashes.discard(hash)
                    if service.type == "qbittorrent":
                        if not self._cover and torrent.get("up_limit", 0) > 0:
                            seen_hashes.add(hash)
                            continue
                    if service.type == "transmission":
                        if not self._cover and downloader_obj.trc.get_torrent(torrent_id=hash).upload_limited:
                            seen_hashes.add(hash)
                            continue
                    if all_torrents:
                        if self._set_torrent_speed(service=service, _hash=hash, _speed=self._torrent_speed):
                            seen_hashes.add(hash)
                        continue
                    # 获取种子当前标签
                    torrent_tags = self._get_tags(torrent=torrent, dl_type=service.type)
                    for tag in torrent_tags:
                        if tag in tag_map:
                            speed = tag_map[tag]
                            self._set_torrent_speed(service=service, _hash=hash, _speed=speed)
                            break
                except Exception as e:
                    logger.error(
                        f"{self.LOG_TAG}分析种子信息时发生了错误: {str(e)}")
            if all_torrents:
                seen_records[record_key] = sorted(seen_hashes)
                self.save_data("seen_torrents", seen_records)
        logger.info(f"{self.LOG_TAG}执行完成")

    @staticmethod
    def _get_hash(torrent: Any, dl_type: str):
        try:
            return torrent.get("hash") if dl_type == "qbittorrent" else torrent.hashString
        except Exception as e:
            print(str(e))
            return ""

    @staticmethod
    def _get_tags(torrent: Any, dl_type: str):
        try:
            return [str(tag).strip() for tag in torrent.get("tags", "").split(',')] if dl_type == "qbittorrent" else torrent.labels or []
        except Exception as e:
            print(str(e))
            return []

    @staticmethod
    def _kib_to_transmission_limit(speed: int) -> int:
        """Transmission 接收整数 kB/s；向下取整，0 仍表示不限速。"""
        return speed * 1024 // 1000

    def _set_torrent_speed(self, service: ServiceInfo, _hash: str, _speed: int = 0) -> bool:
        if not service or not service.instance:
            return False
        downloader_obj = service.instance
        # 下载器api不通用, 因此需分开处理
        if service.type == "qbittorrent":
            # qB 原生接口接收 B/s，配置统一为 KiB/s。
            downloader_obj.qbc.torrents_set_upload_limit(torrent_hashes=_hash, limit=_speed * 1024)
        else:
            result = downloader_obj.change_torrent(hash_string=_hash, upload_limit=self._kib_to_transmission_limit(_speed))
            if result is False:
                logger.error(f"{self.LOG_TAG}下载器: {service.name} 种子id: {_hash} 上传限速设置失败")
                return False
        logger.info(f"{self.LOG_TAG}下载器: {service.name} 种子id: {_hash}  上传限速为 {_speed} KiB/s")
        return True

    def get_form(self) -> Tuple[List[dict], Dict[str, Any]]:
        return [
            {
                'component': 'VForm',
                'content': [
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'enabled',
                                            'label': '启用插件',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'cover',
                                            'label': '覆盖模式',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'global',
                                            'label': '下载器全局限速',
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 3
                                },
                                'content': [
                                    {
                                        'component': 'VCheckboxBtn',
                                        'props': {
                                            'model': 'onlyonce',
                                            'label': '运行一次'
                                        }
                                    }
                                ]
                            },
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'multiple': True,
                                            'chips': True,
                                            'clearable': True,
                                            'model': 'downloaders',
                                            'label': '下载器',
                                            'items': [{"title": config.name, "value": config.name}
                                                      for config in self.downloader_helper.get_configs().values()
                                                      if config.type in ("qbittorrent", "transmission")]
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'limit_mode',
                                            'label': '种子限速方式',
                                            'items': [
                                                {'title': '按标签限速', 'value': '标签'},
                                                {'title': '所有种子限速', 'value': '所有种子'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {'cols': 12, 'md': 6},
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'torrent_speed',
                                            'label': '每个种子上传限速(KiB/s)',
                                            'type': 'number',
                                            'min': 0,
                                            'step': 1,
                                            'hint': '仅所有种子模式生效，0 表示取消种子限速',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VSwitch',
                                        'props': {
                                            'model': 'new_only',
                                            'label': '仅处理新增种子',
                                            'hint': '仅所有种子模式生效。首次无记录时只记录现有种子，后续处理新出现的种子；关闭则每次处理全部种子。',
                                            'persistent-hint': True
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {'cols': 12},
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '所有种子模式逐个设置上传上限，不使用标签规则，不修改下载器全局限速。新增筛选适用于计划任务、固定间隔和运行一次；记录按下载器保存，重启后保留。覆盖模式关闭时跳过已有限速的种子；开启后覆盖已有上限。修改速度后若要应用到旧种子，请关闭新增筛选并开启覆盖模式。'
                                        }
                                    }
                                ]
                            }
                        ]
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'interval',
                                            'label': '定时任务',
                                            'items': [
                                                {'title': '禁用', 'value': '禁用'},
                                                {'title': '计划任务', 'value': '计划任务'},
                                                {'title': '固定间隔', 'value': '固定间隔'}
                                            ]
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'interval_cron',
                                            'label': '计划任务设置',
                                            'placeholder': '0 13 * * *'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VTextField',
                                        'props': {
                                            'model': 'interval_time',
                                            'label': '时间间隔, 每',
                                            'placeholder': '24'
                                        }
                                    }
                                ]
                            },
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 6,
                                    'md': 3,
                                },
                                'content': [
                                    {
                                        'component': 'VSelect',
                                        'props': {
                                            'model': 'interval_unit',
                                            'label': '单位',
                                            'items': [
                                                {'title': '小时', 'value': '小时'},
                                                {'title': '分钟', 'value': '分钟'}
                                            ]
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
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "global_speed",
                                            "label": "全局上传限速(KiB/s)",
                                            "rows": 1,
                                            "placeholder": "如:100",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        "component": "VRow",
                        "content": [
                            {
                                "component": "VCol",
                                "props": {
                                    "cols": 12
                                },
                                "content": [
                                    {
                                        "component": "VTextarea",
                                        "props": {
                                            "model": "tag_map",
                                            "label": "标签:上传限速(KiB/s)",
                                            "rows": 5,
                                            "placeholder": "如:XX:50\nYY:100",
                                        },
                                    }
                                ],
                            }
                        ],
                    },
                    {
                        'component': 'VRow',
                        'content': [
                            {
                                'component': 'VCol',
                                'props': {
                                    'cols': 12
                                },
                                'content': [
                                    {
                                        'component': 'VAlert',
                                        'props': {
                                            'type': 'info',
                                            'variant': 'tonal',
                                            'text': '速度单位统一为 KiB/s（1 KiB/s = 1024 字节/秒）。标签规则每行一条，越靠上优先级越高，使用英文冒号，0 为不限速；留空则不按标签限速。'
                                        }
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ], {
            "enabled": False,
            "onlyonce": False,
            "cover": False,
            "global": False,
            "interval": "计划任务",
            "interval_cron": "0 13 * * *",
            "interval_time": "24",
            "interval_unit": "小时",
            "global_speed": "0",
            "limit_mode": "标签",
            "torrent_speed": "1000",
            "new_only": False,
            "tag_map": ""
        }

    def get_page(self) -> List[dict]:
        pass

    def stop_service(self):
        try:
            if self._scheduler:
                self._scheduler.remove_all_jobs()
                if self._scheduler.running:
                    self._event.set()
                    self._scheduler.shutdown()
                    self._event.clear()
                self._scheduler = None
        except Exception as e:
            print(str(e))
