"""M-Team browser email login and account statistics. Derived from qingyukb, GPL-3.0."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Tuple

DEFAULT_SITE = "https://kp.m-team.cc"
DEFAULT_API_BASE = "https://api.m-team.cc"


# ------------------------------------------------------------------ 统计解析
def human_size(value: Any) -> str:
    try:
        size = float(value)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024 or unit == "PB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return ""


def _first(data: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, ""):
            return data[key]
    return None


def parse_profile(payload: Any) -> Dict[str, Any]:
    """把 /api/member/profile 的返回解析成页面要用的字段（容错优先）。"""
    body = payload if isinstance(payload, Mapping) else {}
    data = body.get("data") if isinstance(body.get("data"), Mapping) else body
    status = data.get("memberStatus") if isinstance(data.get("memberStatus"), Mapping) else {}
    count = data.get("memberCount") if isinstance(data.get("memberCount"), Mapping) else {}

    ratio = _first(count, "shareRate", "ratio", "shareRatio")
    try:
        ratio_value = float(ratio) if ratio is not None else None
    except (TypeError, ValueError):
        ratio_value = None
    uploaded = _first(count, "uploaded", "upload")
    downloaded = _first(count, "downloaded", "download")
    bonus = _first(count, "bonus", "bonusValue")
    return {
        "id": str(_first(data, "id") or ""),
        "username": str(_first(data, "username", "name") or ""),
        "email": str(_first(data, "email") or ""),
        "level": str(_first(data, "memberLevel", "level", "role") or ""),
        "last_login": str(_first(status, "lastLogin", "last_login") or ""),
        "last_browse": str(_first(status, "lastBrowse", "last_browse") or ""),
        "uploaded": human_size(uploaded),
        "downloaded": human_size(downloaded),
        "bonus": str(bonus if bonus is not None else ""),
        "ratio": (f"{ratio_value:.3f}" if ratio_value is not None else ""),
        "ratio_value": ratio_value,
        "warning": str(_first(count, "warning", "warnings") or ""),
    }


# ------------------------------------------------------------------ 最近动向
_TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M",
                 "%Y/%m/%d %H:%M:%S", "%Y-%m-%d")


def parse_datetime(value: Any) -> Optional[datetime]:
    """把 M-Team 返回的时间（字符串 / 毫秒时间戳）解析成 datetime（无时区按本地时区）。"""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value) / (1000 if float(value) > 1e11 else 1)
        try:
            return datetime.fromtimestamp(seconds)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip().replace("Z", "+00:00")
    # 站点可能带相对时间后缀：2026-10-19 17:31:48 (1 分鐘前)
    text = re.sub(r"\s*[（(][^()（）]*[）)]\s*$", "", text).strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        parsed = None
        for fmt in _TIME_FORMATS:
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone().replace(tzinfo=None)
    return parsed


def last_activity(profile: Mapping[str, Any]) -> Tuple[Optional[datetime], str]:
    """取「最近动向」：优先 lastBrowse（最近浏览），退回 lastLogin。"""
    browse = parse_datetime(profile.get("last_browse"))
    if browse is not None:
        return browse, "最近浏览"
    login = parse_datetime(profile.get("last_login"))
    if login is not None:
        return login, "最近登录"
    return None, ""


def format_activity(profile: Mapping[str, Any]) -> str:
    """按站点写法展示最近动向：2026-10-19 17:31:48（1 分鐘前）。"""
    raw = str(profile.get("last_browse") or profile.get("last_login") or "").strip()
    moments = parse_datetime(raw)
    if moments is None:
        return raw
    minutes = int((datetime.now() - moments).total_seconds() // 60)
    if minutes < 1:
        relative = "剛剛"
    elif minutes < 60:
        relative = f"{minutes} 分鐘前"
    elif minutes < 60 * 24:
        relative = f"{minutes // 60} 小時前"
    else:
        relative = f"{minutes // (60 * 24)} 天前"
    return f"{moments.strftime('%Y-%m-%d %H:%M:%S')}（{relative}）"


def activity_minutes_ago(profile: Mapping[str, Any]) -> Optional[float]:
    """最近动向距今多少分钟；读不到返回 None。"""
    moment, _ = last_activity(profile)
    if moment is None:
        return None
    delta = datetime.now() - moment
    return delta.total_seconds() / 60


# ------------------------------------------------------------------ API 读取
def fetch_profile(api_key: str, api_base: str = DEFAULT_API_BASE,
                  timeout: int = 20) -> Tuple[Optional[Dict[str, Any]], str]:
    """用 API Key 读账号详情，返回 (profile, 错误说明)。"""
    try:
        import requests
    except ImportError:
        # 极少见的精简环境没有 requests：保活照常，只是读不到统计
        return None, "当前环境缺少 requests 库，读不到账号统计"

    key = str(api_key or "").strip()
    if not key:
        return None, "未配置 API Key"
    url = str(api_base or DEFAULT_API_BASE).rstrip("/") + "/api/member/profile"
    try:
        response = requests.post(url, headers={"x-api-key": key,
                                               "Content-Type": "application/json",
                                               "Accept": "application/json"},
                                 json={}, timeout=timeout)
    except Exception as error:
        return None, f"请求异常：{error}"
    if response.status_code in {401, 403}:
        return None, f"API Key 无效（HTTP {response.status_code}）"
    if response.status_code >= 400:
        return None, f"接口返回 HTTP {response.status_code}"
    try:
        payload = response.json()
    except ValueError:
        return None, "接口返回的不是 JSON"
    code = payload.get("code") if isinstance(payload, dict) else None
    if code not in (None, 0, "0"):
        return None, f"接口返回异常：{payload.get('message') or code}"
    parsed = parse_profile(payload)
    if not parsed.get("username") and not parsed.get("id"):
        return None, "接口没有返回账号信息"
    return parsed, ""


# ------------------------------------------------------------------ 浏览器保活
LOGIN_JS_FILL = """
(args) => {
  const [username, password] = args;
  const setValue = (node, value) => {
    const setter = Object.getOwnPropertyDescriptor(
      node.constructor.prototype, 'value').set;
    setter.call(node, value);
    node.dispatchEvent(new Event('input', { bubbles: true }));
    node.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const visible = (node) => Boolean(node) &&
    (node.offsetParent !== null || node.getClientRects().length > 0);

  // 密码框最稳：type=password
  const passInput = [...document.querySelectorAll('input[type=password]')].find(visible);
  if (!passInput) return false;

  // 用户名框：同表单里密码框前面的文本框，或按 placeholder / autocomplete 猜
  const form = passInput.form || document;
  const candidates = [
    form.querySelector('input#username'),
    form.querySelector('input[name=username]'),
    form.querySelector('input[autocomplete=username]'),
    form.querySelector('input[type=email]'),
    form.querySelector('input[type=text]'),
    ...[...form.querySelectorAll('input')].filter((node) =>
      /帳號|账号|用戶|用户|郵箱|邮箱|email|account|username/i.test(node.placeholder || '')),
  ].filter((node) => node && node !== passInput && visible(node));

  const userInput = candidates[0];
  if (!userInput) return false;

  setValue(userInput, username);
  setValue(passInput, password);

  const scope = passInput.form || document;
  const button = scope.querySelector('button[type=submit]') ||
                 [...scope.querySelectorAll('button, [role=button]')].find((node) =>
                   /登錄|登录|登入|login|sign in/i.test((node.textContent || '').trim()));
  if (!button) return false;
  button.click();
  return true;
}
"""

EMAIL_CODE_SELECTOR = (
    'input#code:visible, input[autocomplete="one-time-code"]:visible, '
    'input[maxlength="6"]:visible'
)

HAS_LOGIN_FORM_JS = """
() => {
  const pick = (selector) => [...document.querySelectorAll(selector)]
    .some((node) => node.offsetParent !== null || node.getClientRects().length > 0);
  return pick('input[type=password]') || pick('input#username') || pick('input[name=username]')
    || pick('input[placeholder*="帳號"]') || pick('input[placeholder*="账号"]');
}
"""

CHALLENGE_JS = """
() => {
  const text = (document.body && document.body.innerText || '').toLowerCase();
  return /just a moment|checking your browser|正在进行安全检测|正在验证您是否是真人|verify you are human/.test(text)
    || Boolean(document.querySelector('iframe[src*=challenges.cloudflare.com], .cf-turnstile, #cf-chl-widget'));
}
"""

CLICK_CF_JS = """
() => {
  const frame = document.querySelector('iframe[src*=challenges.cloudflare.com]');
  if (frame) {
    try {
      const doc = frame.contentDocument;
      const box = doc && doc.querySelector('input[type=checkbox]');
      if (box) { box.click(); return true; }
    } catch (error) {}
  }
  const turnstile = document.querySelector('.cf-turnstile, #cf-chl-widget');
  if (turnstile) { turnstile.click(); return true; }
  return false;
}
"""

# The public login UI uses an Ant Design email tab and requires the bound email
# before /member/sendLoginEmailVerifyCode. Submitting an existing code must not resend it.
EMAIL_TAB_JS = r"""
() => {
  const tab = [...document.querySelectorAll('[role=tab]')].find(n =>
    /郵箱|邮箱|郵件|邮件|電郵|电子邮件|email|e-mail/i.test(n.textContent || ''));
  if (!tab) return false;
  if (tab.getAttribute('aria-selected') !== 'true') tab.click();
  return true;
}
"""
EMAIL_INPUT_SELECTOR = (
    'input#email:visible, input[type=email]:visible, '
    'input[placeholder*="郵箱"]:visible, input[placeholder*="邮箱"]:visible, '
    'input[placeholder*="郵件"]:visible, input[placeholder*="邮件"]:visible, '
    'input[placeholder*="email" i]:visible'
)
# The email form validates asynchronously (useWatch + validateFields). A disabled
# send button is present during that validation, so wait before clicking once.
EMAIL_BUTTON_QUERY_JS = r"""
() => {
  const email = document.querySelector('input#email') ||
    [...document.querySelectorAll('input')].find(n => n.getClientRects().length &&
      (n.type === 'email' || /郵箱|邮箱|郵件|邮件|email/i.test(n.placeholder || '')));
  const scope = (email && email.form) || document;
  return [...scope.querySelectorAll('button, [role=button]')].find(n =>
    n.getClientRects().length && n.type !== 'submit' &&
    /發送|发送|寄送|寄出|獲取|获取|取得|send|get.*code|verification.*code|^\s*\d+\s*s\s*$/i
      .test(n.textContent || '')) || null;
}
"""
SEND_EMAIL_STATUS_JS = '() => { const n = (' + EMAIL_BUTTON_QUERY_JS + ')(); ' + (
    "return !n ? 'missing' : n.disabled || n.getAttribute('aria-disabled') === 'true' "
    "? 'disabled' : 'ready'; }"
)
SEND_EMAIL_JS = '() => { const n = (' + EMAIL_BUTTON_QUERY_JS + ')(); ' + (
    "if (!n || n.disabled || n.getAttribute('aria-disabled') === 'true') return false; "
    "n.click(); return true; }"
)
STORAGE_JS = "() => ({local: {...localStorage}, session: {...sessionStorage}})"
RESTORE_STORAGE_JS = r"""
(state) => {
  if (location.origin !== state.origin) return;
  // An init script runs on every navigation. Restore once per browser context so
  // a token refreshed by the website is never replaced with the previous token.
  if (sessionStorage.getItem('__mp_mteam_restored')) return;
  for (const [k,v] of Object.entries(state.local || {})) localStorage.setItem(k,v);
  for (const [k,v] of Object.entries(state.session || {})) sessionStorage.setItem(k,v);
  sessionStorage.setItem('__mp_mteam_restored', '1');
}
"""


def session_identity(username: str, password: str, site_url: str) -> str:
    import hashlib
    return hashlib.sha256(json.dumps([username, password, site_url],
                                     ensure_ascii=False).encode()).hexdigest()


def keepalive_login(username: str, password: str, email: str = "", email_code: str = "",
                    request_email: bool = False, state: Optional[dict] = None,
                    site_url: str = DEFAULT_SITE, timeout: int = 180,
                    logger: Any = None) -> Dict[str, Any]:
    """Restore browser state or perform a user-requested email login.

    Only authenticated /member/profile responses count as browser success;
    stale localStorage tokens or an /index URL alone never do.
    """
    from urllib.parse import urlsplit
    base = str(site_url or DEFAULT_SITE).rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
        return {"ok": False, "message": "站点地址必须是有效的 HTTPS 地址"}
    origin = f"{parsed.scheme}://{parsed.netloc}"
    identity = session_identity(username, password, base)
    state = dict(state or {}) if (state or {}).get('identity') == identity else {}
    if not username or not password:
        return {"ok": False, "message": "请先填写账号、密码和绑定邮箱"}
    if email_code and not re.fullmatch(r'[0-9]{6}', email_code):
        return {"ok": False, "message": "邮箱验证码必须为 6 位数字"}
    if not state and not request_email and not email_code:
        return {"ok": False, "message": "尚未登录，请先点击「获取验证码」，再填码并点击「登录」"}
    try:
        from app.helper.browser import PlaywrightHelper
    except ImportError:
        return {"ok": False, "message": "MoviePilot 缺少本地 Playwright 浏览器依赖"}

    def callback(page: Any) -> dict:
        profile = {}
        sent = False
        login_error = False

        def response_received(response: Any) -> None:
            nonlocal profile, sent, login_error
            path = urlsplit(response.url).path
            if path not in ('/api/member/profile', '/api/member/sendLoginEmailVerifyCode', '/api/login'):
                return
            try:
                payload = response.json()
                if not isinstance(payload, dict):
                    return
                if path == '/api/member/profile':
                    data = parse_profile(payload)
                    if payload.get('code') in (0, '0') and data.get('id'):
                        profile = data
                elif path.endswith('/sendLoginEmailVerifyCode'):
                    sent = payload.get('code') in (0, '0')
                else:
                    login_error = payload.get('code') not in (0, '0', 1001, '1001', 1002, '1002')
            except Exception:
                return

        page.on('response', response_received)

        def wait_for(predicate: Any, rounds: int = 30) -> bool:
            for _ in range(rounds):
                if predicate():
                    return True
                page.wait_for_timeout(1000)
            return bool(predicate())

        def result(ok: bool, message: str, save: bool = False) -> dict:
            data = {"ok": ok, "message": message, "email_sent": sent}
            if save:
                storage = page.evaluate(STORAGE_JS)
                storage.get('session', {}).pop('__mp_mteam_restored', None)
                data['state'] = {"identity": identity, "origin": origin,
                                 "cookies": page.context.cookies([base]), **storage}
            return data

        if state and not request_email and not email_code:
            page.context.add_cookies(state.get('cookies') or [])
            restore = {k: state.get(k) for k in ('origin', 'local', 'session')}
            # JSON here is JavaScript data, never shell text. Escape HTML delimiters.
            page.add_init_script('(' + RESTORE_STORAGE_JS + ')(' + json.dumps(restore) + ')')
            page.goto(base + '/index', wait_until='domcontentloaded', timeout=40000)
            if wait_for(lambda: bool(profile)):
                # Let the SPA finish its normal browsing/activity requests.
                page.wait_for_timeout(3000)
                return result(True, '已复用登录会话访问首页（账号接口验证通过）', save=True)
            return result(False, '会话失效或首页未能确认身份，请重新发送邮箱验证码并验证登录')

        if not email:
            return result(False, '邮箱验证需要填写账号绑定邮箱')
        page.goto(base + '/login', wait_until='domcontentloaded', timeout=40000)
        if not wait_for(lambda: page.evaluate(HAS_LOGIN_FORM_JS), 40):
            return result(False, '未加载登录表单，请检查站点与 static.m-team.cc 的连通性或浏览器验证')
        if not page.evaluate(LOGIN_JS_FILL, [username, password]):
            return result(False, '未找到账号密码登录表单')
        if not wait_for(lambda: bool(profile) or login_error or page.evaluate(EMAIL_TAB_JS)):
            return result(False, '站点未提供邮箱验证选项，请检查账号是否允许邮箱验证')
        if profile:
            return result(True, '账号已登录，无需邮箱验证', save=True)
        if login_error:
            return result(False, '账号登录被拒绝，请检查账号密码或站点安全验证')
        page.wait_for_timeout(1000)
        try:
            # Native fill drives React/Ant Design state and validation reliably.
            email_input = page.locator(EMAIL_INPUT_SELECTOR).first
            email_input.fill(email, timeout=5000)
            email_input.press('Tab')
        except Exception:
            return result(False, '未找到或无法填写绑定邮箱输入框，站点页面可能已更新')
        if email_code:
            try:
                code_input = page.locator(EMAIL_CODE_SELECTOR).first
                code_input.fill(email_code, timeout=5000)
                code_input.press('Tab')
                # React must receive the input event before Ant Design submits
                # the form. Native fill/click also waits for actionability.
                form = code_input.locator('xpath=ancestor::form[1]')
                form.locator('button[type="submit"]').click(timeout=5000)
            except Exception:
                return result(False, '未找到或无法提交邮箱验证码表单，请更新插件后重试')
            if wait_for(lambda: bool(profile)):
                page.goto(base + '/index', wait_until='domcontentloaded', timeout=30000)
                page.wait_for_timeout(3000)
                return result(True, '邮箱验证成功，已保存会话并访问首页', save=True)
            return result(False, '邮箱验证码登录未成功，请检查验证码是否正确、过期或触发安全验证')
        if not wait_for(lambda: page.evaluate(SEND_EMAIL_STATUS_JS) == 'ready', 15):
            status = page.evaluate(SEND_EMAIL_STATUS_JS)
            if status == 'disabled':
                return result(False, '发送验证码按钮暂不可用：邮箱校验未通过或仍在发送冷却期，请确认绑定邮箱后重试')
            return result(False, '未找到发送验证码按钮，站点页面结构或按钮文字可能已更新')
        if not page.evaluate(SEND_EMAIL_JS):
            return result(False, '发送验证码按钮状态已改变，请稍后重试')
        if wait_for(lambda: sent, 20):
            return result(False, '验证码已发送，请填入邮件中的 6 位验证码，然后点击「登录」')
        return result(False, '站点未确认邮件发送成功，请检查绑定邮箱、冷却时间或安全验证')

    try:
        outcome = PlaywrightHelper().action(url='about:blank', callback=callback,
                                            headless=True, timeout=timeout)
        return outcome or {"ok": False, "message": "浏览器没有返回结果"}
    except Exception:
        # Browser exceptions may include evaluated input arguments or cookies.
        return {"ok": False, "message": "浏览器执行失败，请检查浏览器依赖、网络及站点安全验证后重试"}
