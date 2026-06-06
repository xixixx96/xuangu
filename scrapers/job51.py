"""
前程无忧/51job 爬虫
前程无忧是最老牌的招聘平台之一，传统行业覆盖面广，也有不少机器人/AI岗位
"""

import json
import logging
import re
from urllib.parse import quote

from .base import BaseScraper

logger = logging.getLogger(__name__)

# 前程无忧城市编码
CITY_CODE = {
    "上海": "020000",
    "杭州": "080200",
    "苏州": "070300",
}


class Job51Scraper(BaseScraper):
    name = "job51"

    def __init__(self, min_delay=3, max_delay=6):
        super().__init__(min_delay, max_delay)

    def _parse_salary(self, text: str) -> tuple:
        """解析: 1.5-3万/月, 15-30K/月 等"""
        # 万/月
        match = re.findall(r"([\d.]+)\s*[-~至]\s*([\d.]+)\s*万/?月?", text)
        if match:
            return int(float(match[0][0]) * 10000), int(float(match[0][1]) * 10000)

        match = re.findall(r"([\d.]+)\s*万/?月?", text)
        if match:
            return int(float(match[0]) * 10000), int(float(match[0]) * 10000)

        # K
        match = re.findall(r"(\d+)\s*[kK]", text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000

        # 千/月: 15-30千/月
        match = re.findall(r"(\d+)\s*[-~至]\s*(\d+)\s*千", text)
        if match:
            return int(match[0][0]) * 1000, int(match[0][1]) * 1000

        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        搜索前程无忧

        URL: https://we.51job.com/pc/search?keyword={keyword}&location={city_code}&page={page}
        或使用移动端 API: https://we.51job.com/api/job/search-pc
        """
        if city not in CITY_CODE:
            logger.warning(f"前程无忧不支持城市: {city}")
            return []

        city_code = CITY_CODE[city]
        jobs = []

        # 使用前程无忧的搜索 API
        api_url = "https://we.51job.com/api/job/search-pc"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Content-Type": "application/json",
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://we.51job.com/",
            "Origin": "https://we.51job.com",
        }

        for p in range(1, page + 1):
            self.delay()
            try:
                # 构建 API 请求参数
                payload = {
                    "keyword": keyword,
                    "location": city_code,
                    "pageNum": str(p),
                    "pageSize": "30",
                    "workYear": "",
                    "salary": "",
                    "degree": "",
                    "companyType": "",
                    "jobArea": city_code,
                }

                resp = self.session.post(
                    api_url,
                    headers=headers,
                    json=payload,
                    timeout=20,
                )

                if resp.status_code == 403 or resp.status_code == 405:
                    logger.warning(f"[{self.name}] 被反爬拦截")
                    # 尝试网页解析回退
                    return self._search_html(keyword, city, city_code, page)

                if resp.status_code != 200:
                    logger.warning(f"[{self.name}] 第{p}页 返回 {resp.status_code}")
                    break

                result = resp.json()

                # 解析返回结果
                items = []
                if isinstance(result, dict):
                    items = (result.get("resultbody", {}) or {}).get("job", {}).get("items", [])
                    if not items:
                        items = result.get("data", {}).get("results", [])
                    if not items:
                        items = result.get("items", [])

                if isinstance(result, list):
                    items = result

                if not items:
                    logger.info(f"[{self.name}] 第{p}页无更多结果，尝试网页解析")
                    return self._search_html(keyword, city, city_code, page)

                for item in items:
                    try:
                        title = item.get("jobName", "") or item.get("job_name", "")
                        company = item.get("coName", "") or item.get("companyName", "")

                        # 51job 薪资字段可能是 provideSalary
                        salary_text = item.get("provideSalary", "") or item.get("salary", "") or ""

                        # 地点
                        area_text = item.get("workAreaName", "") or item.get("workArea", "") or city

                        # 发布日期
                        pub_date = item.get("issueDate", "") or item.get("createDate", "") or ""

                        # 岗位 ID
                        job_id_raw = item.get("jobId", "") or item.get("job_id", "") or item.get("encryptJobId", "")

                        # 岗位链接
                        link = f"https://jobs.51job.com/{city.replace(' ', '')}/{job_id_raw}.html" if job_id_raw else ""

                        # 公司信息
                        company_info_parts = []
                        if item.get("coType"):
                            company_info_parts.append(str(item["coType"]))
                        if item.get("coSize"):
                            company_info_parts.append(str(item["coSize"]))
                        company_info = " | ".join(company_info_parts)

                        # 岗位描述
                        desc_parts = []
                        if item.get("jobWelfare"):
                            desc_parts.append(f"福利: {item['jobWelfare']}")
                        if item.get("attributeText"):
                            desc_parts.extend([str(a) for a in item["attributeText"] if a])
                        description = " | ".join(desc_parts) if desc_parts else ""

                        if not title or not company:
                            continue

                        salary_min, salary_max = self._parse_salary(salary_text)

                        job_id = f"job51_{job_id_raw}"

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
                            "platform": "前程无忧",
                            "pub_date": pub_date,
                        })
                    except Exception as e:
                        logger.debug(f"解析前程无忧岗位异常: {e}")
                        continue

                logger.info(f"[{self.name}] 第{p}页: 提取到 {len(jobs)} 个岗位")

            except json.JSONDecodeError as e:
                logger.warning(f"[{self.name}] JSON解析失败: {e}")
                return self._search_html(keyword, city, city_code, page)
            except Exception as e:
                logger.warning(f"[{self.name}] 第{p}页请求失败: {e}")
                break

        return jobs

    def _search_html(self, keyword: str, city: str, city_code: str, page: int = 1) -> list[dict]:
        """
        网页解析回退方案
        """
        jobs = []
        for p in range(1, page + 1):
            self.delay()
            try:
                url = f"https://we.51job.com/pc/search?keyword={quote(keyword)}&location={city_code}&page={p}"
                resp = self.session.get(url, timeout=20)
                soup = self.soup(resp.text)

                cards = soup.select(".joblist-item, [class*='joblist'] > div, [class*='job-item']")

                for card in cards:
                    try:
                        title_el = card.select_one("[class*='job-name'], .jname, a[class*='title']")
                        title = title_el.get_text(strip=True) if title_el else ""

                        company_el = card.select_one("[class*='company'], .cname, a[class*='company']")
                        company = company_el.get_text(strip=True) if company_el else ""

                        salary_el = card.select_one("[class*='salary'], .sal")
                        salary_text = salary_el.get_text(strip=True) if salary_el else ""

                        area_el = card.select_one("[class*='area'], .area")
                        area_text = area_el.get_text(strip=True) if area_el else city

                        link_el = card.select_one("a[href*='jobs.51job.com']")
                        link = link_el.get("href", "") if link_el else ""

                        if not title or not company:
                            continue

                        salary_min, salary_max = self._parse_salary(salary_text)

                        job_id = f"job51_{hash(title + company + link) & 0x7FFFFFFF:08x}"

                        jobs.append({
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "city": city,
                            "district": area_text.replace(city, "").strip(),
                            "salary_min": salary_min,
                            "salary_max": salary_max,
                            "salary_text": salary_text,
                            "description": "",
                            "url": link,
                            "platform": "前程无忧",
                            "pub_date": "",
                        })
                    except Exception as e:
                        logger.debug(f"解析前程无忧HTML异常: {e}")
                        continue

                logger.info(f"[{self.name}] 第{p}页(HTML): 提取到 {len(jobs)} 个岗位")

            except Exception as e:
                logger.warning(f"[{self.name}] HTML回退失败: {e}")
                break

        return jobs
