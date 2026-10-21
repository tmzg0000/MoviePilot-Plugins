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
        class Input:
            def __init__(self, selector):
                self.selector = selector
            @property
            def first(self):
                return self
            def fill(self, value, **kwargs):
                if self.selector == C.EMAIL_INPUT_SELECTOR:
                    page.email_filled = True
                    page.calls.append(('native_email_fill', value))
                else:
                    page.code_filled = True
                    page.calls.append(('native_code_fill', value))
            def press(self, key):
                page.calls.append(('native_input_press', key))
            def locator(self, selector):
                page.calls.append(('locator', selector))
                return Input(selector)
            def click(self, **kwargs):
                if not getattr(page, 'code_filled', False):
                    raise AssertionError('submit before code entered')
                page.calls.append(('native_code_submit', None))
                if page.scenario == 'code':
                    page.authenticated()
        return Input(selector)

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
        return {'identity': C.session_identity('user', C.DEFAULT_SITE),
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
        self.assertIn(('native_input_press', 'Tab'), page.calls)

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
        self.assertIn(('native_code_submit', None), page.calls)
        self.assertIn(('locator', 'xpath=ancestor::form[1]'), page.calls)

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

    def test_browser_reuses_session_without_password(self):
        page = Page('reuse')
        helper = Mock()
        helper.return_value.action.side_effect = lambda **kw: kw['callback'](page)
        MODULES['app.helper.browser'].PlaywrightHelper = helper
        with patch.dict(sys.modules, MODULES):
            result = C.keepalive_login('user', '', state=self.state())
        self.assertTrue(result['ok'])
        self.assertNotIn(C.LOGIN_JS_FILL, [call[0] for call in page.calls])

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

    def form_data(self, **extra):
        return {"username": "new-user", "password": "new-pass", "email": "new@example.org",
                "api_key": "key", "enabled": True, "notify": False, **extra}

    def test_password_not_in_form_or_any_persisted_config(self):
        form, model = self.plugin.get_form()
        self.assertNotIn('password', model)
        fields = []
        def visit(nodes):
            for node in nodes:
                if node.get('props', {}).get('id') == 'mtaliver-login-password':
                    fields.append(node['props'])
                visit(node.get('content', []))
        visit(form)
        self.assertEqual(len(fields), 1)
        self.assertEqual(fields[0]['type'], 'password')
        self.assertNotIn('model', fields[0])
        self.assertNotIn('value', fields[0])
        with patch.object(M, 'fetch_profile', return_value=(None, 'offline')), patch.object(M, 'keepalive_login', return_value={'ok': False, 'email_sent': True, 'message': 'sent'}):
            self.plugin.api_send_code(self.form_data(password='unique-transient-password'))
        for call in self.plugin.update_config.call_args_list:
            self.assertNotIn('password', call.args[0])
            self.assertNotIn('unique-transient-password', json.dumps(call.args[0]))
        self.assertEqual(self.plugin._password, '')
        self.assertNotIn('unique-transient-password', json.dumps(self.data))

    def test_legacy_plaintext_removed_and_existing_session_migrated(self):
        import hashlib
        old_id = hashlib.sha256(json.dumps(['user', 'legacy-secret', C.DEFAULT_SITE], ensure_ascii=False).encode()).hexdigest()
        self.data['browser_state'] = {'identity': old_id, 'local': {'auth': 'existing-token'}}
        self.plugin.init_plugin({'username': 'user', 'password': 'legacy-secret', 'site_url': C.DEFAULT_SITE})
        self.assertEqual(self.plugin._password, '')
        saved = self.plugin.update_config.call_args.args[0]
        self.assertNotIn('password', saved)
        self.assertNotIn('legacy-secret', json.dumps(saved))
        self.assertEqual(self.data['browser_state']['identity'], C.session_identity('user', C.DEFAULT_SITE))
        self.assertEqual(self.data['browser_state']['local']['auth'], 'existing-token')
        self.assertNotIn('password', self.plugin.get_form()[1])

    def test_refresh_without_password_and_exception_clears_temporary_password(self):
        with patch.object(M, 'fetch_profile', return_value=(None, 'offline')), patch.object(M, 'keepalive_login', return_value={'ok': True, 'message': 'refreshed'}) as login:
            self.plugin.api_refresh_session(self.form_data(password=''))
        self.assertEqual(login.call_args.args[1], '')
        with patch.object(M, 'keepalive_login', side_effect=RuntimeError('failure')):
            self.plugin.api_send_code(self.form_data(password='temporary'))
        self.assertEqual(self.plugin._password, '')

    def test_buttons_use_live_form_and_authenticated_post_api(self):
        form, defaults = self.plugin.get_form()
        serialized = json.dumps(form, ensure_ascii=False)
        self.assertIn('获取验证码', serialized)
        self.assertIn('登录', serialized)
        self.assertNotIn('保存后立即执行一次', serialized)
        self.assertNotIn('"model": "request_email"', serialized)
        self.assertIn('window.MoviePilotAPI.post', serialized)
        self.assertNotIn('localStorage', serialized)
        self.assertFalse(defaults['auth_busy'])
        routes = {r['path']: r for r in self.plugin.get_api()}
        for path in ('/send_code', '/login', '/refresh_session'):
            self.assertEqual(routes[path]['auth'], 'bear')
            self.assertEqual(routes[path]['methods'], ['POST'])

    def test_send_button_saves_unsaved_form_without_scheduling_otp(self):
        with patch.object(M, 'fetch_profile', return_value=(None, 'offline')), patch.object(M, 'keepalive_login', return_value={'ok': False, 'email_sent': True, 'message': 'sent'}) as login, patch.object(M, 'BackgroundScheduler') as scheduler:
            result = self.plugin.api_send_code(self.form_data())
        self.assertTrue(result['success'])
        self.assertEqual(login.call_args.args[:2], ('new-user', 'new-pass'))
        self.assertTrue(login.call_args.kwargs['request_email'])
        self.assertEqual(login.call_args.kwargs['email'], 'new@example.org')
        self.assertEqual(self.plugin.update_config.call_args.args[0]['username'], 'new-user')
        scheduler.assert_not_called()

    def test_login_button_does_not_resend_and_persists_session(self):
        with patch.object(M, 'fetch_profile', return_value=(None, 'offline')), patch.object(M, 'keepalive_login', return_value={'ok': True, 'message': 'logged in', 'state': {'local': {'auth': 'token'}}}) as login:
            result = self.plugin.api_login(self.form_data(email_code='123456'))
        # Login is successful even when the optional activity API is offline.
        self.assertTrue(result['success'])
        self.assertTrue(result['authenticated'])
        self.assertIn('已登录并保存会话', result['message'])
        self.assertFalse(login.call_args.kwargs['request_email'])
        self.assertEqual(login.call_args.kwargs['email_code'], '123456')
        self.assertEqual(self.plugin._password, '')
        self.assertNotIn('password', self.plugin.update_config.call_args.args[0])
        self.assertIn('browser_state', self.data)
        self.assertNotIn('123456', json.dumps(self.data))
        self.assertEqual(self.plugin.update_config.call_args.args[0]['email_code'], '')

    def test_invalid_form_and_concurrent_action_do_not_change_credentials(self):
        for values in ({'email': 'invalid'}, {'username': ''}, {'password': ''}, {'email_code': 'bad'}):
            with patch.object(M, 'keepalive_login') as login:
                self.assertFalse(self.plugin.api_login(self.form_data(**values))['success'])
                login.assert_not_called()
        self.assertEqual(self.plugin._username, 'user')
        self.plugin._run_lock.acquire()
        try:
            self.assertFalse(self.plugin.api_send_code(self.form_data())['success'])
            self.assertEqual(self.plugin._username, 'user')
        finally:
            self.plugin._run_lock.release()

    def test_refresh_button_never_uses_a_code_or_resends(self):
        with patch.object(M, 'fetch_profile', return_value=(None, 'offline')), patch.object(M, 'keepalive_login', return_value={'ok': False, 'message': 'expired'}) as login:
            self.assertFalse(self.plugin.api_refresh_session(self.form_data(email_code='123456'))['success'])
        self.assertEqual(login.call_args.kwargs['email_code'], '')
        self.assertFalse(login.call_args.kwargs['request_email'])

    def test_one_time_job_has_delay_and_misfire_grace(self):
        scheduler = Mock()
        with patch.object(M, 'BackgroundScheduler', return_value=scheduler):
            self.plugin.init_plugin({'run_once': True, 'email_code': '123456'})
        job = scheduler.add_job.call_args.kwargs
        self.assertGreater(job['run_date'].timestamp(), datetime.now().timestamp())
        self.assertIsNotNone(job['run_date'].tzinfo)
        self.assertEqual(job['misfire_grace_time'], 120)
        self.assertEqual(self.data['execution']['status'], 'queued')
        self.assertNotIn('123456', json.dumps(self.data))
        scheduler.start.assert_called_once()
        self.plugin.stop_service()

    def test_running_status_visible_before_browser_returns(self):
        def login(*args, **kwargs):
            self.assertEqual(self.data['execution']['status'], 'running')
            self.assertIn('执行中', json.dumps(self.plugin.get_page(), ensure_ascii=False))
            return {'ok': False, 'message': '验证码被拒绝'}
        with patch.object(M, 'keepalive_login', side_effect=login):
            result = self.plugin.keepalive()
        self.assertFalse(result['ok'])
        self.assertEqual(self.data['execution']['status'], 'finished')

    def test_unexpected_failure_is_recorded_and_secrets_redacted(self):
        with patch.object(M, 'keepalive_login', side_effect=RuntimeError('secret-code-123456')):
            self.assertFalse(self.plugin.keepalive()['ok'])
        self.assertEqual(self.data['execution']['status'], 'failed')
        self.assertIn('last', self.data)
        self.assertNotIn('123456', json.dumps(self.data))

    def test_pending_footer_does_not_report_failure(self):
        self.data['history'] = [{'pending': True, 'time': '2026-10-21 09:00:00'}]
        self.data['last'] = self.data['history'][0]
        page = json.dumps(self.plugin.get_page(), ensure_ascii=False)
        self.assertIn('最近一次：2026-10-21 09:00:00 · 待验证', page)

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
