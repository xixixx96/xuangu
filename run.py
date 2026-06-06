#!/usr/bin/env python3
"""
AI/机器人行业招聘信息抓取与推送机器人

每天运行一次，抓取 5 大招聘平台上 AI/具身智能/机器人行业的产品经理
和解决方案工程师岗位，经过公司财务健康检查后，通过企业微信推送日报。

用法:
    python run.py              # 正常运行（抓取+推送）
    python run.py --test       # 发送测试消息到企业微信
    python run.py --dry-run    # 抓取但不推送，打印结果
    python run.py --setup      # 初始化环境
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    WECOM_WEBHOOK_URL,
    TARGET_CITIES,
    JOB_KEYWORDS,
    MIN_SALARY,
    MAX_PAGES_PER_PLATFORM,
    MAX_JOBS_PER_PUSH,
    DEDUP_DAYS,
    LOG_LEVEL,
    DATA_DIR,
    SEEN_JOBS_FILE,
    COMPANY_CACHE_FILE,
)
from scrapers.boss_zhipin import BossZhipinScraper
from scrapers.lagou import LagouScraper
from scrapers.liepin import LiepinScraper
from scrapers.zhilian import ZhilianScraper
from scrapers.job51 import Job51Scraper
from modules.company_check import check_company
from modules.storage import filter_new_jobs, mark_all_seen, get_stats
from modules.formatter import format_daily_report, format_test_message
from modules.pusher import WecomPusher

# 日志配置
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


def setup_playwright():
    """安装 Playwright 浏览器"""
    logger.info("正在安装 Playwright 浏览器...")
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            logger.info(f"Playwright 已就绪，浏览器: {p.chromium}")
        logger.info("Playwright 安装完成")
    except Exception as e:
        logger.error(f"Playwright 安装失败: {e}")
        logger.info("请手动运行: playwright install chromium")


def scrape_all_platforms(cities: list[str], keywords: list[str]) -> list[dict]:
    """在所有平台抓取岗位"""
    scrapers = [
        BossZhipinScraper(min_delay=5, max_delay=10),
        LagouScraper(min_delay=3, max_delay=6),
        LiepinScraper(min_delay=4, max_delay=8),
        ZhilianScraper(min_delay=3, max_delay=7),
        Job51Scraper(min_delay=3, max_delay=6),
    ]

    all_jobs = []
    for scraper in scrapers:
        try:
            logger.info(f"=" * 50)
            logger.info(f"开始抓取: {scraper.name}")
            jobs = scraper.search_all(cities, keywords)
            logger.info(f"{scraper.name} 共抓取 {len(jobs)} 个岗位")
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"{scraper.name} 抓取失败: {e}")
            continue

    return all_jobs


def filter_by_salary(jobs: list[dict], min_salary: int) -> list[dict]:
    """按最低薪资过滤"""
    filtered = []
    skipped = 0
    for job in jobs:
        salary_max = job.get("salary_max", 0)
        salary_min = job.get("salary_min", 0)
        # 如果薪资上限达到最低要求，或薪资下限达到最低要求
        if salary_max >= min_salary or salary_min >= min_salary:
            filtered.append(job)
        else:
            skipped += 1
    logger.info(f"薪资过滤 (>= {min_salary//1000}K): 保留 {len(filtered)} 个，跳过 {skipped} 个")
    return filtered


def check_companies(jobs: list[dict]) -> tuple[list[dict], int]:
    """
    对公司进行财务健康检查

    Returns:
        (通过检查的岗位列表, 被排除的岗位数)
    """
    passed = []
    excluded = 0

    # 先收集所有公司名并去重
    companies_to_check = {}
    for job in jobs:
        company = job.get("company", "").strip()
        if company and company not in companies_to_check:
            companies_to_check[company] = None

    logger.info(f"需要检查 {len(companies_to_check)} 家公司")

    # 逐家检查
    for i, company in enumerate(companies_to_check, 1):
        logger.info(f"[{i}/{len(companies_to_check)}] 检查: {company}")
        status = check_company(company)
        companies_to_check[company] = status
        time.sleep(1)  # 避免请求过快

    # 应用检查结果
    for job in jobs:
        company = job.get("company", "").strip()
        status = companies_to_check.get(company)

        if status and status.get("excluded"):
            excluded += 1
            logger.info(f"排除: {company} - {status.get('reason', '财务风险')}")
            continue

        job["company_status"] = status
        passed.append(job)

    logger.info(f"财务检查: 通过 {len(passed)} 个，排除 {excluded} 个")
    return passed, excluded


def filter_by_industry(jobs: list[dict]) -> list[dict]:
    """
    根据行业关键词二次过滤，确保岗位确实属于 AI/机器人行业
    因为关键词搜索可能返回不太相关的岗位
    """
    from config import INDUSTRY_KEYWORDS

    filtered = []
    for job in jobs:
        title = job.get("title", "")
        description = job.get("description", "")
        company_info = job.get("company_info", "")
        tags = " ".join(job.get("tags", []))
        text = f"{title} {description} {company_info} {tags}"

        # 检查是否匹配行业关键词
        matched = any(kw in text for kw in INDUSTRY_KEYWORDS)
        if matched:
            filtered.append(job)
        else:
            # 没有直接匹配，但标题包含产品经理/解决方案等目标岗位词也保留
            target_jobs = ["产品经理", "解决方案", "方案工程师", "产品总监"]
            if any(t in title for t in target_jobs):
                filtered.append(job)

    logger.info(f"行业过滤: 保留 {len(filtered)}/{len(jobs)} 个岗位")
    return filtered


def run_test():
    """发送测试消息"""
    pusher = WecomPusher(WECOM_WEBHOOK_URL)
    content = format_test_message()
    success = pusher.send_markdown(content)
    if success:
        logger.info("✅ 测试消息发送成功！请检查企业微信群")
    else:
        logger.error("❌ 测试消息发送失败，请检查 Webhook URL")
    return success


def run_daily():
    """执行每日推送任务"""
    start_time = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=" * 60)
    logger.info(f"🚀 AI/机器人行业岗位日报 | {date_str} | 开始运行")
    logger.info(f"=" * 60)

    # Step 1: 抓取所有平台
    logger.info("[Step 1/6] 多平台抓取岗位...")
    all_jobs = scrape_all_platforms(TARGET_CITIES, JOB_KEYWORDS)
    logger.info(f"共抓取原始岗位: {len(all_jobs)} 个")

    if not all_jobs:
        logger.warning("未抓取到任何岗位，可能所有平台均受限")
        # 仍然发送一条消息通知
        pusher = WecomPusher(WECOM_WEBHOOK_URL)
        msg = f"## 🤖 AI/机器人岗位日报 | {date_str}\n\n> ⚠️ 今日未成功抓取到岗位数据\n> 可能原因：平台反爬限制\n> 系统会继续尝试，明天下午3点再见 👋"
        pusher.send_markdown(msg)
        return

    # Step 2: 薪资过滤
    logger.info("[Step 2/6] 薪资过滤...")
    jobs = filter_by_salary(all_jobs, MIN_SALARY)

    # Step 3: 去重
    logger.info("[Step 3/6] 去重检查...")
    jobs = filter_new_jobs(jobs, SEEN_JOBS_FILE, DEDUP_DAYS)

    # Step 4: 财务检查
    logger.info("[Step 4/6] 公司财务健康检查...")
    jobs, excluded_count = check_companies(jobs)

    # Step 5: 行业二次过滤
    logger.info("[Step 5/6] 行业相关性过滤...")
    jobs = filter_by_industry(jobs)

    # 限制推送数量
    if len(jobs) > MAX_JOBS_PER_PUSH:
        logger.info(f"岗位数 {len(jobs)} 超过限制 {MAX_JOBS_PER_PUSH}，优先推送最新岗位")
        jobs = jobs[:MAX_JOBS_PER_PUSH]

    # Step 6: 格式化 & 推送
    logger.info("[Step 6/6] 生成日报并推送...")
    platforms_used = list(set(j.get("platform", "") for j in jobs))
    markdown = format_daily_report(
        jobs,
        date_str=date_str,
        excluded_count=excluded_count,
        platforms=platforms_used,
        cities=TARGET_CITIES,
    )

    pusher = WecomPusher(WECOM_WEBHOOK_URL)
    success = pusher.send_job_report(markdown)

    if success:
        # 标记为已推送
        mark_all_seen(jobs, SEEN_JOBS_FILE)
        elapsed = time.time() - start_time
        logger.info(f"✅ 日报推送成功！耗时 {elapsed:.0f} 秒")
        logger.info(f"   推送岗位: {len(jobs)} 个")
        logger.info(f"   排除财务风险: {excluded_count} 个")
    else:
        logger.error("❌ 日报推送失败")

    # 打印统计
    stats = get_stats(SEEN_JOBS_FILE)
    logger.info(f"已推送历史: 共记录 {stats['total_seen']} 个岗位")


def run_dry():
    """Dry-run 模式：抓取但不推送"""
    logger.info("=== Dry-Run 模式 ===")
    all_jobs = scrape_all_platforms(TARGET_CITIES, JOB_KEYWORDS)
    logger.info(f"共抓取原始岗位: {len(all_jobs)} 个")
    jobs = filter_by_salary(all_jobs, MIN_SALARY)
    jobs = filter_new_jobs(jobs, SEEN_JOBS_FILE, DEDUP_DAYS)
    jobs, excluded = check_companies(jobs)
    jobs = filter_by_industry(jobs)

    print("\n" + "=" * 60)
    print(f"共 {len(jobs)} 个岗位通过筛选（排除 {excluded} 个财务风险公司）")
    print("=" * 60)
    for i, job in enumerate(jobs, 1):
        print(f"\n{i}. {job['title']} @ {job['company']}")
        print(f"   薪资: {job.get('salary_text', 'N/A')}")
        print(f"   地点: {job.get('city', '')} {job.get('district', '')}")
        print(f"   平台: {job.get('platform', '')}")
        status = job.get("company_status", {})
        if status:
            print(f"   财务: 司法案件{status.get('lawsuits', '?')}条 | 异常:{status.get('abnormal', '?')}")
        print(f"   链接: {job.get('url', '')}")


def main():
    parser = argparse.ArgumentParser(description="AI/机器人行业招聘推送机器人")
    parser.add_argument("--test", action="store_true", help="发送测试消息到企业微信")
    parser.add_argument("--dry-run", action="store_true", help="抓取但不推送，打印结果")
    parser.add_argument("--setup", action="store_true", help="初始化环境")
    args = parser.parse_args()

    if args.setup:
        setup_playwright()
    elif args.test:
        run_test()
    elif args.dry_run:
        run_dry()
    else:
        run_daily()


if __name__ == "__main__":
    main()
