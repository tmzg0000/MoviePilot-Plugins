from ..base.NexusPHP import NexusPHP
from ..base.Decorator import task_info
from ..base.BaseTask import BaseTask
from ..utils.custom_requests import CustomRequests
class Qingwa(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)
        self.bonusshop_url = self.url + "/api/bonus-shop/exchange"

    @staticmethod
    def get_site_name():
        return "青蛙"

    @staticmethod
    def get_url():
        return "https://www.qingwapt.com"

    @staticmethod
    def get_site_domain():
        return "qingwapt.com"



    def do_exchange(self,id,amount):
        response = CustomRequests.post(self.bonusshop_url, headers=self.headers, data={"id": id, "amount": amount})
        return response.json().get("msg", "兑换请求失败")


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Qingwa(cookie))  # 传递 Qingwa 实例



    @task_info(label="每日1k蝌蚪", hint="购买青蛙商店的每日福利：1000蝌蚪")
    def daily_exchange(self):
        return self.client.do_exchange(28,1)
