"""
配置文件 — 所有敏感信息通过环境变量读取
本地开发可在项目根目录创建 .env 文件（自动加载）
"""

import os
from datetime import datetime
from pathlib import Path

# 自动加载项目根目录的 .env 文件
_dotenv_path = Path(__file__).resolve().parent.parent / ".env"
if _dotenv_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_dotenv_path)
    except ImportError:
        pass  # python-dotenv 未安装时静默跳过

# ==================== 微信测试号配置 ====================
WECHAT_APP_ID = os.getenv("WECHAT_APP_ID", "")
WECHAT_APP_SECRET = os.getenv("WECHAT_APP_SECRET", "")
WECHAT_TEMPLATE_ID = os.getenv("WECHAT_TEMPLATE_ID", "")
WECHAT_OPENIDS = [
    oid.strip()
    for oid in os.getenv("WECHAT_OPENIDS", "").split(",")
    if oid.strip()
]

# ==================== AI API 配置（支持多家） ====================
# 可选值: "deepseek" | "claude" | "openai"
AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek")

# DeepSeek 配置
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

# Anthropic Claude 配置
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# OpenAI 兼容配置（备用）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# ==================== 推送策略 ====================
TOP_N = 2  # 每种策略推荐数量

# ----------------------------------------------------------
# 短线策略参数（每日推送）
# ----------------------------------------------------------
SCALPING = {
    "min_change_pct": 2.0,                # 昨日涨幅下限 (%)
    "max_change_pct": 9.0,                # 昨日涨幅上限 (%)
    "min_vol_vs_5ma": 1.5,                # 昨日成交量 / 5日均量下限
    "min_rsi_6": 40,                      # RSI(6) 下限
    "max_rsi_6": 80,                      # RSI(6) 上限
    "min_turnover_rate": 2.0,             # 最小换手率 (%)
    "min_beta": 1.0,                      # 最小贝塔
    "max_listing_days": 60,               # 排除上市 < 60 天
}

# ----------------------------------------------------------
# 波段策略参数（每日推送）
# ----------------------------------------------------------
SWING = {
    "min_rsi_14": 45,                     # RSI(14) 下限
    "max_rsi_14": 65,                     # RSI(14) 上限
    "min_vol_vs_5ma": 1.2,                # 成交量/5日均量下限
    "max_vol_vs_5ma": 2.0,                # 成交量/5日均量上限
    "min_roe": 10.0,                      # 最小 ROE (%)
    "min_revenue_growth": 10.0,           # 最小营收增长率 (%)
}

# ----------------------------------------------------------
# 价值策略参数（每周一推送）
# ----------------------------------------------------------
VALUE = {
    "max_pe": 20.0,                       # 最大 PE
    "max_peg": 1.0,                       # 最大 PEG
    "min_roe": 15.0,                      # 最小 ROE (%)
    "max_debt_ratio": 50.0,               # 最大资产负债率 (%)
    "min_gross_margin": 25.0,             # 最小毛利率 (%)
    "min_net_profit_growth": 15.0,        # 最小净利润增长率 (%)
    "min_dividend_yield": 2.0,            # 最小股息率 (%，可选)
}

# ==================== 基础路径 ====================
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

os.makedirs(OUTPUT_DIR, exist_ok=True)

# ==================== 节假日列表（2026 年） ====================
# 节假日列表（2026年）
_HOLIDAYS_2026 = {
    # 元旦 (2026.1.1-1.3)
    "2026-01-01", "2026-01-02",
    # 春节 (2026.2.17除夕，休市2.16-2.24)
    "2026-02-16", "2026-02-17", "2026-02-18",
    "2026-02-19", "2026-02-20", "2026-02-23", "2026-02-24",
    # 清明节 (2026.4.5周日，休市4.6)
    "2026-04-06",
    # 劳动节 (2026.5.1-5.5)
    "2026-05-01", "2026-05-04", "2026-05-05",
    # 端午节 (2026.6.19周五)
    "2026-06-19",
    # 中秋节 (2026.9.25周五)
    "2026-09-25",
    # 国庆节 (2026.10.1-10.8)
    "2026-10-01", "2026-10-02", "2026-10-05",
    "2026-10-06", "2026-10-07", "2026-10-08",
}


def is_trade_day(check_date: datetime | None = None) -> bool:
    """判断是否为 A 股交易日（排除周末 + 已知节假日）"""
    if check_date is None:
        check_date = datetime.now()
    if check_date.weekday() >= 5:
        return False
    return check_date.strftime("%Y-%m-%d") not in _HOLIDAYS_2026


def is_monday(check_date: datetime | None = None) -> bool:
    """判断是否为周一"""
    if check_date is None:
        check_date = datetime.now()
    return check_date.weekday() == 0
