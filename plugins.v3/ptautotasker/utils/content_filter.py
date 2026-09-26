from lxml import etree
import re


class ContentFilter:

    @staticmethod
    def lxml_get_HTML(response):
        return etree.HTML(response.text)

    @staticmethod
    def lxml_get_text(response, xpath, split_str=""):
        return split_str.join(etree.HTML(response.text).xpath(xpath))

    @staticmethod
    def lxml_get_texts(response, xpath, split_str=""):
        return [split_str.join(item.xpath(".//text()")) for item in etree.HTML(response.text).xpath(xpath)]

    @staticmethod
    def re_get_text(response, pattern, group=0):
        match = re.search(pattern, response.text)
        return match.group(group) if match else None

    @staticmethod
    def re_get_texts(response, pattern, group=0):
        return [match.group(group) for match in re.finditer(pattern, response.text)]

    @staticmethod
    def re_get_match(response, pattern):
        match = re.search(pattern, response.text)
        return match
