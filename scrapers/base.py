"""
基础爬虫类
提供 UA 轮换、请求限速、错误重试等通用能力
"""

import random
import time
import logging
from abc import ABC, abstractmethod
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# User-Agent 池
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

# 常见请求头
HEADERS_TEMPLATE = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Cache-Control": "max-age=0",
}


def random_ua() -> str:
    """随机返回一个 User-Agent"""
    return random.choice(USER_AGENTS)


def make_headers(referer: Optional[str] = None) -> dict:
    """构造请求头"""
    headers = HEADERS_TEMPLATE.copy()
    headers["User-Agent"] = random_ua()
    if referer:
        headers["Referer"] = referer
    return headers


def random_delay(min_sec: float = 3, max_sec: float = 8):
    """随机延迟，模拟人类浏览行为"""
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


class BaseScraper(ABC):
    """爬虫基类"""

    name: str = "base"

    def __init__(self, min_delay: float = 3, max_delay: float = 8):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.session = requests.Session()

    def delay(self):
        random_delay(self.min_delay, self.max_delay)

    def get(self, url: str, headers: Optional[dict] = None, **kwargs) -> requests.Response:
        """发送 GET 请求，自动添加随机 UA"""
        if headers is None:
            headers = make_headers()
        else:
            headers.setdefault("User-Agent", random_ua())

        self.delay()
        logger.debug(f"[{self.name}] GET {url}")
        resp = self.session.get(url, headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def post(self, url: str, headers: Optional[dict] = None, **kwargs) -> requests.Response:
        """发送 POST 请求"""
        if headers is None:
            headers = make_headers()
        else:
            headers.setdefault("User-Agent", random_ua())

        self.delay()
        logger.debug(f"[{self.name}] POST {url}")
        resp = self.session.post(url, headers=headers, timeout=30, **kwargs)
        resp.raise_for_status()
        return resp

    def soup(self, html: str) -> BeautifulSoup:
        """将 HTML 解析为 BeautifulSoup"""
        return BeautifulSoup(html, "lxml")

    @abstractmethod
    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        搜索岗位
        返回格式：
        [
            {
                "job_id": "平台唯一ID",
                "title": "岗位名称",
                "company": "公司全名",
                "city": "城市",
                "district": "区/县",
                "salary_min": 25000,
                "salary_max": 50000,
                "salary_text": "25K-50K",
                "description": "岗位描述",
                "url": "岗位链接",
                "platform": "平台名称",
                "pub_date": "发布日期",
            },
            ...
        ]
        """
        ...

    def search_all(self, cities: list[str], keywords: list[str]) -> list[dict]:
        """遍历城市和关键词搜索，返回合并后的岗位列表"""
        all_jobs = []
        for city in cities:
            for keyword in keywords:
                try:
                    logger.info(f"[{self.name}] 搜索: {city} - {keyword}")
                    jobs = self.search(keyword, city)
                    all_jobs.extend(jobs)
                    logger.info(f"[{self.name}] {city}-{keyword}: 找到 {len(jobs)} 个岗位")
                except Exception as e:
                    logger.error(f"[{self.name}] {city}-{keyword} 搜索失败: {e}")
                    continue
        return all_jobs
