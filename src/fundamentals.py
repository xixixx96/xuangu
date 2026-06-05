"""
基本面指标处理模块
对 data_fetcher 获取的财务数据进行清洗、打分
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

# ============================================================
# 基本面评分（用于价值策略排序）
# ============================================================

# 评分权重
FUNDAMENTAL_WEIGHTS = {
    "profit_growth": 0.20,   # 净利润增长率
    "roe": 0.20,             # ROE
    "pe_ttm": 0.15,          # PE（越低越好）
    "peg": 0.15,             # PEG
    "gross_margin": 0.10,    # 毛利率
    "debt_ratio": 0.10,      # 资产负债率（越低越好）
    "dividend_yield": 0.10,  # 股息率
}


def score_fundamentals(fin: dict) -> dict:
    """
    对单只股票的基本面打分（0-100）
    返回 {score, details}
    """
    scores: dict[str, float] = {}
    details: dict[str, str] = {}

    # --- 净利润增长率 ---
    npg = fin.get("net_profit_growth", 0)
    if npg >= 30:
        scores["profit_growth"] = 100
        details["profit_growth"] = f"净利润增长率 {npg:.1f}% (优秀)"
    elif npg >= 20:
        scores["profit_growth"] = 80
        details["profit_growth"] = f"净利润增长率 {npg:.1f}% (良好)"
    elif npg >= 10:
        scores["profit_growth"] = 50
        details["profit_growth"] = f"净利润增长率 {npg:.1f}% (一般)"
    elif npg >= 0:
        scores["profit_growth"] = 20
        details["profit_growth"] = f"净利润增长率 {npg:.1f}% (偏低)"
    else:
        scores["profit_growth"] = 0
        details["profit_growth"] = f"净利润增长率 {npg:.1f}% (亏损)"

    # --- ROE ---
    roe = fin.get("roe", 0)
    if roe >= 20:
        scores["roe"] = 100
        details["roe"] = f"ROE {roe:.1f}% (优秀)"
    elif roe >= 15:
        scores["roe"] = 85
        details["roe"] = f"ROE {roe:.1f}% (良好)"
    elif roe >= 10:
        scores["roe"] = 60
        details["roe"] = f"ROE {roe:.1f}% (一般)"
    elif roe >= 5:
        scores["roe"] = 30
        details["roe"] = f"ROE {roe:.1f}% (偏低)"
    else:
        scores["roe"] = 0
        details["roe"] = f"ROE {roe:.1f}% (差)"

    # --- PE (TTM) ---
    pe = fin.get("pe_ttm", 999)
    if pe <= 0:
        scores["pe_ttm"] = 0
        details["pe_ttm"] = "PE 为负 (亏损)"
    elif pe <= 10:
        scores["pe_ttm"] = 100
        details["pe_ttm"] = f"PE {pe:.1f} (极低)"
    elif pe <= 15:
        scores["pe_ttm"] = 85
        details["pe_ttm"] = f"PE {pe:.1f} (低估)"
    elif pe <= 20:
        scores["pe_ttm"] = 70
        details["pe_ttm"] = f"PE {pe:.1f} (合理偏低)"
    elif pe <= 30:
        scores["pe_ttm"] = 40
        details["pe_ttm"] = f"PE {pe:.1f} (合理)"
    elif pe <= 50:
        scores["pe_ttm"] = 15
        details["pe_ttm"] = f"PE {pe:.1f} (偏高)"
    else:
        scores["pe_ttm"] = 0
        details["pe_ttm"] = f"PE {pe:.1f} (极高)"

    # --- PEG ---
    peg = fin.get("peg", 999)
    if peg <= 0:
        scores["peg"] = 0
        details["peg"] = "PEG 无意义 (负增长)"
    elif peg <= 0.5:
        scores["peg"] = 100
        details["peg"] = f"PEG {peg:.2f} (极低)"
    elif peg <= 0.8:
        scores["peg"] = 85
        details["peg"] = f"PEG {peg:.2f} (低估)"
    elif peg <= 1.0:
        scores["peg"] = 70
        details["peg"] = f"PEG {peg:.2f} (合理)"
    elif peg <= 1.5:
        scores["peg"] = 35
        details["peg"] = f"PEG {peg:.2f} (偏高)"
    else:
        scores["peg"] = 0
        details["peg"] = f"PEG {peg:.2f} (极高)"

    # --- 毛利率 ---
    gm = fin.get("gross_margin", 0)
    if gm >= 50:
        scores["gross_margin"] = 100
        details["gross_margin"] = f"毛利率 {gm:.1f}% (优秀)"
    elif gm >= 30:
        scores["gross_margin"] = 80
        details["gross_margin"] = f"毛利率 {gm:.1f}% (良好)"
    elif gm >= 20:
        scores["gross_margin"] = 50
        details["gross_margin"] = f"毛利率 {gm:.1f}% (一般)"
    else:
        scores["gross_margin"] = 15
        details["gross_margin"] = f"毛利率 {gm:.1f}% (偏低)"

    # --- 资产负债率 ---
    dr = fin.get("debt_ratio", 100)
    if dr <= 30:
        scores["debt_ratio"] = 100
        details["debt_ratio"] = f"资产负债率 {dr:.1f}% (低风险)"
    elif dr <= 50:
        scores["debt_ratio"] = 80
        details["debt_ratio"] = f"资产负债率 {dr:.1f}% (健康)"
    elif dr <= 60:
        scores["debt_ratio"] = 50
        details["debt_ratio"] = f"资产负债率 {dr:.1f}% (中等)"
    elif dr <= 80:
        scores["debt_ratio"] = 20
        details["debt_ratio"] = f"资产负债率 {dr:.1f}% (偏高)"
    else:
        scores["debt_ratio"] = 0
        details["debt_ratio"] = f"资产负债率 {dr:.1f}% (高风险)"

    # --- 股息率 ---
    dy = fin.get("dividend_yield", 0)
    if dy >= 5:
        scores["dividend_yield"] = 100
        details["dividend_yield"] = f"股息率 {dy:.2f}% (优秀)"
    elif dy >= 3:
        scores["dividend_yield"] = 80
        details["dividend_yield"] = f"股息率 {dy:.2f}% (良好)"
    elif dy >= 2:
        scores["dividend_yield"] = 60
        details["dividend_yield"] = f"股息率 {dy:.2f}% (一般)"
    elif dy >= 1:
        scores["dividend_yield"] = 30
        details["dividend_yield"] = f"股息率 {dy:.2f}% (偏低)"
    else:
        scores["dividend_yield"] = 0
        details["dividend_yield"] = f"股息率 {dy:.2f}% (极低)"

    # --- 加权总分 ---
    total_score = sum(
        scores.get(k, 0) * FUNDAMENTAL_WEIGHTS.get(k, 0)
        for k in FUNDAMENTAL_WEIGHTS
    )

    return {
        "total_score": round(total_score, 1),
        "scores": scores,
        "details": details,
    }


def format_fundamentals_summary(fin: dict) -> str:
    """将基本面数据格式化为可读文本（供 AI 分析用）"""
    lines = []
    if fin.get("revenue_growth") is not None:
        lines.append(f"营收增长率: {fin['revenue_growth']:.1f}%")
    if fin.get("net_profit_growth") is not None:
        lines.append(f"净利润增长率: {fin['net_profit_growth']:.1f}%")
    if fin.get("pe_ttm") is not None:
        lines.append(f"PE(TTM): {fin['pe_ttm']:.1f}")
    if fin.get("peg") is not None:
        lines.append(f"PEG: {fin['peg']:.2f}")
    if fin.get("roe") is not None:
        lines.append(f"ROE: {fin['roe']:.1f}%")
    if fin.get("gross_margin") is not None:
        lines.append(f"毛利率: {fin['gross_margin']:.1f}%")
    if fin.get("debt_ratio") is not None:
        lines.append(f"资产负债率: {fin['debt_ratio']:.1f}%")
    if fin.get("operating_cf") is not None:
        lines.append(f"经营现金流/营收: {fin['operating_cf']:.2f}")
    if fin.get("dividend_yield") is not None:
        lines.append(f"股息率: {fin['dividend_yield']:.2f}%")
    if fin.get("beta") is not None:
        lines.append(f"贝塔系数: {fin['beta']:.2f}")
    return "\n".join(lines)
