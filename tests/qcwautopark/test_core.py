"""Offline API and business-rule regression tests for both MoviePilot versions."""
import copy
import importlib.util
from pathlib import Path
from threading import Event
import unittest
from unittest.mock import Mock

import requests

ROOT = Path(__file__).resolve().parents[2]


def load(version):
    spec = importlib.util.spec_from_file_location("qcw_core_" + version, ROOT / ("plugins." + version) / "qcwautopark/core.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture():
    return {"userId": "me", "serverTime": 10000,
            "users": {"me": {"level": 1, "cash": 0}, "ok": {"level": 3, "cash": 3000},
                      "rich": {"level": 1, "cash": 3001}, "high": {"level": 4, "cash": 10}},
            "userCars": [
                {"id": "exact", "userId": "me", "status": "parked", "carId": 1, "parkedTimestamp": 4000000},
                {"id": "over", "userId": "me", "status": "parked", "carId": 1, "parkedTimestamp": 3940000},
                {"id": "idle", "userId": "me", "status": "idle", "carId": 1},
                {"id": "foreign", "userId": "other", "status": "parked", "carId": 1, "parkedTimestamp": 1000}],
            "parkingSpots": [
                {"id": "occupied", "ownerId": "ok", "spotType": "private", "carInSpot": "over"},
                {"id": "free", "ownerId": "ok", "spotType": "private", "carInSpot": None},
                {"id": "rich", "ownerId": "rich", "spotType": "private", "carInSpot": None},
                {"id": "high", "ownerId": "high", "spotType": "private", "carInSpot": None},
                {"id": "charity", "ownerId": "ok", "spotType": "charity", "carInSpot": None},
                {"id": "own", "ownerId": "me", "spotType": "private", "carInSpot": None}]}


class FakeClient:
    def __init__(self):
        self.data = fixture()
        self.calls = []
        self.reads = 0
        self.on_read = None
        self.refuse = False

    def state(self):
        self.reads += 1
        if self.on_read:
            self.on_read(self)
        return copy.deepcopy(self.data)

    def call(self, endpoint, payload=None):
        if endpoint == "game_data.php":
            return {"cars": [{"id": 1, "earnPerMin": 20}],
                    "gameRules": {"MAX_EARN_PER_SPOT": 3000, "MIN_PARK_DURATION": 10, "MIN_TICKET_TIME": 5}}
        self.calls.append((endpoint, payload))
        if self.refuse:
            return {"success": True}  # False success must be caught by read-back.
        if endpoint == "ticket.php":
            spot = next(s for s in self.data["parkingSpots"] if s["id"] == payload["spotId"])
            car = next(c for c in self.data["userCars"] if c["id"] == spot["carInSpot"])
            car["status"] = "idle"
            spot["carInSpot"] = None
            return {"success": True, "ownerEarn": 700}
        car = next(c for c in self.data["userCars"] if c["id"] == payload["userCarId"])
        if endpoint == "unpark.php":
            car["status"] = "idle"
            for spot in self.data["parkingSpots"]:
                if spot.get("carInSpot") == car["id"]:
                    spot["carInSpot"] = None
            return {"success": True, "earned": 2020}
        spot = next(s for s in self.data["parkingSpots"] if s["id"] == payload["spotId"])
        car["status"] = "parked"
        spot["carInSpot"] = car["id"]
        return {"success": True}


class RulesTests(unittest.TestCase):
    def test_both_inclusive_limits_and_unknown_values(self):
        for version in ("v2", "v3"):
            core = load(version)
            for level, cash, expected in [(3, 3000, True), (2, 3000, True), (3, 0, True),
                                           (4, 100, False), (2, 3001, False), (None, 1, False),
                                           (1, None, False), (True, 10, False), (1, "NaN", False), (-1, 0, False)]:
                with self.subTest(version=version, level=level, cash=cash):
                    self.assertEqual(core.matches_player({"level": level, "cash": cash}), expected)
            self.assertTrue(core.matches_player({"level": 4, "cash": 5000}, 4, 5000))

    def test_strict_income_collection_and_reparking_only_qualified_lots(self):
        for version in ("v2", "v3"):
            core, client = load(version), FakeClient()
            report = core.ParkingRunner(client, interval=0).run()
            self.assertEqual(report["collected"], 1)
            self.assertEqual(report["parked"], 2)
            self.assertEqual(report["idle"], 0)
            self.assertEqual(client.calls[0], ("unpark.php", {"userCarId": "over"}))
            self.assertEqual({p["spotId"] for endpoint, p in client.calls if endpoint == "park.php"}, {"occupied", "free"})
            self.assertNotIn(("unpark.php", {"userCarId": "exact"}), client.calls)

    def test_owner_crossing_limit_is_rechecked_before_parking(self):
        for version in ("v2", "v3"):
            core, client = load(version), FakeClient()
            # No collections; first read builds candidates, subsequent reads see new balance.
            client.data["userCars"] = [client.data["userCars"][2]]
            def change(client):
                if client.reads >= 4:
                    client.data["users"]["ok"]["cash"] = 3001
            client.on_read = change
            report = core.ParkingRunner(client, interval=0).run()
            self.assertEqual(client.calls, [])
            self.assertEqual(report["idle"], 1)

    def test_income_cap_server_time_and_cooldown(self):
        for version in ("v2", "v3"):
            core, client = load(version), FakeClient()
            state, definitions = client.state(), client.call("game_data.php")
            car = dict(state["userCars"][1])
            self.assertEqual(core.earnings(car, state, definitions), 2020)
            state["gameSettings"] = {"MAX_EARN_PER_SPOT": "1500"}
            self.assertEqual(core.earnings(car, state, definitions), 1500)
            car["parkedTimestamp"] = 9990000
            self.assertIsNone(core.earnings(car, state, definitions))
            state.pop("serverTime")
            self.assertIsNone(core.earnings(car, state, definitions))

    def test_cancelled_or_unconfirmed_operation_stops(self):
        for version in ("v2", "v3"):
            core, client = load(version), FakeClient()
            event = Event(); event.set()
            with self.assertRaises(core.ParkingError):
                core.ParkingRunner(client, stop=event, interval=0).run()
            self.assertEqual(client.calls, [])
            client.refuse = True
            with self.assertRaises(core.ParkingError):
                core.ParkingRunner(client, interval=0).run()
            self.assertEqual(len(client.calls), 1)


class TransportTests(unittest.TestCase):
    def test_request_contract_no_redirect_no_state_write(self):
        for version in ("v2", "v3"):
            core = load(version)
            session = Mock(); session.headers = {}
            session.cookies = requests.cookies.RequestsCookieJar()
            session.request.return_value = Mock(status_code=200, json=lambda: {"success": True})
            client = core.ParkingClient("Cookie: test_session=secret", session, request_interval=0)
            client.call("park.php", {"userCarId": "c", "spotId": "s"})
            positional, kwargs = session.request.call_args
            self.assertEqual(positional, ("POST", core.BASE_URL + "/api/park.php"))
            self.assertEqual(kwargs["json"], {"userCarId": "c", "spotId": "s"})
            self.assertFalse(kwargs["allow_redirects"])
            self.assertNotIn("Cookie", session.headers)
            main = requests.Request("GET", "https://www.tangpt.top/parking.php").prepare()
            game = requests.Request("GET", core.BASE_URL + "/api/state.php").prepare()
            self.assertEqual(requests.cookies.get_cookie_header(session.cookies, main), "test_session=secret")
            self.assertIsNone(requests.cookies.get_cookie_header(session.cookies, game))
            with self.assertRaises(core.ParkingError):
                client.call("state.php", {"users": {}})

    def test_auth_failure_invalid_success_and_post_timeout_are_not_retried_or_leaked(self):
        for version in ("v2", "v3"):
            core = load(version)
            for status, body in [(401, {}), (403, {}), (429, {}), (302, {}),
                                  (200, {"success": "true", "error": "secret"}), (200, [])]:
                session = Mock(); session.headers = {}
                session.request.return_value = Mock(status_code=status, json=lambda: body)
                client = core.ParkingClient("session=secret", session, request_interval=0)
                with self.assertRaises(core.ParkingError) as caught:
                    client.call("unpark.php", {"userCarId": "c"})
                self.assertNotIn("secret", str(caught.exception))
                self.assertEqual(session.request.call_count, 1)
            session.request.side_effect = requests.Timeout("cookie=session=secret")
            session.request.reset_mock()
            with self.assertRaises(core.ParkingError) as caught:
                client.call("unpark.php", {"userCarId": "c"})
            self.assertNotIn("secret", str(caught.exception))
            self.assertEqual(session.request.call_count, 1)

    def test_versions_are_identical(self):
        for name in ("core.py", "__init__.py"):
            self.assertEqual((ROOT / "plugins.v2/qcwautopark" / name).read_bytes(),
                             (ROOT / "plugins.v3/qcwautopark" / name).read_bytes())


if __name__ == "__main__":
    unittest.main()
