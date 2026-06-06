"""
主入口 —— 编排选股 + AI分析 + 微信推送全流程

用法:
    python src/main.py                    # 日常推送（短线+波段）
    python src/main.py --mode value       # 仅价值策略
    python src/main.py --mode all         # 全部三种策略
"""

import argparse
import logging
import sys
from datetime import datetime

from config import is_trade_day, is_monday, OUTPUT_DIR
from screener import run_screening, run_value_screening
from analyzer import call_ai_analysis
from push_wechat import push_strategy_pick

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("main")


def save_report(strategy_name: str, analysis_text: str, date_str: str) -> str:
    """保存分析报告到 output 目录"""
    fname = f"{date_str}_{strategy_name}.txt"
    path = f"{OUTPUT_DIR}/{fname}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(analysis_text)
    return path


# ============================================================
# 日常推送（短线 + 波段）
# ============================================================

def run_daily():
    """每个交易日上午推送 短线 + 波段"""
    if not is_trade_day():
        logger.info("非交易日，跳过推送")
        return

    logger.info("=" * 50)
    logger.info("开始每日选股 (%s)", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 50)

    results = run_screening(strategies=("scalping", "swing"))
    today_str = datetime.now().strftime("%Y%m%d")

    strategies_map = [
        ("scalping", "⚡", "短线交易"),
        ("swing", "\U0001f4c8", "波段操作"),
    ]

    for strategy_key, emoji, label in strategies_map:
        candidates = results.get(strategy_key, [])
        if not candidates:
            logger.warning("%s 策略无候选标的", label)
            continue

        logger.info("%s 策略候选: %s", label, [f"{c.code} {c.name}" for c in candidates])

        analysis = call_ai_analysis(candidates, strategy_key)
        save_report(strategy_key, analysis, today_str)
        push_strategy_pick(label, emoji, candidates, analysis)

    logger.info("每日推送完成")


# ============================================================
# 下午盘中推送（短线更新 + 行情提醒）
# ============================================================

def run_afternoon():
    """下午 2:00 推送 行情提醒 + 短线更新 + 波段更新"""
    if not is_trade_day():
        logger.info("非交易日，跳过下午推送")
        return

    logger.info("=" * 50)
    logger.info("开始下午盘中推送 (%s)", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 50)

    results = run_screening(strategies=("scalping", "swing"))
    today_str = datetime.now().strftime("%Y%m%d")

    for strategy_key, emoji, label in [("scalping", "⚡", "短线交易"), ("swing", "📈", "波段操作")]:
        candidates = results.get(strategy_key, [])
        if not candidates:
            logger.warning("%s 策略无候选标的", label)
            continue

        logger.info("%s 策略候选: %s", label, [f"{c.code} {c.name}" for c in candidates])

        analysis = call_ai_analysis(candidates, strategy_key)
        save_report(f"{strategy_key}_pm", analysis, today_str)
        push_strategy_pick(label, emoji, candidates, analysis)

    logger.info("下午推送完成")


# ============================================================
# 价值策略（每周一）
# ============================================================

def run_value():
    """价值策略推送（仅周一执行，一周一次）"""
    if not is_trade_day():
        logger.info("非交易日，跳过价值策略推送")
        return

    if not is_monday():
        logger.info("非周一，价值策略跳过（仅在周一推送）")
        return

    logger.info("=" * 50)
    logger.info("开始价值策略选股 (%s)", datetime.now().strftime("%Y-%m-%d %H:%M"))
    logger.info("=" * 50)

    candidates = run_value_screening()
    if not candidates:
        logger.warning("价值策略无候选标的")
        return

    logger.info("价值策略候选: %s", [f"{c.code} {c.name}" for c in candidates])

    analysis = call_ai_analysis(candidates, "value")
    today_str = datetime.now().strftime("%Y%m%d")
    save_report("value", analysis, today_str)
    push_strategy_pick("价值投资", "\U0001f48e", candidates, analysis)

    logger.info("价值策略推送完成")


# ============================================================
# 全部三种
# ============================================================

def run_all():
    """全部三种策略（短线 + 波段 + 价值）"""
    run_daily()
    run_value()


# ============================================================
# CLI
# ============================================================

def main():
    parser = argparse.ArgumentParser(description="A股选股推送")
    parser.add_argument(
        "--mode",
        choices=["daily", "value", "all", "afternoon"],
        default="daily",
        help="运行模式: daily=短线+波段(默认), value=仅价值, all=全部, afternoon=下午盘中推送",
    )
    args = parser.parse_args()

    if args.mode == "daily":
        run_daily()
    elif args.mode == "value":
        run_value()
    elif args.mode == "all":
        run_all()
    elif args.mode == "afternoon":
        run_afternoon()
    else:
        logger.error("未知模式: %s", args.mode)
        sys.exit(1)


if __name__ == "__main__":
    main()
