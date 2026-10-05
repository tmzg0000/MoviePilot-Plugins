from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Ptskit(NexusPHP):
    @staticmethod
    def get_site_name():
        return "Ptskit"

    @staticmethod
    def get_url():
        return "https://pt.ptskit.org"

    @staticmethod
    def get_site_domain():
        return "ptskit.org"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Ptskit(cookie))

    @task_info(label="Ptskit任务领取", hint="领取 Ptskit 站点的魔力值任务2")
    def daily_claim_task(self):
        return self.client.claim_task("12")
