import re

import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP

urllib3.disable_warnings(InsecureRequestWarning)


class Vclib(NexusPHP):
    @staticmethod
    def get_site_name():
        return "Vc-Lib"

    @staticmethod
    def get_url():
        return "https://pt.vclib.online"

    @staticmethod
    def get_site_domain():
        return "vclib.online"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))

    def _cookies(self):
        return dict(item.strip().split("=", 1) for item in (self.cookie or "").split(";") if "=" in item)

    def _request(self, method, path, **kwargs):
        return requests.request(
            method, f"https://pt.vclib.online/{path}", cookies=self._cookies(),
            timeout=30, verify=False, **kwargs,
        )

    def get_task_status_from_homepage(self):
        try:
            response = self._request("GET", "index.php")
            if response.status_code != 200:
                return {"status": "error", "message": f"获取首页失败，HTTP状态码: {response.status_code}"}
            html = response.text
            if "未登录" in html or "该页面必须在登录后才能访问" in html:
                return {"status": "error", "message": "Cookie已失效，请重新登录"}
            match = re.search(
                r"每周任务_上传量.*?要求[：:]\s*([\d.]+)\s*([A-Za-z]+).*?当前[：:]\s*([\d.]+)\s*([A-Za-z]+).*?结果[：:]\s*(?:<span[^>]*>)?(.*?)(?:</span>)?(?:<br|$|</font)",
                html, re.S,
            )
            if not match:
                return {"status": "not_exist", "message": "未找到每周上传任务"}
            result = match.group(5).strip()
            return {
                "status": "completed" if "完成" in result and "未完成" not in result else "uncompleted",
                "message": result, "requirement": f"{match.group(1)} {match.group(2)}",
                "current": f"{match.group(3)} {match.group(4)}",
            }
        except requests.RequestException as error:
            return {"status": "error", "message": f"请求异常: {error}"}

    def exchange_upload_bonus(self, option=2):
        try:
            current_bonus = self._get_current_bonus()
            if current_bonus is not None and current_bonus < 1300:
                return False, f"魔力值不足 (当前{current_bonus}, 需要1300)"
            response = self._request(
                "POST", "mybonus.php?action=exchange", data={"option": str(option), "submit": "交换"},
            )
            if response.status_code != 200:
                return False, f"兑换上传量请求失败，HTTP状态码: {response.status_code}"
            html = response.text
            if "魔力值不足" in html or "您的魔力值不足" in html:
                return False, "魔力值不足，无法兑换上传量"
            if "未登录" in html or ("登录" in html and "请" in html):
                return False, "Cookie已失效，请重新登录"
            if "今日已兑换" in html or "已兑换过" in html or "系统限制" in html:
                return True, "今日已兑换过上传量"
            return True, "魔力值兑换上传量成功" if "兑换成功" in html or "成功兑换" in html else "兑换上传量请求已发送"
        except requests.RequestException as error:
            return False, f"兑换上传量请求异常: {error}"

    def _get_current_bonus(self):
        try:
            response = self._request("GET", "mybonus.php?action=exchange")
            if response.status_code != 200:
                return None
            match = re.search(r"当前([\d,.]+)\s*魔力值", response.text)
            return float(match.group(1).replace(",", "")) if match else None
        except requests.RequestException:
            return None


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Vclib(cookie))

    @task_info(label="Vc-Lib每周上传任务领取", hint="领取周上传任务；未完成时会消耗1300魔力兑换10GB上传量")
    def weekly_upload_claim_and_exchange(self):
        claim_result = self.client.claim_task("2")
        status = self.client.get_task_status_from_homepage()
        lines = [f"任务领取: {claim_result}"]
        if status.get("status") == "uncompleted":
            success, message = self.client.exchange_upload_bonus(2)
            lines.append(f"兑换上传量: {message}")
            return self.ok(message="\n".join(lines)) if success else self.fail("\n".join(lines))
        lines.append(status.get("message", "未检查到任务状态"))
        return self.ok(message="\n".join(lines)) if status.get("status") != "error" else self.fail("\n".join(lines))

    @task_info(label="Vc-Lib每周魔力值任务领取", hint="领取Vc-Lib站点的每周魔力值任务")
    def weekly_bonus_claim(self):
        return self.client.claim_task("3")

    def daily_checkin(self):
        return self.client.attendance()
