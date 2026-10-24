"""Durable download cycles. No MoviePilot imports; adapters use native clients."""
from hashlib import sha1
from pathlib import Path, PurePosixPath
import math
import uuid


class ConfigError(ValueError):
    pass


def number(value, minimum=0):
    try:
        result = float(value)
        if not math.isfinite(result) or result < minimum:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise ConfigError("配置数值无效") from None


def torrent_hash(data):
    """Hash the original encoded info slice, never a re-encoded dictionary."""
    pos = 0
    info = None

    def parse(depth=0):
        nonlocal pos, info
        if depth > 80 or pos >= len(data):
            raise ValueError
        start = pos
        token = data[pos:pos + 1]
        pos += 1
        if token == b'i':
            end = data.index(b'e', pos)
            result = int(data[pos:end])
            pos = end + 1
            return result
        if token in (b'd', b'l'):
            result = {} if token == b'd' else []
            while data[pos:pos + 1] != b'e':
                if token == b'd':
                    key = parse(depth + 1)
                    if not isinstance(key, bytes) or key in result:
                        raise ValueError
                    begin = pos
                    result[key] = parse(depth + 1)
                    if depth == 0 and key == b'info':
                        info = data[begin:pos]
                else:
                    result.append(parse(depth + 1))
            pos += 1
            return result
        if token.isdigit():
            colon = data.index(b':', start)
            size = int(data[start:colon])
            pos = colon + 1 + size
            if size < 0 or pos > len(data):
                raise ValueError
            return data[colon + 1:pos]
        raise ValueError

    try:
        root = parse()
        meta = root[b'info']
        if pos != len(data) or not info or not isinstance(meta, dict) or b'pieces' not in meta:
            raise ValueError
        return sha1(info).hexdigest()
    except (ValueError, IndexError, KeyError, TypeError, RecursionError):
        raise ConfigError("种子无效或为纯 BT v2 种子（目前支持 v1 / hybrid）") from None


def scan(directory):
    folder = Path(directory)
    if not folder.is_dir():
        raise ConfigError("种子文件目录不存在或不可访问")
    result, errors = {}, []
    for path in sorted(folder.iterdir()):
        if path.suffix.lower() != '.torrent' or not path.is_file():
            continue
        try:
            with path.open('rb') as stream:
                data = stream.read(16 * 1024 * 1024 + 1)
            if len(data) > 16 * 1024 * 1024:
                raise ConfigError("种子文件超过16MiB")
            result.setdefault(torrent_hash(data), (path.name, data))
        except (OSError, ConfigError) as error:
            errors.append(f"{path.name}: {error}")
    return result, errors


class Client:
    def __init__(self, service):
        self.kind = service.type
        instance = service.instance
        self.api = instance.qbc if self.kind == 'qbittorrent' else instance.trc
        if not self.api:
            raise ConfigError("下载器未连接")

    def list(self):
        if self.kind == 'qbittorrent':
            rows = self.api.torrents_info()
            return {t.hash.lower(): {
                'downloaded': int(t.downloaded), 'complete': float(t.progress) >= 1,
                'completed': int(t.completion_on), 'path': t.save_path.rstrip('/'),
                'tags': {x.strip() for x in t.tags.split(',')},
            } for t in rows}
        rows = self.api.get_torrents(arguments=[
            'id', 'hashString', 'downloadedEver', 'percentDone', 'doneDate', 'downloadDir', 'labels'])
        return {t.hash_string.lower(): {
            'downloaded': int(t.downloaded_ever), 'complete': float(t.percent_done) >= 1,
            'completed': t.done_date.timestamp() if t.done_date else 0,
            'path': t.download_dir.rstrip('/'), 'tags': set(t.labels),
        } for t in rows}

    def add(self, data, record):
        if self.kind == 'qbittorrent':
            result = self.api.torrents_add(torrent_files=data, save_path=record['path'],
                                          tags=','.join(record['tags']), use_auto_torrent_management=False,
                                          is_paused=False)
            if str(result).lower() != 'ok.':
                raise ConfigError("下载器未接受添加请求")
        else:
            self.api.add_torrent(torrent=data, download_dir=record['path'],
                                 labels=record['tags'], paused=False)

    def delete(self, hash_value):
        if self.kind == 'qbittorrent':
            self.api.torrents_delete(torrent_hashes=hash_value, delete_files=True)
        else:
            self.api.remove_torrent(ids=hash_value, delete_data=True)


def owns(record, torrent):
    return record['marker'] in torrent['tags'] and record['path'] == torrent['path']


def fresh():
    return {'total': 0, 'reached': False, 'finished': False, 'tasks': {}}


class Runner:
    def __init__(self, config, state, client, save, now, stopped=lambda: False):
        self.config, self.state, self.client = config, state, client
        self.save, self.stopped = save, stopped
        self.clock = now if callable(now) else lambda: now
        self.messages = []

    @property
    def now(self):
        return self.clock()

    def checkpoint(self):
        self.save(self.state)

    def reset(self):
        # Keep ownership and cooldowns. Only bytes observed after this point count.
        torrents = self.client.list()
        for hash_value, record in self.state['tasks'].items():
            torrent = torrents.get(hash_value)
            if torrent and owns(record, torrent):
                record['last'] = torrent['downloaded']
        self.state.update(total=0, reached=False, finished=False)
        self.checkpoint()

    def run(self, sources):
        state, config = self.state, self.config
        torrents = self.client.list()  # A failed list must never be treated as an empty downloader.
        tasks = state['tasks']
        for hash_value, record in tasks.items():
            if self.stopped():
                return
            torrent = torrents.get(hash_value)
            phase = record['phase']
            if phase == 'cooldown':
                continue
            if torrent is None:
                # A pending add may be asynchronous or have an ambiguous network outcome.
                # Retry only while absent; keep the same unique marker and isolated directory.
                if phase == 'adding':
                    continue
                record.update(phase='cooldown', deleted=self.now)
                self.checkpoint()
                continue
            if not owns(record, torrent):
                self.messages.append(f"任务身份不匹配，跳过：{hash_value}")
                continue
            current = torrent['downloaded']
            state['total'] += max(0, current - record.get('last', 0))
            record['last'] = current
            if phase == 'adding':
                record['phase'] = 'active'
            if torrent['complete']:
                if not record.get('completed'):
                    stamp = torrent['completed']
                    record['completed'] = stamp if 0 < stamp <= self.now else self.now
            else:
                record['completed'] = None
        if state['total'] >= config['target_gb'] * 1024 ** 3:
            state['reached'] = True  # Latched until explicit reset, even if the target is later raised.
        self.checkpoint()

        for hash_value, record in list(tasks.items()):
            if self.stopped():
                return
            torrent = torrents.get(hash_value)
            if not torrent or not owns(record, torrent):
                continue
            due = record.get('completed') is not None and self.now - record['completed'] >= config['seed_minutes'] * 60
            if record['phase'] == 'deleting' or due or (state['reached'] and config['finish_mode'] == 'immediate'):
                record['phase'] = 'deleting'
                self.checkpoint()  # Persist intent before sending any destructive request.
                try:
                    self.client.delete(hash_value)
                    # Only confirmed absence starts the cooldown.
                    if hash_value not in self.client.list():
                        record.update(phase='cooldown', deleted=self.now)
                        self.checkpoint()
                except Exception:
                    self.messages.append(f"删除未确认，后续检查重试：{hash_value}")
        if state['reached']:
            state['finished'] = all(r['phase'] == 'cooldown' for r in tasks.values())
            self.checkpoint()
            return

        for hash_value, (name, data) in sources.items():
            if self.stopped():
                return
            record = tasks.get(hash_value)
            if record and record['phase'] not in ('cooldown', 'adding'):
                continue
            if record and record['phase'] == 'cooldown' and self.now - record['deleted'] < config['readd_minutes'] * 60:
                continue
            # Recheck immediately before adding; never adopt an already existing hash.
            existing = self.client.list().get(hash_value)
            if existing:
                if not record or not owns(record, existing):
                    self.messages.append(f'已有同哈希任务，跳过：{name}')
                continue
            if not record or record['phase'] == 'cooldown':
                marker = 'mp-downloadbooster-' + uuid.uuid4().hex
                record = {'phase': 'adding', 'marker': marker, 'tags': [config['tag'], marker],
                          'path': str(PurePosixPath(config['save_path']) / marker),
                          'last': 0, 'completed': None, 'name': name}
                tasks[hash_value] = record
                self.checkpoint()
            try:
                self.client.add(data, record)
                # Remain in adding until a subsequent successful scan proves ownership.
            except Exception:
                self.messages.append(f"添加未确认，后续检查重试：{name}")
        self.checkpoint()
