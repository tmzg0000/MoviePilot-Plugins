from ..base.NexusPHP import NexusPHP
from lxml import etree
from ..base.BaseTask import BaseTask


class Lgs(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)

    @staticmethod
    def get_url():
        return "https://ptlgs.org"


    @staticmethod
    def get_site_name():
        return "PTLGS"

    @staticmethod
    def get_site_domain():
        return "ptlgs.org"

    def send_messagebox(self, message: str, callback=None) -> str:
        return super().send_messagebox(message)


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Lgs(cookie))

    def daily_shotbox(self):
        shbox_text_list = ["黑丝娘 求上传", "黑丝娘 求工分"]
        return "\n".join([self.client.send_messagebox(item) for item in shbox_text_list])

    def daily_checkin(self):
        return self.client.attendance()
