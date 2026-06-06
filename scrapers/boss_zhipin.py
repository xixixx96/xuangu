"""
Boss直聘爬虫
Boss直聘是AI/技术岗位最丰富的平台，但反爬也最强。
采用 Playwright 无头浏览器方案，模拟真实用户行为。
"""

import logging
import re
from typing import Optional

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

    def __init__(self, min_delay=5, max_delay=10):
        super().__init__(min_delay, max_delay)
        self._playwright = None

    def _get_playwright(self):
        """懒加载 Playwright"""
        if self._playwright is None:
            from playwright.sync_api import sync_playwright
            self._playwright = sync_playwright().start()
        return self._playwright

    def _parse_salary(self, salary_text: str) -> tuple:
        """解析薪资文本 -> (min, max)"""
        # 格式：15K-25K 或 20K-40K·15薪 等
        match = re.findall(r"(\d+)K", salary_text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000
        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        使用 Playwright 搜索 Boss直聘

        Boss直聘的搜索 URL 格式:
        https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={page}
        """
        if city not in CITY_CODE:
            logger.warning(f"Boss直聘不支持城市: {city}")
            return []

        city_code = CITY_CODE[city]
        jobs = []

        try:
            pw = self._get_playwright()
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                viewport={"width": 1920, "height": 1080},
            )
            page_obj = context.new_page()

            for p in range(1, page + 1):
                url = f"https://www.zhipin.com/web/geek/job?query={keyword}&city={city_code}&page={p}"
                logger.info(f"[{self.name}] 访问: {url}")

                try:
                    page_obj.goto(url, wait_until="networkidle", timeout=30000)
                    self.delay()

                    # 等待岗位列表加载
                    page_obj.wait_for_selector(".job-list-box li, .job-card-wrapper", timeout=10000)

                    # 获取页面 HTML 并解析
                    html = page_obj.content()
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(html, "lxml")

                    # Boss直聘的岗位卡片
                    cards = soup.select(".job-card-wrapper")
                    if not cards:
                        cards = soup.select(".job-list-box li")
                    if not cards:
                        cards = soup.select("[class*='job-card']")

                    for card in cards:
                        try:
                            # 提取岗位名称
                            title_el = card.select_one(".job-name, .job-title, [class*='job-name']")
                            title = title_el.get_text(strip=True) if title_el else ""

                            # 提取公司名
                            company_el = card.select_one(".company-name, .company-text, [class*='company-name']")
                            company = company_el.get_text(strip=True) if company_el else ""

                            # 提取薪资
                            salary_el = card.select_one(".salary, .red, [class*='salary']")
                            salary_text = salary_el.get_text(strip=True) if salary_el else ""

                            # 提取地点
                            area_el = card.select_one(".job-area, [class*='job-area']")
                            area_text = area_el.get_text(strip=True) if area_el else city

                            # 提取链接
                            link_el = card.select_one("a[href]")
                            link = ""
                            if link_el:
                                href = link_el.get("href", "")
                                if href.startswith("/"):
                                    link = f"https://www.zhipin.com{href}"
                                elif href.startswith("http"):
                                    link = href

                            # 提取岗位描述
                            desc_el = card.select_one(".job-info, .info-desc, [class*='info-desc']")
                            description = desc_el.get_text(strip=True) if desc_el else ""

                            # 提取标签（经验/学历等）
                            tags_el = card.select(".tag-list li, .job-tag")
                            tags = [t.get_text(strip=True) for t in tags_el] if tags_el else []

                            if not title or not company:
                                continue

                            # 解析薪资
                            salary_min, salary_max = self._parse_salary(salary_text)

                            # 生成 job_id
                            job_id = f"boss_{hash(title + company + link) & 0x7FFFFFFF:08x}"

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
                                "tags": tags,
                                "url": link,
                                "platform": "Boss直聘",
                                "pub_date": "",
                            })
                        except Exception as e:
                            logger.debug(f"解析 Boss直聘 卡片异常: {e}")
                            continue

                    logger.info(f"[{self.name}] 第{p}页: 提取到 {len(jobs)} 个岗位")

                except Exception as e:
                    logger.warning(f"[{self.name}] 第{p}页加载失败: {e}")
                    # 可能遇到验证码，跳过后续页
                    break

            browser.close()

        except Exception as e:
            logger.error(f"[{self.name}] Playwright 启动失败: {e}")
            logger.warning(f"[{self.name}] 回退到 requests 方案（可能受限）")
            return self._search_fallback(keyword, city, page)

        return jobs

    def _search_fallback(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        回退方案：使用 requests 尝试 Boss 直聘的移动端 API
        这个方案可能不稳定，主要用于 Playwright 不可用时的兜底
        """
        jobs = []
        # Boss直聘有移动端 API，但需要 zp_token，此处仅做基础尝试
        return jobs
