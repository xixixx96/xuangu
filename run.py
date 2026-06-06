#!/usr/bin/env python3
"""
AI/机器人行业招聘推送（极速版）

每天只需推送 3 个岗位，凑够即停。
"""

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    WECOM_WEBHOOK_URL,
    TARGET_CITIES,
    JOB_KEYWORDS,
    MIN_SALARY,
    DEDUP_DAYS,
    LOG_LEVEL,
    DATA_DIR,
    SEEN_JOBS_FILE,
    INDUSTRY_KEYWORDS,
)
from modules.company_check import check_company
from modules.storage import filter_new_jobs, mark_all_seen, is_seen
from modules.formatter import format_daily_report, format_test_message
from modules.pusher import WecomPusher

os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=getattr(logging, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "logs", "run.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")

TARGET_COUNT = 3  # 每天只推送 3 个
SCRAPE_TIMEOUT = 120  # 单平台最多等 2 分钟


def _scrape_platform(mod_path: str, cls_name: str) -> list[dict]:
    """抓单个平台，每个城市只搜 1 个综合关键词，只取第 1 页"""
    import importlib
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    scraper = cls(min_delay=0.5, max_delay=1.5)
    return scraper.search_all(TARGET_CITIES, JOB_KEYWORDS)


def _check_one_company(name: str) -> dict | None:
    """检查一家公司"""
    try:
        return check_company(name)
    except Exception as e:
        logger.warning(f"企查查失败 {name}: {e}")
        return None


def _is_good_job(job: dict) -> bool:
    """判断岗位是否符合要求"""
    title = job.get("title", "")
    text = f"{title} {job.get('description', '')} {job.get('company_info', '')}"
    if not any(kw in text for kw in INDUSTRY_KEYWORDS):
        if not any(t in title for t in ["产品经理", "解决方案", "方案工程师"]):
            return False
    if max(job.get("salary_max", 0), job.get("salary_min", 0)) < MIN_SALARY:
        return False
    if not job.get("company", "").strip():
        return False
    return True


def _check_company_ok(company: str) -> bool:
    """快速检查公司是否OK（不排除=OK）"""
    status = _check_one_company(company)
    return not (status and status.get("excluded"))


def _process_job(job: dict) -> dict | None:
    """对单个岗位做完整检查，通过返回带 status 的 job，否则返回 None"""
    if is_seen(job):
        return None
    if not _is_good_job(job):
        return None

    company = job["company"].strip()
    status = _check_one_company(company)
    if status and status.get("excluded"):
        logger.info(f"  ❌ {company}: {status.get('reason', '风险')}")
        return None

    job["company_status"] = status
    return job


def run_daily():
    start = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"🚀 岗位日报 {date_str}（目标: {TARGET_COUNT} 个）")

    # 平台列表：按可靠性排序，最靠谱的放前面
    platforms = [
        ("Boss直聘", "scrapers.boss_zhipin", "BossZhipinScraper"),
        ("拉勾网", "scrapers.lagou", "LagouScraper"),
        ("猎聘", "scrapers.liepin", "LiepinScraper"),
        ("前程无忧", "scrapers.job51", "Job51Scraper"),
        ("智联招聘", "scrapers.zhilian", "ZhilianScraper"),
    ]

    good_jobs = []       # 最终推送的岗位
    excluded_count = 0   # 被财务过滤掉的
    seen_companies = set()
    seen_job_ids = set()

    # 逐个平台抓取，凑够就停
    for platform_name, mod_path, cls_name in platforms:
        if len(good_jobs) >= TARGET_COUNT:
            break

        logger.info(f"--- {platform_name} ---")
        try:
            raw = _scrape_platform(mod_path, cls_name)
            logger.info(f"  抓到 {len(raw)} 个原始岗位")

            for job in raw:
                if len(good_jobs) >= TARGET_COUNT:
                    break

                # 去重
                jid = f"{platform_name}:{job.get('job_id', '')}"
                if jid in seen_job_ids:
                    continue
                seen_job_ids.add(jid)

                # 检查
                result = _process_job(job)
                if result is None:
                    excluded_count += 1
                    continue

                good_jobs.append(result)
                logger.info(f"  ✅ #{len(good_jobs)} {result['title']} @ {result['company']} | {result.get('salary_text', '')}")

            logger.info(f"  {platform_name} 贡献 {len(good_jobs)} 个（累计）")

        except Exception as e:
            logger.warning(f"  {platform_name} 失败: {e}")

    # 推送
    logger.info(f"{'='*40}\n总计: {len(good_jobs)} 个推送, {excluded_count} 个被过滤, 耗时 {time.time()-start:.0f}s")

    if good_jobs:
        markdown = format_daily_report(
            good_jobs, date_str=date_str, excluded_count=excluded_count,
            platforms=list(set(j.get("platform", "") for j in good_jobs)),
            cities=TARGET_CITIES,
        )
        pusher = WecomPusher(WECOM_WEBHOOK_URL)
        if pusher.send_job_report(markdown):
            mark_all_seen(good_jobs, SEEN_JOBS_FILE)
            logger.info("✅ 推送成功")
        else:
            logger.error("❌ 推送失败")
    else:
        WecomPusher(WECOM_WEBHOOK_URL).send_markdown(
            f"## 🤖 AI/机器人岗位日报 | {date_str}\n\n"
            f"> 📍 {' · '.join(TARGET_CITIES)} | ⚠️ 今日无匹配岗位\n"
            f"> 明天下午3点继续 👋"
        )


def run_test():
    ok = WecomPusher(WECOM_WEBHOOK_URL).send_markdown(format_test_message())
    print("✅ 测试发送成功" if ok else "❌ 测试发送失败")


def run_dry():
    date_str = datetime.now().strftime("%Y-%m-%d")
    good = []
    for name, mod_path, cls_name in [
        ("Boss直聘", "scrapers.boss_zhipin", "BossZhipinScraper"),
        ("拉勾网", "scrapers.lagou", "LagouScraper"),
    ]:
        try:
            raw = _scrape_platform(mod_path, cls_name)
            print(f"{name}: {len(raw)} 个原始岗位")
            for j in raw[:5]:
                print(f"  - {j.get('title')} @ {j.get('company')} | {j.get('salary_text', '')} | {j.get('city')}")
        except Exception as e:
            print(f"{name}: 失败 - {e}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--test", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if args.test:
        run_test()
    elif args.dry_run:
        run_dry()
    else:
        run_daily()


if __name__ == "__main__":
    main()
