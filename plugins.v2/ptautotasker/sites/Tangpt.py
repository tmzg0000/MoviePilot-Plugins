import json
import math
import re
import time

from ..utils.custom_requests import CustomRequests

PRIZE_KEYS = ("name", "prize", "prize_name", "title", "reward", "reward_name", "award",
              "award_name", "gift", "gift_name", "content", "text", "description", "prize_type", "type")

from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP


class Tangpt(NexusPHP):
    @staticmethod
    def get_site_name():
        return "躺平"

    @staticmethod
    def get_url():
        return "https://www.tangpt.top"

    @staticmethod
    def get_site_domain():
        return "tangpt.top"

    def claim_task(self, task_id: str, rt_method=None):
        return super().claim_task(task_id, lambda response: response.json().get("msg", "未知错误"))


    def _game_page(self, path):
        response = CustomRequests.get(self.url + path, headers=self.headers)
        response.raise_for_status()
        return response.text

    def _game_post(self, path, page, data):
        headers = dict(self.headers, referer=self.url + page)
        headers.update({
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "X-Requested-With": "XMLHttpRequest",
        })
        response = CustomRequests.post(self.url + path, headers=headers, data=data)
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
            raise ValueError("游戏接口返回格式异常")
        return result

    def lottery_remain(self):
        html = self._game_page("/omnibot_lottery.php")
        match = re.search(r"今天还可以抽\s*(\d+)\s*次", html)
        if not match:
            raise ValueError("无法读取今日剩余抽奖次数，请检查Cookie")
        return int(match.group(1))

    def slot_token(self):
        html = self._game_page("/omnibot_slot.php")
        marker = html.find("__slotInitialState")
        if marker >= 0:
            begin = html.find("{", marker)
            if begin >= 0:
                try:
                    state, _ = json.JSONDecoder().raw_decode(html[begin:])
                    token = state.get("user_state", {}).get("spin_token")
                    if isinstance(token, str) and token:
                        return token
                except (ValueError, AttributeError, TypeError):
                    pass
        # 兼容隐藏表单字段和旧版页面中的JS赋值。
        for tag in re.findall(r"<input\b[^>]*>", html, re.I):
            attrs = dict(re.findall(r'''([\w-]+)\s*=\s*["']([^"']*)["']''', tag))
            if attrs.get("name") == "spin_token" and attrs.get("value"):
                return attrs["value"]
        match = re.search(r'''["']?spin_token["']?\s*[:=]\s*["']([^"']+)["']''', html)
        if match:
            return match.group(1)
        raise ValueError("无法获取老虎机spin_token，请检查Cookie")

    def draw_lottery(self, count):
        return self._game_post("/web/omnibot/lottery/draw", "/omnibot_lottery.php", {"count": str(count)})

    def draw_slot(self, token):
        return self._game_post("/web/omnibot/slot-machine/draw", "/omnibot_slot.php",
                               {"multiplier": "1", "spin_token": token})


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Tangpt(cookie))

    @task_info(label="躺平任务领取", hint="领取躺平站点的BUG/VIP任务")
    def daily_claim_task(self):
        return "\n".join((self.client.claim_task("3"), self.client.claim_task("4")))

    @task_info(label="躺平每日1000次抽奖", hint="最多抽奖1000次，按今日剩余次数执行；每批最多100次，间隔1秒，失败停止")
    def daily_lottery(self):
        stats = {"count": 0, "prizes": {}}

        def summary():
            prizes = "、".join(f"{name} × {count:g}" for name, count in
                              sorted(stats["prizes"].items(), key=lambda item: item[1], reverse=True))
            return f"已抽奖{stats['count']}次；奖品：{prizes or '未解析到奖品'}"

        if not self.client.cookie:
            return self.fail(message="未配置躺平站点Cookie", data=stats)
        try:
            remain = self.client.lottery_remain()
            stats["remain"] = remain
            total = min(1000, remain)
            if total <= 0:
                return self.ok(message="今日抽奖次数已经用完", data=stats)
            while stats["count"] < total:
                if stats["count"]:
                    time.sleep(1)
                batch = min(100, total - stats["count"])
                result = self.client.draw_lottery(batch)
                if not result["ok"]:
                    return self.fail(message=f"{summary()}；已停止：{result.get('msg') or result.get('message') or '未知错误'}", data=stats)
                stats["count"] += batch
                stats["remain"] -= batch
                results = result.get("results")
                if isinstance(results, list):
                    for item in results:
                        name = item.strip() if isinstance(item, str) else None
                        if isinstance(item, dict):
                            name = next((item[key].strip() for key in PRIZE_KEYS
                                         if isinstance(item.get(key), str) and item[key].strip()), None)
                        if not name:
                            continue
                        count = 1
                        if isinstance(item, dict):
                            try:
                                value = float(item.get("count", 1))
                                if math.isfinite(value) and value > 0:
                                    count = value
                            except (ValueError, TypeError):
                                pass
                        stats["prizes"][name] = stats["prizes"].get(name, 0) + count
            return self.ok(message=summary(), data=stats)
        except Exception as exc:
            # 请求可能已生效，不在本轮重发。
            return self.fail(message=f"{summary()}；请求异常，已停止：{exc}", data=stats)

    @task_info(label="躺平每日2次老虎机", hint="每天成功完成2次后跳过当天后续任务；倍率1（可能消耗站点余额），间隔1秒，自动更新Token，失败停止")
    def daily_slots(self):
        stats = {"count": 0, "payout": 0, "spins": []}

        def summary():
            return f"老虎机已执行{stats['count']}次，派彩合计{stats['payout']:g}"

        if not self.client.cookie:
            return self.fail(message="未配置躺平站点Cookie", data=stats)
        try:
            token = self.client.slot_token()
            for attempt in range(2):
                if attempt:
                    time.sleep(1)
                result = self.client.draw_slot(token)
                if not result["ok"]:
                    return self.fail(message=f"{summary()}；已停止：{result.get('msg') or result.get('message') or '未知错误'}", data=stats)
                stats["count"] += 1
                payout = float(result.get("payout") or 0)
                if not math.isfinite(payout):
                    raise ValueError("派彩数据异常")
                stats["payout"] += payout
                reels = result.get("reels")
                names = " | ".join(str(item.get("name") or "?") if isinstance(item, dict) else "?"
                                   for item in reels) if isinstance(reels, list) else ""
                stats["spins"].append({"reels": names, "payout": payout,
                                       "is_free_spin": result.get("is_free_spin") is True})
                if attempt < 1:
                    token = result.get("spin_token") or self.client.slot_token()
            details = "；".join(f"{item['reels']}，派彩{item['payout']:g} [{ '免费' if item['is_free_spin'] else '付费' }]"
                               for item in stats["spins"])
            return self.ok(message=f"{summary()}；{details}", data=stats)
        except Exception as exc:
            return self.fail(message=f"{summary()}；请求异常，已停止：{exc}", data=stats)
