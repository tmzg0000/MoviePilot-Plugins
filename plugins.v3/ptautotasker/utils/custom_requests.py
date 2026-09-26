import requests
from .config import Config


class CustomRequests:
    @staticmethod
    def get(url, headers=None, params=None, timeout=Config.REQUEST_TIMEOUT):
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        return response

    @staticmethod
    def post(url, headers=None, data=None, timeout=Config.REQUEST_TIMEOUT):
        response = requests.post(url, headers=headers, data=data, timeout=timeout)
        return response

    @staticmethod
    def put(url, headers=None, data=None, timeout=Config.REQUEST_TIMEOUT):
        response = requests.put(url, headers=headers, data=data, timeout=timeout)
        return response

    @staticmethod
    def delete(url, headers=None, data=None, timeout=Config.REQUEST_TIMEOUT):
        response = requests.delete(url, headers=headers, data=data, timeout=timeout)
        return response
