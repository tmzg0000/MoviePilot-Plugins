from __future__ import annotations

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

from app.main import ScheduleManager, cron_matches, validate_cron_expression, validate_schedule_config


class CronExpressionTests(unittest.TestCase):
    def test_daily_expression_matches_only_configured_minute(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertTrue(cron_matches("15 11  * * *", datetime(2026, 8, 6, 11, 15, tzinfo=timezone)))
        self.assertFalse(cron_matches("15 11 * * *", datetime(2026, 8, 6, 11, 14, tzinfo=timezone)))

    def test_common_ranges_lists_and_steps_are_supported(self) -> None:
        timezone = ZoneInfo("Asia/Shanghai")
        self.assertTrue(cron_matches("*/5 11 * * 1-5", datetime(2026, 8, 6, 11, 20, tzinfo=timezone)))
        self.assertTrue(cron_matches("0 4 1,15 * *", datetime(2026, 8, 15, 4, 0, tzinfo=timezone)))

    def test_invalid_expression_is_rejected_instead_of_silently_clamped(self) -> None:
        with self.assertRaisesRegex(ValueError, "取值超出"):
            validate_cron_expression("99 11 * * *")
        with self.assertRaisesRegex(ValueError, "5 位"):
            validate_schedule_config({"cron": "15 11 * *"})


class ScheduleManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_due_generation_runs_once_per_minute(self) -> None:
        manager = ScheduleManager()
        config = {
            "enabled": True,
            "cron": "15 11 * * *",
            "backup_cron": "",
            "style_config": {"style": "animated_2"},
        }
        scheduled_at = datetime(2026, 8, 6, 11, 15, tzinfo=ZoneInfo("Asia/Shanghai"))
        start = AsyncMock(return_value={})
        with patch("app.main.load_config", return_value=config), patch("app.main.generation_manager.start", start):
            first = await manager.tick(scheduled_at)
            second = await manager.tick(scheduled_at)

        self.assertEqual(first["actions"], ["generation"])
        self.assertEqual(second["actions"], [])
        start.assert_awaited_once_with("animated_2", trigger="schedule")
        self.assertEqual(manager.last_generation, scheduled_at.isoformat())

    async def test_disabled_generation_does_not_run(self) -> None:
        manager = ScheduleManager()
        config = {
            "enabled": False,
            "cron": "15 11 * * *",
            "backup_cron": "",
            "style_config": {"style": "animated_2"},
        }
        start = AsyncMock(return_value={})
        with patch("app.main.load_config", return_value=config), patch("app.main.generation_manager.start", start):
            result = await manager.tick(datetime(2026, 8, 6, 11, 15, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual(result["actions"], [])
        start.assert_not_awaited()

    async def test_due_backup_runs_once_per_minute(self) -> None:
        manager = ScheduleManager()
        config = {
            "enabled": True,
            "cron": "",
            "backup_cron": "30 4 * * *",
            "backup_path": "backups",
            "style_config": {"style": "static_1"},
        }
        scheduled_at = datetime(2026, 8, 6, 4, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
        with patch("app.main.load_config", return_value=config), patch(
            "app.main.create_config_backup",
            return_value=Path("/app/data/backups/config.json"),
        ) as backup:
            first = await manager.tick(scheduled_at)
            second = await manager.tick(scheduled_at)

        self.assertEqual(first["actions"], ["backup"])
        self.assertEqual(second["actions"], [])
        backup.assert_called_once_with(config, "backups")
        self.assertEqual(manager.last_backup, "/app/data/backups/config.json")

    async def test_invalid_cron_is_visible_in_scheduler_status(self) -> None:
        manager = ScheduleManager()
        config = {
            "enabled": True,
            "cron": "99 11 * * *",
            "backup_cron": "",
            "style_config": {"style": "animated_2"},
        }
        start = AsyncMock(return_value={})
        with patch("app.main.load_config", return_value=config), patch("app.main.generation_manager.start", start):
            result = await manager.tick(datetime(2026, 8, 6, 11, 15, tzinfo=ZoneInfo("Asia/Shanghai")))

        self.assertEqual(result["actions"], [])
        self.assertIn("定时生成 cron 无效", result["last_error"])
        start.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
