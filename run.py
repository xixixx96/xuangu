#!/usr/bin/env python3
"""
AI/机器人行业招聘推送机器人

每天从 5 个平台抓取岗位，经过：
  1. 薪资过滤 (≥25K)
  2. 行业匹配 (AI/具身智能/机器人)
  3. 去重检查 (30天内不重复)
  4. 财务检查 (企查查 + 预置数据)
  5. 公司评分排序 (B轮及以上优先)
  6. 5选3精选推送
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
    DEDUP_DAYS,
    DATA_DIR,
    SEEN_JOBS_FILE,
    INDUSTRY_KEYWORDS,
)
from modules.company_check import check_company
from modules.storage import is_seen, mark_all_seen
from modules.formatter import format_daily_report, format_test_message
from modules.pusher import WecomPusher

os.makedirs(os.path.join(DATA_DIR, "logs"), exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(DATA_DIR, "logs", "run.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("bot")


# ============================================================
#  公司评分引擎
# ============================================================

# 融资阶段分数：B轮及以上是好公司的基础门槛
FUNDING_SCORE = {
    "已上市": 100,
    "pre-ipo": 98,
    "e轮": 95, "e+轮": 96,
    "d轮": 90, "d+轮": 92,
    "c轮": 82, "c+轮": 85,
    "b轮": 70, "b+轮": 75,
    "a轮": 45, "a+轮": 50,
    "天使轮": 25, "pre-a轮": 30, "种子轮": 20,
    "未融资": 0,
}


def _calc_company_score(job: dict, status: dict | None) -> int:
    """
    综合评分 0-100
    基础分来自 funding，加分项来自薪资、行业匹配度等
    """
    score = 0

    # 1. 融资阶段评分 (权重 60%)
    if status:
        funding_raw = status.get("funding", "").strip().lower()
        # 模糊匹配
        for key, val in sorted(FUNDING_SCORE.items(), key=lambda x: -len(x[0])):
            if key in funding_raw or funding_raw in key:
                score += int(val * 0.6)
                break
        else:
            score += 25  # 未知融资阶段给低分

        # 如果预置数据有 score 字段直接用
        if "score" in status:
            score = status["score"]
    else:
        score += 25  # 无财务数据，偏低

    # 2. 薪资加分 (权重 20%)
    salary_max = job.get("salary_max", 0)
    if salary_max >= 50000:
        score += 20
    elif salary_max >= 40000:
        score += 16
    elif salary_max >= 35000:
        score += 12
    elif salary_max >= 30000:
        score += 8
    elif salary_max >= 25000:
        score += 4

    # 3. 岗位匹配加分 (权重 10%)
    title = job.get("title", "")
    desc = job.get("description", "")

    high_match = ["具身智能", "人形机器人", "大模型", "agi", "自动驾驶"]
    mid_match = ["机器人", "ai产品", "人工智能", "智能硬件", "slam"]

    for kw in high_match:
        if kw.lower() in (title + desc).lower():
            score += 6
            break

    for kw in mid_match:
        if kw.lower() in (title + desc).lower():
            score += 3
            break

    # 4. 城市加分 (权重 5%) - 上海岗位更多更优质
    city = job.get("city", "")
    if city == "上海":
        score += 5
    elif city == "杭州":
        score += 3
    elif city == "苏州":
        score += 1

    # 5. 司法案件扣分
    if status:
        lawsuits = status.get("lawsuits", 0)
        if lawsuits > 3:
            score -= 10
        elif lawsuits > 1:
            score -= 3

    return max(0, min(100, score))  # clamp to 0-100


# ============================================================
#  核心逻辑
# ============================================================

SCRAPERS = [
    ("Boss直聘", "scrapers.boss_zhipin", "BossZhipinScraper"),
    ("拉勾网", "scrapers.lagou", "LagouScraper"),
    ("猎聘", "scrapers.liepin", "LiepinScraper"),
    ("前程无忧", "scrapers.job51", "Job51Scraper"),
    ("智联招聘", "scrapers.zhilian", "ZhilianScraper"),
]


def _scrape_platform(mod_path: str, cls_name: str) -> list[dict]:
    import importlib
    mod = importlib.import_module(mod_path)
    cls = getattr(mod, cls_name)
    scraper = cls(min_delay=0.5, max_delay=1.5)
    return scraper.search_all(TARGET_CITIES, JOB_KEYWORDS)


def run_daily():
    start = time.time()
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"🚀 岗位日报 {date_str}（目标：精选 3 个）")

    # ====== Phase 1: 5个平台全部抓完，收集所有候选 ======
    candidates = []  # 所有候选岗位（已验证通过）
    excluded_count = 0
    seen_job_ids = set()
    seen_companies = set()

    for platform_name, mod_path, cls_name in SCRAPERS:
        logger.info(f"--- {platform_name} ---")
        try:
            raw = _scrape_platform(mod_path, cls_name)
            logger.info(f"  抓到 {len(raw)} 个原始岗位")

            for job in raw:
                # 去重（30天窗口 + 本次运行内去重）
                jid = f"{platform_name}:{job.get('job_id', '')}"
                if jid in seen_job_ids or is_seen(job, SEEN_JOBS_FILE, DEDUP_DAYS):
                    continue
                seen_job_ids.add(jid)

                # 薪资过滤
                salary = max(job.get("salary_max", 0), job.get("salary_min", 0))
                if salary < MIN_SALARY:
                    continue

                # 行业过滤
                title = job.get("title", "")
                text = f"{title} {job.get('description', '')} {job.get('company_info', '')}"
                industry_ok = any(kw in text for kw in INDUSTRY_KEYWORDS)
                if not industry_ok:
                    if not any(t in title for t in ["产品经理", "解决方案", "方案工程师"]):
                        continue

                # 公司财务检查
                company = job.get("company", "").strip()
                if not company:
                    continue

                if company not in seen_companies:
                    status = check_company(company)
                    seen_companies.add(company)
                else:
                    # 同一家公司已查过，用缓存
                    status = None  # 会在下面从缓存读

                # 重新获取状态（确保同一 run 内复用）
                status = check_company(company)  # check_company 自带缓存

                if status and status.get("excluded"):
                    excluded_count += 1
                    logger.info(f"  ❌ {company}: {status.get('reason', '风险')}")
                    continue

                # 计算评分
                score = _calc_company_score(job, status)

                job["company_status"] = status
                job["_score"] = score
                candidates.append(job)

        except Exception as e:
            logger.warning(f"  {platform_name} 异常: {e}")

    logger.info(f"{'='*40}")
    logger.info(f"Phase 1 完成: {len(candidates)} 个候选 | {excluded_count} 个被财务排除")

    # ====== Phase 2: 5选3 精选 ======
    # 规则：
    #   1. 优先选 B 轮及以上（score >= 70）
    #   2. 同一家公司最多推 1 个岗位
    #   3. 按评分排序取 top 3
    #   4. 如果 B 轮以上不够 3 个，降低门槛补足

    # 按评分排序
    candidates.sort(key=lambda j: j["_score"], reverse=True)

    # 去重公司：同一公司只保留评分最高的那个岗位
    company_picks = {}
    for job in candidates:
        company = job.get("company", "").strip()
        if company not in company_picks:
            company_picks[company] = job

    # 按评分重新排序
    unique_jobs = sorted(company_picks.values(), key=lambda j: j["_score"], reverse=True)

    # 分级精选
    top_tier = [j for j in unique_jobs if j["_score"] >= 70]   # B轮及以上
    mid_tier = [j for j in unique_jobs if 50 <= j["_score"] < 70]
    low_tier = [j for j in unique_jobs if j["_score"] < 50]

    # 优先从 top_tier 选 3 个，不够再从中层补
    picks = top_tier[:3]
    if len(picks) < 3:
        picks += mid_tier[:3 - len(picks)]
    if len(picks) < 3:
        picks += low_tier[:3 - len(picks)]

    # 最终去重：确保同公司在一次推送里只出现一次
    final_picks = []
    picked_companies = set()
    for job in picks:
        c = job.get("company", "").strip()
        if c not in picked_companies:
            picked_companies.add(c)
            final_picks.append(job)
        if len(final_picks) >= 3:
            break

    # 打印精选结果
    logger.info(f"Phase 2 精选:")
    for i, job in enumerate(final_picks, 1):
        s = job["_score"]
        funding = (job.get("company_status") or {}).get("funding", "?")
        logger.info(f"  🏆 #{i} [{s}分|{funding}] {job['title']} @ {job['company']} | {job.get('salary_text','')} | {job['city']}")

    # ====== Phase 3: 推送 ======
    elapsed = time.time() - start
    logger.info(f"推送 {len(final_picks)} 个岗位 | 耗时 {elapsed:.0f}s")

    if final_picks:
        markdown = format_daily_report(
            final_picks, date_str=date_str, excluded_count=excluded_count,
            platforms=list(set(j.get("platform", "") for j in final_picks)),
            cities=TARGET_CITIES,
        )
        pusher = WecomPusher(WECOM_WEBHOOK_URL)
        if pusher.send_job_report(markdown):
            mark_all_seen(final_picks, SEEN_JOBS_FILE)
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
    print("Dry-run 模式...")
    for name, mod_path, cls_name in SCRAPERS[:2]:
        try:
            raw = _scrape_platform(mod_path, cls_name)
            print(f"\n{name}: {len(raw)} 个原始岗位")
            for j in raw[:3]:
                print(f"  - {j.get('title')} @ {j.get('company')} | {j.get('salary_text','')} | {j.get('city')}")
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
