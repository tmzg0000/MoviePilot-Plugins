"""MoviePilot V2/V3 download traffic cycles using one configured downloader."""
from datetime import datetime, timedelta
from threading import Event, Lock
from time import time
from zoneinfo import ZoneInfo
from pathlib import PurePosixPath

from apscheduler.triggers.interval import IntervalTrigger
try:
    from app.sdk.plugin import _PluginBase
    from app.sdk.logging import logger
    from app.sdk.config import settings
    from app.sdk.services import DownloaderHelper
    from app.sdk import scheduler as scheduler_sdk
except ImportError:
    from app.plugins import _PluginBase
    from app.log import logger
    from app.core.config import settings
    from app.helper.downloader import DownloaderHelper
    scheduler_sdk = None

from .core import Client, ConfigError, Runner, fresh, number, scan


DEFAULTS = {'enabled': False, 'downloader': '', 'torrent_path': '', 'save_path': '',
            'target_gb': 100, 'tag': '刷下载', 'seed_minutes': 15, 'readd_minutes': 15,
            'check_minutes': 10, 'finish_mode': 'graceful', 'history_days': 5, 'reset': False}


class DownloadBooster(_PluginBase):
    plugin_name = '刷下载'
    plugin_desc = '循环下载本地种子，做种到时删除数据，达到累计下载目标后停止。'
    plugin_icon = 'Youtube-dl_A.png'
    plugin_version = '1.0.3'
    plugin_author = 'tmzg0000'
    author_url = 'https://github.com/tmzg0000/MoviePilot-Plugins'
    plugin_config_prefix = 'downloadbooster_'
    plugin_order = 40
    auth_level = 2

    def init_plugin(self, config=None):
        if not hasattr(self, '_lock'):
            self._lock = Lock()
            self._scheduler = None
        self.stop_service()
        self._stop = Event()
        self._config = dict(DEFAULTS, **(config or {}))
        self._invalid = False
        try:
            for key in ('target_gb', 'seed_minutes', 'readd_minutes', 'check_minutes', 'history_days'):
                self._config[key] = number(self._config[key], 0.001 if key == 'target_gb' else 1 if key in ('check_minutes', 'history_days') else 0)
            days = number(self._config['history_days'], 1)
            if days != int(days):
                raise ConfigError('日志保留天数必须为大于等于1的整数')
            self._config['history_days'] = int(days)
            if self._config['finish_mode'] not in ('graceful', 'immediate'):
                raise ConfigError('达到目标后的处理选项无效')
            for key in ('downloader', 'torrent_path', 'save_path', 'tag'):
                self._config[key] = str(self._config[key] or '').strip()
            if self._config['enabled'] or self._config['reset']:
                if any(not self._config[k] for k in ('downloader', 'torrent_path', 'save_path', 'tag')):
                    raise ConfigError('请填写下载器、种子目录、数据保存目录及标签')
                path = PurePosixPath(self._config['save_path'])
                if not path.is_absolute() or '..' in path.parts or str(path) == '/':
                    raise ConfigError('数据保存目录必须是下载器内的专用绝对路径，且不能为根目录')
                if ',' in self._config['tag']:
                    raise ConfigError('请填写一个不含英文逗号的标签')
        except ConfigError as error:
            self._invalid = True
            logger.error(f'刷下载：{error}')
        if not self._invalid and (self._config['enabled'] or self._config['reset']):
            self._queue_once()

    def _queue_once(self):
        if scheduler_sdk is not None:
            if not scheduler_sdk.add_plugin_once_job(self.__class__.__name__, 'downloadbooster_start',
                                                     self.run_task, '刷下载启动检查', delay_seconds=3):
                logger.error('刷下载：宿主未能安排启动检查')
            return
        from apscheduler.schedulers.background import BackgroundScheduler
        self._scheduler = BackgroundScheduler(timezone=settings.TZ)
        self._scheduler.add_job(self.run_task, trigger='date',
                                run_date=datetime.now(ZoneInfo(settings.TZ)) + timedelta(seconds=3),
                                misfire_grace_time=120)
        self._scheduler.start()

    def get_state(self):
        return bool(getattr(self, '_config', {}).get('enabled')) and not self._invalid

    def get_service(self):
        if not self.get_state():
            return []
        return [{'id': f'{self.__class__.__name__}.Check', 'name': '刷下载循环检查',
                 'trigger': IntervalTrigger(minutes=self._config['check_minutes'], timezone=settings.TZ),
                 'func': self.run_task, 'kwargs': {}}]

    def run_task(self):
        if self._invalid or not self._lock.acquire(blocking=False):
            return
        config, stop = dict(self._config), self._stop
        try:
            if stop.is_set() or not (config['enabled'] or config['reset']):
                return
            helper = DownloaderHelper()
            services = helper.get_services(name_filters=[config['downloader']]) or {}
            service = next((s for s in services.values() if s.name == config['downloader']), None)
            if not service or service.type not in ('qbittorrent', 'transmission'):
                raise ConfigError('所选下载器不可用，仅支持 qBittorrent / Transmission')
            state = self.get_data('progress') or fresh()
            binding = [service.name, service.type]
            if state.get('binding') and state['binding'] != binding:
                if any(r['phase'] != 'cooldown' for r in state['tasks'].values()) or not config['reset']:
                    raise ConfigError('进度绑定其他下载器，请先在原下载器清理本插件任务，再选择新下载器并重置')
                state = fresh()
            state['binding'] = binding
            client = Client(service)
            runner = Runner(config, state, client, lambda value: self.save_data('progress', value),
                            time, stopped=stop.is_set)
            if config['reset']:
                runner.reset()
                config['reset'] = False
                if self._config is not None and self._stop is stop:
                    self._config['reset'] = False
                    self.update_config(self._config)
            if not config['enabled'] or stop.is_set():
                if not stop.is_set():
                    self._record('已重置', '统计已清零，插件未启用', state)
                return
            # Cleanup must continue even if the source folder was moved or removed.
            try:
                sources, errors = scan(config['torrent_path']) if not state['reached'] else ({}, [])
            except ConfigError as error:
                sources, errors = {}, [str(error)]
            runner.run(sources)
            messages = errors + runner.messages
            status = '已完成' if state['finished'] else '达标清理中' if state['reached'] else '运行中'
            self._record(status, '；'.join(messages[-10:]) or '检查完成', state, runner.report)
            logger.info(f"刷下载：{status}，累计 {state['total'] / 1024 ** 3:.3f} GiB")
            for message in messages:
                logger.warning(f'刷下载：{message}')
        except ConfigError as error:
            self._error(str(error))
        except Exception as error:
            # Native exceptions may include tracker passkeys, credentials or HTTP bodies.
            self._error(f'下载器请求或进度保存失败（{type(error).__name__}），下次检查重试')
        finally:
            self._lock.release()

    def _error(self, message):
        logger.error(f'刷下载：{message}')
        self._record('等待处理', message)

    def _history(self, now, prune=False):
        history = self.get_data('history') or []
        cutoff = now - self._config['history_days'] * 86400
        kept = [row for row in history if row['timestamp'] >= cutoff]
        if prune and len(kept) != len(history):
            self.save_data('history', kept)
        return kept

    def _record(self, status, message, state=None, report=None):
        """Called under the run lock: append every actual check, including failures."""
        now = time()
        state = state if state is not None else self.get_data('progress') or fresh()
        report = report or {}
        checked = datetime.fromtimestamp(now, ZoneInfo(settings.TZ)).isoformat(timespec='seconds')
        row = {'timestamp': now, 'checked': checked, 'status': status, 'message': message,
               'total_gb': f"{state['total'] / 1024 ** 3:.3f}",
               'added': report.get('added', 0), 'deleted': report.get('deleted', 0),
               'managed': sum(r['phase'] != 'cooldown' for r in state['tasks'].values())}
        history = self._history(now)
        history.insert(0, row)
        self.save_data('history', history)
        self.save_data('status', {'status': status, 'checked': checked, 'message': message})

    def get_form(self):
        try:
            options = [{'title': c.name, 'value': c.name} for c in DownloaderHelper().get_configs().values()
                       if c.type in ('qbittorrent', 'transmission')]
        except Exception:
            options = []
        fields = [
            {'component': 'VSwitch', 'props': {'model': 'enabled', 'label': '启用插件'}},
            {'component': 'VSwitch', 'props': {'model': 'reset', 'label': '重置统计并开始新一轮（保存后执行）'}},
            {'component': 'VSelect', 'props': {'model': 'downloader', 'label': 'MP 下载器（单选）', 'items': options}},
        ]
        for key, label in [('torrent_path', '种子文件夹（MP容器内，扫描本层 .torrent）'),
                           ('save_path', '数据保存目录（下载器内的绝对路径）'), ('tag', '任务标签'),
                           ('target_gb', '目标下载量（GiB，1G=1024³字节）'),
                           ('seed_minutes', '下载完成后保留做种时间（分钟）'),
                           ('readd_minutes', '确认删除后重新添加间隔（分钟）'),
                           ('check_minutes', '检查间隔（分钟）'),
                           ('history_days', '日志保留天数（超期自动删除）')]:
            props = {'model': key, 'label': label}
            if key in ('target_gb', 'seed_minutes', 'readd_minutes', 'check_minutes', 'history_days'):
                props.update(type='number', min=0.001 if key == 'target_gb' else 1 if key in ('check_minutes', 'history_days') else 0)
            fields.append({'component': 'VTextField', 'props': props})
        fields += [
            {'component': 'VSelect', 'props': {'model': 'finish_mode', 'label': '达到目标后的处理', 'items': [
                {'title': '现有任务完成下载、做种后删除数据', 'value': 'graceful'},
                {'title': '立即删除本插件任务及数据', 'value': 'immediate'}]}},
            {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal', 'text':
                '所有种子同时添加；每轮使用独立数据子目录，删除任务时同时删除数据，保留源种子。'
                '设置的标签是唯一管理依据：所有带此标签的任务均会统计、到时删除任务及数据；不带此标签的已有任务跳过。达标后停止添加，检查间隔可能导致超量。'
                '关闭插件暂停管理，不清理下载器任务；重新开启继续进度。重置统计保留已有任务及等待时间。'}}]
        return [{'component': 'VForm', 'content': fields}], dict(DEFAULTS)

    def get_page(self):
        state = self.get_data('progress') or fresh()
        status = self.get_data('status') or {}
        text = (f"状态：{status.get('status', '尚未运行')}；累计下载：{state['total'] / 1024 ** 3:.3f} GiB；"
                f"上次检查：{status.get('checked', '—')}。{status.get('message', '')}")
        items = [{'component': 'VAlert', 'props': {'type': 'info', 'text': text}}]
        phases = {'adding': '等待添加确认', 'active': '下载／做种中', 'deleting': '等待删除确认', 'cooldown': '等待重新添加'}
        for hash_value, record in state['tasks'].items():
            items.append({'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal', 'text':
                f"{record.get('name', hash_value)}：{phases.get(record['phase'], record['phase'])}；本轮已下载 {record.get('last', 0) / 1024 ** 3:.3f} GiB"}})
        acquired = self._lock.acquire(blocking=False)
        try:
            history = self._history(time(), prune=acquired)
        finally:
            if acquired:
                self._lock.release()
        columns = [('检查时间', 'checked'), ('状态', 'status'), ('累计下载 GiB', 'total_gb'),
                   ('本次提交添加', 'added'), ('本次确认移除', 'deleted'),
                   ('管理中任务', 'managed'), ('检查说明', 'message')]
        items.append({'component': 'div', 'props': {'class': 'text-subtitle-1 mt-4 mb-2'},
                      'text': f'检查记录（{len(history)} 条，保留 {self._config["history_days"]} 天）'})
        # MP supplies the dynamic component's default slot, hiding VDataTable's
        # generated header/body. Explicit children work with the host renderer.
        if history:
            items.append({'component': 'VTable', 'props': {
                'density': 'compact', 'height': 420, 'fixed-header': True, 'hover': True}, 'content': [
                    {'component': 'thead', 'content': [{'component': 'tr', 'content': [
                        {'component': 'th', 'props': {'style': 'white-space: nowrap'}, 'text': title}
                        for title, _ in columns]}]},
                    {'component': 'tbody', 'content': [{'component': 'tr', 'content': [
                        {'component': 'td', 'props': {'style': 'white-space: nowrap'},
                         'text': str(row.get(key, '—'))} for _, key in columns]} for row in history]},
                ]})
        else:
            items.append({'component': 'VAlert', 'props': {
                'type': 'info', 'variant': 'tonal', 'text': '暂无检查记录'}})
        return items

    @staticmethod
    def get_command():
        return []

    def get_api(self):
        return []

    def stop_service(self):
        if hasattr(self, '_stop'):
            self._stop.set()
        if scheduler_sdk is not None:
            scheduler_sdk.remove_plugin_once_job(self.__class__.__name__, 'downloadbooster_start')
        if getattr(self, '_scheduler', None):
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
