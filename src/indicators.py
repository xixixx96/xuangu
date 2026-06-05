"""
技术指标计算模块
包含: MA, MACD, RSI, KDJ, BOLL, OBV, 成交量相关
所有计算基于 pandas Series，与数据源解耦
"""

import numpy as np
import pandas as pd


# ============================================================
# 移动平均线 (MA)
# ============================================================

def calc_ma(close: pd.Series, periods=(5, 10, 20, 60, 120, 200)) -> dict:
    """计算多条均线，返回 {"ma5": ..., "ma10": ..., ...}"""
    result = {}
    for p in periods:
        result[f"ma{p}"] = close.rolling(window=p).mean()
    return result


# ============================================================
# MACD
# ============================================================

def calc_macd(
    close: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> dict:
    """
    计算 MACD
    返回 {"dif": ..., "dea": ..., "macd": ..., "histogram": ...}
    histogram 即红/绿柱
    """
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    dif = ema_fast - ema_slow
    dea = dif.ewm(span=signal, adjust=False).mean()
    histogram = 2 * (dif - dea)

    return {"dif": dif, "dea": dea, "macd": histogram, "histogram": histogram}


def check_macd_golden_cross(macd_data: dict) -> bool:
    """判断最近一个交易日的 MACD 是否金叉（DIF 上穿 DEA）"""
    dif, dea = macd_data["dif"], macd_data["dea"]
    if len(dif) < 2 or len(dea) < 2:
        return False
    return bool(dif.iloc[-2] <= dea.iloc[-2] and dif.iloc[-1] > dea.iloc[-1])


def check_macd_dead_cross(macd_data: dict) -> bool:
    """判断最近一个交易日 MACD 是否死叉"""
    dif, dea = macd_data["dif"], macd_data["dea"]
    if len(dif) < 2 or len(dea) < 2:
        return False
    return bool(dif.iloc[-2] >= dea.iloc[-2] and dif.iloc[-1] < dea.iloc[-1])


def check_histogram_shortening(macd_data: dict, direction: str = "green") -> bool:
    """
    判断柱线是否缩短
    direction='green' → 绿柱在缩短（空头动能减弱）
    direction='red'   → 红柱在缩短（多头动能减弱）
    """
    hist = macd_data["histogram"]
    if len(hist) < 2:
        return False
    if direction == "green":
        # 绿柱 = histogram < 0; 缩短 = 值变大（接近零轴）
        return bool(hist.iloc[-2] < 0 and hist.iloc[-2] < hist.iloc[-1])
    else:
        return bool(hist.iloc[-2] > 0 and hist.iloc[-2] > hist.iloc[-1])


# ============================================================
# RSI
# ============================================================

def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算 RSI"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return rsi


# ============================================================
# KDJ
# ============================================================

def calc_kdj(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    n: int = 9,
    m1: int = 3,
    m2: int = 3,
) -> dict:
    """
    计算 KDJ
    返回 {"k": ..., "d": ..., "j": ...}
    """
    low_n = low.rolling(window=n).min()
    high_n = high.rolling(window=n).max()

    rsv = ((close - low_n) / (high_n - low_n).replace(0, np.nan)) * 100

    k = rsv.ewm(alpha=1 / m1, adjust=False).mean()
    d = k.ewm(alpha=1 / m2, adjust=False).mean()
    j = 3 * k - 2 * d

    return {"k": k, "d": d, "j": j}


def check_kdj_golden_cross(kdj_data: dict) -> bool:
    """判断 KDJ 是否金叉（K 上穿 D）"""
    k, d = kdj_data["k"], kdj_data["d"]
    if len(k) < 2 or len(d) < 2:
        return False
    return bool(k.iloc[-2] <= d.iloc[-2] and k.iloc[-1] > d.iloc[-1])


# ============================================================
# 布林带 (Bollinger Bands)
# ============================================================

def calc_boll(
    close: pd.Series,
    period: int = 20,
    std_dev: int = 2,
) -> dict:
    """计算布林带，返回 {"upper": ..., "middle": ..., "lower": ...}"""
    middle = close.rolling(window=period).mean()
    std = close.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return {"upper": upper, "middle": middle, "lower": lower}


def boll_position(close_val: float, boll_data: dict) -> str:
    """
    返回价格在布林带中的位置
    'above' / 'middle_upper' / 'middle_lower' / 'below'
    """
    upper = boll_data["upper"].iloc[-1]
    middle = boll_data["middle"].iloc[-1]
    lower = boll_data["lower"].iloc[-1]

    if close_val > upper:
        return "above"
    elif close_val > middle:
        return "middle_upper"
    elif close_val > lower:
        return "middle_lower"
    else:
        return "below"


# ============================================================
# OBV (On-Balance Volume)
# ============================================================

def calc_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """计算 OBV"""
    direction = np.sign(close.diff()).fillna(0)
    obv = (direction * volume).cumsum()
    return obv


# ============================================================
# 成交量 / 量比
# ============================================================

def calc_volume_vs_5ma(volume: pd.Series) -> float:
    """计算最近一日成交量 / 5 日均量"""
    if len(volume) < 5:
        return 1.0
    latest_vol = volume.iloc[-1]
    avg_5 = volume.iloc[-5:].mean()
    if avg_5 == 0:
        return 1.0
    return latest_vol / avg_5


def calc_volume_ratio(volume: pd.Series, period: int = 5) -> pd.Series:
    """计算量比序列"""
    avg = volume.rolling(window=period).mean().shift(1)
    avg.replace(0, np.nan, inplace=True)
    return volume / avg


# ============================================================
# 综合指标计算（一次调用全部算出）
# ============================================================

def calc_all_indicators(df: pd.DataFrame) -> dict:
    """
    输入: 单只股票的历史日线 DataFrame（需包含 close/high/low/volume 列）
    输出: 所有技术指标 dict
          {
              "ma": {...},
              "macd": {...},
              "rsi_6": ...,
              "rsi_14": ...,
              "kdj": {...},
              "boll": {...},
              "obv": ...,
              "vol_vs_5ma": ...,
          }
    """
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    return {
        "ma": calc_ma(close),
        "macd": calc_macd(close),
        "rsi_6": calc_rsi(close, 6),
        "rsi_14": calc_rsi(close, 14),
        "kdj": calc_kdj(high, low, close),
        "boll": calc_boll(close),
        "obv": calc_obv(close, volume),
        "vol_vs_5ma": calc_volume_vs_5ma(volume),
    }
