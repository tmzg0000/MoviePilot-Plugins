from ..base.NexusPHP import NexusPHP
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



class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Lgs(cookie))
