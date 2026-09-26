import time

from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP
from lxml import etree
from ..utils.custom_requests import CustomRequests
from ..base.BaseTask import BaseTask


class Zm(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)
        self.bonus_url = self.url + "/javaapi/user/drawMedalGroupReward?medalGroupId=3"

    @staticmethod
    def get_site_name():
        return "织梦"

    @staticmethod
    def get_url():
        return "https://zmpt.cc"

    @staticmethod
    def get_site_domain():
        return "zmpt.cc"

    def send_messagebox(self, message: str, callback=None) -> str:
        return super().send_messagebox(message, lambda response: "")

    def medal_bonus(self):
        response = CustomRequests.get(self.bonus_url, headers=self.headers)
        response_data = response.json()

        ## response_data format like this
        # {
        #    "serverTime": 1741177064362,
        #    "success": true,
        #    "errorCode": 0,
        #    "errorMsg": "",
        #    "result": {
        #        "rewardAmount": 15000,
        #        "seedBonus": "818255.0"
        #    }
        # }
        result = response_data.get("result", None)
        if result is None:
            return f"勋章套装奖励领取失败：{response_data.get('errorMsg', None)}"
        else:
            reward = result['rewardAmount']
            seed_bonus = result['seedBonus']

            return f"梅兰竹菊成套勋章奖励: {reward}\n总电力: {seed_bonus}"


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Zm(cookie))

    def daily_shotbox(self):
        shbox_text_list = ["皮总，求电力", "皮总，求上传"]
        rsp_text_list = []
        for item in shbox_text_list:
            self.client.send_messagebox(item)
            time.sleep(3)
            message_list = self.client.get_messagebox()
            if message_list:
                message = message_list[0]
                rsp_text_list.append(message)
        return "\n".join(rsp_text_list)

    def daily_checkin(self):
        return self.client.attendance()

    @task_info(label="织梦勋章奖励", hint="领取织梦站点的梅兰竹菊成套勋章奖励")
    def medal_bonus(self):
        return self.client.medal_bonus()
