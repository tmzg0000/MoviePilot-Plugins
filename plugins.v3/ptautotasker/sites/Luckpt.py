from html.parser import HTMLParser

from ..base.BaseTask import BaseTask
from ..base.Decorator import task_info
from ..base.NexusPHP import NexusPHP
from ..utils.custom_requests import CustomRequests


class Luckpt(NexusPHP):
    @staticmethod
    def get_site_name():
        return "LuckPT"

    @staticmethod
    def get_url():
        return "https://pt.luckpt.de"

    @staticmethod
    def get_site_domain():
        return "luckpt.de"

    @staticmethod
    def reward_state(html):
        # 只读取目标套装的标题与领取栏，排除其他套装及购买按钮。
        class Parser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.active = False
                self.found = False
                self.text = []
                self.button = None

            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == "section" and attrs.get("id") == "ccat-8":
                    self.active = self.found = True
                if self.active and "category-body" in attrs.get("class", "").split():
                    self.active = False
                if self.active and tag == "button" and "claim-reward" in attrs.get("class", "").split():
                    self.button = attrs

            def handle_endtag(self, tag):
                if tag == "section":
                    self.active = False

            def handle_data(self, data):
                if self.active:
                    self.text.append(data)

        parser = Parser()
        parser.feed(html)
        text = " ".join(parser.text)
        if not parser.found or "工具支持纪念套装" not in text:
            raise ValueError("未找到工具支持纪念套装，请检查Cookie或页面结构")
        if "每日幸运星" not in text:
            raise ValueError("未找到套装每日幸运星奖励")
        if "已领取" in text and "未领取" not in text:
            return {"claimed": True}
        button = parser.button
        if not button or "disabled" in button:
            raise ValueError("套装奖励不可领取，请确认已集齐工具支持纪念套装")
        if button.get("data-category") != "8" or not button.get("data-type"):
            raise ValueError("套装奖励领取参数异常")
        return {"claimed": False, "category_id": "8", "reward_type": button["data-type"]}

    def get_reward_state(self):
        response = CustomRequests.get(self.url + "/medal_collection.php", headers=self.headers)
        response.raise_for_status()
        return self.reward_state(response.text)

    def claim_medal_reward(self, state):
        headers = dict(self.headers, referer=self.url + "/medal_collection.php")
        headers.update({"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                        "X-Requested-With": "XMLHttpRequest"})
        response = CustomRequests.post(self.url_ajax, headers=headers, data={
            "action": "claimMedalCategoryReward",
            "params[category_id]": state["category_id"],
            "params[reward_type]": state["reward_type"],
        })
        response.raise_for_status()
        result = response.json()
        if not isinstance(result, dict) or "ret" not in result:
            raise ValueError("勋章奖励接口返回格式异常")
        if isinstance(result["ret"], bool) or result["ret"] not in (0, "0"):
            raise ValueError(result.get("msg") or "勋章奖励领取失败")


class Tasks(BaseTask):
    def __init__(self, cookie: str):
        super().__init__(Luckpt(cookie))

    @task_info(label="LuckPT勋章奖励", hint="领取工具支持纪念套装每日幸运星+1000；需集齐套装，今日已领取时自动跳过")
    def medal_bonus(self):
        if not self.client.cookie:
            return self.fail(message="未配置LuckPT站点Cookie")
        try:
            state = self.client.get_reward_state()
            if state["claimed"]:
                return self.ok(message="工具支持纪念套装每日幸运星+1000：今日已领取，跳过")
            self.client.claim_medal_reward(state)
            if not self.client.get_reward_state()["claimed"]:
                return self.fail(message="勋章奖励领取结果未确认，页面仍显示未领取")
            return self.ok(message="工具支持纪念套装奖励领取成功：幸运星+1000")
        except Exception as exc:
            return self.fail(message=f"LuckPT勋章奖励领取失败：{exc}")
