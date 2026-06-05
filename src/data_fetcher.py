"""
数据采集模块 —— 基于 akshare 获取 A 股行情与财务数据
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)


def _safe_float(val, default: float = 0.0) -> float:
    """安全转换为 float"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ============================================================
# 行情数据
# ============================================================

def fetch_daily_quotes() -> pd.DataFrame:
    """
    获取全 A 股日线行情（昨日收盘数据）
    返回 DataFrame，包含: 代码, 名称, 最新价, 涨跌幅, 换手率,
                          成交量, 成交额, 最高, 最低, 开盘, 昨收
    """
    try:
        import akshare as ak

        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            logger.warning("akshare 行情数据返回为空")
            return pd.DataFrame()

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
        df = df[[c for c in keep_cols if c in df.columns]]

        df["change_pct"] = df["change_pct"].apply(_safe_float)
        df["turnover_rate"] = df["turnover_rate"].apply(_safe_float)
        df["volume"] = df["volume"].apply(_safe_float)
        df["close"] = df["close"].apply(_safe_float)
        df["high"] = df["high"].apply(_safe_float)
        df["low"] = df["low"].apply(_safe_float)
        df["open"] = df["open"].apply(_safe_float)
        df["pre_close"] = df["pre_close"].apply(_safe_float)

        # 过滤掉无效数据
        df = df[(df["close"] > 0) & (df["code"].notna())].copy()

        logger.info("行情数据获取成功，共 %d 条记录", len(df))
        return df

    except Exception:
        logger.exception("获取行情数据失败")
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
