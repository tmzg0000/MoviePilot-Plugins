"""V3 SDK-only integration contracts; legacy MoviePilot imports are unavailable."""
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from test_email_session import Page

ROOT = Path(__file__).resolve().parents[2]


def load_v3():
    names = ('app', 'app.sdk', 'app.sdk.plugin', 'app.sdk.logging', 'app.sdk.config',
             'app.sdk.events', 'app.sdk.scheduler', 'app.sdk.browser', 'app.sdk._legacy',
             'app.sdk._legacy.site', 'app.schemas', 'app.schemas.types', 'apscheduler',
             'apscheduler.schedulers', 'apscheduler.schedulers.background',
             'apscheduler.triggers', 'apscheduler.triggers.cron')
    stubs = {name: types.ModuleType(name) for name in names}
    stubs['app.sdk.plugin']._PluginBase = object
    stubs['app.sdk.logging'].logger = Mock()
    stubs['app.sdk.config'].settings = types.SimpleNamespace(TZ='Asia/Shanghai')
    stubs['app.sdk.events'].Event = object
    stubs['app.sdk.events'].eventmanager = types.SimpleNamespace(register=lambda _: lambda f: f)
    stubs['app.schemas.types'].EventType = types.SimpleNamespace(PluginAction='plugin.action')
    stubs['app.schemas.types'].MessageType = types.SimpleNamespace(Plugin='plugin')
    stubs['app.sdk.scheduler'].add_plugin_once_job = Mock(return_value=True)
    stubs['app.sdk.scheduler'].remove_plugin_once_job = Mock()
    stubs['app.sdk.scheduler'].update_plugin_job = Mock()
    stubs['app.sdk.browser'].launch_browser_context = Mock()
    stubs['app.sdk._legacy.site'].SiteOper = Mock()
    stubs['app.sdk._legacy.site'].SiteOper.return_value.list_order_by_pri.return_value = []
    stubs['apscheduler.schedulers.background'].BackgroundScheduler = Mock()
    stubs['apscheduler.triggers.cron'].CronTrigger = Mock()
    directory = ROOT / 'plugins.v3/mtaliver'
    spec = importlib.util.spec_from_file_location('mtaliver_v3_contract', directory / '__init__.py',
                                                submodule_search_locations=[str(directory)])
    module = importlib.util.module_from_spec(spec)
    stubs[spec.name] = module
    with patch.dict(sys.modules, stubs):
        spec.loader.exec_module(module)
    return module, stubs


class V3Tests(unittest.TestCase):
    def setUp(self):
        self.module, self.stubs = load_v3()
        self.core = self.module.mteam
        self.plugin = self.module.MtAliver()
        self.data = {}
        self.plugin.get_data = self.data.get
        self.plugin.save_data = self.data.__setitem__
        self.plugin.update_config = Mock()
        self.plugin.post_message = Mock()
        self.plugin.init_plugin({'username': 'user', 'notify': False})

    def run_browser(self, scenario, **kwargs):
        page = Page(scenario)
        page.set_default_timeout = Mock()
        context = page.context
        context.new_page.return_value = page
        launch = self.stubs['app.sdk.browser'].launch_browser_context
        launch.return_value = context
        with patch.dict(sys.modules, self.stubs):
            result = self.core.keepalive_login('user', '', **kwargs)
        return result, page, launch

    def test_imports_events_and_message_type_without_legacy_paths(self):
        self.assertIs(self.module.NotificationType, self.stubs['app.schemas.types'].MessageType)
        self.assertEqual(self.plugin.get_command()[0]['event'], 'plugin.action')
        self.assertEqual(self.plugin.plugin_version, '1.5.1')

    def test_sdk_browser_reuses_session_without_password_and_closes_context(self):
        state = {'identity': self.core.session_identity('user', self.core.DEFAULT_SITE), 'cookies': []}
        result, page, launch = self.run_browser('reuse', state=state)
        self.assertTrue(result['ok'])
        launch.assert_called_once_with(headless=True)
        page.context.close.assert_called_once()
        page.set_default_timeout.assert_called_once_with(180000)

    def test_sdk_browser_email_login_and_send_code(self):
        for scenario, params in [('code', {'email_code': '123456'}), ('send', {'request_email': True})]:
            page = Page(scenario)
            page.set_default_timeout = Mock()
            context = page.context
            context.new_page.return_value = page
            self.stubs['app.sdk.browser'].launch_browser_context.return_value = context
            with patch.dict(sys.modules, self.stubs):
                result = self.core.keepalive_login('user', 'temporary', email='user@example.org', **params)
            self.assertTrue(result.get('ok') if scenario == 'code' else result.get('email_sent'))
            context.close.assert_called_once()
            self.assertNotIn('temporary', json.dumps(result))

    def test_sdk_browser_failure_also_closes_context(self):
        state = {'identity': self.core.session_identity('user', self.core.DEFAULT_SITE), 'cookies': []}
        page = Mock()
        page.goto.side_effect = RuntimeError('secret')
        context = Mock()
        context.new_page.return_value = page
        self.stubs['app.sdk.browser'].launch_browser_context.return_value = context
        with patch.dict(sys.modules, self.stubs):
            result = self.core.keepalive_login('user', '', state=state)
        self.assertFalse(result['ok'])
        self.assertNotIn('secret', result['message'])
        context.close.assert_called_once()

    def test_once_job_uses_sdk_and_unload_cancels_it(self):
        self.plugin.init_plugin({'run_once': True})
        scheduler = self.stubs['app.sdk.scheduler']
        scheduler.add_plugin_once_job.assert_called_once()
        self.module.BackgroundScheduler.assert_not_called()
        self.plugin.stop_service()
        scheduler.remove_plugin_once_job.assert_called_with('MtAliver', 'mtaliver_once')
        self.assertEqual(self.data['execution']['status'], 'queued')

    def test_host_refusing_once_job_reports_failure(self):
        self.stubs['app.sdk.scheduler'].add_plugin_once_job.return_value = False
        self.plugin.init_plugin({'run_once': True})
        self.assertEqual(self.data['execution']['status'], 'failed')

    def test_site_key_uses_v3_facade(self):
        site = types.SimpleNamespace(domain='https://kp.m-team.cc', apikey='site-key')
        self.stubs['app.sdk._legacy.site'].SiteOper.return_value.list_order_by_pri.return_value = [site]
        with patch.dict(sys.modules, self.stubs):
            self.assertEqual(self.plugin.site_apikey(), 'site-key')

    def test_button_uses_sdk_scheduler_and_does_not_save_password(self):
        with patch.dict(sys.modules, self.stubs), patch.object(self.module, 'keepalive_login', return_value={'ok': True, 'state': {'local': {'auth': 'token'}}}):
            result = self.plugin.api_login({'username': 'user', 'password': 'transient-secret',
                                           'email': 'user@example.org', 'email_code': '123456',
                                           'enabled': True, 'notify': False})
        self.assertTrue(result['success'])
        self.stubs['app.sdk.scheduler'].update_plugin_job.assert_called_once_with('MtAliver')
        self.assertEqual(self.plugin._password, '')
        self.assertNotIn('password', self.plugin.get_form()[1])
        self.assertNotIn('transient-secret', json.dumps(self.data))
        for call in self.plugin.update_config.call_args_list:
            self.assertNotIn('password', call.args[0])

    def test_market_versions_and_shared_sources_match(self):
        for version, requirement in (('v2', '>=2.0.0,<3.0.0'), ('v3', '>=3.0.0')):
            manifest = json.loads((ROOT / ('package.' + version + '.json')).read_text())['MtAliver']
            self.assertEqual(manifest['version'], '1.5.1')
            self.assertEqual(manifest['system_version'], requirement)
        for name in ('__init__.py', 'mteam.py', 'ui.py'):
            self.assertEqual((ROOT / 'plugins.v2/mtaliver' / name).read_bytes(),
                             (ROOT / 'plugins.v3/mtaliver' / name).read_bytes())


if __name__ == '__main__':
    unittest.main()
