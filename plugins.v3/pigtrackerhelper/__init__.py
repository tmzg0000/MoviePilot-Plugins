"""Update Piggo trackers from newly downloaded torrent files."""
from datetime import datetime, timedelta
from threading import Event, Lock
from zoneinfo import ZoneInfo

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

from .core import scan, update


class PigTrackerHelper(_PluginBase):
    plugin_name = '猪猪Tracker更新助手'
    plugin_desc = '根据新种文件更新所选下载器中对应种子的 piggo.me Tracker。'
    plugin_icon = 'https://raw.githubusercontent.com/tmzg0000/MoviePilot-Plugins/main/icons/trackereditor_A.png'
    plugin_version = '1.0.2'
    plugin_author = 'tmzg0000'
    author_url = 'https://github.com/tmzg0000/MoviePilot-Plugins'
    plugin_config_prefix = 'pigtrackerhelper_'
    plugin_order = 31
    auth_level = 1

    def init_plugin(self, config=None):
        if not hasattr(self, '_lock'):
            self._lock, self._stop, self._scheduler = Lock(), Event(), None
        self.stop_service()
        self._stop = Event()
        config = config or {}
        self._config = {'onlyonce': False, 'downloaders': config.get('downloaders') or [],
                        'torrent_path': str(config.get('torrent_path') or '/config/plugins/PigTrackerHelper').strip()}
        try:
            from pathlib import Path
            Path(self._config['torrent_path']).mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning('猪猪Tracker更新助手：无法创建种子目录，请检查路径和权限')
        if config.get('onlyonce'):
            self.update_config(self._config)
            if scheduler_sdk is not None:
                if not scheduler_sdk.add_plugin_once_job('PigTrackerHelper', 'pigtrackerhelper_once', self.task,
                                                         '猪猪Tracker更新助手', delay_seconds=3):
                    logger.error('猪猪Tracker更新助手：无法安排立即执行任务')
            else:
                from apscheduler.schedulers.background import BackgroundScheduler
                self._scheduler = BackgroundScheduler(timezone=settings.TZ)
                self._scheduler.add_job(self.task, trigger='date', run_date=datetime.now(ZoneInfo(settings.TZ)) + timedelta(seconds=3))
                self._scheduler.start()

    def task(self):
        if not self._lock.acquire(blocking=False):
            return
        config, stop = dict(self._config), self._stop
        report = {'matched': 0, 'updated': 0, 'failed': 0, 'errors': 0, 'conflicts': 0, 'message': '执行完成'}
        try:
            if not config['downloaders']:
                raise ValueError('请选择下载器')
            sources, report['errors'], report['conflicts'] = scan(config['torrent_path'])
            services = DownloaderHelper().get_services(name_filters=config['downloaders']) or {}
            by_name = {service.name: service for service in services.values()}
            for name in config['downloaders']:
                if stop.is_set():
                    report['message'] = '任务已停止'
                    break
                try:
                    service = by_name[name]
                    matched, updated, failed = update(service, sources, stop.is_set)
                    report['matched'] += matched
                    report['updated'] += updated
                    report['failed'] += failed
                except Exception:
                    report['failed'] += 1
                    logger.warning(f'猪猪Tracker更新助手：下载器 {name} 处理失败')
            if report['failed'] or report['errors'] or report['conflicts']:
                report['message'] = '执行完成，部分项目未处理，请检查日志和统计'
        except ValueError as error:
            report['message'] = str(error)
        except Exception:
            report['message'] = '目录读取或下载器查询失败，请检查配置和权限'
        finally:
            report['ran_at'] = datetime.now(ZoneInfo(settings.TZ)).strftime('%Y-%m-%d %H:%M:%S')
            self.save_data('latest', report)
            logger.info(f"猪猪Tracker更新助手：{report['message']}，匹配 {report['matched']}，更新 {report['updated']}，失败 {report['failed']}，无效文件 {report['errors']}，冲突 {report['conflicts']}")
            self._lock.release()

    def get_state(self):
        return False

    def get_service(self):
        return []

    @staticmethod
    def get_command():
        return []

    def get_api(self):
        return []

    def get_form(self):
        try:
            options = [{'title': c.name, 'value': c.name} for c in DownloaderHelper().get_configs().values()
                       if c.type in ('qbittorrent', 'transmission')]
        except Exception:
            options = []
        def field(component, model, label, **props):
            return {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                {'component': component, 'props': {'model': model, 'label': label, **props}}]}
        return [{'component': 'VForm', 'content': [{'component': 'VRow', 'content': [
            field('VSwitch', 'onlyonce', '保存后立即运行一次'),
            field('VSelect', 'downloaders', '下载器', items=options, multiple=True, chips=True),
            field('VTextField', 'torrent_path', '新种目录（包括子目录）'),
            {'component': 'VCol', 'props': {'cols': 12}, 'content': [
                {'component': 'VAlert', 'props': {'type': 'info', 'variant': 'tonal'}, 'content': [
                    {'component': 'span', 'text': '也可以先去猪猪'},
                    {'component': 'a', 'props': {'href': 'https://piggo.me/usercp', 'target': '_blank', 'rel': 'noopener noreferrer'}, 'text': '个人中心'},
                    {'component': 'span', 'text': '，点击“仍用密钥汇报的种子”，将仍使用旧密钥汇报的种子打包下载，解压到新种目录后再替换。该入口为临时入口，生成前建议先强制汇报，等待 5 分钟后再使用。'}
                ]}]},
            {'component': 'VCol', 'props': {'cols': 12}, 'content': [{'component': 'VAlert', 'props': {
                'type': 'info', 'variant': 'tonal', 'text': '按种子 info hash 匹配，使用新种中的 piggo.me 地址更新已有种子；同一 hash 的新种地址冲突时跳过。支持 qBittorrent 和 Transmission。'}}]}
        ]}]}], dict(self._config, onlyonce=True)

    def get_page(self):
        report = self.get_data('latest')
        if not report:
            return [{'component': 'VAlert', 'props': {'type': 'info', 'text': '暂无执行记录'}}]
        rows = [('执行时间', report['ran_at']), ('结果', report['message']), ('匹配种子数', report['matched']),
                ('更新种子数', report['updated']), ('失败数', report['failed']), ('无效文件数', report['errors']), ('冲突种子数', report['conflicts'])]
        return [{'component': 'VTable', 'content': [{'component': 'tbody', 'content': [
            {'component': 'tr', 'content': [{'component': 'td', 'text': str(value)} for value in row]} for row in rows]}]}]

    def stop_service(self):
        self._stop.set()
        if scheduler_sdk is not None:
            scheduler_sdk.remove_plugin_once_job('PigTrackerHelper', 'pigtrackerhelper_once')
        if self._scheduler:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
