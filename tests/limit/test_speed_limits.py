"""Offline tests for speed units at the downloader API boundary."""

import importlib.util
from copy import deepcopy
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, call, patch


ROOT = Path(__file__).resolve().parents[2]


def load_plugin(version="v2", legacy=False):
    modules = {}
    names = [
        "pytz", "apscheduler", "apscheduler.schedulers",
        "apscheduler.schedulers.background", "apscheduler.triggers",
        "apscheduler.triggers.cron", "app", "app.schemas",
    ]
    if version == "v2" or legacy:
        names += ["app.core", "app.core.config", "app.helper", "app.helper.downloader",
                  "app.log", "app.plugins"]
        config_path, helper_path = "app.core.config", "app.helper.downloader"
        logger_path, plugin_path, schema_path = "app.log", "app.plugins", "app.schemas"
    else:
        names += ["app.sdk", "app.sdk.config", "app.sdk.services", "app.sdk.logging",
                  "app.sdk.plugin", "app.schemas.system"]
        config_path, helper_path = "app.sdk.config", "app.sdk.services"
        logger_path, plugin_path, schema_path = "app.sdk.logging", "app.sdk.plugin", "app.schemas.system"
    for name in names:
        modules[name] = types.ModuleType(name)
    modules["apscheduler.schedulers.background"].BackgroundScheduler = Mock()
    modules["apscheduler.triggers.cron"].CronTrigger = Mock()
    modules[config_path].settings = types.SimpleNamespace(TZ="UTC")
    modules[helper_path].DownloaderHelper = Mock()
    modules[logger_path].logger = Mock()
    modules[plugin_path]._PluginBase = object
    modules[schema_path].ServiceInfo = object
    spec = importlib.util.spec_from_file_location(
        "limit_under_test", ROOT / f"plugins.{version}/limit/__init__.py"
    )
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module


class SpeedLimitTests(unittest.TestCase):
    VERSION = "v2"

    def setUp(self):
        self.module = load_plugin(self.VERSION)
        self.plugin = self.module.Limit()
        self.plugin._event.clear()
        self.data = {}
        self.attach_data(self.plugin)

    def attach_data(self, plugin):
        plugin.get_data = lambda key: deepcopy(self.data.get(key))
        plugin.save_data = lambda key, value: self.data.__setitem__(key, deepcopy(value))

    def service(self, kind):
        return types.SimpleNamespace(name="test", type=kind, instance=Mock())

    def configure_all_torrents(self, service, torrents, cover=True, speed=3000):
        service.instance.get_torrents.return_value = (torrents, False)
        service.instance.is_inactive.return_value = False
        self.plugin.downloader_helper = Mock()
        self.plugin.downloader_helper.get_services.return_value = {"test": service}
        self.plugin._downloaders = ["test"]
        self.plugin._global = True
        self.plugin._global_speed = 123
        self.plugin._limit_mode = "所有种子"
        self.plugin._torrent_speed = speed
        self.plugin._cover = cover
        self.plugin._tag_map = ""

    def test_qb_tag_limits_use_bytes_per_second_and_keep_zero_unlimited(self):
        for speed in (0, 1, 30000, 300000):
            with self.subTest(speed=speed):
                service = self.service("qbittorrent")
                self.plugin._set_torrent_speed(service, "test-hash", speed)
                service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
                    torrent_hashes="test-hash", limit=speed * 1024
                )
                self.module.logger.info.assert_called_with(
                    f"[Limit]下载器: test 种子id: test-hash  上传限速为 {speed} KiB/s"
                )

    def test_transmission_tag_limits_convert_to_integer_kilobytes(self):
        for speed, expected in ((0, 0), (1, 1), (50, 51), (30000, 30720), (300000, 307200)):
            with self.subTest(speed=speed):
                service = self.service("transmission")
                self.plugin._set_torrent_speed(service, "test-hash", speed)
                service.instance.change_torrent.assert_called_once_with(
                    hash_string="test-hash", upload_limit=expected
                )

    def test_global_limits_do_not_double_convert_qb(self):
        for kind, speed, expected in (
            ("qbittorrent", 300000, 300000), ("qbittorrent", 0, 0),
            ("transmission", 300000, 307200), ("transmission", 0, 0),
        ):
            with self.subTest(kind=kind, speed=speed):
                service = self.service(kind)
                self.plugin.downloader_helper = Mock()
                self.plugin.downloader_helper.get_services.return_value = {"test": service}
                service.instance.is_inactive.return_value = False
                self.plugin._downloaders = ["test"]
                self.plugin._global = True
                self.plugin._global_speed = speed
                self.plugin._tag_map = ""
                self.plugin._complete_limit()
                service.instance.set_speed_limit.assert_called_once_with(
                    download_limit=0, upload_limit=expected
                )
                service.instance.qbc.torrents_set_upload_limit.assert_not_called()

    def test_saved_tag_rule_reaches_qb_api_with_correct_limit(self):
        service = self.service("qbittorrent")
        torrent = {"hash": "test-hash", "tags": "PT"}
        service.instance.get_torrents.return_value = ([torrent], False)
        service.instance.is_inactive.return_value = False
        self.plugin.downloader_helper = Mock()
        self.plugin.downloader_helper.get_services.return_value = {"test": service}
        self.plugin._downloaders = ["test"]
        self.plugin._global = False
        self.plugin._cover = True
        self.plugin._tag_map = "PT:300000"
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="test-hash", limit=307200000
        )
        service.instance.set_speed_limit.assert_not_called()

    def test_all_torrents_sets_individual_limits_even_without_tags(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [
            {"hash": "first", "tags": "", "up_limit": 0},
            {"hash": "second", "tags": "PT", "up_limit": 8000},
            {"hash": "third", "tags": "Other", "up_limit": 0},
        ])
        self.plugin._tag_map = "invalid rule that should be ignored"
        self.plugin._complete_limit()
        self.assertEqual(service.instance.qbc.torrents_set_upload_limit.call_args_list, [
            call(torrent_hashes="first", limit=3072000),
            call(torrent_hashes="second", limit=3072000),
            call(torrent_hashes="third", limit=3072000),
        ])
        service.instance.set_speed_limit.assert_not_called()

    def test_all_torrents_respects_existing_qb_limits_unless_cover_enabled(self):
        for cover in (False, True):
            with self.subTest(cover=cover):
                service = self.service("qbittorrent")
                self.configure_all_torrents(service, [
                    {"hash": "limited", "up_limit": 4096},
                    {"hash": "unlimited", "up_limit": 0},
                ], cover=cover)
                self.plugin._complete_limit()
                hashes = [c.kwargs["torrent_hashes"]
                          for c in service.instance.qbc.torrents_set_upload_limit.call_args_list]
                self.assertEqual(hashes, ["limited", "unlimited"] if cover else ["unlimited"])
                service.instance.set_speed_limit.assert_not_called()

    def test_zero_clears_qb_limits_when_cover_enabled(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [
            {"hash": "limited", "up_limit": 4096},
        ], speed=0)
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="limited", limit=0
        )
        service.instance.set_speed_limit.assert_not_called()

    def test_all_transmission_torrents_convert_units_and_respect_cover(self):
        torrents = [types.SimpleNamespace(hashString="limited"),
                    types.SimpleNamespace(hashString="unlimited")]
        for cover, speed, expected in ((False, 3000, 3072), (True, 3000, 3072), (True, 0, 0)):
            with self.subTest(cover=cover, speed=speed):
                service = self.service("transmission")
                self.configure_all_torrents(service, torrents, cover=cover, speed=speed)
                service.instance.trc.get_torrent.side_effect = (
                    lambda torrent_id: types.SimpleNamespace(upload_limited=torrent_id == "limited")
                )
                self.plugin._complete_limit()
                hashes = ["limited", "unlimited"] if cover else ["unlimited"]
                self.assertEqual(service.instance.change_torrent.call_args_list, [
                    call(hash_string=h, upload_limit=expected) for h in hashes
                ])
                service.instance.set_speed_limit.assert_not_called()

    def test_failed_torrent_does_not_stop_other_torrents(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "bad"}, {"hash": "good"}])
        service.instance.qbc.torrents_set_upload_limit.side_effect = [RuntimeError("API failed"), None]
        self.plugin._complete_limit()
        self.assertEqual(service.instance.qbc.torrents_set_upload_limit.call_count, 2)
        self.module.logger.error.assert_called_once()

    def test_all_torrents_skips_empty_hash_and_stops_when_requested(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": ""}, {"hash": "good"}])
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="good", limit=3072000
        )
        service.instance.qbc.torrents_set_upload_limit.reset_mock()
        self.plugin._event.set()
        try:
            self.plugin._complete_limit()
            service.instance.qbc.torrents_set_upload_limit.assert_not_called()
        finally:
            self.plugin._event.clear()

    def test_empty_or_failed_torrent_listing_does_not_change_limits(self):
        for torrents, error in (([], False), ([{"hash": "test"}], True)):
            with self.subTest(error=error):
                service = self.service("qbittorrent")
                self.configure_all_torrents(service, torrents)
                service.instance.get_torrents.return_value = (torrents, error)
                self.plugin._complete_limit()
                service.instance.qbc.torrents_set_upload_limit.assert_not_called()
                service.instance.set_speed_limit.assert_not_called()

    def test_configuration_loads_new_fields_and_keeps_old_configs_in_tag_mode(self):
        self.plugin.init_plugin({"limit_mode": "所有种子", "torrent_speed": "300000"})
        self.assertEqual(self.plugin._limit_mode, "所有种子")
        self.assertEqual(self.plugin._torrent_speed, 300000)
        self.plugin.init_plugin({"tag_map": "PT:3000", "downloaders": ["test"]})
        self.assertEqual(self.plugin._limit_mode, "标签")
        self.assertEqual(self.plugin._torrent_speed, 1000)
        self.assertEqual(self.plugin._tag_map, "PT:3000")
        self.plugin.init_plugin({"limit_mode": "所有种子", "torrent_speed": "0"})
        self.assertEqual(self.plugin._torrent_speed, 0)

    def test_new_only_baselines_existing_and_limits_new_torrents_once(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "old"}])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_not_called()
        self.assertEqual(self.data["seen_torrents"], {"qbittorrent:test": ["old"]})
        service.instance.get_torrents.return_value = ([{"hash": "old"}, {"hash": "new"}], False)
        self.plugin._complete_limit()
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="new", limit=3072000
        )
        service.instance.set_speed_limit.assert_not_called()

    def test_new_only_persists_across_restart_and_speed_changes(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "old"}])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        self.plugin = self.module.Limit()
        self.attach_data(self.plugin)
        self.configure_all_torrents(service, [{"hash": "old"}, {"hash": "new"}], speed=5000)
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="new", limit=5120000
        )

    def test_disabling_new_only_reapplies_all_and_updates_baseline(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "old"}])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        self.plugin._new_only = False
        self.plugin._complete_limit()
        self.plugin._complete_limit()
        self.assertEqual(service.instance.qbc.torrents_set_upload_limit.call_count, 2)
        self.plugin._new_only = True
        self.plugin._complete_limit()
        self.assertEqual(service.instance.qbc.torrents_set_upload_limit.call_count, 2)

    def test_new_only_retries_failure_without_repeating_success(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.get_torrents.return_value = ([{"hash": "bad"}, {"hash": "good"}], False)
        service.instance.qbc.torrents_set_upload_limit.side_effect = [RuntimeError("API failed"), None]
        self.plugin._complete_limit()
        self.assertEqual(self.data["seen_torrents"]["qbittorrent:test"], ["good"])
        service.instance.qbc.torrents_set_upload_limit.side_effect = None
        service.instance.qbc.torrents_set_upload_limit.reset_mock()
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="bad", limit=3072000
        )

    def test_transmission_false_result_is_retried(self):
        service = self.service("transmission")
        self.configure_all_torrents(service, [])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.get_torrents.return_value = ([types.SimpleNamespace(hashString="new")], False)
        service.instance.change_torrent.return_value = False
        self.plugin._complete_limit()
        self.assertEqual(self.data["seen_torrents"]["transmission:test"], [])
        service.instance.change_torrent.return_value = True
        self.plugin._complete_limit()
        self.assertEqual(service.instance.change_torrent.call_count, 2)
        self.assertEqual(self.data["seen_torrents"]["transmission:test"], ["new"])

    def test_failed_scan_keeps_baseline_and_empty_scan_prunes_deleted(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "old"}])
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.get_torrents.return_value = ([], True)
        self.plugin._complete_limit()
        self.assertEqual(self.data["seen_torrents"]["qbittorrent:test"], ["old"])
        service.instance.get_torrents.side_effect = RuntimeError("connection failed")
        self.plugin._complete_limit()
        self.assertEqual(self.data["seen_torrents"]["qbittorrent:test"], ["old"])
        service.instance.get_torrents.side_effect = None
        service.instance.get_torrents.return_value = ([], False)
        self.plugin._complete_limit()
        self.assertEqual(self.data["seen_torrents"]["qbittorrent:test"], [])
        service.instance.get_torrents.return_value = ([{"hash": "old"}], False)
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="old", limit=3072000
        )

    def test_seen_torrents_are_isolated_by_downloader(self):
        first = self.service("qbittorrent")
        second = self.service("qbittorrent")
        second.name = "other"
        self.configure_all_torrents(first, [{"hash": "same-hash"}])
        second.instance.is_inactive.return_value = False
        second.instance.get_torrents.return_value = ([], False)
        self.plugin.downloader_helper.get_services.return_value = {"test": first, "other": second}
        self.plugin._new_only = True
        self.plugin._complete_limit()
        second.instance.get_torrents.return_value = ([{"hash": "same-hash"}], False)
        self.plugin._complete_limit()
        first.instance.qbc.torrents_set_upload_limit.assert_not_called()
        second.instance.qbc.torrents_set_upload_limit.assert_called_once_with(
            torrent_hashes="same-hash", limit=3072000
        )

    def test_new_only_still_respects_cover_and_scheduler_modes(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [], cover=False)
        self.plugin._new_only = True
        self.plugin._complete_limit()
        service.instance.get_torrents.return_value = ([{"hash": "new", "up_limit": 1234}], False)
        self.plugin._complete_limit()
        service.instance.qbc.torrents_set_upload_limit.assert_not_called()
        self.assertEqual(self.data["seen_torrents"]["qbittorrent:test"], ["new"])
        self.plugin._enabled = True
        for interval in ("计划任务", "固定间隔"):
            self.plugin._interval = interval
            self.assertEqual(self.plugin.get_service()[0]["func"], self.plugin._complete_limit)
        self.plugin.init_plugin({"limit_mode": "所有种子", "new_only": True})
        self.assertTrue(self.plugin._new_only)
        self.plugin.init_plugin({"limit_mode": "所有种子"})
        self.assertFalse(self.plugin._new_only)

    def test_overlapping_run_is_skipped(self):
        service = self.service("qbittorrent")
        self.configure_all_torrents(service, [{"hash": "test"}])
        self.plugin._run_lock.acquire()
        try:
            self.plugin._complete_limit()
            service.instance.get_torrents.assert_not_called()
        finally:
            self.plugin._run_lock.release()

    def test_form_labels_use_kib_and_default_rules_are_empty(self):
        self.plugin.downloader_helper = Mock()
        self.plugin.downloader_helper.get_configs.return_value = {}
        form, defaults = self.plugin.get_form()
        labels = {}

        def collect(nodes):
            for node in nodes:
                props = node.get("props", {})
                if props.get("model") in ("global_speed", "tag_map", "torrent_speed"):
                    labels[props["model"]] = props["label"]
                collect(node.get("content", []))

        collect(form)
        self.assertEqual(set(labels), {"global_speed", "tag_map", "torrent_speed"})
        self.assertTrue(all("KiB/s" in label for label in labels.values()))
        self.assertEqual(defaults["tag_map"], "")
        self.assertEqual(defaults["limit_mode"], "标签")
        self.assertEqual(defaults["torrent_speed"], "1000")
        self.assertFalse(defaults["new_only"])

    def test_manifest_version_matches_plugin(self):
        entry = json.loads((ROOT / f"package.{self.VERSION}.json").read_text())["Limit"]
        self.assertEqual(entry["version"], self.plugin.plugin_version)
        self.assertEqual(entry["author"], self.plugin.plugin_author)
        self.assertEqual(self.plugin.plugin_author, "tmzg0000")


class V3SpeedLimitTests(SpeedLimitTests):
    VERSION = "v3"

    def test_v3_can_fall_back_to_early_v3_import_paths(self):
        module = load_plugin("v3", legacy=True)
        self.assertEqual(module.Limit.plugin_version, "1.1.7")
        self.assertEqual(module.Limit.plugin_author, "tmzg0000")

    def test_v3_ignores_unsupported_downloader_types(self):
        service = self.service("rtorrent")
        self.configure_all_torrents(service, [{"hash": "test"}])
        self.plugin._complete_limit()
        service.instance.get_torrents.assert_not_called()
        service.instance.change_torrent.assert_not_called()
        service.instance.set_speed_limit.assert_not_called()

    def test_v3_form_only_lists_supported_downloaders(self):
        self.plugin.downloader_helper = Mock()
        self.plugin.downloader_helper.get_configs.return_value = {
            "qb": types.SimpleNamespace(name="qb", type="qbittorrent"),
            "tr": types.SimpleNamespace(name="tr", type="transmission"),
            "rt": types.SimpleNamespace(name="rt", type="rtorrent"),
        }
        form, defaults = self.plugin.get_form()
        def props_for(nodes, model):
            for node in nodes:
                if node.get("props", {}).get("model") == model:
                    return node["props"]
                match = props_for(node.get("content", []), model)
                if match:
                    return match
            return None
        self.assertEqual(props_for(form, "downloaders")["items"], [
            {"title": "qb", "value": "qb"}, {"title": "tr", "value": "tr"},
        ])
        entry = json.loads((ROOT / "package.v3.json").read_text())["Limit"]
        self.assertEqual(entry["system_version"], ">=3.0.0")


if __name__ == "__main__":
    unittest.main()
