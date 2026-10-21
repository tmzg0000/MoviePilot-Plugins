"""HTTP/OCR and fallback regression tests; no real accounts or network calls."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

PATH = Path(__file__).parents[2] / 'plugins.v3/captchasignin/core.py'
SPEC = importlib.util.spec_from_file_location('captcha_http_core', PATH)
core = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = core
SPEC.loader.exec_module(core)

FORM = '''<form method="post" action="/attendance.php?check=1">
<input name="csrf" value="keep-this"><input name="imagehash" value="hash1">
<img src="/image.php?action=regimage&amp;imagehash=hash1&amp;secret=">
<input name="imagestring"><input type="submit" name="submit" value="签到">
<input type="checkbox" name="unchecked" value="no"></form>'''
SITE = {'url': 'https://p.t-baozi.cc', 'cookie': 'uid=1; pass=a=b', 'ua': 'MP-test'}


def response(text='', content=b'png', status=200, headers=None):
    res = Mock(text=text, content=content, status_code=status, headers=headers or {})
    res.raise_for_status.return_value = None
    return res


class HttpTests(unittest.TestCase):
    def make_signer(self, responses, code='A12B34'):
        signer = core.HttpSigner(Mock(return_value=code))
        signer._request = Mock(side_effect=responses)
        return signer

    def test_image_keeps_hash_hidden_fields_and_submits_ocr_answer(self):
        signer = self.make_signer([response(FORM), response(), response('签到成功')])
        result = signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc'])
        self.assertIn(result.status, {'success', 'already'})
        signer.recognize.assert_called_once_with(base64.b64encode(b'png').decode())
        calls = signer._request.call_args_list
        self.assertEqual(calls[1].args[2], 'https://p.t-baozi.cc/image.php?action=regimage&imagehash=hash1&secret=')
        self.assertEqual(calls[2].args[1:3], ('POST', 'https://p.t-baozi.cc/attendance.php?check=1'))
        self.assertEqual(dict(calls[2].kwargs['data']), {'csrf':'keep-this', 'imagehash':'hash1', 'imagestring':'A12B34', 'submit':'签到'})
        self.assertNotIn('A12B34', result.message)

    def test_already_signed_does_not_call_ocr(self):
        signer = self.make_signer([response('今日已签到')])
        self.assertEqual(signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc']).status, 'already')
        signer.recognize.assert_not_called()
        self.assertEqual(signer._request.call_count, 1)

    def test_bad_ocr_does_not_submit(self):
        signer = self.make_signer([response(FORM), response()], code='')
        result = signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc'])
        self.assertEqual(result.status, 'failed')
        self.assertEqual(signer._request.call_count, 2)

    def test_ocr_rejected_and_ambiguous_result_are_not_success(self):
        signer = self.make_signer([response(FORM), response(), response('验证码错误'), response(FORM)])
        self.assertEqual(signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc']).status, 'failed')

    def test_opencd_even_json_success_requires_homepage_confirmation(self):
        for homepage, expected in [('首页', 'failed'), ('查看簽到記錄', 'already')]:
            signer = self.make_signer([response('首页'), response(FORM), response(), response('{"state":"success"}'), response(homepage)])
            result = signer.sign(dict(SITE, url='https://open.cd'), core.DEFAULT_RULES['open.cd'])
            self.assertEqual(result.status, expected)
            self.assertEqual(signer._request.call_args_list[3].args[2], 'https://open.cd/plugin_sign-in.php?cmd=signin')
            self.assertEqual(signer._request.call_args_list[4].args[2], 'https://open.cd/')

    def test_opencd_false_is_failure_without_record(self):
        signer = self.make_signer([response('首页'), response(FORM), response(), response('{"state":"false"}'), response('首页')])
        self.assertEqual(signer.sign(dict(SITE, url='https://open.cd'), core.DEFAULT_RULES['open.cd']).status, 'failed')

    def test_cross_origin_form_is_not_submitted(self):
        form = FORM.replace('/attendance.php?check=1', 'https://other.example/steal')
        signer = self.make_signer([response(form), response()])
        self.assertEqual(signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc']).status, 'failed')
        self.assertEqual(signer._request.call_count, 2)

    def test_cross_origin_image_is_not_downloaded(self):
        signer = self.make_signer([response(FORM.replace('/image.php?', 'https://other.example/image.php?'))])
        self.assertEqual(signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc']).status, 'failed')
        self.assertEqual(signer._request.call_count, 1)

    def test_farm_script_token_and_final_verification(self):
        signer = self.make_signer([response('<script src="/slide_check_abc.js"></script>'),
                                   response('const requestUrl = "https://pt.0ff.cc/set_access_token-secret";'),
                                   response('ok'), response('签到成功')])
        result = signer.sign(dict(SITE, url='https://pt.0ff.cc'), core.DEFAULT_RULES['pt.0ff.cc'])
        self.assertEqual(result.status, 'success')
        signer.recognize.assert_not_called()
        self.assertEqual(signer._request.call_args_list[2].args[2], 'https://pt.0ff.cc/set_access_token-secret')
        self.assertNotIn('secret', result.message)

    def test_farm_already_signed_needs_no_script(self):
        signer = self.make_signer([response('今日已签到')])
        self.assertEqual(signer.sign(dict(SITE, url='https://pt.0ff.cc'), core.DEFAULT_RULES['pt.0ff.cc']).status, 'already')
        self.assertEqual(signer._request.call_count, 1)

    def test_farm_token_http_200_is_not_enough(self):
        signer = self.make_signer([response('<script src="/slide_check_a.js"></script>'),
                                   response("const requestUrl = '/set_access_token-x';"), response('ok'),
                                   response('拖动滑块验证')])
        self.assertEqual(signer.sign(dict(SITE, url='https://pt.0ff.cc'), core.DEFAULT_RULES['pt.0ff.cc']).status, 'failed')

    def test_farm_external_token_is_never_requested(self):
        signer = self.make_signer([response('<script src="/slide_check_a.js"></script>'), response('"https://other.example/set_access_token-x"')])
        self.assertEqual(signer.sign(dict(SITE, url='https://pt.0ff.cc'), core.DEFAULT_RULES['pt.0ff.cc']).status, 'failed')
        self.assertEqual(signer._request.call_count, 2)

    def test_request_rejects_external_redirect_before_following(self):
        signer = core.HttpSigner(Mock())
        session = Mock()
        session.request.return_value = response(status=302, headers={'Location': 'https://other.example/login'})
        with self.assertRaises(ValueError):
            signer._request(session, 'GET', SITE['url'])
        self.assertEqual(session.request.call_count, 1)
        self.assertFalse(session.request.call_args.kwargs['allow_redirects'])

    def test_session_carries_cookies_ua_and_selected_proxy(self):
        import requests
        session = requests.Session()
        session.request = Mock(return_value=response('今日已签到'))
        with patch('requests.Session', return_value=session):
            core.HttpSigner(Mock(), proxies={'https':'http://proxy:80'}).sign(dict(SITE, proxy=True), core.DEFAULT_RULES['p.t-baozi.cc'])
        self.assertEqual(session.cookies.get('pass'), 'a=b')
        self.assertEqual(session.headers['User-Agent'], 'MP-test')
        self.assertEqual(session.proxies, {'https':'http://proxy:80'})
        self.assertTrue(session.verify)

    def test_custom_button_text_selects_correct_submit_value(self):
        html = FORM.replace('<input type="submit" name="submit" value="签到">',
                '<button type="submit" name="action" value="cancel">取消</button>'
                '<button type="submit" name="action" value="signin"><span>立即签到</span></button>')
        signer = self.make_signer([response(html),response(),response('签到成功')])
        rule = dict(core.DEFAULT_RULES['p.t-baozi.cc'], submit_text='立即签到')
        result = signer.sign(SITE,rule)
        self.assertIn(result.status, {'success','already'})
        self.assertEqual(dict(signer._request.call_args.kwargs['data'])['action'], 'signin')

    def test_custom_button_missing_does_not_submit_another_button(self):
        signer = self.make_signer([response(FORM)])
        result = signer.sign(SITE, dict(core.DEFAULT_RULES['p.t-baozi.cc'],submit_text='领取今日奖励'))
        self.assertEqual(result.status,'failed')
        self.assertEqual(signer._request.call_count,1)


class SiteRuleTests(unittest.TestCase):
    def test_default_controls_keep_builtin_rules(self):
        site={'id':10,'url':'https://open.cd'}
        default=core.resolve_rule(site,{})
        self.assertEqual(core.resolve_rule(site,{}, {'site_10_mode':'default',
             'site_10_button_source':'default','site_10_button_text':'ignored',
             'site_10_success_source':'default','site_10_success_text':'ignored'}),default)

    def test_unknown_site_supports_image_mode_with_standard_form_defaults(self):
        rule=core.resolve_rule({'id':10,'url':'https://pt.example'}, {}, {'site_10_mode':'image'})
        self.assertEqual(rule['mode'],'image')
        self.assertIn('imagestring',rule['captcha_input_selector'])
        self.assertIn('img',rule['captcha_selector'])

    def test_custom_success_replaces_generic_and_ajax_success(self):
        rule=core.resolve_rule({'id':10,'url':'https://open.cd'}, {},
            {'site_10_success_source':'custom','site_10_success_text':'奖励发放完成\n打卡完成\n奖励发放完成'})
        self.assertEqual(rule['success_keywords'],['奖励发放完成','打卡完成'])
        self.assertEqual(core.classify('签到成功，今日已签到',rule).status,'failed')
        self.assertEqual(core.classify('<p>奖励发放完成</p>',rule).status,'success')
        self.assertEqual(core.classify('<script>奖励发放完成</script>',rule).status,'failed')
        payload=json.dumps({'status':200,'text':'{"state":"success"}'})
        self.assertEqual(core.classify_ajax_response(payload,rule).status,'failed')
        self.assertEqual(rule['verify_success_path'],'/')

    def test_custom_button_changes_native_click_to_text_lookup(self):
        rule=core.resolve_rule({'id':10,'url':'https://pt.example'}, {},
            {'site_10_button_source':'custom','site_10_button_text':'立即签到'})
        self.assertEqual(rule['submit_method'],'dom_click')
        script=core._submit_script(rule['submit_selector'],rule['submit_method'],submit_text=rule['submit_text'])
        self.assertIn('return found || null',script)
        self.assertIn(json.dumps('立即签到'),script)

    def test_blank_custom_values_are_configuration_errors(self):
        for suffix in ('button','success'):
            with self.assertRaises(ValueError):
                core.resolve_rule({'id':10,'url':'https://pt.example'}, {}, {'site_10_'+suffix+'_source':'custom'})

    def test_farm_cannot_be_changed_to_browser_mode(self):
        rule=core.resolve_rule({'id':10,'url':'https://pt.0ff.cc'},
             {'pt.0ff.cc':{'mode':'cloudflare'}}, {'site_10_mode':'cloudflare','site_10_button_source':'custom'})
        self.assertEqual(rule['mode'],'farm')



class FallbackTests(unittest.TestCase):
    def test_direct_success_does_not_construct_browserless(self):
        direct = Mock()
        direct.sign.return_value = core.SignResult('success', 'OCR success')
        factory = Mock()
        self.assertEqual(core.HybridSigner(direct, factory).sign(SITE, {}).status, 'success')
        factory.assert_not_called()

    def test_ocr_failure_uses_browserless_once(self):
        direct, browserless = Mock(), Mock()
        direct.sign.return_value = core.SignResult('failed', 'OCR failed')
        browserless.sign.return_value = core.SignResult('success', 'done')
        result = core.HybridSigner(direct, lambda: browserless).sign(SITE, {'mode':'image'})
        browserless.sign.assert_called_once_with(SITE, {'mode':'image'})
        self.assertEqual(result.status, 'success')
        self.assertIn('Browserless 兜底', result.message)

    def test_no_token_keeps_ocr_failure_reason(self):
        direct = Mock()
        direct.sign.return_value = core.SignResult('failed', 'MP OCR empty')
        result = core.HybridSigner(direct, lambda: None).sign(SITE, {})
        self.assertEqual(result.status, 'failed')
        self.assertIn('MP OCR empty', result.message)
        self.assertIn('未配置 Browserless Token', result.message)

    def test_browser_only_rules_skip_ocr_and_use_fallback(self):
        ocr, browserless = Mock(), Mock()
        browserless.sign.return_value = core.SignResult('already', 'done')
        rule = core.DEFAULT_RULES['hdsky.me']
        result = core.HybridSigner(core.HttpSigner(ocr), lambda: browserless).sign(SITE, rule)
        self.assertEqual(result.status, 'already')
        ocr.assert_not_called()
        browserless.sign.assert_called_once()

    def test_farm_failure_never_constructs_browserless_even_with_token(self):
        direct = Mock()
        direct.sign.return_value = core.SignResult('failed', '农场直连后仍需要滑块验证')
        factory = Mock(return_value=core.BrowserlessSigner('https://browserless.example', 'configured-token'))
        rule = core.resolve_rule({'url':'https://pt.0ff.cc'}, {})
        result = core.HybridSigner(direct, factory).sign(SITE, rule)
        self.assertEqual(result, direct.sign.return_value)
        factory.assert_not_called()
        self.assertNotIn('Browserless', result.message)

    def test_farm_without_token_keeps_original_failure_reason(self):
        direct = Mock()
        direct.sign.return_value = core.SignResult('failed', '农场页面未找到滑块验证脚本')
        factory = Mock(return_value=None)
        result = core.HybridSigner(direct, factory).sign(SITE, {'mode':'farm'})
        self.assertEqual(result.message, '农场页面未找到滑块验证脚本')
        factory.assert_not_called()

    def test_browserless_rejects_farm_without_network_calls(self):
        signer = core.BrowserlessSigner('https://browserless.example', 'configured-token')
        signer._request = Mock()
        result = signer.sign(SITE, {'mode':'farm'})
        self.assertEqual(result.status, 'failed')
        signer._request.assert_not_called()

    def test_image_fallback_handles_cloudflare_403_before_ocr_form(self):
        signer = core.BrowserlessSigner('https://browserless.example', 'token')
        signer._request = Mock(side_effect=[
            {'goto':{'status':403}, 'before':{'html':'<div>Just a moment cf-chl-test</div>'}},
            {'goto':{'status':403}, 'edge':{'found':True,'solved':True},
             'solve':{'found':True,'solved':True}, 'after':{'html':'今日已签到'}},
        ])
        result = signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc'])
        self.assertEqual(result.status, 'already')
        query = signer._request.call_args.args[2]
        self.assertLess(query.index('edge:solve'), query.index('solve:solveImageCaptcha'))

    def test_ordinary_http_403_does_not_repeat_browser_operations(self):
        signer = core.BrowserlessSigner('https://browserless.example', 'token')
        signer._request = Mock(return_value={'goto':{'status':403}, 'before':{'html':'Access denied'}})
        self.assertEqual(signer.sign(SITE, core.DEFAULT_RULES['p.t-baozi.cc']).status, 'failed')
        self.assertEqual(signer._request.call_count, 1)


if __name__ == '__main__':
    unittest.main()
