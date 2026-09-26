from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP
from ..utils.custom_requests import CustomRequests
import datetime
from ..utils.content_filter import ContentFilter
import time
from ..base.BaseTask import BaseTask

class Vicomo(NexusPHP):

    def __init__(self, cookie):
        super().__init__(cookie)
        self.vs_boss_url = self.url + "/customgame.php?action=exchange"

    @staticmethod
    def get_site_name():
        return "象站"

    @staticmethod
    def get_url():
        return "https://ptvicomo.net"

    @staticmethod
    def get_site_domain():
        return "ptvicomo.net"

    def send_messagebox(self, message: str, callback=None) -> str:
        return super().send_messagebox(message,
                                       lambda response: "")

    def vs_boss(self):
        if datetime.date.today().weekday() in [0, 2]:
            vs_boss_data = "option=1&vs_member_name=0&submit=%E9%94%8B%E8%8A%92%E4%BA%A4%E9%94%99+-+1v1"  # Monday Wednesday
        elif datetime.date.today().weekday() in [1, 3]:
            vs_boss_data = "option=1&vs_member_name=0%2C1%2C2%2C3%2C4&submit=%E9%BE%99%E4%B8%8E%E5%87%A4%E7%9A%84%E6%8A%97%E8%A1%A1+-+%E5%9B%A2%E6%88%98+5v5"  # Thuesday Thursday
        elif datetime.date.today().weekday() in [4, 5, 6]:
            vs_boss_data = "option=1&vs_member_name=0%2C1%2C2%2C3%2C4%2C5%2C6%2C7%2C8%2C9%2C10%2C11%2C12%2C13%2C14%2C15%2C16&submit=%E4%B8%96%E7%95%8Cboss+-+%E5%AF%B9%E6%8A%97Sysrous"
        self.headers.update({
            "content-type": "application/x-www-form-urlencoded",
            "pragma": "no-cache",
        })
        response = CustomRequests.post(self.vs_boss_url, headers=self.headers, data=vs_boss_data)

        # """提取签到信息"""
        match = ContentFilter.re_get_match(response, r"\[签到已得(\d+), 补签卡: (\d+)\]")
        if match:
            days = match.group(1)  # 签到天数
            cards = match.group(2)  # 补签卡数量
            print(f"签到已得: {days} , 补签卡: {cards} 张")
        else:
            print("今日未签到")

        # 从响应中提取重定向 URL
        redirect_url = None
        match = ContentFilter.re_get_match(response, r"window\.location\.href\s*=\s*'([^']+战斗结果[^']+)'")
        if match:
            redirect_url = match.group(1)
            print(f"提取到的战斗结果重定向 URL: {redirect_url}")
        else:
            print("未找到战斗结果重定向 URL")
            return None

        # 访问重定向 URL
        battle_result_response = CustomRequests.get(redirect_url, headers=self.headers)
        print(f"战斗结果重定向页面状态码: {battle_result_response.status_code}")
        # print(battle_result_response.text)  # 可选：调试时查看响应内容

        # 解析战斗结果页面并提取 battleMsgInput
        parsed_html = ContentFilter.lxml_get_HTML(battle_result_response)
        battle_msg_input = parsed_html.xpath('//*[@id="battleMsgInput"]')
        if battle_msg_input:
            battle_info = parsed_html.xpath('//*[@id="battleResultStringLastShow"]/div[1]//text()')
            battle_text = ' '.join([text.strip() for text in battle_info if text.strip()])
            print("找到Battle Info:", battle_text)
            print("找到Battle Result:",
                  parsed_html.xpath('//*[@id="battleResultStringLastShow"]/div[2]/text()')[0].strip())
            return parsed_html.xpath('//*[@id="battleResultStringLastShow"]/div[2]/text()')[0].strip()
        else:
            print("未找到Battle Result")
            return None


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Vicomo(cookie))

    def daily_shotbox(self):
        shbox_text_list = ["小象求象草"]
        rsp_text_list = []
        for item in shbox_text_list:
            self.client.send_messagebox(item)
            message_list = self.client.get_message_list()
            if message_list:
                message = message_list[1].get("topic", "")
                rsp_text_list.append(message)
                self.client.set_message_read(message_list[1].get("id", ""))
        return "\n".join(rsp_text_list)

    def daily_checkin(self):
        return self.client.attendance()

    @task_info(label="打Boss", hint="执行象站的打Boss任务")
    def daily_vs_boss(self):
        rsp_list = []
        for i in range(3):
            rsp_list.append(self.client.vs_boss())
            time.sleep(10)  # 休眠10秒
        return "\n".join([rsp for rsp in rsp_list if rsp])
