import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'plugins.v2/mtaliver'


def load_plugin():
    names = ('app', 'app.plugins', 'app.log', 'app.core', 'app.core.config',
             'app.core.event', 'app.schemas', 'app.schemas.types', 'app.helper',
             'app.helper.browser', 'apscheduler', 'apscheduler.schedulers',
             'apscheduler.schedulers.background', 'apscheduler.triggers',
             'apscheduler.triggers.cron')
    modules = {name: types.ModuleType(name) for name in names}
    modules['app.plugins']._PluginBase = object
    modules['app.log'].logger = Mock()
    modules['app.core.config'].settings = types.SimpleNamespace(TZ='Asia/Shanghai')
    modules['app.core.event'].Event = object
    modules['app.core.event'].eventmanager = types.SimpleNamespace(register=lambda _: lambda f: f)
    modules['app.schemas.types'].EventType = types.SimpleNamespace(PluginAction='plugin')
    modules['app.schemas.types'].NotificationType = types.SimpleNamespace(Plugin='plugin')
    modules['apscheduler.schedulers.background'].BackgroundScheduler = Mock()
    modules['apscheduler.triggers.cron'].CronTrigger = Mock()
    spec = importlib.util.spec_from_file_location('mteam_email_tests', DIR / '__init__.py',
                                                submodule_search_locations=[str(DIR)])
    module = importlib.util.module_from_spec(spec)
    modules[spec.name] = module
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(module)
    return module, modules


M, MODULES = load_plugin()
C = M.mteam


class Page:
    def __init__(self, scenario):
        self.scenario = scenario
        self.context = Mock()
        self.context.cookies.return_value = [{'name': 'session', 'value': 'hidden'}]
        self.calls = []
        self.listener = None
        self.email_filled = False
        self.ready_checks = 0

    def locator(self, selector):
        page = self
        class EmailInput:
            @property
            def first(self):
                return self
            def fill(self, value, **kwargs):
                page.email_filled = True
                page.calls.append(('native_email_fill', value))
            def press(self, key):
                page.calls.append(('native_email_press', key))
        return EmailInput()

    def on(self, event, callback):
        self.listener = callback

    def emit(self, path, payload):
        self.listener(types.SimpleNamespace(url='https://api.m-team.cc/api/' + path,
                                            json=lambda: payload))

    def authenticated(self):
        self.emit('member/profile', {'code': '0', 'data': {'id': '42', 'username': 'user'}})

    def goto(self, url, **kwargs):
        self.calls.append(('goto', url))
        if url.endswith('/index') and self.scenario == 'reuse':
            self.authenticated()
        elif url.endswith('/index') and self.scenario == 'stale':
            self.emit('member/profile', {'code': '401', 'data': {}})

    def wait_for_timeout(self, value):
        pass

    def add_init_script(self, value):
        self.calls.append(('restore', value))

    def evaluate(self, script, arg=None):
        self.calls.append((script, arg))
        if script == C.STORAGE_JS:
            return {'local': {'auth': 'hidden'}, 'session': {'__mp_mteam_restored': '1'}}
        if script == C.SEND_EMAIL_STATUS_JS:
            self.ready_checks += 1
            if self.scenario == 'missing_button':
                return 'missing'
            if self.scenario == 'disabled_button':
                return 'disabled'
            if self.scenario == 'delayed_send' and self.ready_checks < 4:
                return 'disabled'
            return 'ready' if self.email_filled else 'disabled'
        if script == C.SEND_EMAIL_JS:
            if not self.email_filled:
                raise AssertionError('must fill email before sending')
            if self.scenario == 'delayed_send' and self.ready_checks < 4:
                raise AssertionError('must wait for asynchronous validation')
            if self.scenario in ('send', 'delayed_send'):
                self.emit('member/sendLoginEmailVerifyCode', {'code': '0'})
            return True
        if script == C.OTP_JS_FILL:
            if self.scenario == 'code':
                self.authenticated()
            return True
        return True


class BrowserTests(unittest.TestCase):
    def run_browser(self, scenario, **kwargs):
        page = Page(scenario)
        helper = Mock()
        helper.return_value.action.side_effect = lambda **kw: kw['callback'](page)
        MODULES['app.helper.browser'].PlaywrightHelper = helper
        with patch.dict(sys.modules, MODULES):
            result = C.keepalive_login('user', 'pass', email='user@example.org', **kwargs)
        return result, page, helper

    def state(self):
        return {'identity': C.session_identity('user', 'pass', C.DEFAULT_SITE),
                'origin': C.DEFAULT_SITE, 'cookies': [], 'local': {'auth': 'old'}}

    def test_send_requires_server_confirmation(self):
        result, page, _ = self.run_browser('send', request_email=True)
        self.assertTrue(result['email_sent'])
        self.assertFalse(result['ok'])
        result, _, _ = self.run_browser('send_rejected', request_email=True)
        self.assertFalse(result['email_sent'])

    def test_waits_for_async_email_validation_and_clicks_once(self):
        result, page, _ = self.run_browser('delayed_send', request_email=True)
        self.assertTrue(result['email_sent'])
        self.assertEqual(page.ready_checks, 4)
        self.assertEqual(sum(c[0] == C.SEND_EMAIL_JS for c in page.calls), 1)
        self.assertIn(('native_email_press', 'Tab'), page.calls)

    def test_distinguishes_disabled_and_missing_buttons_without_sending(self):
        for scenario, message in [('disabled_button', '暂不可用'), ('missing_button', '未找到')]:
            result, page, _ = self.run_browser(scenario, request_email=True)
            self.assertIn(message, result['message'])
            self.assertFalse(result['email_sent'])
            self.assertNotIn(C.SEND_EMAIL_JS, [c[0] for c in page.calls])

    def test_code_does_not_resend_and_saves_state(self):
        result, page, _ = self.run_browser('code', email_code='123456')
        self.assertTrue(result['ok'])
        self.assertIn('state', result)
        self.assertNotIn('__mp_mteam_restored', result['state']['session'])
        self.assertNotIn(C.SEND_EMAIL_JS, [c[0] for c in page.calls])
        self.assertNotIn('123456', json.dumps(result))

    def test_bad_code_not_success(self):
        result, _, _ = self.run_browser('bad_code', email_code='123456')
        self.assertFalse(result['ok'])
        self.assertNotIn('state', result)

    def test_restore_and_stale_token(self):
        result, page, _ = self.run_browser('reuse', state=self.state())
        self.assertTrue(result['ok'])
        self.assertIn('restore', [c[0] for c in page.calls])
        self.assertNotIn(C.LOGIN_JS_FILL, [c[0] for c in page.calls])
        result, page, _ = self.run_browser('stale', state=self.state())
        self.assertFalse(result['ok'])
        self.assertNotIn(C.SEND_EMAIL_JS, [c[0] for c in page.calls])

    def test_changed_account_and_invalid_code_do_not_start_browser(self):
        state = self.state()
        state['identity'] = 'another-account'
        result, _, helper = self.run_browser('reuse', state=state)
        self.assertFalse(result['ok'])
        helper.assert_not_called()
        result, _, helper = self.run_browser('code', email_code='invalid')
        self.assertFalse(result['ok'])
        helper.assert_not_called()

    def test_browser_exception_does_not_expose_credentials(self):
        helper = Mock()
        helper.return_value.action.side_effect = RuntimeError('password=hidden code=123456')
        MODULES['app.helper.browser'].PlaywrightHelper = helper
        with patch.dict(sys.modules, MODULES):
            result = C.keepalive_login('user', 'pass', email_code='123456')
        self.assertFalse(result['ok'])
        self.assertNotIn('hidden', json.dumps(result))
        self.assertNotIn('123456', json.dumps(result))


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.plugin = M.MtAliver()
        self.data = {}
        self.plugin.get_data = self.data.get
        self.plugin.save_data = self.data.__setitem__
        self.plugin.update_config = Mock()
        self.plugin.post_message = Mock()
        self.plugin.site_apikey = lambda: ''
        self.plugin.init_plugin({'enabled': True, 'username': 'user', 'password': 'pass'})

    def test_form_no_totp_and_defaults(self):
        form, defaults = self.plugin.get_form()
        self.assertNotIn('totp', json.dumps(form).lower())
        self.assertEqual(defaults['interval_days'], 1)
        self.assertEqual(defaults['cron'], '35 1,9,21 * * *')

    def test_one_time_values_cleared_and_session_persisted(self):
        self.plugin._email_code = '123456'
        with patch.object(M, 'keepalive_login', return_value={'ok': True, 'state': {'local': {}}}) as login:
            self.plugin.keepalive()
        self.assertEqual(login.call_args.kwargs['email_code'], '123456')
        self.assertEqual(self.plugin._email_code, '')
        self.assertEqual(self.plugin.update_config.call_args.args[0]['email_code'], '')
        self.assertIn('browser_state', self.data)
        self.assertNotIn('123456', json.dumps(self.data))

    def test_scheduled_skips_today_but_runs_next_date(self):
        self.data['last_success'] = {'ok': True, 'time': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        with patch.object(self.plugin, 'keepalive') as run:
            self.plugin.scheduled_keepalive()
            run.assert_not_called()
            self.data['last_success']['time'] = (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')
            self.plugin.scheduled_keepalive()
            run.assert_called_once()

    def test_activity_cannot_override_browser_failure(self):
        self.plugin._api_key = 'key'
        fresh = {'last_browse': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        with patch.object(M, 'fetch_profile', side_effect=[(None, 'unavailable'), (fresh, '')]), patch.object(M, 'keepalive_login', return_value={'ok': False, 'message': 'expired'}):
            self.assertFalse(self.plugin.keepalive()['ok'])

    def test_unchanged_activity_or_failed_api_not_verified(self):
        self.plugin._api_key = 'key'
        fresh = {'last_browse': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        for responses in [[(fresh, ''), (fresh, '')], [(None, 'offline'), (None, 'offline')]]:
            with patch.object(M, 'fetch_profile', side_effect=responses), patch.object(M, 'keepalive_login', return_value={'ok': True}):
                self.assertFalse(self.plugin.keepalive()['ok'])

    def test_activity_updated_and_initial_profile_unavailable(self):
        self.plugin._api_key = 'key'
        fresh = {'last_browse': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        old = {'last_browse': (datetime.now()-timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S')}
        for before in (old, None):
            with patch.object(M, 'fetch_profile', side_effect=[(before, ''), (fresh, '')]), patch.object(M, 'keepalive_login', return_value={'ok': True}):
                self.assertTrue(self.plugin.keepalive()['ok'])

    def test_nonoverlap(self):
        self.plugin._run_lock.acquire()
        try:
            with patch.object(M, 'keepalive_login') as login:
                self.assertFalse(self.plugin.keepalive()['ok'])
                login.assert_not_called()
        finally:
            self.plugin._run_lock.release()


if __name__ == '__main__':
    unittest.main()
