#!/usr/bin/env python3
"""
AI/机器人行业招聘信息抓取与推送机器人（并行优化版）

5 个平台并行抓取，整体 10 分钟内完成。
"""

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    WECOM_WEBHOOK_URL,
    TARGET_CITIES,
    JOB_KEYWORDS,
    MIN_SALARY,
    MAX_JOBS_PER_PUSH,
    DEDUP_DAYS,
    LOG_LEVEL,
    DATA_DIR,
    SEEN_JOBS_FILE,
    COMPANY_CACHE_FILE,
    INDUSTRY_KEYWORDS,
)
from modules.company_check import check_company
from modules.storage import filter_new_jobs, mark_all_seen
from modules.formatter import format_daily_report, format_test_message
from modules.pusher import WecomPusher

os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "logs", "run.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("job_bot")


# ========== 并行抓取 ==========

SCRAPERS = {
    "Boss直聘": ("scrapers.boss_zhipin", "BossZhipinScraper"),
    "拉勾网": ("scrapers.lagou", "LagouScraper"),
    "猎聘": ("scrapers.liepin", "LiepinScraper"),
    "智联招聘": ("scrapers.zhilian", "ZhilianScraper"),
    "前程无忧": ("scrapers.job51", "Job51Scraper"),
}


def _scrape_one(platform_name: str) -> list[dict]:
    """单平台抓取（在线程中执行）"""
    mod_path, cls_name = SCRAPERS[platform_name]
    try:
        import importlib
        mod = importlib.import_module(mod_path)
        cls = getattr(mod, cls_name)
        scraper = cls(min_delay=1, max_delay=3)
        return scraper.search_all(TARGET_CITIES, JOB_KEYWORDS)
    except Exception as e:
        logger.error(f"[{platform_name}] 抓取失败: {e}")
        return []


def scrape_all_parallel() -> list[dict]:
    """5 个平台并行抓取"""
    all_jobs = []
    logger.info(f"🚀 并行抓取 {len(SCRAPERS)} 个平台 ({'、'.join(SCRAPERS)})")
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_scrape_one, name): name for name in SCRAPERS}
        for future in as_completed(futures):
            name = futures[future]
            try:
                jobs = future.result()
                logger.info(f"  ✅ {name}: {len(jobs)} 个岗位")
                all_jobs.extend(jobs)
            except Exception as e:
                logger.error(f"  ❌ {name}: {e}")
    logger.info(f"并行抓取完成 → {len(all_jobs)} 个原始岗位")
    return all_jobs


# ========== 过滤 ==========

def filter_by_salary(jobs: list[dict]) -> list[dict]:
    """薪资 ≥ MIN_SALARY"""
    result = [j for j in jobs if max(j.get("salary_max", 0), j.get("salary_min", 0)) >= MIN_SALARY]
    logger.info(f"薪资过滤(≥{MIN_SALARY//1000}K): {len(result)}/{len(jobs)}")
    return result


def filter_by_industry(jobs: list[dict]) -> list[dict]:
    """行业相关性二次过滤"""
    result = []
    for j in jobs:
        title = j.get("title", "")
        text = f"{title} {j.get('description', '')} {j.get('company_info', '')}"
        if any(kw in text for kw in INDUSTRY_KEYWORDS):
            result.append(j)
        elif any(t in title for t in ["产品经理", "解决方案", "方案工程师"]):
            result.append(j)
    logger.info(f"行业过滤: {len(result)}/{len(jobs)}")
    return result


# ========== 财务检查（并行） ==========

def check_companies_parallel(jobs: list[dict]) -> tuple[list[dict], int]:
    """并行财务检查"""
    companies = list(set(j.get("company", "").strip() for j in jobs if j.get("company", "").strip()))
    if not companies:
        return jobs, 0

    logger.info(f"财务检查 {len(companies)} 家公司（并行）...")
    results = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(check_company, c): c for c in companies}
        for future in as_completed(futures):
            c = futures[future]
            try:
                results[c] = future.result(timeout=15)
            except Exception as e:
                logger.warning(f"检查失败 {c}: {e}")
                results[c] = None
            time.sleep(0.3)

    passed, excluded = [], 0
    for j in jobs:
        s = results.get(j.get("company", "").strip())
        if s and s.get("excluded"):
            excluded += 1
            logger.info(f"  ❌ {j['company']}: {s.get('reason', '')}")
        else:
            j["company_status"] = s
            passed.append(j)

    logger.info(f"财务检查: {len(passed)} 通过, {excluded} 排除")
    return passed, excluded


# ========== 推送 ==========

def _push_fallback(date_str: str, reason: str):
    """推送空结果通知"""
    pusher = WecomPusher(WECOM_WEBHOOK_URL)
    msg = (
        f"## 🤖 AI/机器人岗位日报 | {date_str}\n\n"
        f"> 📍 {' · '.join(TARGET_CITIES)}\n"
        f"> ⚠️ {reason}\n"
        f"> 明天下午3点继续 👋"
    )
    pusher.send_markdown(msg)


# ========== 主流程 ==========

def run_daily():
    start = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"{'='*50}\n🚀 岗位日报 {date_str} 开始")

    # 1. 并行抓取
    all_jobs = scrape_all_parallel()
    if not all_jobs:
        _push_fallback(date_str, "所有平台均未抓取到岗位数据")
        return

    # 2. 薪资过滤
    jobs = filter_by_salary(all_jobs)

    # 3. 去重
    jobs = filter_new_jobs(jobs, SEEN_JOBS_FILE, DEDUP_DAYS)

    # 4. 财务检查
    jobs, excluded = check_companies_parallel(jobs)

    # 5. 行业过滤
    jobs = filter_by_industry(jobs)

    # 6. 截断 + 推送
    if len(jobs) > MAX_JOBS_PER_PUSH:
        jobs = jobs[:MAX_JOBS_PER_PUSH]

    platforms_used = list(set(j.get("platform", "") for j in jobs))
    markdown = format_daily_report(
        jobs, date_str=date_str, excluded_count=excluded,
        platforms=platforms_used, cities=TARGET_CITIES,
    )

    pusher = WecomPusher(WECOM_WEBHOOK_URL)
    if pusher.send_job_report(markdown):
        mark_all_seen(jobs, SEEN_JOBS_FILE)
        logger.info(f"✅ 完成！{time.time()-start:.0f}s | 推送{len(jobs)}个 | 排除{excluded}个")
    else:
        logger.error("❌ 推送失败")


def run_test():
    ok = WecomPusher(WECOM_WEBHOOK_URL).send_markdown(format_test_message())
    logger.info("✅ 测试发送成功" if ok else "❌ 测试发送失败")


def run_dry():
    all_jobs = scrape_all_parallel()
    jobs = filter_by_salary(all_jobs)
    jobs = filter_new_jobs(jobs, SEEN_JOBS_FILE, DEDUP_DAYS)
    jobs, exc = check_companies_parallel(jobs)
    jobs = filter_by_industry(jobs)
    print(f"\n{'='*50}\n{len(jobs)} 个岗位（排除 {exc} 家风险公司）\n{'='*50}")
    for i, j in enumerate(jobs, 1):
        print(f"{i}. {j['title']} @ {j['company']} | {j.get('salary_text','')} | {j['city']}|{j['platform']}")


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
