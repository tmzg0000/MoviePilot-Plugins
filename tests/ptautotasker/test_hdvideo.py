"""Offline checks: never purchase tickets on the real site."""
import importlib
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import unittest


def load_site(version):
    name = 'scratch_test_' + version
    package = types.ModuleType(name)
    package.__path__ = [str(Path(__file__).parents[2] / ('plugins.' + version) / 'ptautotasker')]
    sys.modules[name] = package
    return importlib.import_module(name + '.sites.HDVideo')


def test_purchase_headers_and_registration(site):
    response = Mock()
    response.json.return_value = {'ok': True}
    tasks = site.Tasks('session=test')
    with patch.object(site.CustomRequests, 'post', return_value=response) as post:
        assert tasks.client.buy_scratch() == {'ok': True}
    assert post.call_args.args == ('https://hdvideo.top/games/scratch/',)
    assert post.call_args.kwargs['data'] == {'action': 'buy'}
    assert post.call_args.kwargs['headers']['cookie'] == 'session=test'
    assert post.call_args.kwargs['headers']['referer'].endswith('/games/scratch/')
    response.raise_for_status.assert_called_once()
    assert [t['id'] for t in tasks.get_registered_tasks()] == ['hdvideo_daily_scratch']


def test_full_run_and_cooldown(site):
    tasks = site.Tasks('session=test')
    with patch.object(tasks.client, 'buy_scratch', return_value={'ok': True, 'delta': -2, 'balance': 200, 'name': '奖'}) as buy, patch.object(site.time, 'sleep') as sleep:
        result = tasks.daily_scratch()
    assert result.success
    assert result.data['count'] == 100
    assert result.data['delta'] == -200
    assert result.data['balance'] == 200
    assert buy.call_count == 100
    assert sleep.call_count == 99
    assert all(c.args == (2.1,) for c in sleep.call_args_list)


def test_stop_preserves_partial_results(site, failure):
    tasks = site.Tasks('session=test')
    with patch.object(tasks.client, 'buy_scratch', side_effect=[{'ok': True, 'delta': 5, 'balance': 10}, failure]) as buy, patch.object(site.time, 'sleep'):
        result = tasks.daily_scratch()
    assert not result.success
    assert result.data == {'count': 1, 'delta': 5, 'balance': 10, 'last_prize': None}
    assert buy.call_count == 2
    assert ('电影票不足' if isinstance(failure, dict) else 'timeout') in result.message


def test_invalid_response(site, payload):
    response = Mock()
    response.json.return_value = payload
    with patch.object(site.CustomRequests, 'post', return_value=response):
        result = site.Tasks('session=test').daily_scratch()
    assert not result.success
    assert result.data['count'] == 0


def test_http_json_and_missing_cookie(site):
    for failure_at in ['raise_for_status', 'json']:
        response = Mock()
        getattr(response, failure_at).side_effect = ValueError('invalid response')
        with patch.object(site.CustomRequests, 'post', return_value=response) as post:
            result = site.Tasks('session=test').daily_scratch()
        assert not result.success
        assert post.call_count == 1
    with patch.object(site.CustomRequests, 'post') as post:
        assert not site.Tasks(None).daily_scratch().success
        post.assert_not_called()

class HDVideoTests(unittest.TestCase):
    def test_both_versions(self):
        # HTML parsing is not used by this adapter. Allow tests on minimal hosts.
        try:
            import lxml
        except ImportError:
            stub = types.ModuleType('lxml')
            stub.etree = Mock()
            sys.modules['lxml'] = stub
        try:
            for version in ('v2', 'v3'):
                site = load_site(version)
                for check in [test_purchase_headers_and_registration, test_full_run_and_cooldown, test_http_json_and_missing_cookie]:
                    with self.subTest(version=version, check=check.__name__):
                        check(site)
                for failure in [{'ok': False, 'error': '电影票不足'}, RuntimeError('timeout')]:
                    with self.subTest(version=version, failure=failure):
                        test_stop_preserves_partial_results(site, failure)
                for payload in [[], {}, {'ok': 'false'}]:
                    with self.subTest(version=version, payload=payload):
                        test_invalid_response(site, payload)
        finally:
            if 'stub' in locals():
                sys.modules.pop('lxml', None)


if __name__ == '__main__':
    unittest.main()
