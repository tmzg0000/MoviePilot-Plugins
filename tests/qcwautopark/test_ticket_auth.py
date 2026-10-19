import copy
import unittest
from unittest.mock import Mock, patch

import requests

from test_core import FakeClient, load


class TicketTests(unittest.TestCase):
    def client(self):
        client = FakeClient()
        client.data["userCars"] = [
            {"id": "visitor", "userId": "other", "status": "parked", "carId": 1, "parkedTimestamp": 7000000}]
        client.data["parkingSpots"] = [
            {"id": "mine", "ownerId": "me", "spotType": "private", "carInSpot": "visitor", "parkedTimestamp": 7000000}]
        return client

    def test_ticket_inclusive_boundary_and_minimum_time(self):
        for version in ("v2", "v3"):
            core = load(version)
            for income, expected in ((980, 0), (1000, 1), (1020, 1)):
                client = self.client()
                stamp = 10000000 - (income // 20) * 60000
                client.data["parkingSpots"][0]["parkedTimestamp"] = stamp
                report = core.ParkingRunner(client, interval=0).run()
                self.assertEqual(report["ticketed"], expected)
                self.assertEqual(report["earned"], 700 if expected else 0)
            client = self.client()
            client.data["parkingSpots"][0]["parkedTimestamp"] = 10000000 - 4 * 60000
            self.assertEqual(core.ParkingRunner(client, ticket_threshold=0, interval=0).run()["ticketed"], 0)

    def test_excludes_charity_foreign_lot_and_own_car_and_supports_switch_and_custom_threshold(self):
        for version in ("v2", "v3"):
            core = load(version)
            for change in ("charity", "foreign", "owncar", "disabled", "threshold"):
                client = self.client()
                options = {"threshold": 1000000}
                if change == "charity":
                    client.data["parkingSpots"][0]["spotType"] = "charity"
                if change == "foreign":
                    client.data["parkingSpots"][0]["ownerId"] = "other"
                if change == "owncar":
                    client.data["userCars"][0]["userId"] = "me"
                if change == "disabled":
                    options["auto_ticket"] = False
                if change == "threshold":
                    options["ticket_threshold"] = 1001
                core.ParkingRunner(client, interval=0, **options).run()
                self.assertFalse(any(e == "ticket.php" for e, _ in client.calls), change)

    def test_ticket_refusal_and_concurrent_car_change(self):
        for version in ("v2", "v3"):
            core, client = load(version), self.client()
            client.refuse = True
            with self.assertRaises(core.ParkingError):
                core.ParkingRunner(client, interval=0).run()
            self.assertEqual(client.calls, [("ticket.php", {"spotId": "mine"})])
            client = self.client()
            client.on_read = lambda c: c.data["parkingSpots"][0].update(carInSpot=None) if c.reads > 1 else None
            self.assertEqual(core.ParkingRunner(client, interval=0).run()["ticketed"], 0)


class AuthTests(unittest.TestCase):
    def session(self):
        session = Mock()
        session.headers = {}
        session.cookies = requests.cookies.RequestsCookieJar()
        return session

    def test_observed_parking_entry_redirect_iframe_and_authenticated_state(self):
        for version in ("v2", "v3"):
            core, session = load(version), self.session()
            state = FakeClient().state()
            state["success"] = True
            session.request.side_effect = [
                Mock(status_code=200, text='<iframe src="/tp-open-connect/sso/generate?app_id=example"></iframe>'),
                Mock(status_code=302, headers={"Location": "https://qcw.tangpt.top/api/callback.php?ticket=hidden"}),
                Mock(status_code=302, headers={"Location": "/index.html?userId=me"}),
                Mock(status_code=200, text="<html>game</html>"),
                Mock(status_code=200, json=lambda: state)]
            client = core.ParkingClient("session=hidden", session, request_interval=0)
            client.authenticate()
            urls = [c.args[1] for c in session.request.call_args_list]
            self.assertEqual(urls[0], "https://www.tangpt.top/parking.php")
            self.assertEqual(urls[-1], core.BASE_URL + "/api/state.php")
            self.assertEqual(len(urls), 5)
            for call in session.request.call_args_list:
                self.assertFalse(call.kwargs["allow_redirects"])
                self.assertNotIn("Cookie", call.kwargs.get("headers", {}))

    def test_expired_cookie_and_external_redirect_stop_without_exposing_token(self):
        for version in ("v2", "v3"):
            core = load(version)
            for target in ("/login.php", "https://evil.example/?ticket=hidden", "http://qcw.tangpt.top/callback?token=hidden"):
                session = self.session()
                session.request.return_value = Mock(status_code=302, headers={"Location": target})
                client = core.ParkingClient("session=hidden", session, request_interval=0)
                with self.assertRaises(core.ParkingError) as caught:
                    client.authenticate()
                self.assertNotIn("hidden", str(caught.exception))
                self.assertEqual(session.request.call_count, 1)

    def test_meta_and_literal_script_navigation(self):
        for version in ("v2", "v3"):
            core = load(version)
            url = "https://qcw.tangpt.top/api/callback.php?ticket=safe"
            for html in (f'<meta http-equiv="refresh" content="0;url={url}">',
                         f'<script>window.location.href = "{url}";</script>',
                         f'<script>location.replace("{url}");</script>'):
                self.assertEqual(core.login_navigation(html, "https://www.tangpt.top/parking.php"), url)

    def test_every_request_waits_ten_seconds_after_previous_response_and_stop_cancels(self):
        for version in ("v2", "v3"):
            core, session = load(version), self.session()
            event = Mock(); event.wait.return_value = False; event.is_set.return_value = False
            session.request.return_value = Mock(status_code=200, json=lambda: {"success": True})
            client = core.ParkingClient("session=hidden", session, stop=event)
            with patch.object(core.time, "monotonic", side_effect=[100, 100, 110]):
                client.call("game_data.php")
                client.call("park.php", {"userCarId": "c", "spotId": "s"})
            event.wait.assert_called_once_with(10)
            event.wait.return_value = True
            with self.assertRaises(core.ParkingError):
                client.call("state.php")
            self.assertEqual(session.request.call_count, 2)


if __name__ == "__main__":
    unittest.main()
