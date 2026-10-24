"""CHDBits encrypted-bank sign-in; only the native skip action is submitted."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlsplit

from .core import SignResult, cookie_objects, normalize_host, target_url
from .vault import read_bank

HOST = "ptchdbits.co"
SIGNED = "今天已经签过到了"


class SigninError(ValueError):
    """An account-free message suitable for the results page."""


def normalize(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


class PageParser(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.forms, self.feedback = [], []
        self.form = self.row = self.option = None
        self.depth = self.ignored = 0
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ("script", "style", "textarea"):
            self.ignored += 1
        if tag == "form":
            self.depth += 1
            if urlsplit(attrs.get("action", "")).path in ("/bakatest.php", "bakatest.php"):
                self.form = {"rows": [], "options": [], "hidden": [], "images": False,
                             "method": attrs.get("method", "get").lower(), "skip": False}
        if self.form is None:
            return
        if tag == "tr":
            self.row = []
        if tag == "input":
            self.option = None
            kind, name = attrs.get("type", "").lower(), attrs.get("name", "")
            if name == "wantskip" and attrs.get("value") == "不会" and kind == "submit":
                self.form["skip"] = True
            if kind == "hidden" and name:
                self.form["hidden"].append((name, attrs.get("value", "")))
            if name == "choice[]" and kind in ("radio", "checkbox"):
                self.option = {"value": attrs.get("value", ""), "kind": kind, "text": []}
                self.form["options"].append(self.option)
        if tag == "br":
            self.option = None
        if tag == "img":
            self.form["images"] = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "textarea"):
            self.ignored = max(0, self.ignored - 1)
        if tag == "tr" and self.form is not None:
            if self.row is not None:
                self.form["rows"].append(normalize("".join(self.row)))
            self.row = self.option = None
        if tag == "form":
            if self.form is not None:
                self.forms.append(self.form)
            self.form = self.row = self.option = None
            self.depth = max(0, self.depth - 1)

    def handle_data(self, text):
        if self.ignored:
            return
        if not self.depth:
            self.feedback.append(text)
        if self.row is not None:
            self.row.append(text)
        if self.option is not None:
            self.option["text"].append(text)


def parse_question(html):
    forms = [f for f in PageParser(html).forms if f["options"]]
    if len(forms) != 1:
        raise SigninError("未找到唯一题目表单，请检查 Cookie、验证页或页面结构")
    form = forms[0]
    ids = [v for k, v in form["hidden"] if k == "questionid"]
    if len(ids) != 1 or not re.fullmatch(r"[1-9]\d{0,9}", ids[0]):
        raise SigninError("未读到有效 questionid，停止提交")
    options = [{**o, "text": normalize("".join(o["text"]))} for o in form["options"]]
    # Decorative images can exist inside the quiz form; only the parsed choice
    # controls determine whether this is a supported text question.
    if (not form["skip"] or form["method"] != "post" or not 2 <= len(options) <= 8
            or len({o["kind"] for o in options}) != 1
            or len({o["value"] for o in options}) != len(options)
            or len({o["text"] for o in options}) != len(options)
            or any(not o["text"] or not re.fullmatch(r"[1-9]\d{0,8}", o["value"]) for o in options)):
        raise SigninError("题目结构不支持或缺少“不会”按钮，停止提交")
    prompt = form["rows"][0] if form["rows"] else ""
    if "请问:" not in prompt:
        raise SigninError("题干格式无法识别")
    prompt = re.sub(r"^\d+\s*[、.]\s*", "", prompt)
    kind = options[0]["kind"]
    signature = hashlib.sha256(json.dumps([prompt, kind, sorted(o["text"] for o in options)],
                                         ensure_ascii=False).encode()).hexdigest()
    return {"id": ids[0], "prompt": prompt, "kind": kind, "options": options,
            "signature": signature, "hidden": form["hidden"]}



def is_signed(html):
    # Exclude scripts, styles and quiz content so options cannot forge a result.
    return SIGNED in normalize(" ".join(PageParser(html).feedback))


class ChdSigner:
    def __init__(self, direct, key, reserve):
        self.direct, self.key, self.reserve = direct, key, reserve

    def _read(self, session, method, target, **kwargs):
        response = self.direct._request(session, method, target, **kwargs)
        if not re.search(r"charset\s*=", response.headers.get("Content-Type", ""), re.I):
            charset = re.search(br"charset\s*=\s*['\"]?([\w-]+)", response.content[:4096], re.I)
            response.encoding = charset.group(1).decode("ascii") if charset else "utf-8"
        return response.text

    def sign(self, site, rule):
        import requests

        if not self.key:
            return SignResult("failed", "请先输入有效的插件解锁密码")
        base = str(site.get("url") or "")
        if normalize_host(base) != HOST or urlsplit(base).scheme != "https" or not site.get("cookie"):
            return SignResult("failed", "彩虹岛需要 HTTPS 站点地址和有效 Cookie")
        target = target_url(base, "/bakatest.php")
        try:
            with requests.Session() as session:
                session.trust_env = False
                session.headers.update({"User-Agent": str(site.get("ua") or "Mozilla/5.0"),
                                        "Referer": target, "Cache-Control": "no-cache"})
                for item in cookie_objects(str(site["cookie"]), target):
                    session.cookies.set(item["name"], item["value"], domain=urlsplit(base).hostname, path="/")
                if site.get("proxy") and self.direct.proxies:
                    session.proxies.update(self.direct.proxies)
                page = self._read(session, "GET", target)
                if is_signed(page):
                    return SignResult("already", "彩虹岛：今天已经签过到了")
                question = parse_question(page)
                saved = read_bank(self.key).get(question["signature"], {})
                correct = saved.get("correct")
                by_text = {option["text"]: option["value"] for option in question["options"]}
                if (saved.get("id") != question["id"] or not isinstance(correct, list) or not correct
                        or len(set(correct)) != len(correct) or not all(text in by_text for text in correct)
                        or (question["kind"] == "radio" and len(correct) != 1)):
                    return SignResult("failed", "彩虹岛：题库未命中有效答案，本次未提交")
                reserved = {"choice[]", "submit", "wantchange", "wantskip", "usercomment"}
                fields = [(k, v) for k, v in question["hidden"] if k not in reserved]
                fields += [("choice[]", by_text[text]) for text in correct]
                fields += [("usercomment", "此刻心情:无"), ("wantskip", "不会")]
                if not self.reserve(site):
                    return SignResult("failed", "彩虹岛：北京时间今天已发起过提交，仅回查未确认签到；不重复提交")
                # Reserving before POST prevents retries, overlapping jobs or a restart
                # from submitting twice after a timeout. Only GET is retried here.
                try:
                    self._read(session, "POST", target, data=fields)
                except requests.RequestException:
                    pass
                checked = self._read(session, "GET", target)
                if is_signed(checked):
                    return SignResult("success", "彩虹岛：不会签到完成，页面确认今天已经签过到了")
                return SignResult("failed", "彩虹岛：已点不会，页面未出现今天已经签过到了；本日不再提交")
        except SigninError as error:
            return SignResult("failed", "彩虹岛：" + str(error))
        except ImportError:
            return SignResult("failed", "彩虹岛：缺少 cryptography 依赖，请重新安装插件依赖")
        except requests.RequestException:
            return SignResult("failed", "彩虹岛：网络请求或状态回查失败；若已提交，本日不再提交")
        except Exception:
            return SignResult("failed", "彩虹岛：题库解密或页面处理失败，请检查配置及插件资源")
