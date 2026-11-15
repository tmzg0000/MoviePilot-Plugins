"""HDHaven website check-in over HTTP; no browser or OpenAPI credentials."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

import requests

HOST = "hdhaven.com"
ORIGIN = "https://hdhaven.com"
URL = ORIGIN + "/me"
PROFILE = "/api/auth/me"
MODES = {"normal": "普通签到", "gamble": "赌狗签到"}
CHECKIN_PATHS = {"normal": "/api/account/checkin", "gamble": "/api/account/checkin/gamble"}
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")
TIMEOUT = (10, 30)
ERROR_CODES = {
    "BROWSER_REQUIRED": "站点拒绝了网页直连请求，本次停止；不会启动浏览器或切换 OpenAPI",
    "SCRAPE_CHALLENGE_REQUIRED": "站点要求安全验证，请手动访问栖影完成验证后同步 Cookie",
    "SESSION_VERIFY_REQUIRED": "站点要求验证登录会话，请手动完成验证后同步 Cookie",
}


class SigninError(Exception):
    pass


def cookie_items(header):
    items = []
    for part in header.split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            items.append((name, value))
    if not items:
        raise SigninError("CookieCloud 中栖影 Cookie 为空或格式无效")
    return items


def _cancelled(stop):
    if stop and stop.is_set():
        raise SigninError("任务已停止")


def _payload(response):
    try:
        payload = response.json()
    except (ValueError, requests.RequestException):
        return {}
    return payload if isinstance(payload, dict) else {}


def _check_response(response, payload, stage="账户校验"):
    # Only emit our own messages: response text can contain account/session data.
    code = payload.get("code")
    if isinstance(code, str) and code in ERROR_CODES:
        raise SigninError(ERROR_CODES[code])
    status = response.status_code
    if status == 401:
        raise SigninError(f"{stage} HTTP 401：站点未接受 CookieCloud 中的登录 Cookie")
    if 300 <= status < 400:
        location = str(response.headers.get("Location", ""))
        path = urlsplit(location).path
        target = "登录页" if path.rstrip("/") == "/login" else (
            "会话验证页" if path.rstrip("/") == "/verify-session" else "其他页面")
        raise SigninError(f"{stage} HTTP {status}：跳转到{target}，尚不能确认 Cookie 过期")
    if status == 403:
        raise SigninError("栖影拒绝访问（HTTP 403），请检查会话验证、Cookie 和代理出口")
    if status == 429:
        raise SigninError("站点请求限流（HTTP 429），本次停止，不自动重试提交")
    if status != 200:
        raise SigninError(f"栖影请求失败（HTTP {status}）")
    if payload.get("success") is False:
        raise SigninError("栖影返回业务失败，本次未确认签到")


def _get_profile(session, stop):
    _cancelled(stop)
    try:
        response = session.get(ORIGIN + PROFILE, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        raise SigninError("读取栖影账户失败，请检查网络和 MP 代理") from None
    payload = _payload(response)
    _check_response(response, payload)
    profile = payload.get("data")
    if not isinstance(profile, dict) or type(profile.get("checkin_today")) is not bool:
        raise SigninError("账户响应缺少明确的今日签到状态，可能 Cookie 无效或站点格式变化")
    return profile


def _summary(profile, submitted=None):
    parts = []
    for label, key, source in (("本次积分", "earned", submitted or {}),
                               ("当前积分", "points", profile),
                               ("连续天数", "checkin_streak", profile)):
        value = source.get(key)
        if type(value) in (int, float):
            parts.append(f"{label} {value}")
    return "；" + "，".join(parts) if parts else ""


def run_http(session, mode, before_submit, attempted=False, stop=None, check_only=False):
    if mode not in MODES:
        raise SigninError("签到模式无效，请重新选择")
    _cancelled(stop)
    # Visit the requested account page before checking its live website account state.
    try:
        response = session.get(URL, timeout=TIMEOUT, allow_redirects=False)
    except requests.RequestException:
        raise SigninError("访问栖影个人中心失败，请检查网络和 MP 代理") from None
    # A redirect on the HTML entry is not an authoritative session verdict.
    # Still read the fixed account URL (never follow the Location with cookies).
    landing_status = response.status_code
    if not 300 <= landing_status < 400:
        _check_response(response, _payload(response), stage="个人中心")
    profile = _get_profile(session, stop)
    if profile["checkin_today"]:
        return {"status": "已签到", "message": "账户确认今日已签到" + _summary(profile)}
    if check_only:
        return {"status": "已登录", "message": "账户确认 Cookie 有效，今日尚未签到；仅检测，未提交签到"}
    if attempted:
        raise SigninError("今天已发起过提交，账户尚未确认签到；为避免重复操作不再提交")
    _cancelled(stop)
    before_submit()
    response = None
    payload = {}
    try:
        # Same request as the website button: empty POST, no OpenAPI or bearer token.
        response = session.post(ORIGIN + CHECKIN_PATHS[mode], timeout=TIMEOUT, allow_redirects=False)
        payload = _payload(response)
    except requests.RequestException:
        # A timeout may occur after the server committed the check-in. Read back once;
        # never repeat the POST, even if the read also fails or the plugin restarts.
        pass
    try:
        profile = _get_profile(session, stop)
    except SigninError:
        raise SigninError("已发起签到，但账户复查失败；结果未确认，今天不再重复提交") from None
    if profile["checkin_today"]:
        submitted = payload.get("data")
        # Use award data only from a successful website response.
        if response is None or response.status_code != 200 or payload.get("success") is False:
            submitted = None
        return {"status": "成功", "message": MODES[mode] + "后账户确认今日已签到" +
                _summary(profile, submitted if isinstance(submitted, dict) else None)}
    if response is not None:
        _check_response(response, payload)
    raise SigninError("已发起签到，但账户未确认成功；今天不再自动重复提交")


def cookie_diagnostic(items):
    # Names/counts only. Never include values, hashes, lengths or response bodies.
    names = []
    for name, value in items:
        if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name) and name not in names:
            names.append(name)
    duplicates = len(items) - len({name for name, value in items})
    empty = sum(not value for name, value in items)
    fields = ", ".join(names[:12]) or "无可显示字段"
    return f"同步 Cookie {len(items)} 项；字段 {fields}；同名重复 {duplicates}；空值 {empty}"


def sign(cookie, mode, proxy, before_submit, attempted=False, stop=None, check_only=False):
    _cancelled(stop)
    items = cookie_items(cookie)
    with requests.Session() as session:
        # Explicit MP proxy choice also controls environment proxy inheritance.
        session.trust_env = False
        if proxy:
            session.proxies.update(proxy)
        session.headers.update({
            "User-Agent": USER_AGENT, "Accept": "*/*", "Referer": URL, "Origin": ORIGIN,
            "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors", "Sec-Fetch-Dest": "empty",
            "Cache-Control": "no-cache",
        })
        for name, value in items:
            session.cookies.set(name, value, domain=HOST, path="/", secure=True)
        # All URLs are fixed HTTPS destinations and redirects are disabled to keep
        # cookies on HDHaven; requests keeps TLS certificate validation enabled.
        try:
            result = run_http(session, mode, before_submit, attempted, stop, check_only)
            if check_only:
                result["message"] += "；" + cookie_diagnostic(items)
            return result
        except SigninError as error:
            raise SigninError(str(error) + "；" + cookie_diagnostic(items)) from None
