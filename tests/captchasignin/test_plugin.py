"""MoviePilot entrypoint integration with lightweight application stubs."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).parents[2]


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.settings = types.SimpleNamespace(OCR_HOST='http://custom-ocr:9899/', PROXY={})
        self.sites = Mock()
        names = ['apscheduler', 'apscheduler.triggers', 'apscheduler.triggers.cron',
                 'app', 'app.plugins', 'app.db', 'app.db.oper', 'app.db.oper.site',
                 'app.sdk', 'app.sdk.logging', 'app.schemas', 'app.core', 'app.core.config']
        modules = {name: types.ModuleType(name) for name in names}
        modules['apscheduler.triggers.cron'].CronTrigger = Mock()
        modules['app.plugins']._PluginBase = type('PluginBase', (), {})
        modules['app.db.oper.site'].SiteOper = Mock(return_value=self.sites)
        modules['app.sdk.logging'].logger = Mock()
        modules['app.schemas'].NotificationType = types.SimpleNamespace(SiteMessage='site')
        modules['app.core.config'].settings = self.settings
        self.modules_patch = patch.dict(sys.modules, modules)
        self.modules_patch.start()
        self.addCleanup(self.modules_patch.stop)
        name = 'captcha_test_plugin'
        spec = importlib.util.spec_from_file_location(name, ROOT/'plugins.v3/captchasignin/__init__.py',
                                                     submodule_search_locations=[str(ROOT/'plugins.v3/captchasignin')])
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[name] = self.module
        spec.loader.exec_module(self.module)
        self.plugin = self.module.CaptchaSignIn()
        self.plugin.get_data = Mock(return_value=None)
        self.plugin.save_data = Mock()
        self.plugin.post_message = Mock()
        self.plugin.update_config = Mock()
        self.site = types.SimpleNamespace(id=9, name='农场', url='https://pt.0ff.cc', cookie='uid=1', ua='', proxy=False)
        self.sites.list_order_by_pri.return_value = [self.site]

    def test_old_token_group_selection_is_preserved(self):
        self.plugin.init_plugin({'browserless_token_1':'old-token', 'site_ids_1':[9]})
        self.assertEqual(self.plugin._site_ids, [9])
        self.assertEqual(self.plugin._site_tokens[9], 'old-token')
        self.assertEqual(self.plugin._config()['site_ids'], [9])
        self.assertEqual(self.plugin._config()['site_9_token'], 1)

    def test_legacy_single_token_migration_is_preserved(self):
        self.plugin.init_plugin({'browserless_token':'legacy', 'site_ids':[9]})
        self.assertEqual(self.plugin._config()['browserless_tokens'], 'legacy')
        self.assertEqual(self.plugin._site_ids, [9])

    def test_direct_and_group_sites_are_deduplicated_and_saved(self):
        self.plugin.init_plugin({'direct_site_ids':[9,10], 'site_ids_1':[9], 'browserless_token_1':'fallback'})
        self.assertEqual(self.plugin._site_ids, [9,10])
        self.assertEqual(self.plugin._config()['site_ids'], [9,10])

    def test_no_token_does_not_prevent_running_direct_signer(self):
        self.plugin.init_plugin({'direct_site_ids':[9], 'notify':False, 'retry_count':0})
        signer = Mock()
        signer.sign.return_value = self.module.SignResult('success','农场直连完成')
        self.plugin._make_signer = Mock(return_value=signer)
        self.plugin.run_sign_in()
        signer.sign.assert_called_once()
        latest = next(call.args[1] for call in self.plugin.save_data.call_args_list if call.args[0]=='latest')
        self.assertEqual(latest[0]['status'], 'success')
        self.assertEqual(latest[0]['url'], 'https://pt.0ff.cc/attendance.php')

    def test_empty_token_group_still_runs_direct(self):
        self.plugin.init_plugin({'site_ids_1':[9], 'browserless_token_1':'', 'notify':False, 'retry_count':0})
        self.assertEqual(self.plugin._site_ids, [9])
        self.assertIsNone(self.plugin._make_signer('').browserless_factory())

    def test_daily_success_skips_both_network_paths(self):
        self.plugin.init_plugin({'direct_site_ids':[9], 'notify':False})
        self.plugin.get_data.side_effect = lambda key: {'id:9':{'site':'农场','site_id':'9','status':'success'}} if key.startswith('state_') else None
        self.plugin._make_signer = Mock()
        self.plugin.run_sign_in()
        self.plugin._make_signer.assert_not_called()

    def test_ocr_adapter_uses_current_mp_host_without_site_cookie(self):
        with patch('requests.post') as post:
            post.return_value.json.return_value = {'result':'A12B34'}
            self.assertEqual(self.plugin._recognize_captcha('png-base64'), 'A12B34')
            post.assert_called_once_with('http://custom-ocr:9899/captcha/base64', json={'base64_img':'png-base64'}, timeout=30)
            self.settings.OCR_HOST = 'https://another-ocr'
            self.plugin._recognize_captcha('png-base64')
            self.assertEqual(post.call_args.args[0], 'https://another-ocr/captcha/base64')

    def nodes(self, nodes):
        for node in nodes:
            yield node
            yield from self.nodes(node.get('content') or [])

    def test_form_has_plain_token_list_before_site_selection(self):
        self.plugin.init_plugin({})
        form, defaults = self.plugin.get_form()
        nodes = list(self.nodes(form))
        fields = {node.get('props', {}).get('model'):node for node in nodes if node.get('props', {}).get('model')}
        keys = list(fields)
        self.assertLess(keys.index('retry_count'), keys.index('browserless_tokens'))
        self.assertLess(keys.index('browserless_tokens'), keys.index('site_ids'))
        self.assertEqual(fields['browserless_tokens']['component'], 'VTextarea')
        self.assertNotEqual(fields['browserless_tokens']['props'].get('type'), 'password')
        self.assertNotIn('browserless_token_1', defaults)
        self.assertIn('site_9_token', fields)
        self.assertIn('site_9_mode', fields)
        self.assertEqual(defaults['site_9_mode'], 'farm')
        self.assertEqual(defaults['site_9_token'], 0)

    def test_sites_choose_explicit_token_without_round_robin(self):
        self.plugin.init_plugin({'browserless_tokens':'first\nsecond', 'site_ids':[9,10,11],
                                 'site_9_token':2, 'site_10_token':2, 'site_11_token':0})
        self.assertEqual(self.plugin._site_tokens, {9:'second',10:'second',11:''})
        saved = self.plugin._config()
        self.plugin.init_plugin(saved)
        self.assertEqual(self.plugin._site_tokens, {9:'second',10:'second',11:''})

    def test_invalid_token_reference_never_substitutes_another_token(self):
        self.plugin.init_plugin({'browserless_tokens':'first', 'site_ids':[9,10], 'site_9_token':3, 'site_10_token':'bad'})
        self.assertEqual(self.plugin._site_tokens, {9:'',10:''})

    def test_old_groups_retain_assignments_after_empty_slot_and_duplicate_token(self):
        self.plugin.init_plugin({'site_ids_1':[], 'browserless_token_1':'',
                                 'site_ids_2':[9,10], 'browserless_token_2':'second',
                                 'site_ids_3':[11,9], 'browserless_token_3':'third',
                                 'site_ids_4':[12], 'browserless_token_4':'second'})
        self.assertEqual(self.plugin._browserless_tokens, 'second\nthird')
        self.assertEqual(self.plugin._site_tokens, {9:'second',10:'second',11:'third',12:'second'})
        self.assertEqual(self.plugin._config()['site_11_token'], 2)

    def test_clearing_new_site_selection_does_not_restore_legacy_sites(self):
        self.plugin.init_plugin({'config_layout':'site', 'site_ids':[], 'browserless_tokens':'', 'site_ids_1':[9]})
        self.assertEqual(self.plugin._site_ids, [])

    def test_nonfarm_site_card_has_reactive_token_and_custom_controls(self):
        self.sites.list_order_by_pri.return_value = [types.SimpleNamespace(id=10, name='测试站',
                         url='https://pt.example', cookie='uid=1', ua='', proxy=False), self.site]
        self.plugin.init_plugin({'browserless_tokens':'first\nsecond', 'site_ids':[10]})
        form, defaults = self.plugin.get_form()
        nodes = list(self.nodes(form))
        fields = {node.get('props', {}).get('model'):node for node in nodes if node.get('props', {}).get('model')}
        labels = fields['site_10_mode']['props']['items']
        self.assertIn({'title':'点击确定','value':'open_page'}, labels)
        self.assertIn({'title':'验证码','value':'image'}, labels)
        self.assertIn({'title':'CF盾','value':'cloudflare'}, labels)
        self.assertIn('site_10_button_source', fields)
        self.assertIn('site_10_success_source', fields)
        shows = [node.get('props',{}).get('show','') for node in nodes]
        self.assertIn("{{ site_10_button_source === 'custom' }}", shows)
        self.assertIn("{{ site_10_success_source === 'custom' }}", shows)
        self.assertIn("{{ (site_ids || []).map(String).includes('10') }}", shows)
        self.assertIn("Token ", fields['site_10_token']['props']['items'])
        self.assertIn('site_9_token', defaults)

    def test_sign_one_applies_site_overrides_to_actual_signer(self):
        self.plugin.init_plugin({'browserless_tokens':'one', 'site_ids':[10], 'site_10_token':1,
                'site_10_mode':'cloudflare', 'site_10_button_source':'custom', 'site_10_button_text':'签到',
                'site_10_success_source':'custom', 'site_10_success_text':'领取完成'})
        site = types.SimpleNamespace(id=10, name='测试站', url='https://pt.example', cookie='uid=1', ua='', proxy=False)
        signer = Mock()
        signer.sign.return_value = self.module.SignResult('success','ok')
        result = self.plugin._sign_one(site, {}, signer)
        self.assertEqual(result['status'], 'success')
        rule = signer.sign.call_args.args[1]
        self.assertEqual(rule['mode'], 'cloudflare')
        self.assertEqual(rule['submit_text'], '签到')
        self.assertEqual(rule['success_keywords'], ['领取完成'])

    def test_piggo_defaults_to_local_mode_and_exposes_local_option(self):
        self.sites.list_order_by_pri.return_value = [types.SimpleNamespace(id=10,name='猪猪',
            url='https://www.piggo.me',cookie='uid=1',ua='',proxy=False)]
        self.plugin.init_plugin({'browserless_tokens':'token','site_ids':[10],'site_10_token':1})
        form, defaults = self.plugin.get_form()
        fields={n.get('props',{}).get('model'):n for n in self.nodes(form) if n.get('props',{}).get('model')}
        self.assertEqual(defaults['site_10_mode'],'local_browser')
        self.assertIn({'title':'本地浏览器','value':'local_browser'},fields['site_10_mode']['props']['items'])
        self.assertIn('local_browser',fields['site_10_token']['props']['disabled'])
        signer=self.plugin._make_signer('token')
        self.assertIsInstance(signer.local,self.module.LocalBrowserSigner)

    def test_v2_entrypoint_uses_legacy_database_and_logger_imports(self):
        db = types.ModuleType('app.db.site_oper')
        db.SiteOper = Mock(return_value=self.sites)
        log = types.ModuleType('app.log')
        log.logger = Mock()
        with patch.dict(sys.modules, {'app.db.oper.site':None, 'app.sdk.logging':None,
                                      'app.db.site_oper':db, 'app.log':log}):
            spec = importlib.util.spec_from_file_location('captcha_test_v2', ROOT/'plugins.v2/captchasignin/__init__.py',
                         submodule_search_locations=[str(ROOT/'plugins.v2/captchasignin')])
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            plugin = module.CaptchaSignIn()
            plugin.init_plugin({'direct_site_ids':[9]})
            self.assertEqual(plugin._site_ids,[9])
            self.assertEqual(plugin.plugin_version,'2.0.1')


if __name__ == '__main__':
    unittest.main()
