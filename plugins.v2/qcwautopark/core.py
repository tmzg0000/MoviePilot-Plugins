"""Cookie-authenticated parking API client; no browser or state.php writes."""
from __future__ import annotations

import math
import re
import time
from html import unescape
from html.parser import HTMLParser
from http.cookies import SimpleCookie
from threading import Event
from urllib.parse import urljoin, urlsplit

import requests


BASE_URL = "https://qcw.tangpt.top"
MAIN_HOSTS = ("www.tangpt.top", "tangpt.top")


class ParkingError(Exception):
    """Safe, credential-free error suitable for the plugin UI."""


def number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def matches_player(player, max_level=3, max_cash=3000):
    """Both inclusive bounds must match; missing/invalid fields never qualify."""
    level, cash = number(player.get("level")), number(player.get("cash"))
    return level is not None and cash is not None and 0 <= level <= max_level and 0 <= cash <= max_cash


def own_cars(state):
    return [c for c in state["userCars"] if c.get("userId") == state["userId"]]


def private_spot(spot):
    # The frontend uses 'charity' for charity spaces; accept only known private types.
    return spot.get("spotType") in ("private",)


def earnings(car, state, definitions, minimum_key="MIN_PARK_DURATION", timestamp=None):
    """Match garage base income: whole minutes * rate, capped, before scene bonus."""
    if car.get("status") != "parked":
        return None
    stamp = number(car.get("parkedTimestamp") if timestamp is None else timestamp)
    now = number(state.get("serverTime"))
    if stamp is None or now is None or stamp <= 0 or now <= 0:
        return None
    rules = dict(definitions.get("gameRules") or {})
    rules.update(state.get("gameSettings") or {})
    cap, minimum = number(rules.get("MAX_EARN_PER_SPOT")), number(rules.get(minimum_key))
    if cap is None or minimum is None or cap < 0 or minimum < 0:
        return None
    duration = max(0, math.floor((now * 1000 - stamp) / 60000))
    if duration < minimum:
        return None
    if car.get("carId") == 0 and car.get("flashCarName"):
        rate = number(car.get("flashEarnPerMin") or 5)
    else:
        model = next((m for m in definitions.get("cars", []) if m.get("id") == car.get("carId")), {})
        rate = number(model.get("earnPerMin"))
    return min(duration * rate, cap) if rate is not None and rate >= 0 else None


def site_host(url):
    text = str(url or "").strip()
    return urlsplit(text if "://" in text else "https://" + text).hostname


def trusted_url(url):
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in (*MAIN_HOSTS, "qcw.tangpt.top")
            or parts.username or parts.password or parts.port not in (None, 443)):
        raise ParkingError("主站登录跳转到未支持的地址，已停止认证")
    return url


class _NavigationParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.targets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "iframe" and attrs.get("src"):
            self.targets.append(attrs["src"])
        if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url\s*=\s*(.+)", attrs.get("content", ""), re.I)
            if match:
                self.targets.insert(0, match[1].strip(" '\""))
        if tag == "a" and "/tp-open-connect/sso/generate" in attrs.get("href", ""):
            self.targets.append(attrs["href"])


def login_navigation(html, current_url):
    """Only literal SSO navigation; no JavaScript execution or guessed callback URLs."""
    parser = _NavigationParser()
    parser.feed(html)
    script = re.search(r'''(?:window\.|top\.|parent\.)?location(?:\.href)?\s*=\s*['"]([^'"]+)['"]|(?:window\.)?location\.(?:replace|assign)\(\s*['"]([^'"]+)['"]''', html)
    if script:
        parser.targets.insert(0, script.group(1) or script.group(2))
    for target in parser.targets:
        target = urljoin(current_url, unescape(target))
        try:
            trusted_url(target)
        except (ParkingError, ValueError):
            continue
        parts = urlsplit(target)
        if parts.hostname == "qcw.tangpt.top" or "/tp-open-connect/sso/" in parts.path:
            return target
    return None


class ParkingClient:
    def __init__(self, cookie, session=None, site_url="https://www.tangpt.top", user_agent=None,
                 stop=None, request_interval=10):
        cookie = str(cookie or "").strip()
        if cookie.lower().startswith("cookie:"):
            cookie = cookie.split(":", 1)[1].strip()
        if not cookie or "=" not in cookie or "\n" in cookie or "\r" in cookie:
            raise ParkingError("MP 主站 Cookie 无效，请在站点管理中更新")
        host = site_host(site_url)
        if host not in MAIN_HOSTS:
            raise ParkingError("请选择 MP 中对应的躺平 PT 主站")
        parsed = SimpleCookie()
        try:
            parsed.load(cookie)
        except Exception:
            raise ParkingError("MP 主站 Cookie 无法解析，请在站点管理中更新") from None
        if not parsed:
            raise ParkingError("MP 主站 Cookie 无法解析，请在站点管理中更新")
        self.session = session or requests.Session()
        self.session.headers.pop("Cookie", None)
        for name, morsel in parsed.items():
            self.session.cookies.set(name, morsel.value, domain=host, path="/", secure=True)
        self.session.headers.update({"User-Agent": str(user_agent or "Mozilla/5.0")})
        self.main_url = "https://" + host + "/parking.php"
        self.stop = stop or Event()
        self.request_interval = max(0, request_interval)
        self._last_finished = None

    def close(self):
        self.session.close()

    def _request(self, method, url, **kwargs):
        trusted_url(url)
        if self._last_finished is not None:
            delay = max(0, self.request_interval - (time.monotonic() - self._last_finished))
            if self.stop.wait(delay):
                raise ParkingError("任务已停止")
        if self.stop.is_set():
            raise ParkingError("任务已停止")
        try:
            return self.session.request(method, url, timeout=(15, 90), allow_redirects=False, **kwargs)
        except requests.RequestException:
            raise ParkingError("游戏请求失败或超时，本轮停止；下次先重新读取状态") from None
        finally:
            self._last_finished = time.monotonic()

    def authenticate(self):
        """Enter through the game's observed main-site login link, retaining Set-Cookie."""
        current, referer, seen = self.main_url, BASE_URL + "/index.html", set()
        for _ in range(12):
            if current in seen:
                raise ParkingError("主站登录跳转循环，请更新 MP 主站 Cookie")
            seen.add(current)
            response = self._request("GET", current, headers={"Referer": referer})
            if response.status_code == 429:
                raise ParkingError("主站登录被限流，本轮停止")
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("Location")
                if not location:
                    raise ParkingError("主站登录跳转缺少目标地址")
                target = urljoin(current, location)
                trusted_url(target)
            elif response.status_code == 200:
                target = login_navigation(response.text, current)
                if not target:
                    if urlsplit(current).hostname != "qcw.tangpt.top":
                        raise ParkingError("未取得游戏登录跳转，请更新 MP 主站 Cookie；若有授权或验证提示需先手动完成")
                    self.state()  # A landing page alone never proves authentication.
                    return
            else:
                raise ParkingError("主站游戏登录失败，请检查 MP 站点 Cookie 与连接")
            if urlsplit(target).path.rstrip("/").lower() in ("/login.php", "/login"):
                raise ParkingError("主站 Cookie 已失效，请在 MP 站点管理中更新")
            referer, current = current, target
        raise ParkingError("主站游戏登录跳转次数过多，本轮停止")

    def call(self, endpoint, payload=None):
        if endpoint not in ("state.php", "game_data.php", "park.php", "unpark.php", "ticket.php"):
            raise ParkingError("不支持的游戏操作")
        if (payload is None) != (endpoint in ("state.php", "game_data.php")):
            raise ParkingError("游戏请求方式不匹配")
        response = self._request("GET" if payload is None else "POST", BASE_URL + "/api/" + endpoint,
                                 headers={"Referer": BASE_URL + "/index.html", "Origin": BASE_URL},
                                 **({"json": payload} if payload is not None else {}))
        if response.status_code in (401, 403):
            raise ParkingError("游戏认证失败，请更新 MP 主站 Cookie，下轮将重新从主站登录")
        if response.status_code == 429:
            raise ParkingError("游戏接口限流，本轮停止，等待下一次定时检查")
        if response.status_code != 200:
            raise ParkingError("游戏接口响应异常（HTTP %s）" % response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise ParkingError("游戏接口未返回 JSON，请检查登录状态") from None
        if not isinstance(data, dict) or data.get("success") is not True:
            message = str(data.get("error") or "") if isinstance(data, dict) else ""
            if any(word in message for word in ("登录", "凭证", "认证", "token", "Cookie")):
                raise ParkingError("游戏认证失败，请更新 MP 主站 Cookie，下轮将重新从主站登录")
            raise ParkingError("游戏接口拒绝操作，本轮停止；下轮将重新检查状态")
        return data

    def state(self):
        data = self.call("state.php")
        if (not data.get("userId") or not isinstance(data.get("users"), dict)
                or not isinstance(data.get("userCars"), list) or not isinstance(data.get("parkingSpots"), list)
                or not all(isinstance(c, dict) for c in data["userCars"] + data["parkingSpots"])
                or not all(isinstance(p, dict) for p in data["users"].values())):
            raise ParkingError("游戏状态结构异常，已停止操作")
        return data


class ParkingRunner:
    def __init__(self, client, threshold=2000, max_level=3, max_cash=3000, stop=None, interval=0,
                 ticket_threshold=1000, auto_ticket=True):
        self.client = client
        self.threshold, self.max_level, self.max_cash = threshold, max_level, max_cash
        self.stop = stop or Event()
        self.interval = interval
        self.ticket_threshold, self.auto_ticket = ticket_threshold, auto_ticket
        self.report = {"collected": 0, "parked": 0, "ticketed": 0, "idle": None, "earned": 0, "actions": []}

    def check(self):
        if self.stop.is_set():
            raise ParkingError("任务已停止")

    def after_action(self):
        if self.stop.wait(self.interval):
            raise ParkingError("任务已停止")

    def run(self):
        self.check()
        definitions = self.client.call("game_data.php")
        if not isinstance(definitions.get("cars"), list) or not all(isinstance(c, dict) for c in definitions["cars"]):
            raise ParkingError("车型数据结构异常")
        state = self.client.state()
        account = state["userId"]
        def refresh():
            self.check()
            current = self.client.state()
            if current["userId"] != account:
                raise ParkingError("游戏账号发生变化，已停止")
            return current
        if self.auto_ticket:
            ticket_ids = [s.get("id") for s in state["parkingSpots"] if s.get("id")
                          and s.get("ownerId") == account and private_spot(s) and s.get("carInSpot")]
            for spot_id in ticket_ids:
                state = refresh()
                spot = next((s for s in state["parkingSpots"] if s.get("id") == spot_id), None)
                if not spot or spot.get("ownerId") != account or not private_spot(spot) or not spot.get("carInSpot"):
                    continue
                car = next((c for c in state["userCars"] if c.get("id") == spot["carInSpot"]), None)
                if not car or car.get("userId") in (None, account):
                    continue
                stamp = number(spot.get("parkedTimestamp"))
                if stamp is None or stamp <= 0:
                    continue
                amount = earnings(car, state, definitions, minimum_key="MIN_TICKET_TIME", timestamp=stamp)
                if amount is None or amount < self.ticket_threshold:
                    continue
                previous_car = spot["carInSpot"]
                self.check()
                result = self.client.call("ticket.php", {"spotId": spot_id})
                self.after_action()
                state = refresh()
                current = next((s for s in state["parkingSpots"] if s.get("id") == spot_id), None)
                if not current or current.get("carInSpot") == previous_car:
                    raise ParkingError("接口返回贴条成功，但状态未确认，本轮停止")
                self.report["ticketed"] += 1
                self.report["earned"] += number(result.get("ownerEarn")) or 0
                self.report["actions"].append("贴条成功")
        state = refresh()
        ids = [c.get("id") for c in own_cars(state) if c.get("id") and c.get("status") == "parked"]
        for car_id in ids:
            state = refresh()
            car = next((c for c in own_cars(state) if c.get("id") == car_id), None)
            amount = earnings(car, state, definitions) if car else None
            if amount is None or amount <= self.threshold:
                continue
            self.check()
            result = self.client.call("unpark.php", {"userCarId": car_id})
            self.after_action()
            state = refresh()
            car = next((c for c in own_cars(state) if c.get("id") == car_id), None)
            if not car or car.get("status") != "idle":
                raise ParkingError("接口返回收车成功，但状态未确认，本轮停止")
            self.report["collected"] += 1
            self.report["earned"] += number(result.get("earned")) or 0
            self.report["actions"].append("收车成功")
        # Snapshot only IDs. Recheck owner, both limits, occupancy and idle car before EVERY POST.
        state = refresh()
        spots = [s.get("id") for s in state["parkingSpots"] if s.get("id") and private_spot(s)
                 and not s.get("carInSpot") and s.get("ownerId") != account
                 and matches_player(state["users"].get(s.get("ownerId"), {}), self.max_level, self.max_cash)]
        for spot_id in spots[:100]:
            state = refresh()
            idle = [c for c in own_cars(state) if c.get("id") and c.get("status") == "idle"]
            if not idle:
                break
            spot = next((s for s in state["parkingSpots"] if s.get("id") == spot_id), None)
            if (not spot or not private_spot(spot) or spot.get("carInSpot") or spot.get("ownerId") == account
                    or not matches_player(state["users"].get(spot.get("ownerId"), {}), self.max_level, self.max_cash)):
                continue
            car_id = idle[0]["id"]
            self.check()
            self.client.call("park.php", {"userCarId": car_id, "spotId": spot_id})
            self.after_action()
            state = refresh()
            car = next((c for c in own_cars(state) if c.get("id") == car_id), None)
            spot = next((s for s in state["parkingSpots"] if s.get("id") == spot_id), None)
            if not car or car.get("status") != "parked" or not spot or spot.get("carInSpot") != car_id:
                raise ParkingError("接口返回停车成功，但状态未确认，本轮停止")
            self.report["parked"] += 1
            self.report["actions"].append("停车成功")
        state = refresh()
        self.report["idle"] = sum(c.get("status") == "idle" for c in own_cars(state))
        return self.report
