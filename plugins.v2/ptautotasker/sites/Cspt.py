from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Cspt(NexusPHP):
    @staticmethod
    def get_site_name():
        return "财神"

    @staticmethod
    def get_url():
        return "https://cspt.top"

    @staticmethod
    def get_site_domain():
        return "cspt.top"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Cspt(cookie))

    @task_info(label="财神任务领取", hint="领取财神站点的西财神任务")
    def daily_claim_task(self):
        return self.client.claim_task("5")
