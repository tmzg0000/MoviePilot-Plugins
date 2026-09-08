"""Browserless-backed PT attendance primitives shared by all plugin entrypoints.

This module deliberately has no MoviePilot imports so the behaviour can be
unit-tested and copied unchanged into the V2 and V3 plugin directories.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_RULES: Dict[str, Dict[str, Any]] = {
    "open.cd": {
        "mode": "image",
        "path": "/plugin_sign-in.php",
        "captcha_selector": "#frmSignin img",
        "captcha_input_selector": "#imagestring",
        "submit_selector": "#ok",
        "submit_method": "ajax",
        "success_json": {"field": "/state", "values": ["success", "false"]},
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
        "wait": 5000,
    },
    "hdsky.me": {
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


def resolve_rule(site: Mapping[str, Any], custom_rules: Mapping[str, Mapping[str, Any]]) -> Dict[str, Any]:
    host = normalize_host(str(site.get("url") or ""))
    custom = (custom_rules.get(str(site.get("id"))) or custom_rules.get(host)
              or custom_rules.get("www." + host) or {})
    preset = DEFAULT_RULES.get(host)
    if preset is None and host.endswith(".open.cd"):
        preset = DEFAULT_RULES["open.cd"]
    rule = dict(preset or {})
    rule.update(custom)
    # 1.0.13 exposed dom_click for LuckPT.  Its reward handler always opens a
    # confirmation dialog, so migrate saved rules to the complete action.
    if host == "pt.luckpt.de" and rule.get("submit_method") == "dom_click":
        rule["submit_method"] = "confirm_click"
    rule.setdefault("mode", "open_page")
    rule.setdefault("path", "/attendance.php")
    rule.setdefault("submit_selector", "input[type='submit']")
    rule.setdefault("already_keywords", [])
    return validate_rule(rule)


def validate_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(rule)
    mode = result.get("mode")
    if mode not in {"open_page", "cloudflare", "image", "trigger_image", "altcha"}:
        raise ValueError("签到方式必须为 open_page、cloudflare、image、trigger_image 或 altcha")
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
      if (wanted) { const matches = [...document.querySelectorAll('input, button, a')];
        const found = matches.find((node) => ((node.value || node.textContent || '').trim().includes(wanted)));
        if (found) return found; }
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
    checkbox = json.dumps(str(rule["altcha_checkbox_selector"]))
    payload = json.dumps(str(rule["altcha_payload_selector"]))
    submit = _submit_script(str(rule["submit_selector"]), "dom_click", submit_text=rule.get("submit_text"))
    return """(async () => {
      const ready = () => { const input = document.querySelector(%s); return input && input.value.trim() ? input : null; };
      if (!ready()) { const checkbox = document.querySelector(%s); if (!checkbox) return false; checkbox.click(); }
      const deadline = Date.now() + 30000;
      while (!ready() && Date.now() < deadline) await new Promise((resolve) => setTimeout(resolve, 250));
      if (!ready()) return false;
      return await %s;
    })()""" % (payload, checkbox, submit)


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
    if extra:
        variable_suffix += " " + extra
    variable_suffix += user_agent_variable
    return """mutation CheckIn($cookies:[CookieInput!]! $url:String! $beforeWait:Float! $wait:Float!%s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitBefore:waitForTimeout(time:$beforeWait){time}
      before:html{html}
      %s
      %s
      %s
      waitAfter:waitForTimeout(time:$wait){time}
      response:evaluate(content:"JSON.stringify(window.__captchasignin_response || null)"){value}
      after:html{html}
    }""" % (variable_suffix, set_user_agent,
              "trigger:evaluate(content:$trigger){value}\n      waitForTrigger:waitForTimeout(time:$triggerWait){time}" if triggered_image else "",
              solve,
              "submit:click(selector:$selector){selector time}" if native_click else "submit:evaluate(content:$submit){value}")


def build_preflight_query(user_agent: Optional[str] = None) -> str:
    """Read the page before a solver can fail on an absent post-sign-in CAPTCHA."""
    set_user_agent = "userAgent(userAgent:$userAgent){time}" if user_agent else ""
    user_agent_variable = " $userAgent:String!" if user_agent else ""
    return """mutation CheckInPreflight($cookies:[CookieInput!]! $url:String!%s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitForTimeout(time:2000){time}
      before:html{html}
    }""" % (user_agent_variable, set_user_agent)


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
    if any(word.lower() in lower for word in rule.get("success_keywords", [])) or any(word in lower for word in SUCCESS_WORDS):
        return SignResult("success", text or "签到成功")
    if any(word.lower() in lower for word in rule.get("already_keywords", [])) or any(word in lower for word in ALREADY_WORDS):
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
        preflight_variables: Dict[str, Any] = {"cookies": cookies, "url": target}
        if user_agent:
            preflight_variables["userAgent"] = user_agent
        preflight = self._request(preflight_variables, "CheckInPreflight", build_preflight_query(user_agent))
        if isinstance(preflight, SignResult):
            return preflight
        if preflight.get("goto", {}).get("status") not in range(200, 400):
            return SignResult("failed", "打开签到页失败")
        initial = classify(str((preflight.get("before") or {}).get("html") or ""), rule)
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
        if rule["mode"] == "trigger_image":
            variables["trigger"] = _trigger_script(str(rule["trigger_selector"]))
            variables["triggerWait"] = int(rule.get("trigger_wait") or 500)
        if rule["mode"] != "open_page":
            variables["solveTimeout"] = 60000
        if rule["mode"] in {"image", "trigger_image"}:
            variables.update({"captchaSelector": rule["captcha_selector"], "captchaInputSelector": rule["captcha_input_selector"]})
        if user_agent:
            variables["userAgent"] = user_agent
        data = self._request(variables, "CheckIn", build_query(rule, user_agent))
        if isinstance(data, SignResult):
            return data
        if data.get("goto", {}).get("status") not in range(200, 400):
            return SignResult("failed", "打开签到页失败")
        solve = data.get("solve") or {}
        if rule["mode"] in {"image", "trigger_image"} and not solve.get("found"):
            return SignResult("failed", "未找到图片验证码；请检查验证码图片选择器")
        if rule["mode"] != "open_page" and solve.get("found") and not solve.get("solved"):
            return SignResult("failed", "找到验证码但未能完成验证")
        submitted = (data.get("submit") or {}).get("value")
        if rule["mode"] in {"image", "trigger_image"} and submitted in (False, "false"):
            return SignResult("failed", "验证码未自动填入输入框，未发送签到请求")
        ajax_result = classify_ajax_response((data.get("response") or {}).get("value"), rule)
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
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            return SignResult("failed", "Browserless 请求失败：%s" % str(exc))
        errors = value.get("errors") or []
        if errors:
            return SignResult("failed", "Browserless 执行失败：" + str(errors[0].get("message") or "未知错误"))
        return value.get("data") or {}
