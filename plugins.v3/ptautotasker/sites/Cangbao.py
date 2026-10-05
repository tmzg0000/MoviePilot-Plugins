from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Cangbao(NexusPHP):
    @staticmethod
    def get_site_name():
        return "藏宝阁"

    @staticmethod
    def get_url():
        return "https://cangbao.ge"

    @staticmethod
    def get_site_domain():
        return "cangbao.ge"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Cangbao(cookie))

    @task_info(label="藏宝阁任务领取", hint="领取藏宝阁站点的做种传奇任务")
    def daily_claim_task(self):
        return self.client.claim_task("12")
