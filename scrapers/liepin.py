"""
猎聘爬虫
猎聘定位中高端人才招聘，解决方案工程师岗位较多
"""

import json
import logging
import re
from urllib.parse import quote

from .base import BaseScraper

logger = logging.getLogger(__name__)

# 猎聘城市编码
CITY_CODE = {
    "上海": "020",
    "杭州": "070",
    "苏州": "090",
}


class LiepinScraper(BaseScraper):
    name = "liepin"

    def __init__(self, min_delay=4, max_delay=8):
        super().__init__(min_delay, max_delay)

    def _parse_salary(self, text: str) -> tuple:
        """
        解析猎聘薪资: 20-40k·15薪 -> (20000, 40000)
        """
        # 匹配数字部分
        match = re.findall(r"(\d+)\s*[kK]", text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000

        # 匹配万/月: 2.5-5万/月
        match = re.findall(r"([\d.]+)\s*万", text)
        if len(match) >= 2:
            return int(float(match[0]) * 10000), int(float(match[1]) * 10000)
        if len(match) == 1:
            return int(float(match[0]) * 10000), int(float(match[0]) * 10000)

        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        搜索猎聘

        猎聘搜索 URL:
        https://www.liepin.com/zhaopin/?key={keyword}&dqs={city_code}&curPage={page}
        """
        if city not in CITY_CODE:
            logger.warning(f"猎聘不支持城市: {city}")
            return []

        city_code = CITY_CODE[city]
        jobs = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://www.liepin.com/",
        }

        for p in range(1, page + 1):
            self.delay()
            try:
                url = f"https://www.liepin.com/zhaopin/?key={quote(keyword)}&dqs={city_code}&curPage={p}"

                resp = self.session.get(url, headers=headers, timeout=20)

                if resp.status_code != 200:
                    logger.warning(f"[{self.name}] 第{p}页 返回 {resp.status_code}")
                    break

                html = resp.text
                soup = self.soup(html)

                # 猎聘的岗位列表
                cards = soup.select(".job-list-item, .job-list-box > li, [class*='job-list'] > li")
                if not cards:
                    cards = soup.select("[class*='job-card'], [class*='job-item']")

                for card in cards:
                    try:
                        # 岗位名称
                        title_el = card.select_one(".job-title-name, .job-name, [class*='job-name'] a")
                        title = title_el.get_text(strip=True) if title_el else ""

                        # 公司名
                        company_el = card.select_one(".company-name, [class*='company-name'] a")
                        company = company_el.get_text(strip=True) if company_el else ""

                        # 薪资
                        salary_el = card.select_one(".job-salary, .salary, [class*='salary']")
                        salary_text = salary_el.get_text(strip=True) if salary_el else ""

                        # 地点
                        area_el = card.select_one(".job-area, .area, [class*='area']")
                        area_text = area_el.get_text(strip=True) if area_el else city

                        # 链接
                        link_el = card.select_one("a[href*='job']")
                        link = ""
                        if link_el:
                            href = link_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://www.liepin.com{href}"
                            elif href.startswith("http"):
                                link = href

                        # 发布信息 / 标签
                        info_el = card.select_one(".job-info, [class*='job-info']")
                        info_text = info_el.get_text(strip=True) if info_el else ""

                        if not title or not company:
                            continue

                        salary_min, salary_max = self._parse_salary(salary_text)

                        job_id = f"liepin_{hash(title + company + link) & 0x7FFFFFFF:08x}"

                        jobs.append({
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "city": city,
                            "district": area_text.replace(city, "").strip().rstrip("区").strip(),
                            "salary_min": salary_min,
                            "salary_max": salary_max,
                            "salary_text": salary_text,
                            "description": info_text,
                            "url": link,
                            "platform": "猎聘",
                            "pub_date": "",
                        })
                    except Exception as e:
                        logger.debug(f"解析猎聘卡片异常: {e}")
                        continue

                logger.info(f"[{self.name}] 第{p}页: 提取到 {len(jobs)} 个岗位")

                if not cards:
                    break

            except Exception as e:
                logger.warning(f"[{self.name}] 第{p}页请求失败: {e}")
                break

        return jobs
