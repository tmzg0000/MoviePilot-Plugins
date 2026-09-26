from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP
from ..utils.custom_requests import CustomRequests
from lxml import etree
from ..base.BaseTask import BaseTask


class LemonHD(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)
        self.lottery_url = self.url + "/lottery.php"

    @staticmethod
    def get_url():
        return "https://lemonhd.club"

    @staticmethod
    def get_site_name():
        return "柠檬"

    @staticmethod
    def get_site_domain():
        return "lemonhd.club"

    def lottery(self, parameter: tuple = None, rt_method: callable = None):
        response = CustomRequests.post(self.lottery_url, headers=self.headers, data="type=0")
        return ''.join(etree.HTML(response.text).xpath("//table/tr[1]/td[1]/text()")).strip()


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(LemonHD(cookie))

    def daily_checkin(self):
        return self.client.attendance(
            lambda response: "".join(etree.HTML(response.text).xpath('//table//tr/td/text()')).strip())

    @task_info(label="每日神游", hint="执行{client_name}站点的每日免费神游")
    def daily_lottery(self):
        return self.client.lottery()
