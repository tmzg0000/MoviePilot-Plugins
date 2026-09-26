from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class City13(NexusPHP):
    @staticmethod
    def get_site_name():
        return "13City"

    @staticmethod
    def get_url():
        return "https://13city.org"

    @staticmethod
    def get_site_domain():
        return "13city.org"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(City13(cookie))

    @task_info(label="13City 每日做种任务", hint="领取 13city 的每日做种任务")
    def daily_claim_task(self):
        return self.client.claim_task("2")

    @task_info(label="13City 每月做种任务", hint="领取 13city 的每月做种任务")
    def monthly_claim_task(self):
        return self.client.claim_task("6")

    def daily_checkin(self):
        return self.client.attendance()
