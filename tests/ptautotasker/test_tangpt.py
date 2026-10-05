"""Offline TangPT game tests for both plugin versions."""
import importlib
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class TangPTTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import lxml
        except ImportError:
            cls.stub = types.ModuleType('lxml')
            cls.stub.etree = Mock()
            sys.modules['lxml'] = cls.stub

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, 'stub'):
            sys.modules.pop('lxml', None)

    def sites(self):
        for version in ('v2', 'v3'):
            name = 'tang_test_' + version
            package = types.ModuleType(name)
            package.__path__ = [str(Path(__file__).parents[2] / ('plugins.' + version) / 'ptautotasker')]
            sys.modules[name] = package
            yield importlib.import_module(name + '.sites.Tangpt')

    def test_lottery_batching_and_prizes(self):
        for site in self.sites():
            for remain, batches in [(1200, [100]*10), (250, [100,100,50]), (0, [])]:
                with self.subTest(site=site.__name__, remain=remain):
                    tasks = site.Tasks('cookie')
                    with patch.object(tasks.client, 'lottery_remain', return_value=remain), patch.object(tasks.client, 'draw_lottery', return_value={'ok': True, 'results': ['电影票', {'prize_name': '电影票', 'count': '2'}, {'title': '魔力'}, {}]}) as draw, patch.object(site.time, 'sleep') as sleep:
                        result = tasks.daily_lottery()
                    self.assertTrue(result.success)
                    self.assertEqual([call.args[0] for call in draw.call_args_list], batches)
                    self.assertEqual(result.data['count'], sum(batches))
                    self.assertEqual(result.data['prizes'].get('电影票', 0), len(batches)*3)
                    self.assertEqual(sleep.call_count, max(0,len(batches)-1))

    def test_failure_stops_and_preserves_progress(self):
        for site in self.sites():
            for failure in [{'ok': False, 'message': '次数不足'}, ValueError('network')]:
                tasks = site.Tasks('cookie')
                with patch.object(tasks.client, 'lottery_remain', return_value=1000), patch.object(tasks.client, 'draw_lottery', side_effect=[{'ok':True},failure]) as draw, patch.object(site.time, 'sleep'):
                    result = tasks.daily_lottery()
                self.assertFalse(result.success)
                self.assertEqual(result.data['count'],100)
                self.assertEqual(draw.call_count,2)
                with patch.object(tasks.client, 'slot_token', return_value='first'), patch.object(tasks.client, 'draw_slot', side_effect=[{'ok':True,'payout':4,'spin_token':'next'},failure]) as draw, patch.object(site.time,'sleep'):
                    result = tasks.daily_slots()
                self.assertFalse(result.success)
                self.assertEqual(result.data['count'],1)
                self.assertEqual(result.data['payout'],4)
                self.assertEqual(draw.call_count,2)

    def test_token_rotation_and_fallback(self):
        for site in self.sites():
            for next_token in ['returned', None]:
                tasks = site.Tasks('cookie')
                with patch.object(tasks.client,'slot_token',side_effect=['initial','refreshed']) as token, patch.object(tasks.client,'draw_slot',return_value={'ok':True,'spin_token':next_token,'payout':'3','is_free_spin':True,'reels':[{'name':'苹果'}]}) as draw, patch.object(site.time,'sleep') as sleep:
                    result=tasks.daily_slots()
                self.assertTrue(result.success)
                self.assertEqual([c.args[0] for c in draw.call_args_list],['initial',next_token or 'refreshed'])
                self.assertEqual(token.call_count,1 if next_token else 2)
                self.assertEqual(sleep.call_count,1)
                self.assertEqual(result.data['payout'],6)
                self.assertEqual(result.data['count'],2)

    def test_page_parsing_and_request_parameters(self):
        for site in self.sites():
            client=site.Tangpt('session=test')
            state={'nested':{'text':'brace } escaped "'},'user_state':{'spin_token':'state-token'}}
            for html, expected in [('window.__slotInitialState = '+json.dumps(state)+';', 'state-token'), ('<input value="input-token" name="spin_token">','input-token'), ("spin_token = 'js-token';",'js-token')]:
                with patch.object(client,'_game_page',return_value=html):
                    self.assertEqual(client.slot_token(),expected)
            with patch.object(client,'_game_page',return_value='今天还可以抽 250 次'):
                self.assertEqual(client.lottery_remain(),250)
            for method, args, path, data, page in [(client.draw_lottery,(100,),'/web/omnibot/lottery/draw',{'count':'100'},'/omnibot_lottery.php'),(client.draw_slot,('token',),'/web/omnibot/slot-machine/draw',{'multiplier':'1','spin_token':'token'},'/omnibot_slot.php')]:
                response=Mock();response.json.return_value={'ok':True}
                with patch.object(site.CustomRequests,'post',return_value=response) as post:
                    method(*args)
                self.assertEqual(post.call_args.args,(client.url+path,))
                self.assertEqual(post.call_args.kwargs['data'],data)
                self.assertEqual(post.call_args.kwargs['headers']['referer'],client.url+page)
                self.assertEqual(post.call_args.kwargs['headers']['X-Requested-With'],'XMLHttpRequest')
                self.assertEqual(post.call_args.kwargs['headers']['cookie'],'session=test')
                response.raise_for_status.assert_called_once()

    def test_invalid_pages_responses_and_cookie(self):
        for site in self.sites():
            tasks=site.Tasks('cookie')
            with patch.object(tasks.client,'_game_page',return_value='<html>login</html>'), patch.object(site.CustomRequests,'post') as post:
                self.assertFalse(tasks.daily_lottery().success)
                self.assertFalse(tasks.daily_slots().success)
                post.assert_not_called()
            for payload in [[],{}, {'ok':'false'}]:
                response=Mock();response.json.return_value=payload
                with patch.object(tasks.client,'lottery_remain',return_value=1000), patch.object(site.CustomRequests,'post',return_value=response) as post:
                    self.assertFalse(tasks.daily_lottery().success)
                    self.assertEqual(post.call_count,1)
            for method in [site.Tasks(None).daily_lottery,site.Tasks(None).daily_slots]:
                with patch.object(site.CustomRequests,'get') as get:
                    self.assertFalse(method().success)
                    get.assert_not_called()
            self.assertEqual({t['id'] for t in tasks.get_registered_tasks()}, {'tangpt_daily_claim_task','tangpt_daily_lottery','tangpt_daily_slots'})


if __name__ == '__main__':
    unittest.main()
