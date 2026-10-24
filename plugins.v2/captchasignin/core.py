"""HTTP/OCR-first PT attendance primitives shared by all plugin entrypoints.

This module deliberately has no MoviePilot imports so the behaviour can be
unit-tested and copied unchanged into the V2 and V3 plugin directories.
"""

from __future__ import annotations

import base64
import json
import os
import signal
import subprocess
import sys
from html.parser import HTMLParser
from http.cookies import SimpleCookie
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
    "ptchdbits.co": {"mode": "chd", "path": "/bakatest.php", "submit_text": "不会",
                      "already_keywords": ["今天已经签过到了"], "strict_status_keywords": True},
    "0ff.cc": {"mode": "farm", "path": "/attendance.php"},
    "pt.0ff.cc": {"mode": "farm", "path": "/attendance.php"},
    "open.cd": {
        "mode": "image",
        "path": "/plugin_sign-in.php",
        "http_post_path": "/plugin_sign-in.php?cmd=signin",
        "preflight_path": "/",
        "verify_success_path": "/",
        "captcha_selector": "#frmSignin img",
        "captcha_input_selector": "#imagestring",
        "submit_selector": "#ok",
        "submit_method": "ajax",
        "success_json": {"field": "/state", "values": ["success"]},
        "already_keywords": ["查看簽到記錄"],
        "strict_status_keywords": True,
    },
    "p.t-baozi.cc": {
        "mode": "image",
        "path": "/attendance.php",
        # The form action differs between NexusPHP versions (for example, it
        # may include a leading slash or query parameters), so do not bind the
        # captcha controls to an exact action string.
        "captcha_selector": "form:has(input[name='imagestring']) img",
        "captcha_input_selector": "input[name='imagestring']",
        "submit_selector": "input[type='submit']",
        "already_keywords": ["签到成功"],
    },
    "pt.muxuege.org": {
        "mode": "open_page",
        "path": "/attendance.php",
        "submit_selector": "input[type='submit'], button[type='submit']",
        "submit_text": "立即签到",
    },
    "oshen.win": {
        "mode": "image",
        "path": "/attendance.php",
        "captcha_selector": "form:has(input[name='imagestring']) img[alt='CAPTCHA']",
        "captcha_input_selector": "form input[name='imagestring']",
        "submit_selector": "form input[type='submit'][value='立即签到']",
        # Capture the form response instead of losing a server-side CAPTCHA
        # rejection in the subsequently rendered attendance page.
        "submit_method": "ajax",
    },
    "pt.luckpt.de": {
        "mode": "open_page",
        "path": "/medal_collection.php",
        "submit_selector": ".claim-bar button.claim-reward[data-type='bonus_daily']",
        # The handler opens a layer.confirm dialog before it sends the AJAX
        # request, so the confirmation must be accepted in the page context.
        "submit_method": "confirm_click",
        "submit_text": "领取 幸运星 ×1000",
        "success_keywords": ["奖励领取成功"],
        "already_keywords": ["今日已领取", "已经领取", "已领取"],
    },
    "yemapt.org": {
        "mode": "altcha",
        "path": "/",
        "route_fragment": "#/user/growth?tab=checkIn",
        "altcha_checkbox_selector": "altcha-widget input[type='checkbox']",
        "altcha_payload_selector": "altcha-widget .altcha[data-state='verified'] input[name='altchaPayload']",
        "submit_selector": "button.ant-btn-primary.ant-btn-lg.ant-btn-block:not([disabled])",
        "submit_method": "altcha_click",
        "submit_text": "立即签到",
        "already_keywords": ["已签到，明日继续", "你的今日状态：已签到"],
        # The check-in view is client-rendered.  Allow it to render before
        # preflight decides whether a repeat run can stop as already signed.
        "preflight_wait": 8000,
        "wait": 5000,
    },
    "hdsky.me": {
        "http_handler": "hdsky",
        # HDSky only inserts its CAPTCHA controls after the user opens the
        # Show Up dialog.  Solve the image after that trigger, then use its
        # AJAX button handler to submit the value.
        "mode": "trigger_image",
        "path": "/index.php",
        "trigger_selector": "#showup",
        "captcha_selector": "#showupimg",
        "captcha_input_selector": "#imagestring",
        "submit_selector": "#showupbutton",
        "submit_method": "dom_click",
        "submit_text": "Let's Go",
        "success_keywords": ["已签到"],
    },
    "piggo.me": {
        "mode": "local_browser", "path": "/index.php",
        "submit_selector": "a, button, input[type='submit'], [role='button']",
        "submit_text": "签到", "submit_method": "dom_click",
        "challenge_wait": 40, "wait": 15000,
        "ad_selector": "#adtools a[href]",
        "already_keywords": ["今日已签到", "今天已签到", "已簽到"],
    },
    "dstudio.me": {"mode": "cloudflare", "path": "/attendance.php"},
    "mua.xloli.cc": {
        "mode": "cloudflare",
        "path": "/attendance.php",
        "submit_selector": "form[action*='attendance.php'] input[type='submit']",
    },
    "share.ilolicon.com": {
        "mode": "cloudflare",
        "path": "/attendance.php",
        "submit_selector": "form[action*='attendance.php'] input[type='submit']",
    },
}

# These sites use the same imagehash/imagestring NexusPHP form.
for _host in ("pt.vclib.online", "si-qi.xyz", "pt.novahd.top"):
    DEFAULT_RULES[_host] = {
        "mode": "image", "path": "/attendance.php",
        "captcha_selector": "form:has(input[name='imagestring']) img",
        "captcha_input_selector": "input[name='imagestring']",
        "submit_selector": "input[type='submit'], button[type='submit']",
    }

SUCCESS_WORDS = ("签到成功", "簽到成功", "成功签到", "打卡成功")
ALREADY_WORDS = ("已签到", "已经签到", "今日已签", "今天已签", "已打卡", "already")
LOGIN_WORDS = ("用户登录", "會員登入", "login")


@dataclass(frozen=True)
class SignResult:
    status: str
    message: str


DEFAULT_BROWSERLESS_URL = "https://production-sfo.browserless.io"


def normalize_host(url: str) -> str:
    return (urllib.parse.urlparse(url).hostname or "").lower().removeprefix("www.").rstrip(".")


def parse_rules(raw: Any) -> Dict[str, Dict[str, Any]]:
    """Read custom JSON rules without allowing a malformed rule to abort all sites."""
    if not raw:
        return {}
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        raise ValueError("站点规则必须是有效 JSON 对象")
    if not isinstance(value, Mapping):
        raise ValueError("站点规则必须是以域名或站点 ID 为键的 JSON 对象")
    result: Dict[str, Dict[str, Any]] = {}
    for key, rule in value.items():
        if isinstance(key, str) and isinstance(rule, Mapping):
            result[key.lower()] = dict(rule)
    return result


def resolve_rule(site: Mapping[str, Any], custom_rules: Mapping[str, Mapping[str, Any]],
                 site_options: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    host = normalize_host(str(site.get("url") or ""))
    custom = (custom_rules.get(str(site.get("id"))) or custom_rules.get(host)
              or custom_rules.get("www." + host) or {})
    preset = DEFAULT_RULES.get(host)
    if preset is None and host.endswith(".open.cd"):
        preset = DEFAULT_RULES["open.cd"]
    rule = dict(preset or {})
    # CHDBits must always use its bank and native skip action. Generic overrides
    # must never turn this into a normal submit or a Browserless request.
    if host == "ptchdbits.co":
        return validate_rule(rule)
    rule.update(custom)
    # 1.0.13 exposed dom_click for LuckPT.  Its reward handler always opens a
    # confirmation dialog, so migrate saved rules to the complete action.
    if host == "pt.luckpt.de" and rule.get("submit_method") == "dom_click":
        rule["submit_method"] = "confirm_click"
    rule.setdefault("mode", "open_page")
    rule.setdefault("path", "/attendance.php")
    rule.setdefault("submit_selector", "input[type='submit']")
    rule.setdefault("already_keywords", [])
    if site_options:
        rule = apply_site_options(site, rule, site_options)
    # Farm is always HTTP-only, even if a stale saved rule selected a browser mode.
    if host in {"0ff.cc", "pt.0ff.cc"}:
        rule["mode"] = "farm"
    return validate_rule(rule)


def apply_site_options(site: Mapping[str, Any], rule: Mapping[str, Any], options: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(rule)
    prefix = "site_%s_" % site.get("id")
    mode = ("farm" if normalize_host(str(site.get("url") or "")) in {"0ff.cc", "pt.0ff.cc"}
            else str(options.get(prefix + "mode") or "default"))
    if mode != "default" and mode != result["mode"]:
        result["mode"] = mode
        # A handler from another mode (e.g. Altcha's click) cannot be reused.
        result["submit_method"] = "click"
        for key in ("trigger_selector", "http_post_path", "route_fragment"):
            result.pop(key, None)
    if result["mode"] in {"image", "trigger_image"}:
        result.setdefault("captcha_selector", "form:has(input[name='imagestring']) img")
        result.setdefault("captcha_input_selector", "input[name='imagestring']")
    if result["mode"] == "trigger_image":
        result.setdefault("trigger_selector", "#showup")
    if result["mode"] == "altcha":
        result.setdefault("altcha_checkbox_selector", "altcha-widget input[type='checkbox']")
        result.setdefault("altcha_payload_selector", "altcha-widget input[name='altchaPayload']")
        result["submit_method"] = "altcha_click"
    if options.get(prefix + "button_source") == "custom" and result["mode"] != "farm":
        text = str(options.get(prefix + "button_text") or "").strip()
        if not text:
            raise ValueError("自定义按钮文字不能为空")
        result["submit_text"] = text
        # Native BrowserQL clicks only accept selectors. Use page-side lookup
        # when the user requested a text label instead of the preset selector.
        if result.get("submit_method", "click") == "click":
            result["submit_method"] = "dom_click"
    if options.get(prefix + "success_source") == "custom":
        words = [line.strip() for line in str(options.get(prefix + "success_text") or "").splitlines() if line.strip()]
        if not words:
            raise ValueError("自定义成功确认文字不能为空")
        result.update(success_keywords=list(dict.fromkeys(words)), already_keywords=[],
                      strict_status_keywords=True, success_json={}, custom_success_confirmation=True)
    return result


def validate_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(rule)
    mode = result.get("mode")
    if mode not in {"open_page", "cloudflare", "image", "trigger_image", "altcha", "farm", "local_browser", "chd"}:
        raise ValueError("签到方式必须为 open_page、cloudflare、image、trigger_image、altcha、farm、local_browser 或 chd")
    path = str(result.get("path") or "")
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "#" in path:
        raise ValueError("签到路径必须是以 / 开头的站内路径")
    route_fragment = str(result.get("route_fragment") or "")
    if route_fragment and (not route_fragment.startswith("#/") or "\\" in route_fragment):
        raise ValueError("路由片段必须以 #/ 开头")
    if mode in {"image", "trigger_image"}:
        for name in ("captcha_selector", "captcha_input_selector", "submit_selector"):
            if not str(result.get(name) or "").strip():
                raise ValueError("图片验证码规则缺少 " + name)
    if mode == "trigger_image" and not str(result.get("trigger_selector") or "").strip():
        raise ValueError("弹窗图片验证码规则缺少 trigger_selector")
    if mode == "altcha":
        for name in ("altcha_checkbox_selector", "altcha_payload_selector", "submit_selector"):
            if not str(result.get(name) or "").strip():
                raise ValueError("Altcha 规则缺少 " + name)
    return result


def target_url(base_url: str, path: str, route_fragment: Optional[str] = None) -> str:
    target = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    return target.split("#", 1)[0] + (route_fragment or "")


def site_state_key(site: Mapping[str, Any]) -> str:
    site_id = str(site.get("id") or "").strip()
    if normalize_host(str(site.get("url") or "")) == "ptchdbits.co":
        day = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        return ("id:" + site_id if site_id else "host:ptchdbits.co") + ":chd:" + day
    if site_id:
        return "id:" + site_id
    host = urllib.parse.urlparse(str(site.get("url") or "")).hostname
    return "host:" + host.lower() if host else ""


def cookie_objects(cookie_header: str, target_url: str) -> List[Dict[str, Any]]:
    parsed = urllib.parse.urlparse(target_url)
    domain = parsed.hostname
    if not domain:
        return []
    cookies: List[Dict[str, Any]] = []
    for item in cookie_header.split(";"):
        if "=" not in item:
            continue
        name, value = item.strip().split("=", 1)
        if name:
            cookies.append({"name": name.strip(), "value": value.strip(), "domain": domain,
                            "path": "/", "secure": parsed.scheme == "https", "url": target_url})
    return cookies


def bql_endpoint(address: str, token: str) -> str:
    address = address.strip()
    token = token.strip()
    if not address or not token:
        raise ValueError("Browserless 地址和 Token 都不能为空")
    parsed = urllib.parse.urlparse(address)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Browserless 地址必须以 http:// 或 https:// 开头")
    path = parsed.path.rstrip("/")
    if not path.endswith("/bql"):
        path = (path + "/bql") if path.endswith("/stealth") else (path + "/stealth/bql")
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query["token"] = token
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, path, "", urllib.parse.urlencode(query), ""))


def _submit_script(selector: str, method: str, captcha_input: Optional[str] = None,
                   submit_text: Optional[str] = None) -> str:
    selector_json = json.dumps(selector)
    input_json = json.dumps(captcha_input or "")
    text_json = json.dumps(submit_text or "")
    target_script = """(() => { const wanted = %s.trim();
      if (wanted) { const matches = [...document.querySelectorAll('input[type=submit], input[type=button], button, a')];
        const found = matches.find((node) => ((node.value || node.textContent || '').trim().includes(wanted)));
        return found || null; }
      return document.querySelector(%s);
    })()""" % (text_json, selector_json)
    if method in {"click", "dom_click", "confirm_click"}:
        confirm = "" if method != "confirm_click" else """
          await new Promise((resolve) => setTimeout(resolve, 150));
          const confirm = [...document.querySelectorAll('.layui-layer-btn0, .layui-layer-btn a')]
            .find((node) => node.offsetParent !== null && /确定|确认/.test((node.textContent || '').trim()));
          if (!confirm) return false; confirm.click();"""
        return """(async () => { const input = %s ? document.querySelector(%s) : null;
          if (input && !input.value.trim()) return false;
          const button = %s; if (!button) return false; button.click(); %s return true;
        })()""" % (input_json, input_json, target_script, confirm)
    return """(async () => {
      const input = %s ? document.querySelector(%s) : null; if (input && !input.value.trim()) return false;
      const target = %s; const form = target && (target.form || target);
      if (!(form instanceof HTMLFormElement)) throw new Error('未找到签到表单');
      const action = new URL(form.action, location.href);
      if (action.origin !== location.origin) throw new Error('只允许同源提交');
      const data = new FormData(form); if (target.name && !target.disabled) data.append(target.name, target.value);
      const response = await fetch(action.href, {method: form.method || 'POST', credentials:'same-origin', body:data});
      window.__captchasignin_response = {status:response.status, text:await response.text()}; return response.status;
    })()""" % (input_json, input_json, target_script)


def _altcha_submit_script(rule: Mapping[str, Any]) -> str:
    payload = json.dumps(str(rule["altcha_payload_selector"]))
    submit = _submit_script(str(rule["submit_selector"]), "dom_click", submit_text=rule.get("submit_text"))
    return """(async () => {
      const ready = () => { const input = document.querySelector(%s); return input && input.value.trim() ? input : null; };
      const deadline = Date.now() + 30000;
      while (!ready() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 250));
      if (!ready()) return false;
      return await %s;
    })()""" % (payload, submit)


def _trigger_script(selector: str) -> str:
    selector_json = json.dumps(selector)
    return """(() => { const trigger = document.querySelector(%s);
      if (!trigger) return false; trigger.click(); return true;
    })()""" % selector_json


def build_query(rule: Mapping[str, Any], user_agent: Optional[str] = None) -> str:
    """Build one BrowserQL operation for a site check-in.

    Browserless recommends automatic captcha detection for Cloudflare and
    Turnstile.  Restricting ``solve`` to ``cloudflare`` made a Turnstile page
    depend on Browserless classifying it as that one specific type.
    """
    image = rule["mode"] in {"image", "trigger_image"}
    triggered_image = rule["mode"] == "trigger_image"
    altcha = rule["mode"] == "altcha"
    verifies_success = bool(rule.get("verify_success_path"))
    needs_solver = rule["mode"] in {"image", "trigger_image", "cloudflare"}
    native_click = str(rule.get("submit_method") or "click") == "click"
    solve = ("solve:solveImageCaptcha(captchaSelector:$captchaSelector,inputSelector:$captchaInputSelector,timeout:$solveTimeout){found solved time}"
             if image else "solve:solve(timeout:$solveTimeout){found solved time}" if rule["mode"] == "cloudflare"
             else "solve:evaluate(content:\"'skipped'\"){value}")
    extra = "$captchaSelector:String! $captchaInputSelector:String!" if image else ""
    set_user_agent = "userAgent(userAgent:$userAgent){time}" if user_agent else ""
    user_agent_variable = " $userAgent:String!" if user_agent else ""
    variable_suffix = (" $solveTimeout:Float!" if needs_solver else "")
    variable_suffix += " $selector:String!" if native_click else " $submit:String!"
    if triggered_image:
        variable_suffix += " $trigger:String! $triggerWait:Float!"
    if altcha:
        variable_suffix += " $altchaSelector:String!"
    if verifies_success:
        variable_suffix += " $verifyUrl:String!"
    if extra:
        variable_suffix += " " + extra
    variable_suffix += user_agent_variable
    return """mutation CheckIn($cookies:[CookieInput!]! $url:String! $beforeWait:Float! $wait:Float!%s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitBefore:waitForTimeout(time:$beforeWait){time}
      %s
      before:html{html}
      %s
      %s
      %s
      %s
      waitAfter:waitForTimeout(time:$wait){time}
      response:evaluate(content:"JSON.stringify(window.__captchasignin_response || null)"){value}
      %s
      after:html{html}
    }""" % (variable_suffix, set_user_agent,
              "edge:solve(timeout:$solveTimeout){found solved time}" if image else "",
              "trigger:evaluate(content:$trigger){value}\n      waitForTrigger:waitForTimeout(time:$triggerWait){time}" if triggered_image else "",
              "altcha:click(selector:$altchaSelector){selector time}" if altcha else "",
              solve,
              "submit:click(selector:$selector){selector time}" if native_click else "submit:evaluate(content:$submit){value}",
              "verify:goto(url:$verifyUrl,waitUntil:domContentLoaded){status}\n      verifyPage:html{html}" if verifies_success else "")


def build_preflight_query(user_agent: Optional[str] = None, wait: int = 2000) -> str:
    """Read the page before a solver can fail on an absent post-sign-in CAPTCHA."""
    set_user_agent = "userAgent(userAgent:$userAgent){time}" if user_agent else ""
    user_agent_variable = " $userAgent:String!" if user_agent else ""
    return """mutation CheckInPreflight($cookies:[CookieInput!]! $url:String!%s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitForTimeout(time:%s){time}
      before:html{html}
    }""" % (user_agent_variable, set_user_agent, max(1000, min(int(wait), 15000)))


def page_text(html: str) -> str:
    visible_html = re.sub(r"<(script|style)\b[^>]*>.*?</\1\s*>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", visible_html)).strip()


def compact_html(html: str) -> str:
    return page_text(html)[:240]


def classify(html: str, rule: Mapping[str, Any]) -> SignResult:
    full_text = page_text(html)
    text = full_text[:240]
    lower = full_text.lower()
    if any(word.lower() in lower for word in LOGIN_WORDS) and "logout" not in lower:
        return SignResult("failed", "Cookie 无效或已过期")
    if any(word.lower() in lower for word in rule.get("success_keywords", [])):
        return SignResult("success", text or "签到成功")
    if any(word.lower() in lower for word in rule.get("already_keywords", [])):
        return SignResult("already", text or "今日已经签到")
    if not rule.get("strict_status_keywords") and any(word in lower for word in SUCCESS_WORDS):
        return SignResult("success", text or "签到成功")
    if not rule.get("strict_status_keywords") and any(word in lower for word in ALREADY_WORDS):
        return SignResult("already", text or "今日已经签到")
    return SignResult("failed", text or "未识别到签到成功结果")


def classify_ajax_response(value: Any, rule: Mapping[str, Any]) -> Optional[SignResult]:
    if not value or value == "null":
        return None
    try:
        response = json.loads(str(value))
    except (TypeError, ValueError):
        return None
    if not isinstance(response, Mapping):
        return None
    status = response.get("status")
    if isinstance(status, int) and not 200 <= status < 400:
        return SignResult("failed", "签到请求失败（HTTP %s）" % status)
    text = str(response.get("text") or "")
    success_json = rule.get("success_json") or {}
    if success_json:
        try:
            body = json.loads(text)
            current: Any = body
            for key in str(success_json.get("field") or "").lstrip("/").split("/"):
                current = current[key]
            if str(current) in {str(item) for item in success_json.get("values", [])}:
                return SignResult("success", "签到成功")
        except (KeyError, TypeError, ValueError):
            pass
    return classify(text, rule)


class BrowserlessSigner:
    def __init__(self, address: str, token: str, timeout: int = 100):
        self.endpoint = bql_endpoint(address, token)
        self.timeout = max(15, min(int(timeout), 300))

    def sign(self, site: Mapping[str, Any], rule: Mapping[str, Any]) -> SignResult:
        if rule["mode"] in {"farm", "local_browser"}:
            return SignResult("failed", "此站点使用直连或本地浏览器，不调用 Browserless")
        base_url = str(site.get("url") or "").rstrip("/")
        cookie = str(site.get("cookie") or "").strip()
        if not base_url or not cookie:
            return SignResult("failed", "站点地址或 Cookie 为空")
        target = target_url(base_url, str(rule["path"]), rule.get("route_fragment"))
        cookies = cookie_objects(cookie, target)
        if not cookies:
            return SignResult("failed", "站点 Cookie 格式无效")
        user_agent = str(site.get("ua") or "").strip()
        # Always inspect the page before interacting.  A site may remove its
        # action button after either a successful sign-in or an already-signed
        # state; both must be terminal results, regardless of sign-in mode.
        preflight_target = target_url(base_url, str(rule.get("preflight_path") or rule["path"]))
        preflight_variables: Dict[str, Any] = {"cookies": cookies, "url": preflight_target}
        if user_agent:
            preflight_variables["userAgent"] = user_agent
        preflight_wait = max(1000, min(int(rule.get("preflight_wait") or 2000), 15000))
        preflight = self._request(preflight_variables, "CheckInPreflight", build_preflight_query(user_agent, preflight_wait))
        if isinstance(preflight, SignResult):
            return preflight
        preflight_html = str((preflight.get("before") or {}).get("html") or "")
        challenge = any(marker in preflight_html.lower() for marker in ("cf-chl-", "challenge-platform", "just a moment"))
        status = preflight.get("goto", {}).get("status")
        if status not in range(200, 400) and not (status in {403, 429, 503} and challenge):
            return SignResult("failed", "打开签到页失败")
        initial = classify(preflight_html, rule)
        if initial.status in {"already", "success"}:
            return initial
        submit_method = str(rule.get("submit_method") or "click")
        variables: Dict[str, Any] = {"cookies": cookies, "url": target, "beforeWait": 2000, "wait": int(rule.get("wait") or 3500)}
        if submit_method == "click":
            variables["selector"] = rule["submit_selector"]
        else:
            variables["submit"] = (_altcha_submit_script(rule) if submit_method == "altcha_click"
                                   else _submit_script(rule["submit_selector"], submit_method,
                                                       rule.get("captcha_input_selector"), rule.get("submit_text")))
        if submit_method == "altcha_click":
            variables["altchaSelector"] = rule["altcha_checkbox_selector"]
        if rule["mode"] == "trigger_image":
            variables["trigger"] = _trigger_script(str(rule["trigger_selector"]))
            variables["triggerWait"] = int(rule.get("trigger_wait") or 500)
        if rule["mode"] != "open_page":
            variables["solveTimeout"] = 60000
        if rule["mode"] in {"image", "trigger_image"}:
            variables.update({"captchaSelector": rule["captcha_selector"], "captchaInputSelector": rule["captcha_input_selector"]})
        if rule.get("verify_success_path"):
            variables["verifyUrl"] = target_url(base_url, str(rule["verify_success_path"]))
        if user_agent:
            variables["userAgent"] = user_agent
        data = self._request(variables, "CheckIn", build_query(rule, user_agent))
        if isinstance(data, SignResult):
            return data
        ajax_result = classify_ajax_response((data.get("response") or {}).get("value"), rule)
        if rule.get("verify_success_path"):
            if (data.get("verify") or {}).get("status") not in range(200, 400):
                return SignResult("failed", "无法打开页面确认签到记录")
            verified = classify(str((data.get("verifyPage") or {}).get("html") or ""), rule)
            if verified.status in {"success", "already"}:
                return SignResult("success", "已在首页确认签到记录")
            return SignResult("failed", "首页未显示“查看簽到記錄”，未确认签到成功")
        final = classify(str((data.get("after") or {}).get("html") or ""), rule)
        if ajax_result and ajax_result.status in {"success", "already"}:
            return ajax_result
        if final.status in {"success", "already"}:
            return final
        if data.get("goto", {}).get("status") not in range(200, 400):
            edge = data.get("edge") or data.get("solve") or {}
            if not edge.get("solved"):
                return SignResult("failed", "打开签到页失败")
        solve = data.get("solve") or {}
        if rule["mode"] in {"image", "trigger_image"} and not solve.get("found"):
            return SignResult("failed", "未找到图片验证码；请检查验证码图片选择器")
        if rule["mode"] != "open_page" and solve.get("found") and not solve.get("solved"):
            return SignResult("failed", "找到验证码但未能完成验证")
        submitted = (data.get("submit") or {}).get("value")
        if rule["mode"] in {"image", "trigger_image"} and submitted in (False, "false"):
            return SignResult("failed", "验证码未自动填入输入框，未发送签到请求")
        if ajax_result:
            return ajax_result
        result = classify(str((data.get("after") or {}).get("html") or ""), rule)
        if result.status == "failed":
            before = classify(str((data.get("before") or {}).get("html") or ""), rule)
            if before.status == "already":
                return before
        return result

    def _request(self, variables: Mapping[str, Any], operation: str, query: str) -> Any:
        payload = json.dumps({"query": query, "operationName": operation, "variables": variables}).encode()
        request = urllib.request.Request(self.endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return SignResult("failed", "Browserless HTTP %s" % exc.code)
        except (urllib.error.URLError, TimeoutError, ValueError):
            return SignResult("failed", "Browserless 请求失败或响应格式异常")
        errors = value.get("errors") or []
        if errors:
            message = str(errors[0].get("message") or "未知错误")
            if "waiting for page navigation" in message.lower():
                return SignResult("failed", "Browserless 页面导航超时；请检查该站是否可由当前 Browserless 节点访问")
            return SignResult("failed", "Browserless 执行失败：" + message)
        return value.get("data") or {}


class AttendancePage(HTMLParser):
    """Extract ordinary NexusPHP forms; JavaScript-only controls use Browserless."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.forms: List[Dict[str, Any]] = []
        self.inputs: List[Dict[str, str]] = []
        self.images: List[str] = []
        self.scripts: List[str] = []
        self.current: Optional[Dict[str, Any]] = None
        self.button: Optional[Dict[str, str]] = None
        self.feed(html)

    def handle_starttag(self, tag: str, attrs: Any) -> None:
        attr = dict(attrs)
        if tag == "form":
            self.current = {"action": attr.get("action") or "", "method": (attr.get("method") or "get").lower(), "inputs": []}
            self.forms.append(self.current)
        elif tag in {"input", "button"}:
            field = {"name": attr.get("name") or "", "value": attr.get("value") or "",
                     "type": (attr.get("type") or ("submit" if tag == "button" else "text")).lower()}
            if "disabled" in attr or (field["type"] in {"checkbox", "radio"} and "checked" not in attr):
                return
            if tag == "button":
                field["text"] = ""
                self.button = field
            self.inputs.append(field)
            if self.current is not None:
                self.current["inputs"].append(field)
        elif tag == "img" and attr.get("src"):
            self.images.append(attr["src"])
        elif tag == "script" and attr.get("src"):
            self.scripts.append(attr["src"])

    def handle_data(self, data: str) -> None:
        if self.button is not None:
            self.button["text"] += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.current = None
        elif tag == "button":
            self.button = None


def same_origin_url(base: str, value: str) -> str:
    target = urllib.parse.urljoin(base, value)
    def origin(url: str) -> Any:
        parsed = urllib.parse.urlparse(url)
        return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    parsed = urllib.parse.urlparse(target)
    if parsed.scheme not in {"https", "http"} or parsed.username or parsed.password or origin(base) != origin(target):
        raise ValueError("直连接口必须与站点同源")
    return target


class HttpSigner:
    """Keep site cookies in one session; send only image bytes to MP's OCR service."""

    def __init__(self, recognize: Any, proxies: Optional[dict] = None, timeout: int = 30):
        self.recognize = recognize
        self.proxies = proxies
        self.timeout = timeout

    def _request(self, session: Any, method: str, url: str, **kwargs: Any) -> Any:
        # Validate every redirect before sending account cookies or form data.
        for _ in range(6):
            response = session.request(method, url, timeout=self.timeout, allow_redirects=False, **kwargs)
            if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("Location"):
                url = same_origin_url(url, response.headers["Location"])
                if response.status_code == 303 or (method == "POST" and response.status_code in {301, 302}):
                    method = "GET"
                    kwargs.pop("data", None)
                kwargs.pop("params", None)
                continue
            response.raise_for_status()
            return response
        raise ValueError("站点重定向次数过多")

    def sign(self, site: Mapping[str, Any], rule: Mapping[str, Any]) -> SignResult:
        import requests

        sky = rule.get("http_handler") == "hdsky" and rule["mode"] in {"image", "trigger_image"}
        if rule["mode"] not in {"image", "farm"} and not sky:
            return SignResult("failed", "此签到流程需要浏览器")
        base = str(site.get("url") or "")
        cookie = str(site.get("cookie") or "")
        if not base or not cookie:
            return SignResult("failed", "站点地址或 Cookie 为空")
        try:
            with requests.Session() as session:
                session.headers.update({"User-Agent": str(site.get("ua") or "Mozilla/5.0"), "Referer": base,
                                        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
                host = urllib.parse.urlparse(base).hostname
                for item in cookie_objects(cookie, base):
                    session.cookies.set(item["name"], item["value"], domain=host, path="/")
                if site.get("proxy") and self.proxies:
                    session.proxies.update(self.proxies)
                target = target_url(base, str(rule["path"]))
                if rule.get("preflight_path"):
                    initial = self._request(session, "GET", target_url(base, str(rule["preflight_path"])))
                    state = classify(initial.text, rule)
                    if state.status in {"success", "already"}:
                        return SignResult(state.status, "直连检查：今日已签到")
                response = self._request(session, "GET", target)
                state = classify(response.text, rule)
                if state.status in {"success", "already"}:
                    return SignResult(state.status, "直连检查：今日已签到")
                if sky:
                    if state.message == "Cookie 无效或已过期":
                        return state
                    return self._hdsky(session, target, rule)
                page = AttendancePage(response.text)
                if rule["mode"] == "farm":
                    return self._farm(session, target, page, rule)
                return self._image(session, target, page, rule)
        except requests.RequestException:
            return SignResult("failed", "直连请求失败或 HTTP 状态异常")
        except ValueError:
            # Only local validation errors are exposed, never response bodies/URLs.
            return SignResult("failed", "直连页面或接口格式不支持")
        except Exception:
            return SignResult("failed", "MP OCR 调用或直连签到异常")

    def _image(self, session: Any, target: str, page: AttendancePage, rule: Mapping[str, Any]) -> SignResult:
        wanted = str(rule.get("submit_text") or "").strip()
        def matching_button(field: Mapping[str, str]) -> bool:
            return field["type"] in {"submit", "button"} and wanted in (field.get("text") or field["value"])
        forms = [form for form in page.forms if any(field["name"] == "imagestring" for field in form["inputs"])]
        form = next((form for form in forms if not wanted or any(matching_button(field) for field in form["inputs"])), None)
        fields = form["inputs"] if form is not None else page.inputs
        imagehash = next((field["value"] for field in fields if field["name"] == "imagehash"), "")
        if not imagehash or (form is None and not rule.get("http_post_path")):
            return SignResult("failed", "未找到标准图片验证码表单，需要浏览器处理")
        source = next((src for src in page.images if imagehash in src or "image.php" in src), "")
        if not source:
            return SignResult("failed", "未找到验证码图片地址")
        image_url = same_origin_url(target, source)
        image = self._request(session, "GET", image_url).content
        if not image or len(image) > 5 * 1024 * 1024:
            return SignResult("failed", "验证码图片为空或过大")
        code = str(self.recognize(base64.b64encode(image).decode()) or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9]{1,16}", code):
            return SignResult("failed", "MP OCR 未返回有效验证码")
        data = [(field["name"], field["value"]) for field in fields
                if field["name"] and field["type"] not in {"submit", "button", "reset", "file", "image"}
                and field["name"] != "imagestring"]
        data.append(("imagestring", code))
        submit = next((field for field in fields if matching_button(field)), None) if wanted else next(
            (field for field in fields if field["type"] == "submit" and field["name"]), None)
        if wanted and submit is None:
            return SignResult("failed", "未找到指定文字的签到按钮")
        if submit and submit["name"]:
            data.append((submit["name"], submit["value"]))
        post_url = same_origin_url(target, str(rule.get("http_post_path") or form["action"] or target))
        method = "POST" if rule.get("http_post_path") else form["method"].upper()
        if method not in {"GET", "POST"}:
            return SignResult("failed", "不支持的签到表单方法")
        parsed = urllib.parse.urlparse(target)
        origin = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, "", "", "", ""))
        response = self._request(session, method, post_url, headers={"Referer": target, "Origin": origin},
                                 **({"data": data} if method == "POST" else {"params": data}))
        result = classify_ajax_response(json.dumps({"status": response.status_code, "text": response.text}), rule)
        if rule.get("verify_success_path"):
            verify = self._request(session, "GET", same_origin_url(target, str(rule["verify_success_path"])))
            result = classify(verify.text, rule)
            return SignResult(result.status, "MP OCR：已在首页确认签到记录" if result.status in {"success", "already"} else "MP OCR：首页未确认签到记录")
        if result and result.status in {"success", "already"}:
            return SignResult(result.status, "MP OCR：签到成功或今日已签到")
        verify = self._request(session, "GET", target)
        result = classify(verify.text, rule)
        return SignResult(result.status, "MP OCR：签到成功或今日已签到" if result.status in {"success", "already"} else "MP OCR 提交后未确认签到成功")

    def _hdsky_confirm(self, session: Any, target: str, rule: Mapping[str, Any]) -> SignResult:
        response = self._request(session, "GET", target)
        result = classify(response.text, rule)
        return SignResult(result.status, "天空 MP OCR：已复查确认签到" if result.status in {"success", "already"}
                          else "天空提交后回查未确认签到成功")

    def _hdsky(self, session: Any, target: str, rule: Mapping[str, Any]) -> SignResult:
        import requests
        headers = {"Referer": target, "X-Requested-With": "XMLHttpRequest"}
        attempts = max(1, min(int(rule.get("http_ocr_attempts") or 3), 3))
        reason = "天空未取得有效验证码"
        for _ in range(attempts):
            challenge = self._request(session, "POST", same_origin_url(target, "/image_code_ajax.php"),
                                      data={"action": "new"}, headers=headers)
            try:
                payload = json.loads(challenge.text)
            except (TypeError, ValueError):
                return SignResult("failed", "天空验证码接口响应格式异常")
            if not isinstance(payload, Mapping) or payload.get("success") not in (True, "true", "1"):
                return SignResult("failed", "天空验证码接口未确认成功")
            imagehash = str(payload.get("code") or "").strip()
            if not imagehash or len(imagehash) > 256:
                return SignResult("failed", "天空验证码接口缺少 imagehash")
            image_url = same_origin_url(target, "/image.php?" + urllib.parse.urlencode({"action": "regimage", "imagehash": imagehash}))
            image = self._request(session, "GET", image_url, headers={"Referer": target}).content
            if not image or len(image) > 5 * 1024 * 1024:
                return SignResult("failed", "天空验证码图片为空或过大")
            code = str(self.recognize(base64.b64encode(image).decode()) or "").strip()
            if not re.fullmatch(r"[A-Za-z0-9]{6}", code):
                reason = "天空 MP OCR 未返回六位验证码"
                continue
            try:
                response = self._request(session, "POST", same_origin_url(target, "/showup.php"),
                                         data={"action": "showup", "imagehash": imagehash, "imagestring": code}, headers=headers)
            except requests.RequestException:
                # A response timeout is not evidence that the server rejected
                # the submit. Read the homepage once before another engine acts.
                return self._hdsky_confirm(session, target, rule)
            try:
                result = json.loads(response.text)
            except (TypeError, ValueError):
                return self._hdsky_confirm(session, target, rule)
            if not isinstance(result, Mapping):
                return self._hdsky_confirm(session, target, rule)
            if result.get("success") in (True, "true", "1"):
                if rule.get("custom_success_confirmation"):
                    return self._hdsky_confirm(session, target, rule)
                return SignResult("success", "天空 MP OCR：签到接口确认成功")
            message = str(result.get("message") or "")
            if message == "date_unmatch":
                if rule.get("custom_success_confirmation"):
                    return self._hdsky_confirm(session, target, rule)
                return SignResult("already", "天空 MP OCR：今日已签到")
            if message == "invalid_imagehash":
                reason = "天空验证码被拒绝，已重新获取验证挑战"
                continue
            return self._hdsky_confirm(session, target, rule)
        return SignResult("failed", reason + "（已达本轮尝试上限）")

    def _farm(self, session: Any, target: str, page: AttendancePage, rule: Mapping[str, Any]) -> SignResult:
        source = next((src for src in page.scripts if re.search(r"/slide_check_[^/]+\.js(?:\?|$)", src)), "")
        if not source:
            return SignResult("failed", "农场页面未找到滑块验证脚本")
        script = self._request(session, "GET", same_origin_url(target, source)).text
        match = re.search(r'''["']([^"'\s]*set_access_token-[^"'\s]+)["']''', script)
        if not match:
            return SignResult("failed", "农场脚本未找到验证接口")
        self._request(session, "GET", same_origin_url(target, match.group(1)), headers={"Referer": target})
        time.sleep(3)
        response = self._request(session, "GET", target)
        if "slide_check" in response.text or "拖动滑块验证" in response.text:
            return SignResult("failed", "农场直连后仍需要滑块验证")
        result = classify(response.text, rule)
        return SignResult(result.status, "农场直连：签到成功或今日已签到" if result.status in {"success", "already"} else "农场直连后未确认签到成功")


class HybridSigner:
    def __init__(self, direct: HttpSigner, browserless_factory: Any, local: Any = None, chd: Any = None):
        self.direct = direct
        self.browserless_factory = browserless_factory
        self.local = local
        self.chd = chd

    def sign(self, site: Mapping[str, Any], rule: Mapping[str, Any]) -> SignResult:
        if rule.get("mode") == "chd":
            return self.chd.sign(site, rule) if self.chd else SignResult("failed", "彩虹岛题库签到未解锁")
        if rule.get("mode") == "local_browser":
            local = self.local or LocalBrowserSigner()
            return local.sign(site, rule)
        first = self.direct.sign(site, rule)
        if rule.get("mode") == "farm" or first.status in {"success", "already"}:
            return first
        try:
            browserless = self.browserless_factory()
        except ValueError:
            return SignResult("failed", first.message + "；Browserless 地址配置无效")
        if browserless is None:
            return SignResult("failed", first.message + "；未配置 Browserless Token，无法兜底")
        result = browserless.sign(site, rule)
        if result.status in {"success", "already"}:
            return SignResult(result.status, "Browserless 兜底：" + result.message)
        return SignResult("failed", first.message + "；Browserless 兜底：" + result.message)


class LocalBrowserSigner:
    """Run MP's installed CloakBrowser in a disposable process at the local exit."""

    def __init__(self, action: Any = None, proxies: Optional[dict] = None, timeout: int = 180,
                 progress: Any = None):
        self.action = action
        self.proxies = proxies
        self.timeout = timeout
        self.progress = progress

    @staticmethod
    def _challenge(html: str) -> bool:
        # Do not treat a normal page's Turnstile script reference as an edge
        # interstitial. A challenge must clear before any sign-in control acts.
        text = page_text(html).lower()
        return bool(re.search(r"just a moment|verify you are human|checking your browser|安全检测|正在验证您是否是真人|雷池\s*waf|safeline\s*(waf|challenge)|异地登录|異地登錄", text)
                    or re.search(r"_cf_chl_opt|chl_page|safeline-challenge", html, re.I))

    def _wait_page(self, page: Any, target: str, seconds: int) -> str:
        html = ""
        for _ in range(max(1, seconds)):
            try:
                same_origin_url(target, str(page.url))
            except ValueError:
                return ""
            try:
                html = page.content() or ""
            except Exception:
                html = ""
            if html and (not self._challenge(html) or re.search(r"异地登录|異地登錄", page_text(html))):
                return html
            # Only operate on an actual verification control, never arbitrary
            # labels/containers. An unsupported challenge remains a failure.
            try:
                for frame in getattr(page, "frames", []):
                    if urllib.parse.urlparse(str(frame.url)).hostname == "challenges.cloudflare.com":
                        checkbox = frame.locator("input[type='checkbox']").first
                        if checkbox.is_visible():
                            checkbox.click(timeout=500)
            except Exception:
                pass
            page.wait_for_timeout(1000)
        return html

    def _open_ad(self, page: Any, result: SignResult, ad_url: str) -> SignResult:
        """Open one Piggo reward link without altering the confirmed sign-in result."""
        self._report("签到已确认", result)
        tab = None
        detail = "广告链接未找到或不符合站内跳转规则"
        if ad_url:
            try:
                self._report("开始广告访问", result)
                tab = page.context.new_page()
                response = tab.goto(ad_url, wait_until="domcontentloaded", timeout=15000)
                tab.wait_for_timeout(2000)
                if response is not None and response.status < 400 and not self._challenge(tab.content()):
                    detail = "广告已打开，魔力到账未核实"
                else:
                    detail = "广告访问未确认完成，魔力到账未核实"
            except Exception:
                detail = "广告访问失败，魔力到账未核实"
            finally:
                if tab is not None:
                    try:
                        self._report("关闭广告页面", result)
                        tab.close()
                    except Exception:
                        pass
        return SignResult(result.status, result.message + "；" + detail)

    def sign(self, site: Mapping[str, Any], rule: Mapping[str, Any]) -> SignResult:
        action = self.action
        if action is None:
            try:
                from app.core.config import settings
                options = {"humanize": getattr(settings, "CLOAKBROWSER_HUMANIZE", False),
                           "human_preset": getattr(settings, "CLOAKBROWSER_HUMAN_PRESET", "default")}
            except Exception:
                return SignResult("failed", "MP 本地浏览器接口不可用；未转交云端 Browserless")
            return self._sign_isolated(site, rule, options)
        base = str(site.get("url") or "")
        cookie = str(site.get("cookie") or "").strip()
        if not base or not cookie:
            return SignResult("failed", "站点地址或 Cookie 为空")
        target = target_url(base, str(rule["path"]))
        try:
            parsed_cookie = SimpleCookie()
            parsed_cookie.load(cookie)
            if not parsed_cookie:
                raise ValueError("empty cookies")
            origin = urllib.parse.urlsplit(base)
            cookie_url = urllib.parse.urlunsplit((origin.scheme, origin.netloc, "/", "", ""))
            browser_cookies = [{"name": name, "value": item.value, "url": cookie_url}
                               for name, item in parsed_cookie.items()]
        except Exception:
            return SignResult("failed", "站点 Cookie 无法解析")
        budget = max(1, min(int(rule.get("challenge_wait") or 40), 60))

        def callback(page: Any) -> SignResult:
            # Seed the browser jar before navigation, so challenge cookies can
            # evolve normally instead of being masked by a fixed Cookie header.
            page.context.add_cookies(browser_cookies)
            try:
                page.goto(target, wait_until="domcontentloaded", timeout=30000)
            except Exception:
                pass  # A navigation timeout can still leave a usable document.
            before = self._wait_page(page, target, budget)
            same_origin_url(target, str(page.url))
            if not before or self._challenge(before):
                return SignResult("failed", "本地浏览器仍处于安全验证或异地登录确认页面")
            ad_enabled = (urllib.parse.urlsplit(base).hostname == "piggo.me"
                          and bool(rule.get("ad_selector")))
            ad_url = ""
            if ad_enabled:
                try:
                    # Read the current homepage slot before signing navigates away.
                    href = page.locator(str(rule["ad_selector"])).first.get_attribute("href", timeout=1000)
                    candidate = same_origin_url(target, href) if isinstance(href, str) and href else ""
                    if urllib.parse.urlsplit(candidate).path == "/adredir.php":
                        ad_url = candidate
                except Exception:
                    pass
            initial = classify(before, rule)
            if initial.status in {"success", "already"}:
                confirmed = SignResult(initial.status, "本地浏览器：已确认今日签到")
                return self._open_ad(page, confirmed, ad_url) if ad_enabled else confirmed
            if initial.message == "Cookie 无效或已过期":
                return initial
            selector = str(rule.get("submit_selector") or "input[type='submit'], button")
            text = str(rule.get("submit_text") or "").strip()
            # Find the smallest visible exact-text control first. Use actual
            # Playwright clicks so a native click/navigation handler can run.
            choice = page.evaluate("""([selector, wanted]) => {
              const nodes = [...document.querySelectorAll(selector)].filter(node => {
                const label = (node.value || node.textContent || '').trim();
                return !node.disabled && node.getClientRects().length && (!wanted || label.includes(wanted));
              });
              nodes.sort((a,b) => {
                const x=(a.value||a.textContent||'').trim(), y=(b.value||b.textContent||'').trim();
                return Number(y===wanted)-Number(x===wanted) || x.length-y.length;
              });
              const node=nodes[0]; if (!node) return null;
              if (node.tagName==='A' && new URL(node.href,location.href).origin!==location.origin) return null;
              node.setAttribute('data-captchasignin-target','true'); return true;
            }""", [selector, text])
            if not choice:
                return SignResult("failed", "本地浏览器未找到指定签到按钮")
            try:
                page.click('[data-captchasignin-target="true"]', timeout=10000)
            except Exception:
                pass  # Submission may have arrived; inspect the resulting page.
            page.wait_for_timeout(max(1000, min(int(rule.get("wait") or 4000), 15000)))
            after = self._wait_page(page, target, budget)
            same_origin_url(target, str(page.url))
            if not after or self._challenge(after):
                return SignResult("failed", "签到后仍处于安全验证页面，未确认成功")
            result = classify(after, rule)
            confirmed = SignResult(result.status, "本地浏览器：签到已确认" if result.status in {"success", "already"}
                              else "本地浏览器点击后未确认签到成功")
            return self._open_ad(page, confirmed, ad_url) if ad_enabled and result.status in {"success", "already"} else confirmed

        try:
            result = action(url="about:blank", callback=callback, cookies=None,
                            ua=str(site.get("ua") or "").strip() or None,
                            proxies=self.proxies if site.get("proxy") else None,
                            headless=True, timeout=self.timeout)
            return result if isinstance(result, SignResult) else SignResult("failed", "本地浏览器未返回有效签到结果")
        except Exception:
            return SignResult("failed", "MP 本地浏览器运行失败；未转交云端 Browserless")

    def _report(self, stage: str, result: Optional[SignResult] = None) -> None:
        if self.progress:
            self.progress(stage, result)

    @staticmethod
    def _kill_browser_process(process: Any) -> None:
        # Chromium may create its own session. Snapshot the owned descendants
        # before killing the worker, otherwise they can be reparented to init.
        descendants = []
        pending = [process.pid]
        while pending and os.path.isdir("/proc"):
            parent = pending.pop()
            try:
                children = set()
                for tid in os.listdir("/proc/%s/task" % parent):
                    try:
                        with open("/proc/%s/task/%s/children" % (parent, tid)) as stream:
                            children.update(int(value) for value in stream.read().split())
                    except OSError:
                        continue
                descendants.extend(children)
                pending.extend(children)
            except (OSError, ValueError):
                pass
        # Every invocation owns a separate session. Never kill shared MP browsers.
        try:
            if os.name == "posix":
                os.killpg(process.pid, signal.SIGKILL)
            elif process.poll() is None:
                process.kill()
        except ProcessLookupError:
            pass
        for pid in reversed(descendants):
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def _sign_isolated(self, site: Mapping[str, Any], rule: Mapping[str, Any],
                       options: Mapping[str, Any]) -> SignResult:
        payload = json.dumps({"site": dict(site), "rule": dict(rule), "options": dict(options),
                              "proxies": self.proxies if site.get("proxy") else None})
        process = None
        output = ""
        timed_out = False
        try:
            # Execute a clean interpreter; forking a threaded MP process would
            # inherit Playwright event loops and locks. Credentials travel on stdin.
            env = os.environ.copy()
            # MP can extend sys.path to its venv at startup. Carry that search
            # path into the clean interpreter without booting the whole app.
            env["PYTHONPATH"] = os.pathsep.join(dict.fromkeys(
                [path for path in sys.path if path] + env.get("PYTHONPATH", "").split(os.pathsep)))
            process = subprocess.Popen([sys.executable, os.path.abspath(__file__), "--local-browser-worker"],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, text=True,
                                       start_new_session=(os.name == "posix"), env=env)
            try:
                output, _ = process.communicate(payload, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                self._kill_browser_process(process)
                output, _ = process.communicate(timeout=3)
        except Exception:
            return SignResult("failed", "本地浏览器进程运行失败；未转交云端 Browserless")
        finally:
            if process is not None:
                self._kill_browser_process(process)
                if process.poll() is None:
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        pass
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
        confirmed = None
        completed = None
        stage = "启动浏览器"
        for line in output.splitlines():
            if not line.startswith("CAPTCHA_BROWSER:"):
                continue
            try:
                event = json.loads(line[len("CAPTCHA_BROWSER:"):])
                stage = event["stage"]
                value = event.get("result")
                result = SignResult(value["status"], value["message"]) if value else None
                if result and result.status in {"success", "already"}:
                    confirmed = result
                if stage == "完成":
                    completed = result
                self._report(stage, result)
            except (ValueError, KeyError, TypeError):
                continue
        if timed_out:
            message = "本地浏览器整体超时（%s），已终止本次浏览器进程" % stage
            if confirmed:
                return SignResult(confirmed.status, confirmed.message + "；" + message + "；魔力到账未核实")
            return SignResult("failed", message + "；签到结果未确认")
        if completed and (completed.status in {"success", "already"} or not confirmed):
            return completed
        if confirmed:
            return SignResult(confirmed.status, confirmed.message + "；浏览器异常退出，魔力到账未核实")
        return SignResult("failed", "本地浏览器未返回有效签到结果；未转交云端 Browserless")


def _local_browser_worker() -> None:
    """Disposable browser owner, supervised by the parent wall-clock deadline."""
    payload = json.load(sys.stdin)

    def report(stage: str, result: Optional[SignResult] = None) -> None:
        event = {"stage": stage, "result": {"status": result.status, "message": result.message} if result else None}
        print("CAPTCHA_BROWSER:" + json.dumps(event, ensure_ascii=False), flush=True)

    def action(**kwargs: Any) -> SignResult:
        from cloakbrowser import launch_context
        context = page = None
        result = None
        try:
            report("启动浏览器")
            context = launch_context(headless=True, proxy=payload.get("proxies"),
                                     user_agent=kwargs.get("ua"), **payload["options"])
            report("打开签到页面")
            page = context.new_page()
            page.set_default_timeout(15000)
            result = kwargs["callback"](page)
            report("签到及广告处理结束", result)
            return result
        finally:
            # A failure closing one page must not skip context cleanup.
            try:
                if page is not None:
                    report("关闭签到页面", result)
                    page.close()
            except Exception:
                pass
            finally:
                if context is not None:
                    report("关闭浏览器上下文", result)
                    context.close()

    signer = LocalBrowserSigner(action=action, proxies=payload.get("proxies"), progress=report)
    result = signer.sign(payload["site"], payload["rule"])
    report("完成", result)


if __name__ == "__main__" and "--local-browser-worker" in sys.argv:
    _local_browser_worker()
