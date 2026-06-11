"""
量化筛选模块 —— 短线 / 波段 / 价值三种策略

流程:
1. 从全 A 股行情数据出发
2. 逐个标的计算技术指标 + 判断条件
3. 按策略分类、打分、排序
4. 输出 Top N 候选
"""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import pandas as pd

from config import (
    SCALPING,
    SWING,
    VALUE,
    TOP_N,
)
from data_fetcher import (
    fetch_daily_quotes,
    fetch_financial_data,
    fetch_historical_daily,
    is_st_stock,
    is_recent_ipo,
)
from indicators import (
    calc_all_indicators,
    check_macd_golden_cross,
    check_histogram_shortening,
)
from fundamentals import score_fundamentals

logger = logging.getLogger(__name__)

MAX_WORKERS = 10  # 并发数


@dataclass
class Candidate:
    code: str
    name: str
    close: float
    change_pct: float
    strategy: str  # "scalping" | "swing" | "value"
    score: float = 0.0
    reason: str = ""
    fundamentals: dict = field(default_factory=dict)
    indicators_summary: str = ""


# ============================================================
# 主入口
# ============================================================

def run_screening(strategies=None) -> dict:
    """
    执行筛选，返回 {"scalping": [Candidate, ...], "swing": [...], "value": [...]}
    """
    if strategies is None:
        strategies = ("scalping", "swing", "value")

    logger.info("开始全 A 股行情数据采集...")
    quotes = fetch_daily_quotes()
    if quotes.empty:
        logger.error("行情数据为空，终止筛选")
        return {"scalping": [], "swing": [], "value": []}

    # 快筛（秒级，只用收盘快照）
    quotes = _fast_pre_filter(quotes)
    logger.info("快筛后剩余 %d 只标的", len(quotes))

    results: dict = {s: [] for s in strategies}

    # 确保 total_mv / circ_mv 列存在（部分数据源不提供，默认 0）
    for col in ["total_mv", "circ_mv"]:
        if col not in quotes.columns:
            quotes[col] = 0.0

    # 只做短线/波段需要技术指标（价值策略主要看基本面，但也需要行情价格）
    cols = ["code", "name", "close", "change_pct", "turnover_rate", "volume", "total_mv", "circ_mv"]
    codes = quotes[cols].to_dict("records")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for row in codes:
            f = executor.submit(_process_stock, row)
            futures[f] = row["code"]

        for future in as_completed(futures):
            code = futures[future]
            try:
                stock_result = future.result(timeout=60)
                if stock_result is None:
                    continue
                for strategy_name, cand in stock_result.items():
                    if cand and strategy_name in results:
                        results[strategy_name].append(cand)
            except Exception:
                logger.debug("处理 %s 异常", code, exc_info=True)

    # 排序 & 取 Top N
    for s in strategies:
        results[s] = sorted(results[s], key=lambda c: c.score, reverse=True)[:TOP_N]
        logger.info(
            "%s 策略: 选出 %d 只",
            s,
            len(results[s]),
        )

    return results


# ============================================================
# 内部
# ============================================================

def _fast_pre_filter(df: pd.DataFrame) -> pd.DataFrame:
    """快筛：仅用收盘快照数据，不拉历史日线，秒级完成"""
    df = df.copy()
    # 排除 ST / 退市
    df = df[~df.apply(lambda r: is_st_stock(r["code"], r["name"]), axis=1)]
    # 基本有效性
    df = df[(df["close"] > 0.01) & (df["volume"] > 0)]
    # 涨跌幅合理区间（排除极端，正筛会有更严格的2%-9%）
    df = df[(df["change_pct"] >= 2.0) & (df["change_pct"] <= 9.0)]
    # 换手率 >= 2%（仅当数据源提供时过滤；新浪不提供换手率，全为0则跳过）
    if df["turnover_rate"].max() > 0:
        df = df[df["turnover_rate"] >= 2.0]
    # 排除低价垃圾股
    df = df[df["close"] >= 2.0]
    return df



def _pre_filter(df: pd.DataFrame) -> pd.DataFrame:
    """粗筛：排除 ST、停牌、无效价格"""
    df = df[df["code"].notna()].copy()
    df = df[~df.apply(lambda r: is_st_stock(r["code"], r["name"]), axis=1)]
    df = df[df["close"] > 0.01]
    df = df[df["volume"] > 0]
    return df


def _process_stock(row: dict) -> dict | None:
    """
    对单只股票运行三种策略检查，返回 {"scalping": Candidate|None, ...}
    """
    code = row["code"]
    name = row["name"]
    close = row["close"]
    change_pct = row["change_pct"]

    # 获取历史日线
    hist_df = fetch_historical_daily(code, period="daily", days=130)
    if hist_df.empty or len(hist_df) < 30:
        return None

    # 计算技术指标
    ind = calc_all_indicators(hist_df)

    result = {}

    # ---- 短线 ----
    sc = _check_scalping(code, name, close, change_pct, row, hist_df, ind)
    result["scalping"] = sc

    # ---- 波段 ----
    sw = _check_swing(code, name, close, change_pct, row, hist_df, ind)
    result["swing"] = sw

    # ---- 价值（如果短线/波段命中了就复用财务数据，否则按需获取） ----
    # 改为 value 独立检查，在 main 中单独运行以降低每日成本
    result["value"] = None  # 不在日常调用中触发，由 main 独立处理

    return result


# ============================================================
# 短线策略检查
# ============================================================

def _check_scalping(
    code: str,
    name: str,
    close: float,
    change_pct: float,
    row: dict,
    hist_df: pd.DataFrame,
    ind: dict,
) -> Candidate | None:
    """检查是否符合短线策略"""

    # 1. 昨日涨幅 2%-9%
    if not (SCALPING["min_change_pct"] <= change_pct <= SCALPING["max_change_pct"]):
        return None

    # 2. 排除昨日涨停（涨幅 >= 9.8% 视为涨停，考虑不同板块）
    if change_pct >= 9.8:
        return None

    # 3. 排除上市 < 60 天新股
    if is_recent_ipo(code):
        return None

    # 4. 昨日成交量 / 5日均量 > 1.5
    vol_ratio = ind.get("vol_vs_5ma", 1.0)
    if vol_ratio < SCALPING["min_vol_vs_5ma"]:
        return None

    # 5. MA5 上穿 MA10 或 MA20（金叉或刚金叉）
    ma = ind["ma"]
    ma5 = ma["ma5"].iloc[-1]
    ma10 = ma["ma10"].iloc[-1]
    ma20 = ma["ma20"].iloc[-1]
    ma5_prev = ma["ma5"].iloc[-2]
    ma10_prev = ma["ma10"].iloc[-2]

    golden_cross_5_10 = ma5_prev <= ma10_prev and ma5 > ma10
    above_20 = ma5 > ma20
    if not (golden_cross_5_10 or above_20):
        # 放宽：只需 MA5 > MA10 或接近金叉
        if ma5 <= ma10:
            return None

    # 6. MACD 日线金叉或红柱放大
    macd = ind["macd"]
    has_golden = check_macd_golden_cross(macd)
    has_red_rising = (
        not has_golden
        and macd["histogram"].iloc[-2] > 0
        and macd["histogram"].iloc[-1] > macd["histogram"].iloc[-2]
    )
    if not (has_golden or has_red_rising):
        return None

    # 7. RSI(6) 在 40-80
    rsi6 = ind["rsi_6"].iloc[-1]
    if pd.isna(rsi6) or not (SCALPING["min_rsi_6"] <= rsi6 <= SCALPING["max_rsi_6"]):
        return None

    # 8. 换手率 > 2%
    turnover = row.get("turnover_rate", 0)
    if turnover < SCALPING["min_turnover_rate"]:
        return None

    # 简单打分：成交量因子 + 涨幅因子
    score = (vol_ratio * 20) + (change_pct * 3) + (turnover * 2)
    # 金叉加分
    if has_golden:
        score += 15

    reason_parts = [
        f"昨日涨幅 {change_pct:.1f}%",
        f"成交量/5日均量 {vol_ratio:.2f}",
        f"换手率 {turnover:.2f}%",
        f"RSI(6)={rsi6:.1f}",
        f"MA5{cross_ma5_desc(ma5, ma10, ma20)}",
        f"MACD{'金叉' if has_golden else '红柱放大'}",
    ]

    return Candidate(
        code=code,
        name=name,
        close=close,
        change_pct=change_pct,
        strategy="scalping",
        score=score,
        reason="; ".join(reason_parts),
        indicators_summary=_format_indicators_short(ind, hist_df),
    )


def cross_ma5_desc(ma5, ma10, ma20) -> str:
    if ma5 > ma10:
        return f"上穿MA10({ma10:.2f})"
    elif ma5 > ma20:
        return f"站上MA20({ma20:.2f})"
    return f"距MA10({ma10:.2f})"


# ============================================================
# 波段策略检查
# ============================================================

def _check_swing_fundamentals(code: str) -> bool:
    """波段基本面: ROE > 10%, 营收增长 > 10%"""
    try:
        fin = fetch_financial_data(code)
        roe = fin.get("roe", 0)
        rg = fin.get("revenue_growth", 0)
        return roe >= 10.0 and rg >= 10.0
    except Exception:
        return True  # 数据不可用时放行，不卡死



def _check_swing(
    code: str,
    name: str,
    close: float,
    change_pct: float,
    row: dict,
    hist_df: pd.DataFrame,
    ind: dict,
) -> Candidate | None:
    """检查是否符合波段策略"""

    # 1. 均线多头排列 MA20 > MA60 > MA120
    ma = ind["ma"]
    ma20 = ma["ma20"].iloc[-1]
    ma60 = ma["ma60"].iloc[-1]
    ma120 = ma["ma120"].iloc[-1] if "ma120" in ma and not pd.isna(ma["ma120"].iloc[-1]) else 0
    if pd.isna(ma20) or pd.isna(ma60):
        return None
    if not (ma20 > ma60):
        return None
    # MA60 > MA120 可选（部分股票上市不足 120 天）
    long_ma_ok = ma120 == 0 or ma60 > ma120

    # 2. MACD 日线金叉 + 周线绿柱缩短
    macd = ind["macd"]
    has_golden = check_macd_golden_cross(macd)
    green_shortening = check_histogram_shortening(macd, "green")
    if not (has_golden or green_shortening):
        return None

    # 3. RSI(14) 在 45-65
    rsi14 = ind["rsi_14"].iloc[-1]
    if pd.isna(rsi14) or not (SWING["min_rsi_14"] <= rsi14 <= SWING["max_rsi_14"]):
        return None

    # 4. 价格在布林带中轨上方
    from indicators import boll_position
    bpos = boll_position(close, ind["boll"])
    if bpos in ("middle_lower", "below"):
        return None

    # 5. 成交量/5日均量 1.2-2.0
    vol_ratio = ind.get("vol_vs_5ma", 1.0)
    if not (SWING["min_vol_vs_5ma"] <= vol_ratio <= SWING["max_vol_vs_5ma"]):
        return None

    # 6. 流通市值 > 50 亿（仅当数据源提供时检查；不提供时跳过）
    circ_mv = row.get("circ_mv", 0)
    if circ_mv > 0 and circ_mv < 50:
        return None

    # 7. 基本面: ROE > 10%, 营收增长 > 10%
    if not _check_swing_fundamentals(code):
        return None

    # 打分
    score = (vol_ratio * 15) + (rsi14 * 0.3)
    if has_golden:
        score += 20
    if green_shortening:
        score += 10
    if long_ma_ok and ma120 > 0:
        score += 10

    reason_parts = [
        f"均线{'多头排列' if long_ma_ok else 'MA20>MA60'}",
        f"MACD{'金叉' if has_golden else '绿柱缩短'}",
        f"RSI(14)={rsi14:.1f}",
        f"布林带位置={bpos}",
        f"成交量/5日均量={vol_ratio:.2f}",
    ]

    return Candidate(
        code=code,
        name=name,
        close=close,
        change_pct=change_pct,
        strategy="swing",
        score=score,
        reason="; ".join(reason_parts),
        indicators_summary=_format_indicators_short(ind, hist_df),
    )


# ============================================================
# 价值策略检查（独立调用，不走 daily 流程）
# ============================================================

def run_value_screening() -> list[Candidate]:
    """价值策略：从全 A 股中按基本面筛选"""
    logger.info("开始价值策略筛选...")

    quotes = fetch_daily_quotes()
    if quotes.empty:
        logger.error("行情数据为空")
        return []

    quotes = _pre_filter(quotes)
    # 价值策略只关注有足够成交量的
    quotes = quotes[quotes["volume"] > 0]

    candidates = []
    codes = quotes[["code", "name", "close", "change_pct"]].to_dict("records")

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {
            executor.submit(_check_value, row): row["code"]
            for row in codes
        }
        for future in as_completed(futures):
            try:
                cand = future.result(timeout=60)
                if cand:
                    candidates.append(cand)
            except Exception:
                pass

    candidates = sorted(candidates, key=lambda c: c.score, reverse=True)
    logger.info("价值策略初筛 %d 只，取 Top %d", len(candidates), TOP_N)
    return candidates[:TOP_N]


def _check_value(row: dict) -> Candidate | None:
    """检查单只股票是否符合价值投资策略"""
    code = row["code"]

    # 获取财务数据
    fin = fetch_financial_data(code)

    # 1. PE < 20
    pe = fin.get("pe_ttm", 999)
    if pe <= 0 or pe > VALUE["max_pe"]:
        return None

    # 2. PEG < 1.0
    peg = fin.get("peg", 999)
    if peg > VALUE["max_peg"]:
        return None

    # 3. ROE > 15%（连续3年）
    roe_3y = fin.get("roe_3y", [])
    if len(roe_3y) >= 3:
        if not all(r >= VALUE["min_roe"] for r in roe_3y):
            return None
    else:
        # 数据不足3年，用最新年度兜底
        roe = fin.get("roe", 0)
        if roe < VALUE["min_roe"]:
            return None

    # 4. 资产负债率 < 50%
    dr = fin.get("debt_ratio", 100)
    if dr > VALUE["max_debt_ratio"]:
        return None

    # 5. 毛利率 > 25%
    gm = fin.get("gross_margin", 0)
    if gm < VALUE["min_gross_margin"]:
        return None

    # 6. 净利润增长率 > 15%
    npg = fin.get("net_profit_growth", 0)
    if npg < VALUE["min_net_profit_growth"]:
        return None

    # 7. 经营现金流 > 0
    ocf = fin.get("operating_cf", 0)

    # 打分
    scored = score_fundamentals(fin)
    total = scored["total_score"]

    # 加分项：股息率
    dy = fin.get("dividend_yield", 0)
    if dy >= VALUE["min_dividend_yield"]:
        total += 5

    # 加分项：经营现金流为正
    if ocf > 0:
        total += 5

    reason_parts = [
        f"PE={pe:.1f}",
        f"PEG={peg:.2f}",
        f"ROE={roe:.1f}%",
        f"毛利率={gm:.1f}%",
        f"资产负债率={dr:.1f}%",
        f"净利润增长={npg:.1f}%",
    ]
    if dy > 0:
        reason_parts.append(f"股息率={dy:.2f}%")

    return Candidate(
        code=code,
        name=row["name"],
        close=row["close"],
        change_pct=row["change_pct"],
        strategy="value",
        score=total,
        reason="; ".join(reason_parts),
        fundamentals=fin,
    )


# ============================================================
# 工具函数
# ============================================================

def _format_indicators_short(ind: dict, hist_df: pd.DataFrame) -> str:
    """简短的技术指标摘要"""
    lines = []
    try:
        close = hist_df["close"].iloc[-1]
        lines.append(f"最新价={close:.2f}")

        ma = ind["ma"]
        if "ma5" in ma and not pd.isna(ma["ma5"].iloc[-1]):
            lines.append(f"MA5={ma['ma5'].iloc[-1]:.2f}, MA10={ma['ma10'].iloc[-1]:.2f}, MA20={ma['ma20'].iloc[-1]:.2f}")

        macd = ind["macd"]
        lines.append(f"DIF={macd['dif'].iloc[-1]:.3f}, DEA={macd['dea'].iloc[-1]:.3f}")

        rsi6 = ind["rsi_6"].iloc[-1]
        rsi14 = ind["rsi_14"].iloc[-1]
        lines.append(f"RSI(6)={rsi6:.1f}, RSI(14)={rsi14:.1f}")

        kdj = ind["kdj"]
        lines.append(f"K={kdj['k'].iloc[-1]:.1f}, D={kdj['d'].iloc[-1]:.1f}, J={kdj['j'].iloc[-1]:.1f}")

        boll = ind["boll"]
        lines.append(
            f"BOLL 上={boll['upper'].iloc[-1]:.2f}, "
            f"中={boll['middle'].iloc[-1]:.2f}, "
            f"下={boll['lower'].iloc[-1]:.2f}"
        )

        lines.append(f"成交量/5日均量={ind['vol_vs_5ma']:.2f}")
    except Exception:
        pass

    return "\n".join(lines)
