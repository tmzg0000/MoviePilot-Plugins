from ..base.NexusPHP import NexusPHP
from ..base.BaseTask import BaseTask

class Cyanbug(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)

    @staticmethod
    def get_url():
        return "https://cyanbug.net"

    @staticmethod
    def get_site_name():
        return "大青虫"

    @staticmethod
    def get_site_domain():
        return "cyanbug.net"

    def send_messagebox(self, message: str, callback=None) -> str:
        return super().send_messagebox(message)


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Cyanbug(cookie))

    def daily_shotbox(self):
        shbox_text_list = ["青虫娘，求上传", "青虫娘，求魔力", "青虫娘，求下载"]
        return "\n".join([self.client.send_messagebox(item) for item in shbox_text_list])

    def daily_checkin(self):
        return self.client.attendance()
