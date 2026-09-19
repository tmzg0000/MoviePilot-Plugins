"""Telegram command submission for MoviePilot."""
from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Target:
    bot: str
    command: str


@dataclass
class Submission:
    bot: str
    command: str
    status: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def parse_targets(raw: str) -> list[Target]:
    targets = []
    for item in (part.strip() for part in (raw or "").split(",")):
        if not item:
            continue
        bot, separator, command = item.partition(":")
        if bot.strip():
            targets.append(Target(bot.strip(), (command.strip() if separator else "") or "/qd"))
    return targets


def moviepilot_proxy(proxy_map: Mapping[str, Any] | None) -> tuple | None:
    """Convert MoviePilot's HTTP proxy mapping for Telethon/PySocks."""
    value = (proxy_map or {}).get("https") or (proxy_map or {}).get("http") if isinstance(proxy_map, Mapping) else None
    if not isinstance(value, str) or not value.strip():
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() != "http" or not parsed.hostname or not parsed.port:
        return None
    import socks
    return (socks.HTTP, parsed.hostname, parsed.port, True, parsed.username, parsed.password)


async def submit_commands(*, api_id: int, api_hash: str, session_string: str,
                          targets: Sequence[Target], proxy: tuple | None = None,
                          delay: Callable[[int, int], int] = random.randint,
                          sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep) -> list[Submission]:
    """Send every command once; stop after global or ambiguous failures."""
    from telethon import TelegramClient
    from telethon.errors import RPCError
    from telethon.sessions import StringSession
    client = TelegramClient(StringSession(session_string), api_id, api_hash, proxy=proxy)
    results: list[Submission] = []
    try:
        await client.start()
        for target in targets:
            try:
                await client.send_message(target.bot, target.command)
            except RPCError:
                results.append(Submission(target.bot, target.command, "global_failed", "Telegram 拒绝了本次请求，已停止后续发送"))
                break
            except Exception:
                results.append(Submission(target.bot, target.command, "unconfirmed", "发送结果不确定，已停止后续发送以避免重复"))
                break
            else:
                results.append(Submission(target.bot, target.command, "submitted", "消息发送调用已完成"))
            await sleep(delay(2, 5))
    except Exception:
        if not results:
            results.append(Submission("配置", "", "global_failed", "无法建立 Telegram 会话或配置无效"))
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return results
