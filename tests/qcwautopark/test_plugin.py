"""Plugin lifecycle checks without a running MoviePilot service."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]


def load_plugin(version):
    names = ("app", "app.plugins", "app.log", "app.sdk", "app.sdk.logging", "apscheduler",
             "apscheduler.triggers", "apscheduler.triggers.interval", "app.db", "app.db.oper", "app.db.oper.site", "app.db.site_oper")
    modules = {name: types.ModuleType(name) for name in names}
    modules["app.plugins"]._PluginBase = object
    modules["app.db.oper.site"].SiteOper = modules["app.db.site_oper"].SiteOper = Mock()
    modules["app.db.oper.site"].SiteOper.return_value.list_order_by_pri.return_value = [
        types.SimpleNamespace(id=1, name="躺平", url="https://www.tangpt.top", cookie="session=hidden", ua="site-ua", is_active=True)]
    modules["app.log"].logger = modules["app.sdk.logging"].logger = Mock()
    modules["apscheduler.triggers.interval"].IntervalTrigger = Mock()
    name = "qcw_plugin_test_" + version
    spec = importlib.util.spec_from_file_location(name, ROOT / ("plugins." + version) / "qcwautopark/__init__.py",
                                                submodule_search_locations=[str(ROOT / ("plugins." + version) / "qcwautopark")])
    module = importlib.util.module_from_spec(spec)
    modules[name] = module
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class PluginTests(unittest.TestCase):
    def test_default_service_and_custom_inclusive_limits(self):
        for version in ("v2", "v3"):
            module = load_plugin(version)
            plugin = module.QcwAutoPark()
            plugin.init_plugin({"enabled": True})
            services = plugin.get_service()
            self.assertEqual(len(services), 1)
            module.IntervalTrigger.assert_called_once_with(minutes=5)
            self.assertEqual(plugin._max_level, 3)
            self.assertEqual(plugin._max_cash, 3000)
            self.assertEqual(plugin._ticket_threshold, 1000)
            self.assertEqual(plugin._request_interval, 10)
            plugin.init_plugin({"enabled": True, "interval_minutes": 7, "max_level": 0, "max_cash": 0, "threshold": 0})
            self.assertEqual(plugin._max_level, 0)
            self.assertEqual(plugin._max_cash, 0)
            self.assertEqual(plugin._threshold, 0)
            plugin.get_service()
            module.IntervalTrigger.assert_called_with(minutes=7)
            plugin.init_plugin({"enabled": True, "interval_minutes": "bad"})
            self.assertEqual(plugin.get_service(), [])

    def test_run_once_resets_and_config_reload_cancels_old_task(self):
        for version in ("v2", "v3"):
            module = load_plugin(version)
            plugin = module.QcwAutoPark()
            plugin.update_config = Mock()
            plugin.run_task = Mock()
            plugin.init_plugin({"run_once": True, "cookie": "session=hidden"})
            plugin.run_task.assert_called_once()
            self.assertFalse(plugin.update_config.call_args.args[0]["run_once"])
            previous = plugin._stop
            plugin.init_plugin({})
            self.assertTrue(previous.is_set())
            self.assertFalse(plugin._stop.is_set())
            plugin.stop_service()
            self.assertTrue(plugin._stop.is_set())

    def test_nonoverlap_failure_redaction_and_history(self):
        for version in ("v2", "v3"):
            module = load_plugin(version)
            plugin = module.QcwAutoPark()
            plugin.init_plugin({"cookie": "session=hidden"})
            data = {}
            plugin.get_data = lambda key: data.get(key)
            plugin.save_data = lambda key, value: data.__setitem__(key, value)
            with patch.object(module, "ParkingClient") as client:
                plugin._lock.acquire()
                try:
                    plugin.run_task()
                    client.assert_not_called()
                finally:
                    plugin._lock.release()
                client.side_effect = RuntimeError("hidden Cookie")
                for _ in range(22):
                    plugin.run_task()
            self.assertEqual(len(data["history"]), 20)
            self.assertNotIn("hidden", json.dumps(data))
            self.assertEqual(data["history"][0]["idle"], "未知")
            self.assertFalse(plugin._lock.locked())

    def test_reads_latest_mp_cookie_authenticates_and_passes_ticket_options(self):
        for version in ("v2", "v3"):
            module = load_plugin(version)
            plugin = module.QcwAutoPark()
            plugin.init_plugin({"site_id": 1, "ticket_threshold": 1234, "request_interval": 12})
            plugin.get_data, plugin.save_data = Mock(return_value=[]), Mock()
            with patch.object(module, "ParkingClient") as client, patch.object(module, "ParkingRunner") as runner:
                runner.return_value.run.return_value = {"idle": 0}
                plugin.run_task()
                self.assertEqual(client.call_args.args, ("session=hidden",))
                self.assertEqual(client.call_args.kwargs["user_agent"], "site-ua")
                self.assertEqual(client.call_args.kwargs["request_interval"], 12)
                client.return_value.authenticate.assert_called_once()
                self.assertEqual(runner.call_args.kwargs["ticket_threshold"], 1234)
                self.assertTrue(runner.call_args.kwargs["auto_ticket"])
                site = types.SimpleNamespace(id=1, name="躺平", url="https://www.tangpt.top", cookie="session=new", is_active=True)
                module.SiteOper.return_value.list_order_by_pri.return_value = [site]
                plugin.run_task()
                self.assertEqual(client.call_args.args, ("session=new",))
                self.assertNotIn("cookie", plugin._config())

    def test_marketplace_entry_matches_plugin_and_system_version(self):
        for version in ("v2", "v3"):
            module = load_plugin(version)
            entry = json.loads((ROOT / ("package." + version + ".json")).read_text())["QcwAutoPark"]
            self.assertEqual(entry["version"], module.QcwAutoPark.plugin_version)
            self.assertIn("2.0.0" if version == "v2" else "3.0.0", entry["system_version"])


if __name__ == "__main__":
    unittest.main()
