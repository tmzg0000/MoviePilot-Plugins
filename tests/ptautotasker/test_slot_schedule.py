"""Exercise plugin scheduling with persisted completion state, without MoviePilot."""
import ast
import inspect
import typing
import unittest
from datetime import datetime as RealDatetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo


class TaskResult:
    def __init__(self, success, count):
        self.success = success
        self.data = {'count': count}
        self.message = '完成' if success else '失败'


class Clock:
    value = RealDatetime(2026, 10, 5, 0, 8)

    @classmethod
    def now(cls, tz):
        return cls.value.replace(tzinfo=tz)


class ScheduleTests(unittest.TestCase):
    def test_success_skip_failure_retry_next_day_and_restart(self):
        for version in ('v2', 'v3'):
            with self.subTest(version=version):
                tree = ast.parse((Path(__file__).parents[2] / f'plugins.{version}/ptautotasker/__init__.py').read_text())
                cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'PTAutoTasker')
                fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__do_tasks')
                ns = {'datetime':Clock, 'pytz':SimpleNamespace(timezone=ZoneInfo), 'settings':SimpleNamespace(TZ='Asia/Shanghai'), 'inspect':inspect, 'TaskResult':TaskResult, 'logger':Mock(), 'Dict':typing.Dict, 'List':typing.List, 'Optional':typing.Optional}
                exec(compile(ast.Module(body=[fn], type_ignores=[]), '<schedule>', 'exec'), ns)
                execute = ns['__do_tasks']
                stored = {}
                calls = []
                results = []
                class Tasks:
                    def __init__(self, cookie=None):
                        pass
                    def daily_slots(self):
                        calls.append('slot')
                        return results.pop(0)
                    def daily_other(self):
                        calls.append('other')
                        return TaskResult(True, 0)
                task = {'id':'tangpt_daily_slots', 'label':'老虎机', 'func':Tasks().daily_slots}
                other = {'id':'other', 'label':'其他任务', 'func':Tasks().daily_other}
                def instance():
                    return SimpleNamespace(tangpt_daily_slots=True, other=True, _retry_count=0, _notify=False, get_filter_sites=lambda:[{'name':'躺平','domain':'tangpt.top','cookie':'test','tasks':[task,other]}], get_data=lambda key:stored.get(key), save_data=lambda key,value:stored.update({key:value}), _save_history_run=Mock())
                obj = instance()
                Clock.value = RealDatetime(2026,10,5,0,8)
                results.append(TaskResult(False,1)); execute(obj)
                self.assertNotIn('tangpt_slots_completed',stored)
                Clock.value = RealDatetime(2026,10,5,9,8)
                results.append(TaskResult(True,2)); execute(obj)
                self.assertEqual(stored['tangpt_slots_completed']['date'],'2026-10-05')
                Clock.value = RealDatetime(2026,10,5,21,8)
                restarted = instance(); execute(restarted)
                self.assertEqual(calls.count('slot'),2)
                self.assertEqual(calls.count('other'),3)
                records = restarted._save_history_run.call_args.args[0]
                self.assertTrue(records[0]['skipped'])
                self.assertTrue(records[0]['success'])
                Clock.value = RealDatetime(2026,10,6,0,8)
                results.append(TaskResult(True,2)); execute(restarted)
                self.assertEqual(calls.count('slot'),3)
                self.assertEqual(stored['tangpt_slots_completed']['date'],'2026-10-06')
                # A partial-success result must not mark two spins as completed.
                Clock.value = RealDatetime(2026,10,7,0,8)
                results.append(TaskResult(True,1)); execute(restarted)
                self.assertEqual(stored['tangpt_slots_completed']['date'],'2026-10-06')


if __name__ == '__main__':
    unittest.main()
