from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class NovaHD(NexusPHP):
    @staticmethod
    def get_site_name():
        return "NovaHD"

    @staticmethod
    def get_url():
        return "https://pt.novahd.top"

    @staticmethod
    def get_site_domain():
        return "novahd.top"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(NovaHD(cookie))

    @task_info(label="NovaHD每月任务领取", hint="领取NovaHD站点的保种任务")
    def daily_claim_task(self):
        return self.client.claim_task("3")
