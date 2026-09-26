from ..utils.custom_requests import CustomRequests
from lxml import etree


class NexusPHP:
    url = ""
    name_cn = ""
    domain = ""
    def __init__(self, cookie: str, url_shoutbox: str = None, url_ajax: str = None, attendance_url: str = None,
                 messages_url: str = None):
        self.url = self.get_url()
        self.name_cn = self.get_site_name()
        self.domain = self.get_site_domain()
        self.url_shoutbox = url_shoutbox or self.url + "/shoutbox.php"
        self.url_ajax = url_ajax or self.url + "/ajax.php"
        self.attendance_url = attendance_url or self.url + "/attendance.php"
        self.messages_url = messages_url or self.url + "/messages.php"
        self.cookie = cookie
        self.headers = {
            "cookie": self.cookie,
            "referer": self.url,
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 Edg/132.0.0.0"
        }

    @staticmethod
    def get_url():
        raise NotImplementedError("Subclasses should implement this method to return the URL.")

    @staticmethod
    def get_site_name():
        raise NotImplementedError("Subclasses should implement this method to return the Name.")

    @staticmethod
    def get_site_domain():
        raise NotImplementedError("Subclasses should implement this method to return the Domain.")

    """
    发送群聊区消息
    """

    def send_messagebox(self, message: str, rt_method: callable = None) -> str:
        if rt_method is None:
            rt_method = lambda response: " ".join(
                etree.HTML(response.text).xpath("//tr[1]/td//text()"))
        params = {
            "shbox_text": message,
            "shout": "%E6%88%91%E5%96%8A",
            "sent": "yes",
            "type": "shoutbox"
        }
        response = CustomRequests.get(self.url_shoutbox, headers=self.headers, params=params)
        return rt_method(response)

    """
    获取群聊区消息
    """

    def get_messagebox(self, rt_method: callable = None) -> list:
        if rt_method is None:
            rt_method = lambda response: ["".join(item.xpath(".//text()")) for item in
                                          etree.HTML(response.text).xpath("//tr/td")]
        response = CustomRequests.get(self.url_shoutbox, headers=self.headers)
        return rt_method(response)

    """
    申领任务
    """

    def claim_task(self, task_id: str, rt_method: callable) -> str:
        data = {
            "action": "claimTask",
            "params[exam_id]": task_id
        }

        response = CustomRequests.post(self.url_ajax, headers=self.headers, data=data)
        return rt_method(response)

    """
    每日签到
    """

    def attendance(self, rt_method: callable = None):
        if rt_method is None:
            rt_method = lambda response: "".join(etree.HTML(response.text).xpath("//td/table//tr/td/p//text()"))
        response = CustomRequests.get(self.attendance_url, headers=self.headers)
        return rt_method(response)

    """
    获取邮件列表
    """

    def get_message_list(self, rt_method: callable = None):
        if rt_method is None:
            rt_method = lambda response: [
                {"status": "".join(item.xpath("./td[1]/img/@title")), "topic": "".join(item.xpath("./td[2]//text()")),
                 "from": "".join(item.xpath("./td[3]/text()")), "time": "".join(item.xpath("./td[4]//text()")),
                 "id": "".join(item.xpath("./td[5]/input/@value"))} for item in
                etree.HTML(response.text).xpath("//form/table//tr")]
        response = CustomRequests.get(self.messages_url, headers=self.headers)
        return rt_method(response)

    """
    将邮件设为已读
    """

    def set_message_read(self, message_id: str, rt_method: callable = lambda response: ""):
        data = {
            "action": "moveordel",
            "messages[]": message_id,
            "markread": "设为已读",
            "box": "1"
        }
        response = CustomRequests.post(self.messages_url, headers=self.headers, data=data)
        return rt_method(response)

    """
    抽奖
    """

    def lottery(self, parameter: tuple = None, rt_method: callable = None):
        pass
