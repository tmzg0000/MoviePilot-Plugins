"""Offline regression tests for CaptchaSignIn BrowserQL request construction."""

import json
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


CORE = Path(__file__).parents[2] / "plugins.v3" / "captchasignin" / "core.py"
SPEC = spec_from_file_location("captchasignin_core", CORE)
core = module_from_spec(SPEC)
assert SPEC and SPEC.loader
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)


def test_default_browserless_address_and_token_endpoint():
    assert core.DEFAULT_BROWSERLESS_URL == "https://production-sfo.browserless.io"
    assert core.bql_endpoint(core.DEFAULT_BROWSERLESS_URL, "safe token") == (
        "https://production-sfo.browserless.io/stealth/bql?token=safe+token"
    )


def test_cloudflare_rule_uses_auto_detection_for_turnstile_compatibility():
    query = core.build_query({"mode": "cloudflare"})
    assert "solve(timeout:$solveTimeout)" in query
    assert "solve(type:cloudflare" not in query
    assert "waitUntil:domContentLoaded" in query


def test_image_rule_keeps_selector_solver_and_optional_site_user_agent():
    query = core.build_query({"mode": "image"}, "Mozilla/5.0 test")
    assert "solveImageCaptcha(captchaSelector:$captchaSelector" in query
    assert "userAgent(userAgent:$userAgent)" in query
    assert "$userAgent:String!" in query


def test_opencd_ajax_success_is_not_lost_after_html_refresh():
    result = core.classify_ajax_response(
        '{"status": 200, "text": "{\\"state\\": \\"success\\"}"}',
        {"success_json": {"field": "/state", "values": ["success"]}},
    )
    assert result == core.SignResult("success", "签到成功")


def test_signer_sends_site_user_agent_and_auto_cloudflare_query():
    captured = {}

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": {"goto": {"status": 200}, "solve": {"found": True, "solved": True}, "submit": {"value": "true"}, "response": {"value": "null"}, "before": {"html": ""}, "after": {"html": "签到成功"}}}).encode()

    original_urlopen = core.urllib.request.urlopen
    try:
        def fake_urlopen(request, timeout):
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return Response()

        core.urllib.request.urlopen = fake_urlopen
        result = core.BrowserlessSigner("https://browserless.example", "safe-token").sign(
            {"url": "https://pt.example", "cookie": "uid=1", "ua": "Mozilla/5.0 test"},
            {"mode": "cloudflare", "path": "/attendance.php", "submit_selector": "#sign"},
        )
    finally:
        core.urllib.request.urlopen = original_urlopen

    assert result.status == "success"
    assert captured["body"]["variables"]["userAgent"] == "Mozilla/5.0 test"
    assert "solve(timeout:$solveTimeout)" in captured["body"]["query"]
