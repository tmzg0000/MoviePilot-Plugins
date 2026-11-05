"""Read source torrents and update only matching Piggo trackers."""
from hashlib import sha1
from pathlib import Path
from urllib.parse import urlsplit


def is_piggo(url):
    try:
        host = urlsplit(url).hostname or ''
        return host.lower() == 'piggo.me' or host.lower().endswith('.piggo.me')
    except ValueError:
        return False


def read_torrent(data):
    pos = 0
    info = None

    def parse(depth=0):
        nonlocal pos, info
        if depth > 80 or pos >= len(data):
            raise ValueError('invalid torrent')
        start = pos
        token = data[pos:pos + 1]
        pos += 1
        if token == b'i':
            end = data.index(b'e', pos)
            value = int(data[pos:end])
            pos = end + 1
            return value
        if token in (b'd', b'l'):
            value = {} if token == b'd' else []
            while data[pos:pos + 1] != b'e':
                if token == b'd':
                    key = parse(depth + 1)
                    if not isinstance(key, bytes) or key in value:
                        raise ValueError('invalid dictionary')
                    begin = pos
                    value[key] = parse(depth + 1)
                    if depth == 0 and key == b'info':
                        info = data[begin:pos]
                else:
                    value.append(parse(depth + 1))
            pos += 1
            return value
        if token.isdigit():
            colon = data.index(b':', start)
            size = int(data[start:colon])
            pos = colon + 1 + size
            if size < 0 or pos > len(data):
                raise ValueError('invalid string')
            return data[colon + 1:pos]
        raise ValueError('invalid token')

    root = parse()
    if pos != len(data) or not isinstance(root, dict) or not isinstance(root.get(b'info'), dict) or not info or b'pieces' not in root[b'info']:
        raise ValueError('unsupported torrent')
    urls = []
    def add(raw):
        if isinstance(raw, bytes):
            url = raw.decode('utf-8')
            if is_piggo(url) and url not in urls:
                urls.append(url)
    add(root.get(b'announce'))
    tiers = root.get(b'announce-list', [])
    if isinstance(tiers, list):
        for tier in tiers:
            if isinstance(tier, list):
                for url in tier:
                    add(url)
    return sha1(info).hexdigest(), urls


def scan(directory):
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    sources, conflicts, errors = {}, set(), 0
    def onerror(_error):
        nonlocal errors
        errors += 1
    import os
    for base, _, files in os.walk(folder, onerror=onerror):
        for name in sorted(files):
            if not name.lower().endswith('.torrent'):
                continue
            try:
                with (Path(base) / name).open('rb') as stream:
                    data = stream.read(16 * 1024 * 1024 + 1)
                if len(data) > 16 * 1024 * 1024:
                    raise ValueError('too large')
                key, urls = read_torrent(data)
                if not urls:
                    continue
                if key in sources and sources[key] != urls:
                    conflicts.add(key)
                else:
                    sources[key] = urls
            except (OSError, ValueError, TypeError, UnicodeError, RecursionError, IndexError):
                errors += 1
    for key in conflicts:
        sources.pop(key, None)
    return sources, errors, len(conflicts)


def update(service, sources, stopped=lambda: False):
    kind = service.type
    if kind not in ('qbittorrent', 'transmission'):
        raise ValueError('unsupported downloader')
    api = service.instance.qbc if kind == 'qbittorrent' else service.instance.trc
    if not api:
        raise ValueError('downloader unavailable')
    rows = api.torrents_info() if kind == 'qbittorrent' else api.get_torrents(arguments=['id', 'hashString', 'trackers'])
    updated = failed = matched = 0
    for torrent in rows:
        if stopped():
            break
        key = (torrent.hash if kind == 'qbittorrent' else torrent.hash_string).lower()
        if key not in sources:
            continue
        matched += 1
        try:
            urls = sources[key]
            if kind == 'qbittorrent':
                old = [t.url for t in api.torrents_trackers(torrent_hash=key) if is_piggo(t.url)]
                missing = [url for url in urls if url not in old]
                stale = [url for url in old if url not in urls]
                changed = bool(missing or stale)
                if missing:
                    api.torrents_add_trackers(torrent_hash=key, urls='\n'.join(missing))
                if stale:
                    api.torrents_remove_trackers(torrent_hash=key, urls='|'.join(stale))
            else:
                from collections import OrderedDict
                tiers = OrderedDict()
                old = [t.announce for t in torrent.trackers if is_piggo(t.announce)]
                changed = old != urls
                inserted = False
                for tracker in torrent.trackers:
                    tier = tiers.setdefault(tracker.tier, [])
                    if is_piggo(tracker.announce):
                        if not inserted:
                            tier.extend(urls)
                            inserted = True
                    else:
                        tier.append(tracker.announce)
                if not inserted:
                    tiers.setdefault(max(tiers, default=-1) + 1, []).extend(urls)
                    changed = True
                if changed:
                    api.change_torrent(ids=key, tracker_list=[v for v in tiers.values() if v])
            updated += bool(changed)
        except Exception:
            failed += 1
    return matched, updated, failed
