"""LuckPT medal checks use sanitized fixtures; no real reward is claimed."""
import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def page(claim):
    return '<section id="ccat-1"><span>已领取</span></section><section id="ccat-8"><div class="category-row"><h2>工具支持纪念套装</h2><div class="progress-text">7 / 7 · 100%</div><div class="row-reward"><div class="reward-inline-text">每日幸运星 +1000'+('（已领取）' if claim=='已领取' else '')+'</div><div class="claim-bar">'+claim+'</div></div></div><div class="category-body"><button class="buy-action">购买</button></div></section>'


CLAIMED = page('已领取')
AVAILABLE = page('<button class="claim-reward" data-category="8" data-type="daily">领取</button>')


class LuckPTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import lxml
        except ImportError:
            cls.stub = types.ModuleType('lxml'); cls.stub.etree = Mock(); sys.modules['lxml']=cls.stub

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls,'stub'):sys.modules.pop('lxml',None)

    def sites(self):
        for version in ('v2','v3'):
            name='luck_test_'+version; package=types.ModuleType(name)
            package.__path__=[str(Path(__file__).parents[2]/f'plugins.{version}/ptautotasker')]
            sys.modules[name]=package
            yield importlib.import_module(name+'.sites.Luckpt')

    def test_claimed_skip_and_registration(self):
        for site in self.sites():
            response=Mock(text=CLAIMED)
            tasks=site.Tasks('test')
            with patch.object(site.CustomRequests,'get',return_value=response),patch.object(site.CustomRequests,'post') as post:
                result=tasks.medal_bonus()
            self.assertTrue(result.success);self.assertIn('跳过',result.message);post.assert_not_called()
            self.assertEqual([t['id'] for t in tasks.get_registered_tasks()],['luckpt_medal_bonus'])

    def test_claim_parameters_and_verification(self):
        for site in self.sites():
            response=Mock();response.json.return_value={'ret':0}
            with patch.object(site.CustomRequests,'get',side_effect=[Mock(text=AVAILABLE),Mock(text=CLAIMED)]) as get,patch.object(site.CustomRequests,'post',return_value=response) as post:
                result=site.Tasks('test').medal_bonus()
            self.assertTrue(result.success);self.assertEqual(get.call_count,2)
            self.assertEqual(post.call_args.args,('https://pt.luckpt.de/ajax.php',))
            self.assertEqual(post.call_args.kwargs['data'],{'action':'claimMedalCategoryReward','params[category_id]':'8','params[reward_type]':'daily'})
            self.assertEqual(post.call_args.kwargs['headers']['cookie'],'test')
            response.raise_for_status.assert_called_once()

    def test_invalid_pages_never_submit(self):
        for site in self.sites():
            for html in ['login',page('未集齐'),AVAILABLE.replace('data-category="8"','data-category="9"'),AVAILABLE.replace('data-type="daily"',''),AVAILABLE.replace('class="claim-reward"','class="claim-reward" disabled')]:
                with self.subTest(site=site.__name__,html=html):
                    with patch.object(site.CustomRequests,'get',return_value=Mock(text=html)),patch.object(site.CustomRequests,'post') as post:
                        self.assertFalse(site.Tasks('test').medal_bonus().success)
                        post.assert_not_called()
            with patch.object(site.CustomRequests,'get') as get:
                self.assertFalse(site.Tasks(None).medal_bonus().success);get.assert_not_called()

    def test_failed_or_unverified_claim(self):
        for site in self.sites():
            for payload in [{'ret':1,'msg':'拒绝'}, {}, [], {'ret':False}, {'ret':0}]:
                response=Mock();response.json.return_value=payload
                with patch.object(site.CustomRequests,'get',return_value=Mock(text=AVAILABLE)),patch.object(site.CustomRequests,'post',return_value=response) as post:
                    self.assertFalse(site.Tasks('test').medal_bonus().success)
                    self.assertEqual(post.call_count,1)
            with patch.object(site.CustomRequests,'get',return_value=Mock(text=AVAILABLE)),patch.object(site.CustomRequests,'post',side_effect=RuntimeError('timeout')) as post:
                self.assertFalse(site.Tasks('test').medal_bonus().success);self.assertEqual(post.call_count,1)


if __name__=='__main__':unittest.main()
