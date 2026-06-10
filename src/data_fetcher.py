"""
数据采集模块 —— 基于 akshare 获取 A 股行情与财务数据

早盘推送（8:30）使用前一个交易日收盘数据做初筛，
通过 akshare spot API + 东财直连双路径保障数据可用性。
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

# 东财全 A 股行情 API（与 akshare 同源）
_EASTMONEY_SPOT_URL = "http://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_FIELDS = (
    "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21"
)
_EASTMONEY_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"


def _safe_float(val, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def fetch_daily_quotes() -> pd.DataFrame:
    """
    获取全 A 股行情数据（前一个交易日收盘）

    策略：
      1. 优先通过 akshare (stock_zh_a_spot_em) 获取，重试 3 次
      2. 若仍失败，改用 requests 直连东方财富 API
      3. 全部失败则返回空 DataFrame

    返回 DataFrame，包含: code, name, close, change_pct, turnover_rate,
                          volume, amount, high, low, open, pre_close
    """
    # ---- 路径 1：akshare ----
    for attempt in range(3):
        try:
            import akshare as ak

            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                result = _parse_spot_df(df)
                if not result.empty:
                    logger.info(
                        "akshare 行情获取成功 (attempt %d)，共 %d 条",
                        attempt + 1,
                        len(result),
                    )
                    return result

            logger.warning("akshare 返回空数据 (attempt %d/3)", attempt + 1)
            if attempt < 2:
                time.sleep(10)

        except Exception:
            logger.warning("akshare 调用异常 (attempt %d/3)", attempt + 1, exc_info=True)
            if attempt < 2:
                time.sleep(10)

    # ---- 路径 2：直连东财 API ----
    logger.warning("akshare 全部失败，切换为东财直连")
    df = _fetch_from_eastmoney_direct()
    if not df.empty:
        logger.info("东财直连获取成功，共 %d 条", len(df))
        return df

    logger.error("所有数据源均失败，行情数据为空")
    return pd.DataFrame()


def _parse_spot_df(df: pd.DataFrame) -> pd.DataFrame:
    """将 akshare / 东财 返回的原始 DataFrame 转成统一格式"""
    df = df.rename(columns={
        "代码": "code",
        "名称": "name",
        "最新价": "close",
        "涨跌幅": "change_pct",
        "换手率": "turnover_rate",
        "成交量": "volume",
        "成交额": "amount",
        "最高": "high",
        "最低": "low",
        "今开": "open",
        "昨收": "pre_close",
    })

    keep_cols = [
        "code", "name", "close", "change_pct", "turnover_rate",
        "volume", "amount", "high", "low", "open", "pre_close",
    ]
    df = df[[c for c in keep_cols if c in df.columns]].copy()

    for col in ["close", "change_pct", "turnover_rate", "volume",
                "high", "low", "open", "pre_close"]:
        if col in df.columns:
            df[col] = df[col].apply(_safe_float)

    df = df[(df["close"] > 0) & (df["code"].notna())]
    return df


def _fetch_from_eastmoney_direct() -> pd.DataFrame:
    """
    直接请求东方财富全 A 股行情 API（与 akshare 同源）。
    盘前调用时返回的是前一日收盘数据。
    """
    try:
        params = {
            "pn": "1",
            "pz": "10000",
            "po": "1",
            "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2",
            "invt": "2",
            "fid": "f3",
            "fs": _EASTMONEY_FS,
            "fields": _EASTMONEY_FIELDS,
        }
        resp = requests.get(_EASTMONEY_SPOT_URL, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("data", {}).get("diff", [])
        if not items:
            logger.warning("东财直连返回空数据")
            return pd.DataFrame()

        # 字段映射: API field -> 中文列名
        field_map = {
            "f2": "最新价",
            "f3": "涨跌幅",
            "f4": "涨跌额",
            "f5": "成交量",
            "f6": "成交额",
            "f7": "振幅",
            "f8": "换手率",
            "f9": "动态市盈率",
            "f10": "量比",
            "f12": "代码",
            "f13": "市场",
            "f14": "名称",
            "f15": "最高",
            "f16": "最低",
            "f17": "今开",
            "f18": "昨收",
            "f20": "总市值",
            "f21": "流通市值",
        }

        rows = []
        for item in items:
            row = {}
            for key, chinese in field_map.items():
                row[chinese] = item.get(key)
            rows.append(row)

        df = pd.DataFrame(rows)
        if df.empty:
            return df

        result = _parse_spot_df(df)
        # 如果 close 为 0（盘前可能），用昨收填充
        if "close" in result.columns and "pre_close" in result.columns:
            mask = result["close"] == 0
            result.loc[mask, "close"] = result.loc[mask, "pre_close"]

        return result

    except Exception:
        logger.exception("东财直连失败")
        return pd.DataFrame()



def fetch_historical_daily(
    code: str,
    period: str = "daily",
    days: int = 120,
    retries: int = 2,
) -> pd.DataFrame:
    """
    获取单只股票历史日线数据（含重试）
    code: 纯数字代码（如 "600519"）
    """
    for attempt in range(retries):
        try:
            import akshare as ak

            start = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
            end = datetime.now().strftime("%Y%m%d")

            df = ak.stock_zh_a_hist(
                symbol=code,
                period=period,
                start_date=start,
                end_date=end,
                adjust="qfq",
            )
            if df is None or df.empty:
                if attempt < retries - 1:
                    logger.debug("%s 历史日线为空，重试 %d/%d", code, attempt + 1, retries)
                    continue
                return pd.DataFrame()

            df = df.rename(columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
                "成交额": "amount",
                "换手率": "turnover_rate",
            })

            for col in ["open", "close", "high", "low", "volume", "amount"]:
                if col in df.columns:
                    df[col] = df[col].apply(_safe_float)

            df["date"] = pd.to_datetime(df["date"])
            df = df.sort_values("date").reset_index(drop=True)
            return df.tail(days)

        except Exception:
            if attempt < retries - 1:
                logger.debug("获取 %s 历史日线失败，重试 %d/%d", code, attempt + 1, retries)
                continue
            logger.debug("获取 %s 历史日线最终失败", code)
            return pd.DataFrame()


# ============================================================
# 财务数据
# ============================================================

def fetch_financial_data(code: str) -> dict:
    """
    获取单只股票的核心财务指标
    返回 dict，包含: roe, pe_ttm, pb, peg, revenue_growth,
                    net_profit_growth, gross_margin, debt_ratio,
                    operating_cf, dividend_yield, beta
    """
    result: dict = {}

    try:
        import akshare as ak

        # --- 个股估值指标 (PE / PB) ---
        # 通过个股历史日线的最新 close 和 spot 估算 PE
        # 先用 东方财富 的直接API
        try:
            # 使用新版 akshare 的个股估值
            info = ak.stock_individual_info_em(symbol=code)
            if info is not None and not info.empty:
                for _, row in info.iterrows():
                    item = row.get("item", "")
                    val = row.get("value", "")
                    if "市盈率" in str(item) and "动态" in str(item):
                        result["pe_ttm"] = _safe_float(val)
                    elif "市净率" in str(item):
                        result["pb"] = _safe_float(val)
        except Exception:
            logger.debug("获取 %s PE/PB 方式1失败", code)

        # fallback: 用财务数据中的每股净资产+收盘价估算PB
        if result.get("pb", 0) == 0:
            try:
                hist = fetch_historical_daily(code, days=5)
                if not hist.empty:
                    result["_close_latest"] = hist["close"].iloc[-1]
            except Exception:
                pass

        # --- 财务摘要 (年度) ---
        try:
            fin = ak.stock_financial_abstract_new_ths(symbol=code, indicator="按年度")
            if fin is not None and not fin.empty:
                # 取最新一个完整年度
                latest_year = fin["report_date"].max()
                year_data = fin[fin["report_date"] == latest_year]
                for _, row in year_data.iterrows():
                    metric = row["metric_name"]
                    val = row["value"]
                    if metric == "index_weighted_avg_roe":
                        result["roe"] = _safe_float(val)
                    elif metric == "calculate_parent_holder_net_profit_yoy_growth_ratio":
                        result["net_profit_growth"] = _safe_float(val)
                    elif metric == "calculate_operating_income_total_yoy_growth_ratio":
                        result["revenue_growth"] = _safe_float(val)
                    elif metric == "sale_gross_margin":
                        result["gross_margin"] = _safe_float(val)
                    elif metric == "assets_debt_ratio":
                        result["debt_ratio"] = _safe_float(val)
                    elif metric == "index_per_operating_cash_flow_net":
                        result["operating_cf"] = _safe_float(val)
        except Exception:
            logger.debug("获取 %s 财务摘要失败", code)

        # --- PEG ---
        try:
            peg_val = _safe_float(result.get("pe_ttm", 0))
            npg = abs(_safe_float(result.get("net_profit_growth", 0)))
            if peg_val > 0 and npg > 0:
                result["peg"] = round(peg_val / npg, 2)
            else:
                result["peg"] = 999.0
        except Exception:
            result["peg"] = 999.0

        # --- 股息率 ---
        try:
            div = ak.stock_a_gxl(symbol=code)
            if div is not None and not div.empty:
                result["dividend_yield"] = _safe_float(
                    div.iloc[-1].get("股息率")
                )
        except Exception:
            result["dividend_yield"] = 0.0

        # --- 贝塔 ---
        try:
            beta_df = ak.stock_a_beta(symbol=code)
            if beta_df is not None and not beta_df.empty:
                result["beta"] = _safe_float(beta_df.iloc[-1].get("beta"))
        except Exception:
            result["beta"] = 1.0

    except Exception:
        logger.exception("获取 %s 财务数据失败", code)

    # 填充默认值
    for key in [
        "roe", "pe_ttm", "pb", "peg", "revenue_growth",
        "net_profit_growth", "gross_margin", "debt_ratio",
        "operating_cf", "dividend_yield", "beta",
    ]:
        result.setdefault(key, 0.0)

    return result


# ============================================================
# 市场/板块
# ============================================================

def is_st_stock(code: str, name: str = "") -> bool:
    """判断是否为 ST / *ST / 退市整理期"""
    upper = name.upper() if name else ""
    return any(
        t in upper
        for t in ("ST", "*ST", "退市", "N", "C")
        if t
    )


def is_recent_ipo(code: str, listing_date: Optional[datetime] = None) -> bool:
    """判断是否为上市 < 60 天的新股"""
    try:
        import akshare as ak

        info = ak.stock_individual_info_em(symbol=code)
        if info is None or info.empty:
            return False

        date_row = info[info["item"] == "上市时间"]
        if date_row.empty:
            return False

        list_date = pd.to_datetime(date_row["value"].values[0])
        return (datetime.now() - list_date).days < 60
    except Exception:
        logger.debug("判断 %s 上市日期失败，视为非新股", code)
        return False


def fetch_trade_calendar(year: int = None) -> set:
    """获取 A 股交易日历（备用）"""
    if year is None:
        year = datetime.now().year
    try:
        import akshare as ak

        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            return set()
        dates = pd.to_datetime(df["trade_date"]).dt.strftime("%Y-%m-%d")
        return set(dates)
    except Exception:
        return set()
