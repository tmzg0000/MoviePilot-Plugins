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



class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Cyanbug(cookie))
