"""Offline regression tests for TelegramAutoSignIn configuration helpers."""

import sys
import types
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


CORE = Path(__file__).parents[2] / "plugins.v3" / "telegramautosignin" / "core.py"
SPEC = spec_from_file_location("telegramautosignin_core", CORE)
core = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


def test_parse_targets_preserves_commands_and_defaults_missing_ones():
    assert core.parse_targets(" @first:/qd, @second:sign, @third ") == [
        core.Target("@first", "/qd"), core.Target("@second", "sign"), core.Target("@third", "/qd"),
    ]


def test_parse_targets_ignores_blank_bot_entries():
    assert core.parse_targets(" , :/qd, @ok:") == [core.Target("@ok", "/qd")]


def test_moviepilot_http_proxy_is_converted_without_exposing_the_source_url():
    previous = sys.modules.get("socks")
    sys.modules["socks"] = types.SimpleNamespace(HTTP="HTTP")
    try:
        assert core.moviepilot_proxy({"https": "http://user:pass@proxy.example:8080"}) == (
            "HTTP", "proxy.example", 8080, True, "user", "pass",
        )
    finally:
        if previous is None:
            del sys.modules["socks"]
        else:
            sys.modules["socks"] = previous


def test_missing_or_unsupported_proxy_returns_direct_connection():
    assert core.moviepilot_proxy({}) is None
    assert core.moviepilot_proxy({"https": "socks5://proxy.example:1080"}) is None
