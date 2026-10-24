"""Tracker text rules and native downloader operations, adapted from honue's TrackerEditor."""
from collections import OrderedDict
from urllib.parse import urlsplit


class ConfigError(ValueError):
    """A locally generated validation error safe to display to the user."""


def parse_rules(text):
    """Validate every rule before any downloader connection is opened."""
    rules = []
    for number, line in enumerate(str(text or "").splitlines(), 1):
        if not line.strip():
            continue
        if line.count("|") != 1:
            raise ConfigError(f"第 {number} 行应为：待替换文本|新文本")
        old, new = (part.strip() for part in line.split("|", 1))
        if not old or not new or old == new:
            raise ConfigError(f"第 {number} 行两侧不能为空，且必须不同")
        rules.append((old, new))
    if not rules:
        raise ConfigError("请填写至少一条有效的 Tracker 替换规则")
    return rules


def replace_url(url, rules):
    """Apply the first matching literal rule once, without cascading replacements."""
    if not url.startswith(("http://", "https://", "udp://", "ws://", "wss://")):
        return url
    for old, new in rules:
        if old in url:
            return url.replace(old, new)
    return url


def connection_address(host, port, downloader_type):
    """Normalize a hostname or HTTP(S) URL while preserving a Transmission RPC path."""
    address = urlsplit(host if "://" in host else "http://" + host)
    if address.scheme not in ("http", "https") or not address.hostname:
        raise ConfigError("下载器地址必须是主机名、IP 或 HTTP(S) URL")
    if address.username or address.password or address.query or address.fragment:
        raise ConfigError("请在独立字段填写用户名和密码，地址不要包含凭据、查询或片段")
    try:
        number = int(port) if port not in (None, "") else address.port
    except (TypeError, ValueError):
        raise ConfigError("下载器端口无效") from None
    if number is None:
        number = (443 if address.scheme == "https" else
                  9091 if downloader_type == "transmission" else 8080)
    if not 1 <= number <= 65535:
        raise ConfigError("下载器端口必须介于 1 与 65535 之间")
    return address, number


def open_client(config):
    """Connect without calling MoviePilot wrappers that synchronize global preferences."""
    kind = config["downloader_type"]
    if kind not in ("qbittorrent", "transmission"):
        raise ConfigError("不支持的下载器类型")
    address, port = connection_address(config["host"], config["port"], kind)
    credentials = {key: config[key] for key in ("username", "password")}
    if kind == "qbittorrent":
        from qbittorrentapi import Client
        # Keep the scheme, optional IPv6 brackets and any reverse-proxy prefix.
        hostname = address.hostname
        if ":" in hostname:
            hostname = f"[{hostname}]"
        host = f"{address.scheme}://{hostname}:{port}{address.path.rstrip('/')}"
        client = Client(host=host, REQUESTS_ARGS={"timeout": (10, 30)}, **credentials)
        client.auth_log_in()
        return client
    from transmission_rpc import Client
    hostname = address.hostname
    if ":" in hostname:
        hostname = f"[{hostname}]"
    return Client(host=hostname, port=port, protocol=address.scheme,
                  path=address.path.rstrip("/") or "/transmission/rpc", timeout=30,
                  **credentials)


def torrent_list(client, kind):
    """Fetch only the Transmission fields needed for replacements and preserve tiers."""
    if kind == "qbittorrent":
        return client.torrents_info()
    session = client.get_session()
    if int(str(session.version).split(".", 1)[0]) < 4:
        raise ConfigError("Transmission 需要 4.0 或以上版本")
    return client.get_torrents(arguments=["id", "hashString", "trackers"])


def edit_torrent(client, kind, torrent, rules, on_change):
    """Report each acknowledged edit, including partial qBittorrent success before an error."""
    if kind == "qbittorrent":
        for tracker in client.torrents_trackers(torrent_hash=torrent.hash):
            old = tracker.url
            new = replace_url(old, rules)
            if old != new:
                client.torrents_edit_tracker(torrent_hash=torrent.hash, original_url=old, new_url=new)
                on_change(1)
        return
    tiers = OrderedDict()
    changes = 0
    for tracker in torrent.trackers:
        old = tracker.announce
        new = replace_url(old, rules)
        tiers.setdefault(tracker.tier, []).append(new)
        changes += old != new
    if changes:
        client.change_torrent(ids=torrent.hash_string, tracker_list=list(tiers.values()))
        on_change(changes)
