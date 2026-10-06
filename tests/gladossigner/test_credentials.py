"""Credential parsing tests without MoviePilot runtime dependencies."""
import ast
import json
import logging
from pathlib import Path
import shlex
import unittest
from urllib.parse import urlsplit


class CredentialTests(unittest.TestCase):
    def test_both_versions(self):
        root = Path(__file__).resolve().parents[2]
        for version in (2, 3):
            with self.subTest(version=version):
                tree = ast.parse((root / f'plugins.v{version}/gladossigner/__init__.py').read_text())
                plugin = next(n for n in tree.body if isinstance(n, ast.ClassDef))
                methods = [n for n in plugin.body if isinstance(n, ast.FunctionDef)
                           and n.name in ('_parse_curl_bundle', '_parse_auth_bundle')]
                isolated = ast.Module(body=[ast.ClassDef(name='gladossigner', bases=[],
                                      keywords=[], body=methods, decorator_list=[])], type_ignores=[])
                namespace = dict(shlex=shlex, urlsplit=urlsplit, json=json,
                                 Any=object, Dict=dict, logger=logging.getLogger(__name__))
                exec(compile(ast.fix_missing_locations(isolated), '<parser>', 'exec'), namespace)
                parse = namespace['gladossigner']._parse_auth_bundle
                command = """curl 'https://glados.cloud/api/user/checkin' \
  -H 'Authorization: fingerprint-1080-1920' \
  -H 'User-Agent: Mozilla/5.0 Windows' \
  -b 'koa:sess=test%2Bvalue; koa:sess.sig=signature' \
  --data-raw '{"token":"glados.cloud"}'"""
                expected = dict(cookie='koa:sess=test%2Bvalue; koa:sess.sig=signature',
                                device='fingerprint-1080-1920', domain='glados.cloud',
                                ua='Mozilla/5.0 Windows')
                self.assertEqual(parse(command), expected)
                self.assertEqual(parse("curl --url=https://glados.cloud/api/user/status "
                                       "--header='cookie: a=b; c=d' --header='authorization: fp'"),
                                 dict(cookie='a=b; c=d', device='fp', domain='glados.cloud', ua=''))
                for invalid in ("curl 'unterminated", "curl https://glados.cloud -b a=b",
                                "curl https://glados.cloud -H 'Authorization: fp' -b /tmp/cookies",
                                "curl -H 'Cookie: a=b' -H 'Authorization: fp'", "curl -H"):
                    self.assertEqual(parse(invalid), {})
                self.assertEqual(parse(json.dumps(expected)), dict(expected, screen='', at=''))
                self.assertEqual(parse('Cookie: a=b\nAuthorization: fp'), dict(cookie='a=b', device='fp'))
                self.assertEqual(parse('a=b; c=d'), dict(cookie='a=b; c=d', device=''))


if __name__ == '__main__':
    unittest.main()
