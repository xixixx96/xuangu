"""
Boss直聘爬虫（API版）
使用 Boss 直聘公开搜索 API，不需要登录。
"""

import json
import logging
import re
import time

from .base import BaseScraper

logger = logging.getLogger(__name__)

# Boss直聘城市编码
CITY_CODE = {
    "上海": "101020100",
    "杭州": "101210100",
    "苏州": "101190400",
}


class BossZhipinScraper(BaseScraper):
    name = "boss_zhipin"

    def __init__(self, min_delay=1, max_delay=3):
        super().__init__(min_delay, max_delay)
        self._last_call = 0

    def _rate_limit(self):
        now = time.time()
        wait = 1.0 - (now - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.time()

    def _parse_salary(self, salary_text: str) -> tuple:
        match = re.findall(r"(\d+)\s*[Kk]", salary_text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000
        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        if city not in CITY_CODE:
            return []

        city_code = CITY_CODE[city]
        jobs = []

        for p in range(1, page + 1):
            try:
                self._rate_limit()
                url = (
                    f"https://www.zhipin.com/wapi/zpgeek/search/joblist.json"
                    f"?query={keyword}&city={city_code}&page={p}&pageSize=30"
                )
                headers = {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    "Referer": "https://www.zhipin.com/",
                    "Accept": "application/json",
                }
                resp = self.session.get(url, headers=headers, timeout=10)

                if resp.status_code != 200:
                    logger.debug(f"[boss] {city}-{keyword} 返回 {resp.status_code}")
                    break

                data = resp.json()
                if data.get("code") != 0:
                    logger.debug(f"[boss] API 返回 code={data.get('code')}, msg={data.get('msg','')}")
                    break

                items = data.get("zpData", {}).get("jobList", [])
                if not items:
                    break

                for item in items:
                    title = item.get("jobName", "")
                    company = item.get("brandName", "")
                    if not title or not company:
                        continue

                    salary_text = item.get("salaryDesc", "")
                    smin, smax = self._parse_salary(salary_text)
                    job_id = item.get("encryptJobId", "")
                    link = f"https://www.zhipin.com/job_detail/{job_id}.html" if job_id else ""

                    jobs.append({
                        "job_id": f"boss_{job_id}",
                        "title": title,
                        "company": company,
                        "city": city,
                        "district": item.get("areaDistrict", ""),
                        "salary_min": smin,
                        "salary_max": smax,
                        "salary_text": salary_text,
                        "description": item.get("jobTagList", ""),
                        "tags": item.get("skills", []) or [],
                        "url": link,
                        "platform": "Boss直聘",
                        "pub_date": item.get("activeTimeDesc", ""),
                    })

                logger.debug(f"[boss] {city}-{keyword} p{p}: {len(items)} 个")

            except Exception:
                pass

        return jobs
