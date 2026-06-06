"""
拉勾网爬虫
拉勾网专注于互联网和科技行业招聘，对 AI/技术类岗位覆盖较好
"""

import json
import logging
import re
import time

from .base import BaseScraper

logger = logging.getLogger(__name__)


class LagouScraper(BaseScraper):
    name = "lagou"

    def __init__(self, min_delay=3, max_delay=6):
        super().__init__(min_delay, max_delay)

    def _parse_salary(self, text: str) -> tuple:
        """解析薪资: 15k-25k -> (15000, 25000)"""
        match = re.findall(r"(\d+)\s*[kK]", text)
        if len(match) >= 2:
            return int(match[0]) * 1000, int(match[1]) * 1000
        if len(match) == 1:
            return int(match[0]) * 1000, int(match[0]) * 1000
        return 0, 0

    def search(self, keyword: str, city: str, page: int = 1) -> list[dict]:
        """
        搜索拉勾网

        使用拉勾的公开搜索 API（移动端接口）
        """
        jobs = []

        # 拉勾网搜索 API
        search_url = "https://www.lagou.com/jobs/v2/positionAjax.json"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            "Referer": "https://www.lagou.com/jobs/list_",
            "Origin": "https://www.lagou.com",
            "X-Requested-With": "XMLHttpRequest",
            "X-Anit-Forge-Token": "0",
            "X-Anit-Forge-Code": "0",
        }

        for p in range(1, page + 1):
            self.delay()
            try:
                data = {
                    "first": "true" if p == 1 else "false",
                    "pn": str(p),
                    "kd": keyword,
                    "city": city,
                }

                resp = self.session.post(
                    search_url,
                    headers=headers,
                    data=data,
                    cookies=self._get_cookies(),
                )

                if resp.status_code != 200:
                    logger.warning(f"[{self.name}] 第{p}页 返回 {resp.status_code}")
                    continue

                result = resp.json()

                if result.get("success") is False:
                    logger.warning(f"[{self.name}] API 返回失败: {result.get('msg', '')}")
                    break

                # 拉勾返回的职位在 content.positionResult.result 中
                position_result = result.get("content", {}).get("positionResult", {})
                items = position_result.get("result", [])

                if not items:
                    logger.info(f"[{self.name}] 第{p}页无更多结果")
                    break

                for item in items:
                    try:
                        company = item.get("companyFullName", "")
                        title = item.get("positionName", "")
                        salary_text = item.get("salary", "")
                        district = item.get("district", "")
                        position_id = item.get("positionId", "")

                        salary_min, salary_max = self._parse_salary(salary_text)

                        desc = ""
                        # 尝试获取详细描述
                        desc_parts = []
                        if item.get("positionAdvantage"):
                            desc_parts.append(item["positionAdvantage"])
                        if item.get("industryField"):
                            desc_parts.append(item["industryField"])
                        desc = " | ".join(desc_parts)

                        job_id = f"lagou_{position_id}"

                        jobs.append({
                            "job_id": job_id,
                            "title": title,
                            "company": company,
                            "city": city,
                            "district": district,
                            "salary_min": salary_min,
                            "salary_max": salary_max,
                            "salary_text": salary_text,
                            "description": desc,
                            "url": f"https://www.lagou.com/jobs/{position_id}.html",
                            "platform": "拉勾网",
                            "pub_date": item.get("createTime", ""),
                            "tags": item.get("positionLables", []),
                        })
                    except Exception as e:
                        logger.debug(f"解析拉勾岗位异常: {e}")
                        continue

                logger.info(f"[{self.name}] 第{p}页: {len(items)} 个岗位")

            except json.JSONDecodeError as e:
                logger.warning(f"[{self.name}] JSON 解析失败: {e}")
                # 可能遇到验证码页面
                break
            except Exception as e:
                logger.error(f"[{self.name}] 第{p}页请求异常: {e}")
                break

        return jobs

    def _get_cookies(self) -> dict:
        """获取拉勾需要的 cookies"""
        # 拉勾需要先访问主页获取 cookie
        if not hasattr(self, "_lagou_cookies"):
            try:
                resp = self.session.get(
                    "https://www.lagou.com/",
                    headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
                    timeout=15,
                )
                self._lagou_cookies = dict(resp.cookies)
            except Exception:
                self._lagou_cookies = {}
        return self._lagou_cookies
