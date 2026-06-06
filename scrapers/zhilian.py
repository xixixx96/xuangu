"""
智联招聘爬虫
智联招聘是老牌综合招聘平台，覆盖面广
"""

import json
import logging
import re
from urllib.parse import quote

from .base import BaseScraper

logger = logging.getLogger(__name__)

# 智联城市编码
CITY_CODE = {
    "上海": "538",
    "杭州": "653",
    "苏州": "639",
}


class ZhilianScraper(BaseScraper):
    name = "zhilian"

    def __init__(self, min_delay=3, max_delay=7):
        super().__init__(min_delay, max_delay)

    def _parse_salary(self, text: str) -> tuple:
        """解析: 1.5-3万/月, 15K-30K 等"""
        # 万/月
        match = re.findall(r"([\d.]+)\s*[-~至]\s*([\d.]+)\s*万", text)
        if match:
            return int(float(match[0][0]) * 10000), int(float(match[0][1]) * 10000)

        match = re.findall(r"([\d.]+)\s*万", text)
        if match:
            return int(float(match[0]) * 10000), int(float(match[0]) * 10000)

        # K
        match = re.findall(r"(\d+)\s*[kK]", text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000

        # 纯数字
        match = re.findall(r"(\d+)\s*[-~至]\s*(\d+)", text)
        if match:
            lo, hi = int(match[0][0]), int(match[0][1])
            if lo < 100:  # 如果数字很小，可能是"万"
                return lo * 10000, hi * 10000
            return lo, hi

        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        搜索智联招聘

        使用智联招聘搜索页面:
        https://sou.zhaopin.com/?jl={city_code}&kw={keyword}&p={page}
        """
        if city not in CITY_CODE:
            logger.warning(f"智联招聘不支持城市: {city}")
            return []

        city_code = CITY_CODE[city]
        jobs = []

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }

        for p in range(1, page + 1):
            self.delay()
            try:
                # 智联搜索 URL
                url = f"https://sou.zhaopin.com/?jl={city_code}&kw={quote(keyword)}&p={p}"

                resp = self.session.get(url, headers=headers, timeout=20)
                if resp.status_code != 200:
                    logger.warning(f"[{self.name}] 第{p}页 返回 {resp.status_code}")
                    break

                html = resp.text
                soup = self.soup(html)

                # 智联的岗位列表
                # 页面结构: div.joblist-box__item 或 div.positionlist 下的 div
                cards = soup.select(".joblist-box__item, .positionlist__item")
                if not cards:
                    cards = soup.select("[class*='joblist'] > div, [class*='positionlist'] > div")
                if not cards:
                    cards = soup.select("[class*='job-box'], [class*='position-box']")

                for card in cards:
                    try:
                        # 岗位名称
                        title_el = card.select_one(".jobinfo__name a, .job-name a, [class*='job-name'] a, a[class*='name']")
                        title = title_el.get_text(strip=True) if title_el else ""

                        # 公司名
                        company_el = card.select_one(".company__name a, .company-name a, [class*='company-name'] a")
                        company = company_el.get_text(strip=True) if company_el else ""

                        # 薪资
                        salary_el = card.select_one(".jobinfo__salary, .salary, [class*='salary']")
                        salary_text = salary_el.get_text(strip=True) if salary_el else ""

                        # 地点
                        area_el = card.select_one(".jobinfo__area, .area, [class*='area']")
                        area_text = area_el.get_text(strip=True) if area_el else city

                        # 链接
                        link_el = card.select_one("a[href*='job']")
                        link = ""
                        if link_el:
                            href = link_el.get("href", "")
                            if href.startswith("/"):
                                link = f"https://sou.zhaopin.com{href}"
                            elif href.startswith("http"):
                                link = href

                        # 描述 / 标签
                        desc_el = card.select_one(".jobinfo__detail, .job-detail, [class*='job-detail']")
                        description = desc_el.get_text(strip=True) if desc_el else ""

                        # 公司信息
                        company_info_el = card.select_one(".company__info, [class*='company-info']")
                        company_info = company_info_el.get_text(strip=True) if company_info_el else ""

                        if not title or not company:
                            continue

                        salary_min, salary_max = self._parse_salary(salary_text)

                        job_id = f"zhilian_{hash(title + company + link) & 0x7FFFFFFF:08x}"

                        jobs.append({
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "city": city,
                            "district": area_text.replace(city, "").strip(),
                            "salary_min": salary_min,
                            "salary_max": salary_max,
                            "salary_text": salary_text,
                            "description": description,
                            "company_info": company_info,
                            "url": link,
                            "platform": "智联招聘",
                            "pub_date": "",
                        })
                    except Exception as e:
                        logger.debug(f"解析智联卡片异常: {e}")
                        continue

                logger.info(f"[{self.name}] 第{p}页: 提取到 {len(jobs)} 个岗位")

                if not cards:
                    break

            except Exception as e:
                logger.warning(f"[{self.name}] 第{p}页请求失败: {e}")
                break

        return jobs
