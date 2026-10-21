"""Sky HTTP/OCR and Piggo local-browser regression tests without live accounts."""
import base64
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
import requests

PATH=Path(__file__).parents[2]/'plugins.v3/captchasignin/core.py'
SPEC=importlib.util.spec_from_file_location('captcha_special_core',PATH)
core=importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name]=core
SPEC.loader.exec_module(core)


def response(text='', content=b'captcha'):
    return types.SimpleNamespace(text=text,content=content,status_code=200)


def challenge(code='hash-1', success=True):
    return response(json.dumps({'success':success,'code':code}))


class SkyTests(unittest.TestCase):
    def setUp(self):
        self.site={'id':1,'url':'https://www.hdsky.me','cookie':'uid=1','ua':'MP-test'}
        self.rule=core.resolve_rule(self.site,{})
        self.signer=core.HttpSigner(Mock(return_value='ABC123'))

    def sign(self, responses, rule=None):
        self.signer._request=Mock(side_effect=responses)
        return self.signer.sign(self.site,rule or self.rule)

    def test_same_session_image_bytes_and_explicit_showup_fields(self):
        result=self.sign([response('欢迎'),challenge(),response(content=b'exact-image'),response('{"success":true}')])
        self.assertEqual(result.status,'success')
        calls=self.signer._request.call_args_list
        self.assertEqual([c.args[1] for c in calls],['GET','POST','GET','POST'])
        self.assertEqual(calls[1].args[2],'https://www.hdsky.me/image_code_ajax.php')
        self.assertEqual(calls[1].kwargs['data'],{'action':'new'})
        self.assertEqual(calls[-1].args[2],'https://www.hdsky.me/showup.php')
        self.assertEqual(calls[-1].kwargs['data'],{'action':'showup','imagehash':'hash-1','imagestring':'ABC123'})
        self.assertTrue(all(c.args[0] is calls[0].args[0] for c in calls))
        self.signer.recognize.assert_called_once_with(base64.b64encode(b'exact-image').decode())
        self.assertNotIn('ABC123',result.message)

    def test_already_signed_needs_no_ocr(self):
        result=self.sign([response('已签到')])
        self.assertIn(result.status,{'success','already'})
        self.signer.recognize.assert_not_called()
        self.assertEqual(self.signer._request.call_count,1)

    def test_date_unmatch_means_already(self):
        result=self.sign([response('欢迎'),challenge(),response(),response('{"success":false,"message":"date_unmatch"}')])
        self.assertEqual(result.status,'already')

    def test_string_false_is_not_success(self):
        result=self.sign([response('欢迎'),challenge(success='false')])
        self.assertEqual(result.status,'failed')
        self.signer.recognize.assert_not_called()

    def test_short_ocr_refreshes_challenge_before_next_submit(self):
        self.signer.recognize.side_effect=['A','ABC123']
        result=self.sign([response('欢迎'),challenge('old'),response(),challenge('fresh'),response(),response('{"success":true}')])
        self.assertEqual(result.status,'success')
        self.assertEqual(self.signer._request.call_args.kwargs['data']['imagehash'],'fresh')
        self.assertEqual(sum(c.args[2].endswith('showup.php') for c in self.signer._request.call_args_list),1)

    def test_explicit_captcha_error_refreshes_challenge(self):
        result=self.sign([response('欢迎'),challenge('old'),response(),response('{"success":false,"message":"invalid_imagehash"}'),
                          challenge('fresh'),response(),response('{"success":true}')])
        self.assertEqual(result.status,'success')
        self.assertEqual(self.signer._request.call_args.kwargs['data']['imagehash'],'fresh')

    def test_failed_ocr_is_bounded(self):
        self.signer.recognize.return_value=''
        result=self.sign([response('欢迎')]+[item for _ in range(3) for item in [challenge(),response()]])
        self.assertEqual(result.status,'failed')
        self.assertEqual(self.signer.recognize.call_count,3)
        self.assertEqual(self.signer._request.call_count,7)

    def test_submit_timeout_checks_homepage_before_browserless(self):
        result=self.sign([response('欢迎'),challenge(),response(),requests.Timeout('secret-cookie'),response('已签到')])
        self.assertIn(result.status,{'success','already'})
        self.assertEqual(self.signer._request.call_args.args[1:3],('GET','https://www.hdsky.me/index.php'))
        self.assertNotIn('secret-cookie',result.message)

    def test_custom_success_still_requires_selected_words(self):
        rule=core.resolve_rule(self.site,{}, {'site_1_success_source':'custom','site_1_success_text':'已领取今日奖励'})
        for text,status in [('已签到','failed'),('已领取今日奖励','success')]:
            result=self.sign([response('欢迎'),challenge(),response(),response('{"success":true}'),response(text)],rule)
            self.assertEqual(result.status,status)

    def test_sky_failure_falls_back_to_selected_browserless(self):
        self.signer._request=Mock(return_value=response('没有首页'))
        browser=Mock()
        browser.sign.return_value=core.SignResult('success','browser verified')
        result=core.HybridSigner(self.signer,lambda:browser).sign(self.site,self.rule)
        self.assertEqual(result.status,'success')
        browser.sign.assert_called_once_with(self.site,self.rule)


class LocalBrowserTests(unittest.TestCase):
    def setUp(self):
        self.site={'id':2,'url':'https://piggo.me','cookie':'uid=2','ua':'Pig-UA','proxy':True}
        self.rule=core.resolve_rule(self.site,{})
        self.rule.update(challenge_wait=2,wait=1000)
        self.page=Mock(url='https://piggo.me/index.php',frames=[])
        self.page.evaluate.return_value=True
        self.proxy={'https':'http://local-proxy:8080'}
        self.action=Mock(side_effect=lambda **kw:kw['callback'](self.page))
        self.signer=core.LocalBrowserSigner(action=self.action,proxies=self.proxy)

    def test_piggo_preset_and_proxy_are_local(self):
        self.assertEqual(self.rule['mode'],'local_browser')
        self.page.content.side_effect=['欢迎回来','签到成功']
        result=self.signer.sign(self.site,self.rule)
        self.assertEqual(result.status,'success')
        self.page.click.assert_called_once()
        self.assertEqual(self.action.call_args.kwargs['url'],'about:blank')
        self.assertEqual(self.action.call_args.kwargs['cookies'],'uid=2')
        self.assertEqual(self.action.call_args.kwargs['ua'],'Pig-UA')
        self.assertEqual(self.action.call_args.kwargs['proxies'],self.proxy)
        self.page.goto.assert_called_once_with('https://piggo.me/index.php',wait_until='domcontentloaded',timeout=30000)

    def test_already_signed_does_not_click(self):
        self.page.content.return_value='今日已签到'
        self.assertIn(self.signer.sign(self.site,self.rule).status,{'success','already'})
        self.page.click.assert_not_called()

    def test_challenges_before_and_after_click_must_clear(self):
        self.page.content.side_effect=['正在进行安全检测','欢迎','正在验证您是否是真人','签到成功']
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'success')
        self.assertEqual(self.page.click.call_count,1)
        self.assertEqual(self.page.wait_for_timeout.call_count,3)

    def test_persistent_challenge_never_clicks_signin(self):
        self.page.content.return_value='正在进行安全检测'
        result=self.signer.sign(self.site,self.rule)
        self.assertEqual(result.status,'failed')
        self.page.click.assert_not_called()
        self.assertEqual(self.page.content.call_count,2)

    def test_location_confirmation_is_not_automatically_accepted(self):
        self.page.content.return_value='异地登录，请确认登录位置'
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'failed')
        self.page.click.assert_not_called()
        self.page.wait_for_timeout.assert_not_called()

    def test_cookie_invalid_is_failure(self):
        self.page.content.return_value='用户登录'
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'failed')
        self.page.click.assert_not_called()

    def test_button_disappearing_without_result_is_not_success(self):
        self.page.content.side_effect=['欢迎','欢迎，按钮不见了']
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'failed')

    def test_click_timeout_still_checks_final_page(self):
        self.page.content.side_effect=['欢迎','签到成功']
        self.page.click.side_effect=RuntimeError('navigation timeout')
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'success')

    def test_missing_button_does_not_claim_success(self):
        self.page.content.return_value='欢迎'
        self.page.evaluate.return_value=None
        self.assertEqual(self.signer.sign(self.site,self.rule).status,'failed')
        self.page.click.assert_not_called()

    def test_browser_failure_is_sanitized(self):
        self.action.side_effect=RuntimeError('uid=private-cookie')
        result=self.signer.sign(self.site,self.rule)
        self.assertEqual(result.status,'failed')
        self.assertNotIn('private-cookie',result.message)

    def test_missing_mp_browser_reports_failure_without_cloud_fallback(self):
        with patch.dict(sys.modules,{'app.helper.browser':None}):
            result=core.LocalBrowserSigner().sign(self.site,self.rule)
        self.assertEqual(result.status,'failed')
        self.assertIn('接口不可用',result.message)

    def test_local_mode_never_constructs_browserless_even_when_failed(self):
        direct,factory,local=Mock(),Mock(),Mock()
        local.sign.return_value=core.SignResult('failed','not solved')
        result=core.HybridSigner(direct,factory,local).sign(self.site,self.rule)
        self.assertEqual(result.status,'failed')
        direct.sign.assert_not_called()
        factory.assert_not_called()

    def test_proxy_is_not_used_when_site_disabled_it(self):
        self.page.content.return_value='今日已签到'
        self.signer.sign(dict(self.site,proxy=False),self.rule)
        self.assertIsNone(self.action.call_args.kwargs['proxies'])


class BrowserResultTests(unittest.TestCase):
    def test_explicit_success_wins_over_solver_failure(self):
        signer=core.BrowserlessSigner('https://browserless.example','token')
        signer._request=Mock(side_effect=[{'goto':{'status':200},'before':{'html':'欢迎'}},
             {'goto':{'status':200},'solve':{'found':True,'solved':False},'after':{'html':'签到成功'}}])
        result=signer.sign({'url':'https://hdsky.me','cookie':'uid=1'},core.DEFAULT_RULES['hdsky.me'])
        self.assertEqual(result.status,'success')

    def test_final_success_wins_over_initial_challenge_status(self):
        signer=core.BrowserlessSigner('https://browserless.example','token')
        signer._request=Mock(side_effect=[{'goto':{'status':403},'before':{'html':'Just a moment'}},
             {'goto':{'status':403},'solve':{'found':True,'solved':False},'after':{'html':'签到成功'}}])
        result=signer.sign({'url':'https://hdsky.me','cookie':'uid=1'},core.DEFAULT_RULES['hdsky.me'])
        self.assertEqual(result.status,'success')

    def test_opencd_still_requires_homepage_when_solver_failed(self):
        signer=core.BrowserlessSigner('https://browserless.example','token')
        signer._request=Mock(side_effect=[{'goto':{'status':200},'before':{'html':'欢迎'}},
             {'goto':{'status':200},'solve':{'found':True,'solved':False},'after':{'html':'签到成功'},
              'verify':{'status':200},'verifyPage':{'html':'没有签到记录'}}])
        result=signer.sign({'url':'https://open.cd','cookie':'uid=1'},core.DEFAULT_RULES['open.cd'])
        self.assertEqual(result.status,'failed')


if __name__=='__main__':
    unittest.main()
