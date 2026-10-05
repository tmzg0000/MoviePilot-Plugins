import time

from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP
from ..utils.custom_requests import CustomRequests


class HDVideo(NexusPHP):
    @staticmethod
    def get_site_name():
        return "HDVIDEO"

    @staticmethod
    def get_url():
        return "https://hdvideo.top"

    @staticmethod
    def get_site_domain():
        return "hdvideo.top"

    def buy_scratch(self):
        url = self.url + "/games/scratch/"
        headers = dict(self.headers, referer=url)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = CustomRequests.post(url, headers=headers, data={"action": "buy"})
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("刮奖接口返回格式异常")
        return result


class Tasks(BaseTask):
    MAX_TRIES = 100
    COOLDOWN = 2.1

    def __init__(self, cookie: str):
        super().__init__(HDVideo(cookie))

    @task_info(label="HDVIDEO 自动刮奖", hint="每次最多购买100次刮刮乐，消耗电影票；间隔2.1秒，次数用完、余额不足或请求异常时停止")
    def daily_scratch(self):
        stats = {"count": 0, "delta": 0, "balance": None}

        def summary():
            text = f"已刮奖{stats['count']}次，净盈亏{stats['delta']:+g}"
            if stats["balance"] is not None:
                text += f"，电影票余额{stats['balance']}"
            return text

        if not self.client.cookie:
            return self.fail(message="未配置HDVIDEO站点Cookie", data=stats)

        for attempt in range(self.MAX_TRIES):
            if attempt:
                time.sleep(self.COOLDOWN)
            try:
                result = self.client.buy_scratch()
            except Exception as exc:
                # 购买请求可能已生效，当前轮次不重发，避免重复扣票。
                return self.fail(message=f"{summary()}；网络或请求异常，已停止：{exc}", data=stats)
            if not result["ok"]:
                reason = result.get("error") or "今日次数已用完或电影票不足"
                return self.fail(message=f"{summary()}；已停止：{reason}", data=stats)
            stats["count"] += 1
            stats["balance"] = result.get("balance", stats["balance"])
            stats["last_prize"] = result.get("name")
            try:
                stats["delta"] += float(result["delta"])
            except (KeyError, TypeError, ValueError):
                return self.fail(message=f"{summary()}；净盈亏数据异常，已停止", data=stats)
        return self.ok(message=summary(), data=stats)
