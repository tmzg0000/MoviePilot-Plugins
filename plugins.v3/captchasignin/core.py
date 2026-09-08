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

SUCCESS_WORDS = ("签到成功", "簽到成功", "成功签到", "打卡成功", "success")
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
    custom = custom_rules.get(str(site.get("id"))) or custom_rules.get(host) or {}
    preset = DEFAULT_RULES.get(host)
    if preset is None and host.endswith(".open.cd"):
        preset = DEFAULT_RULES["open.cd"]
    rule = dict(preset or {})
    rule.update(custom)
    rule.setdefault("mode", "open_page")
    rule.setdefault("path", "/attendance.php")
    rule.setdefault("submit_selector", "input[type='submit']")
    rule.setdefault("already_keywords", [])
    return validate_rule(rule)


def validate_rule(rule: Mapping[str, Any]) -> Dict[str, Any]:
    result = dict(rule)
    mode = result.get("mode")
    if mode not in {"open_page", "cloudflare", "image"}:
        raise ValueError("签到方式必须为 open_page、cloudflare 或 image")
    path = str(result.get("path") or "")
    if not path.startswith("/") or path.startswith("//") or "\\" in path or "#" in path:
        raise ValueError("签到路径必须是以 / 开头的站内路径")
    if mode == "image":
        for name in ("captcha_selector", "captcha_input_selector", "submit_selector"):
            if not str(result.get(name) or "").strip():
                raise ValueError("图片验证码规则缺少 " + name)
    return result


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
    if method == "click":
        return """(() => { const input = %s ? document.querySelector(%s) : null;
          if (input && !input.value.trim()) return false;
          const button = %s; if (!button) return false; button.click(); return true;
        })()""" % (input_json, input_json, target_script)
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


def build_query(rule: Mapping[str, Any], user_agent: Optional[str] = None) -> str:
    """Build one BrowserQL operation for a site check-in.

    Browserless recommends automatic captcha detection for Cloudflare and
    Turnstile.  Restricting ``solve`` to ``cloudflare`` made a Turnstile page
    depend on Browserless classifying it as that one specific type.
    """
    image = rule["mode"] == "image"
    solve = ("solveImageCaptcha(captchaSelector:$captchaSelector,inputSelector:$captchaInputSelector,timeout:$solveTimeout)"
             if image else "solve(timeout:$solveTimeout)" if rule["mode"] == "cloudflare"
             else "evaluate(content:\"'skipped'\"){value}")
    extra = "$captchaSelector:String! $captchaInputSelector:String!" if image else ""
    set_user_agent = "userAgent(userAgent:$userAgent){time}" if user_agent else ""
    user_agent_variable = " $userAgent:String!" if user_agent else ""
    return """mutation CheckIn($cookies:[CookieInput!]! $url:String! $submit:String! $beforeWait:Float! $wait:Float! $solveTimeout:Float! %s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitBefore:waitForTimeout(time:$beforeWait){time}
      before:html{html}
      solve:%s{found solved time}
      submit:evaluate(content:$submit){value}
      waitAfter:waitForTimeout(time:$wait){time}
      response:evaluate(content:"JSON.stringify(window.__captchasignin_response || null)"){value}
      after:html{html}
    }""" % (extra + user_agent_variable, set_user_agent, solve)


def build_preflight_query(user_agent: Optional[str] = None) -> str:
    """Read the page before a solver can fail on an absent post-sign-in CAPTCHA."""
    set_user_agent = "userAgent(userAgent:$userAgent){time}" if user_agent else ""
    user_agent_variable = " $userAgent:String!" if user_agent else ""
    return """mutation CheckInPreflight($cookies:[CookieInput!]! $url:String!%s) {
      %s
      cookies(cookies:$cookies){cookies{name}}
      goto(url:$url,waitUntil:domContentLoaded){status}
      waitForTimeout(time:2000){time}
      html{html}
    }""" % (user_agent_variable, set_user_agent)


def page_text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def compact_html(html: str) -> str:
    return page_text(html)[:240]


def classify(html: str, rule: Mapping[str, Any]) -> SignResult:
    full_text = page_text(html)
    text = full_text[:240]
    lower = full_text.lower()
    if any(word.lower() in lower for word in LOGIN_WORDS) and "logout" not in lower:
        return SignResult("failed", "Cookie 无效或已过期")
    if any(word.lower() in lower for word in rule.get("already_keywords", [])) or any(word in lower for word in ALREADY_WORDS):
        return SignResult("already", text or "今日已经签到")
    if any(word in lower for word in SUCCESS_WORDS):
        return SignResult("success", text or "签到成功")
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
        target_url = urllib.parse.urljoin(base_url + "/", str(rule["path"]).lstrip("/"))
        cookies = cookie_objects(cookie, target_url)
        if not cookies:
            return SignResult("failed", "站点 Cookie 格式无效")
        user_agent = str(site.get("ua") or "").strip()
        preflight_variables: Dict[str, Any] = {"cookies": cookies, "url": target_url}
        if user_agent:
            preflight_variables["userAgent"] = user_agent
        preflight = self._request(preflight_variables, "CheckInPreflight", build_preflight_query(user_agent))
        if isinstance(preflight, SignResult):
            return preflight
        if preflight.get("goto", {}).get("status") not in range(200, 400):
            return SignResult("failed", "打开签到页失败")
        initial = classify(str((preflight.get("html") or {}).get("html") or ""), rule)
        if initial.status in {"already", "success"}:
            return initial
        variables: Dict[str, Any] = {
            "cookies": cookies, "url": target_url,
            "submit": _submit_script(rule["submit_selector"], str(rule.get("submit_method") or "click"),
                                     rule.get("captcha_input_selector"), rule.get("submit_text")),
            "beforeWait": 2000, "wait": 3500, "solveTimeout": 60000,
        }
        if rule["mode"] == "image":
            variables.update({"captchaSelector": rule["captcha_selector"], "captchaInputSelector": rule["captcha_input_selector"]})
        if user_agent:
            variables["userAgent"] = user_agent
        data = self._request(variables, "CheckIn", build_query(rule, user_agent))
        if isinstance(data, SignResult):
            return data
        if data.get("goto", {}).get("status") not in range(200, 400):
            return SignResult("failed", "打开签到页失败")
        solve = data.get("solve") or {}
        if rule["mode"] == "image" and not solve.get("found"):
            return SignResult("failed", "未找到图片验证码；请检查验证码图片选择器")
        if rule["mode"] != "open_page" and solve.get("found") and not solve.get("solved"):
            return SignResult("failed", "找到验证码但未能完成验证")
        submitted = (data.get("submit") or {}).get("value")
        if rule["mode"] == "image" and submitted in (False, "false"):
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
