from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class FreeFarm(NexusPHP):
    @staticmethod
    def get_site_name():
        return "自由农场"

    @staticmethod
    def get_url():
        return "https://pt.0ff.cc"

    @staticmethod
    def get_site_domain():
        return "0ff.cc"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(FreeFarm(cookie))

    @task_info(label="自由农场每周任务领取", hint="领取自由农场站点的每周做种任务")
    def weekly_claim_task(self):
        return self.client.claim_task("12")

    def daily_checkin(self):
        return self.client.attendance()
