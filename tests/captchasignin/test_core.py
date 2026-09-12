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


def test_open_page_rule_generates_valid_evaluate_response_shape():
    query = core.build_query({"mode": "open_page"})
    assert "solve:evaluate(content:\"'skipped'\"){value}" in query
    assert "{value}{found solved time}" not in query
    assert "$solveTimeout" not in query
    assert "$submit" not in query
    assert "submit:click(selector:$selector){selector time}" in query


def test_luckpt_accepts_its_confirmation_dialog_and_recognizes_its_result():
    rule = core.resolve_rule(
        {"url": "https://pt.luckpt.de", "id": "luckpt"},
        {"pt.luckpt.de": {"submit_method": "dom_click"}},
    )
    assert rule["submit_method"] == "confirm_click"
    query = core.build_query(rule)
    assert "$submit:String!" in query
    assert "submit:evaluate(content:$submit){value}" in query
    assert "submit:click(selector:$selector)" not in query
    script = core._submit_script(rule["submit_selector"], rule["submit_method"], submit_text=rule["submit_text"])
    assert "button.click()" in script
    assert ".layui-layer-btn0" in script
    assert json.dumps(rule["submit_text"]) in script
    assert core.classify("<p>奖励领取成功</p>", rule).status == "success"
    assert core.classify("<p>今日已领取</p>", rule).status == "already"


def test_yemapt_uses_hash_route_and_native_altcha_click_before_waiting_for_payload():
    rule = core.resolve_rule({"url": "https://www.yemapt.org", "id": "yemapt"}, {})
    assert rule["mode"] == "altcha"
    assert core.target_url("https://www.yemapt.org", rule["path"], rule["route_fragment"]) == (
        "https://www.yemapt.org/#/user/growth?tab=checkIn"
    )
    script = core._altcha_submit_script(rule)
    assert "altchaPayload" in script
    assert "Date.now() + 30000" in script
    assert "ant-btn-primary" in script
    query = core.build_query(rule)
    assert "$altchaSelector:String!" in query
    assert "altcha:click(selector:$altchaSelector){selector time}" in query
    assert query.index("altcha:click") < query.index("submit:evaluate")
    assert core.classify("<p>你的今日状态：已签到</p>", rule).status == "already"
    preflight = core.build_preflight_query(wait=rule["preflight_wait"])
    assert "waitForTimeout(time:8000)" in preflight


def test_default_rules_produce_direct_sign_in_links():
    luckpt = core.resolve_rule({"url": "https://pt.luckpt.de", "id": "luckpt"}, {})
    hdsky = core.resolve_rule({"url": "https://hdsky.me", "id": "hdsky"}, {})
    assert core.target_url("https://pt.luckpt.de", luckpt["path"], luckpt.get("route_fragment")) == (
        "https://pt.luckpt.de/medal_collection.php"
    )
    assert core.target_url("https://hdsky.me", hdsky["path"], hdsky.get("route_fragment")) == "https://hdsky.me/index.php"


def test_site_state_key_prefers_moviepilot_id_and_falls_back_to_hostname():
    assert core.site_state_key({"id": 42, "url": "https://pt.example.org"}) == "id:42"
    assert core.site_state_key({"url": "https://PT.Example.org/attendance.php"}) == "host:pt.example.org"


def test_hdsky_treats_its_signed_marker_as_success():
    rule = core.resolve_rule({"url": "https://hdsky.me", "id": "hdsky"}, {})
    assert core.classify("<p>已签到</p>", rule).status == "success"


def test_hdsky_opens_its_dialog_before_solving_the_image_captcha():
    rule = core.resolve_rule({"url": "https://hdsky.me", "id": "hdsky"}, {})
    assert rule["mode"] == "trigger_image"
    assert rule["trigger_selector"] == "#showup"
    assert rule["captcha_selector"] == "#showupimg"
    assert rule["captcha_input_selector"] == "#imagestring"
    assert rule["submit_selector"] == "#showupbutton"
    query = core.build_query(rule)
    assert "trigger:evaluate(content:$trigger){value}" in query
    assert "waitForTrigger:waitForTimeout(time:$triggerWait)" in query
    assert query.index("trigger:evaluate") < query.index("solve:solveImageCaptcha")
    assert "$trigger:String! $triggerWait:Float!" in query
    assert core._trigger_script(rule["trigger_selector"]).count("#showup") == 1


def test_hdsky_signer_sends_the_trigger_before_image_captcha_variables():
    requests = []

    class Response:
        def __init__(self, data):
            self.data = data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"data": self.data}).encode()

    replies = [
        {"goto": {"status": 200}, "before": {"html": "欢迎回来"}},
        {"goto": {"status": 200}, "solve": {"found": True, "solved": True},
         "submit": {"value": "true"}, "response": {"value": "null"},
         "before": {"html": "欢迎回来"}, "after": {"html": "签到成功"}},
    ]
    original_urlopen = core.urllib.request.urlopen
    try:
        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode()))
            return Response(replies.pop(0))

        core.urllib.request.urlopen = fake_urlopen
        result = core.BrowserlessSigner("https://browserless.example", "safe-token").sign(
            {"url": "https://hdsky.me", "cookie": "uid=1"},
            core.DEFAULT_RULES["hdsky.me"],
        )
    finally:
        core.urllib.request.urlopen = original_urlopen

    assert result.status == "success"
    action = requests[1]
    assert "trigger" in action["variables"]
    assert "#showup" in action["variables"]["trigger"]
    assert action["variables"]["triggerWait"] == 500
    assert action["variables"]["captchaSelector"] == "#showupimg"


def test_oshen_uses_ajax_to_capture_the_form_result():
    rule = core.resolve_rule(
        {"url": "https://www.oshen.win", "id": "oshen"},
        {"www.oshen.win": {"submit_selector": "#custom-submit"}},
    )
    assert rule["mode"] == "image"
    assert rule["submit_method"] == "ajax"
    assert rule["submit_selector"] == "#custom-submit"


def test_ajax_rule_declares_submit_once_and_does_not_declare_selector():
    query = core.build_query({"mode": "image", "submit_method": "ajax"})
    assert query.count("$submit:String!") == 1
    assert "$selector:String!" not in query


def test_page_script_text_does_not_count_as_success():
    result = core.classify("<script>const success = true;</script><p>勋章中心</p>", {})
    assert result.status == "failed"


def test_image_rule_keeps_selector_solver_and_optional_site_user_agent():
    query = core.build_query({"mode": "image"}, "Mozilla/5.0 test")
    assert "solveImageCaptcha(captchaSelector:$captchaSelector" in query
    assert "userAgent(userAgent:$userAgent)" in query
    assert "$userAgent:String!" in query


def test_preflight_reads_page_before_the_image_solver_and_preserves_user_agent():
    query = core.build_preflight_query("Mozilla/5.0 test")
    assert "mutation CheckInPreflight" in query
    assert "before:html{html}" in query
    assert "solveImageCaptcha" not in query
    assert "userAgent(userAgent:$userAgent)" in query


def test_muxuege_uses_plain_click_and_text_based_button_location():
    rule = core.resolve_rule({"url": "https://pt.muxuege.org", "id": "muxuege"}, {})
    assert rule["mode"] == "open_page"
    script = core._submit_script(rule["submit_selector"], "click", submit_text=rule["submit_text"])
    assert json.dumps(rule["submit_text"]) in script
    assert "querySelectorAll" in script


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


def test_signer_returns_already_before_trying_absent_baozi_captcha():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": {"goto": {"status": 200}, "before": {"html": "今日已签"}}}).encode()

    original_urlopen = core.urllib.request.urlopen
    try:
        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode()))
            return Response()

        core.urllib.request.urlopen = fake_urlopen
        result = core.BrowserlessSigner("https://browserless.example", "safe-token").sign(
            {"url": "https://p.t-baozi.cc", "cookie": "uid=1"},
            core.DEFAULT_RULES["p.t-baozi.cc"],
        )
    finally:
        core.urllib.request.urlopen = original_urlopen

    assert result.status == "already"
    assert len(requests) == 1
    assert requests[0]["operationName"] == "CheckInPreflight"


def test_signer_returns_success_before_clicking_an_already_processed_open_page():
    requests = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        @staticmethod
        def read():
            return json.dumps({"data": {"goto": {"status": 200}, "before": {"html": "签到成功"}}}).encode()

    original_urlopen = core.urllib.request.urlopen
    try:
        def fake_urlopen(request, timeout):
            requests.append(json.loads(request.data.decode()))
            return Response()

        core.urllib.request.urlopen = fake_urlopen
        result = core.BrowserlessSigner("https://browserless.example", "safe-token").sign(
            {"url": "https://pt.example", "cookie": "uid=1"},
            {"mode": "open_page", "path": "/attendance.php", "submit_selector": "#sign"},
        )
    finally:
        core.urllib.request.urlopen = original_urlopen

    assert result.status == "success"
    assert len(requests) == 1
    assert requests[0]["operationName"] == "CheckInPreflight"
