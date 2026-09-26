from ..base.NexusPHP import NexusPHP
from lxml import etree
from ..base.Decorator import task_info
from ..base.BaseTask import BaseTask


class Car(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)

    @staticmethod
    def get_site_name():
        return "CARPT"

    @staticmethod
    def get_url():
        return "https://carpt.net"

    @staticmethod
    def get_site_domain():
        return "carpt.net"

    def send_messagebox(self, message: str, callback=None) -> str:
        return super().send_messagebox(message)

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Car(cookie))

    @task_info(label="Car 任务领取", hint="领取Car站点的天天快乐任务")
    def daily_claim_task(self):
        task_id = '5'
        rsp = self.client.claim_task(task_id)
        if rsp == "认领人数已达上限":
            return self.fail(rsp)
        return self.ok(message=rsp)

    def daily_checkin(self):
        return self.client.attendance()
