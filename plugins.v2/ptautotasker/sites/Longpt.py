from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Longpt(NexusPHP):
    @staticmethod
    def get_site_name():
        return "LongPT"

    @staticmethod
    def get_url():
        return "https://longpt.org"

    @staticmethod
    def get_site_domain():
        return "longpt.org"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Longpt(cookie))

    @task_info(label="Longpt每月保种领取(难)", hint="领取 Longpt 的每月保种任务（难）")
    def monthly_claim_task(self):
        return self.client.claim_task("2")

    def daily_checkin(self):
        return self.client.attendance()
