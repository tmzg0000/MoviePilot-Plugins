from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Tangpt(NexusPHP):
    @staticmethod
    def get_site_name():
        return "躺平"

    @staticmethod
    def get_url():
        return "https://www.tangpt.top"

    @staticmethod
    def get_site_domain():
        return "tangpt.top"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Tangpt(cookie))

    @task_info(label="躺平任务领取", hint="领取躺平站点的BUG/VIP任务")
    def daily_claim_task(self):
        return "\n".join((self.client.claim_task("3"), self.client.claim_task("4")))

    def daily_checkin(self):
        return self.client.attendance()
