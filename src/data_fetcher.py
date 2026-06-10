"""
数据采集模块 - 基于腾讯/新浪 A 股行情与财务数据

数据源: 腾讯 qt.gtimg.cn -> 新浪 hq.sinajs.cn -> akshare -> 东财直连
"""

import json
import logging
import sys
import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd
import requests

logger = logging.getLogger(__name__)

_EASTMONEY_SPOT_URL = "http://push2.eastmoney.com/api/qt/clist/get"
_EASTMONEY_FIELDS = "f2,f3,f4,f5,f6,f7,f8,f9,f10,f12,f13,f14,f15,f16,f17,f18,f20,f21"
_EASTMONEY_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23"

_TENCENT_FIELDS = {
    "name": 1, "code": 2, "close": 3, "pre_close": 4,
    "open": 5, "volume": 6, "high": 33, "low": 34,
    "change_pct": 32, "amount": 37, "turnover_rate": 38,
}

def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


def fetch_daily_quotes() -> pd.DataFrame:
    df = _fetch_from_tencent()
    if not df.empty:
        logger.info("tencent: %d", len(df))
        return df
    df = _fetch_from_sina()
    if not df.empty:
        logger.info("sina: %d", len(df))
        return df
    for attempt in range(2):
        try:
            import akshare as ak
            df = ak.stock_zh_a_spot_em()
            if df is not None and not df.empty:
                result = _parse_spot_df(df)
                if not result.empty:
                    logger.info("akshare: %d", len(result))
                    return result
            if attempt < 1:
                time.sleep(3)
        except Exception:
            if attempt < 1:
                time.sleep(3)
    df = _fetch_from_eastmoney_direct()
    if not df.empty:
        logger.info("eastmoney: %d", len(df))
        return df
    logger.error("all sources failed")
    return pd.DataFrame()


def _fetch_from_tencent() -> pd.DataFrame:
    try:
        codes = _get_stock_list()
        if not codes:
            return pd.DataFrame()
        all_rows = []
        for i in range(0, len(codes), 80):
            batch = codes[i:i + 80]
            tencodes = []
            cmap = {}
            for code, name in batch:
                p = "sh" if code.startswith("6") else "sz"
                tc = p + code
                tencodes.append(tc)
                cmap[tc] = code
            try:
                resp = requests.get("http://qt.gtimg.cn/q=" + ",".join(tencodes), timeout=30)
                resp.encoding = "gbk"
            except Exception:
                continue
            for line in resp.text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                try:
                    parts = line.split('="', 1)
                    if len(parts) != 2:
                        continue
                    key = parts[0].replace("v_", "")
                    vals = parts[1].strip(';\n').split("~")
                    if len(vals) < 40:
                        continue
                    row = {}
                    for fn, idx in _TENCENT_FIELDS.items():
                        row[fn] = vals[idx] if idx < len(vals) else ""
                    row["code"] = cmap.get(key, row.get("code", ""))
                    all_rows.append(row)
                except Exception:
                    continue
            time.sleep(0.05)
        if not all_rows:
            return pd.DataFrame()
        return _normalize_quote_df(pd.DataFrame(all_rows))
    except Exception:
        logger.exception("tencent error")
        return pd.DataFrame()


def _fetch_from_sina() -> pd.DataFrame:
    try:
        codes = _get_stock_list()
        if not codes:
            return pd.DataFrame()
        all_rows = []
        for i in range(0, len(codes), 200):
            batch = codes[i:i + 200]
            sinacodes = []
            for code, name in batch:
                p = "sh" if code.startswith("6") else "sz"
                sinacodes.append(p + code)
            try:
                resp = requests.get(
                    "http://hq.sinajs.cn/list=" + ",".join(sinacodes),
                    headers={"Referer": "https://finance.sina.com.cn"},
                    timeout=30,
                )
                resp.encoding = "gbk"
            except Exception:
                continue
            for line in resp.text.strip().split("\n"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                try:
                    parts = line.split('="', 1)
                    if len(parts) != 2:
                        continue
                    key = parts[0].replace("var hq_str_", "")
                    vals = parts[1].strip(';\n').split(",")
                    if len(vals) < 32 or not vals[0]:
                        continue
                    c = _safe_float(vals[3])
                    pc = _safe_float(vals[2])
                    chg = round((c - pc) / pc * 100, 2) if pc > 0 else 0.0
                    all_rows.append({
                        "code": key, "name": vals[0],
                        "close": c, "pre_close": pc,
                        "open": _safe_float(vals[1]),
                        "high": _safe_float(vals[4]),
                        "low": _safe_float(vals[5]),
                        "volume": _safe_float(vals[8]),
                        "amount": _safe_float(vals[9]) * 10000,
                        "change_pct": chg,
                        "turnover_rate": 0.0,
                    })
                except Exception:
                    continue
            time.sleep(0.05)
        if not all_rows:
            return pd.DataFrame()
        return _normalize_quote_df(pd.DataFrame(all_rows))
    except Exception:
        logger.exception("sina error")
        return pd.DataFrame()


def _get_stock_list() -> list:
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        if df is not None and not df.empty:
            return list(zip(
                df["code"].astype(str).str.zfill(6),
                df["name"],
            ))
    except Exception:
        logger.warning("stock list failed")
    return []


def _normalize_quote_df(df: pd.DataFrame) -> pd.DataFrame:
    req = {
        "code": "", "name": "", "close": 0.0, "change_pct": 0.0,
        "turnover_rate": 0.0, "volume": 0.0, "amount": 0.0,
        "high": 0.0, "low": 0.0, "open": 0.0, "pre_close": 0.0,
    }
    for col, d in req.items():
        if col not in df.columns:
            df[col] = d
    for col in ["close", "change_pct", "turnover_rate", "volume",
                "amount", "high", "low", "open", "pre_close"]:
        if col in df.columns:
            df[col] = df[col].apply(_safe_float)
    df = df[(df["close"] > 0) & (df["code"].notna()) & (df["code"] != "")]
    keep = ["code", "name", "close", "change_pct", "turnover_rate",
            "volume", "amount", "high", "low", "open", "pre_close"]
    return df[[c for c in keep if c in df.columns]].copy()


def _parse_spot_df(df: pd.DataFrame) -> pd.DataFrame:
    return _normalize_quote_df(df.rename(columns={
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
    }))


def _fetch_from_eastmoney_direct() -> pd.DataFrame:
    """
    直接请求东方财富全 A 股行情 API（与 akshare 同源）。
    盘前调用时返回的是前一日收盘数据。
    带浏览器 UA / Referer，防止被反爬拦截。
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Referer": "http://quote.eastmoney.com/",
    }
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

    # 尝试多个东财节点（有时某个节点不可用）
    urls = [
        "http://push2.eastmoney.com/api/qt/clist/get",
        "http://82.push2.eastmoney.com/api/qt/clist/get",
    ]

    for url in urls:
        try:
            logger.info("东财直连尝试: %s ...", url[:40])
            resp = requests.get(url, params=params, headers=headers, timeout=90)
            resp.raise_for_status()
            data = resp.json()

            items = data.get("data", {}).get("diff", [])
            if not items:
                logger.warning("东财节点 %s 返回空数据", url[:40])
                continue

            # 字段映射: API field → 中文列名
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
                continue

            result = _parse_spot_df(df)
            # 如果 close 为 0（盘前可能），用昨收填充
            if "close" in result.columns and "pre_close" in result.columns:
                mask = result["close"] == 0
                result.loc[mask, "close"] = result.loc[mask, "pre_close"]

            logger.info("东财直连成功 (节点 %s)，共 %d 条", url[:40], len(result))
            return result

        except Exception as e:
            logger.warning("东财节点 %s 失败: %s", url[:40], str(e))

    logger.error("所有东财节点均失败")
    return pd.DataFrame()



def fetch_historical_daily(
    code: str,
    period: str = "daily",
    days: int = 120,
    retries: int = 2,
) -> pd.DataFrame:
    """
    获取单只股票历史日线数据
    数据源: 新浪 → 腾讯 → akshare
    code: 纯数字代码（如 "600519"）
    """
    prefix = "sh" if code.startswith("6") else "sz"
    
    # ---- 路径 1: 新浪历史 ----
    try:
        df = _sina_hist(code, prefix, days)
        if not df.empty:
            return df
    except Exception:
        logger.debug("sina hist failed for %s", code)

    # ---- 路径 2: 腾讯历史 ----
    try:
        df = _tencent_hist(code, prefix, days)
        if not df.empty:
            return df
    except Exception:
        logger.debug("tencent hist failed for %s", code)

    # ---- 路径 3: akshare stock_zh_a_daily ----
    for attempt in range(retries):
        try:
            import akshare as ak
            df = ak.stock_zh_a_daily(symbol=f"{prefix}{code}", adjust="qfq")
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "date": "date", "open": "open", "close": "close",
                    "high": "high", "low": "low", "volume": "volume",
                })
                if "amount" in df.columns:
                    pass  # keep it
                for col in ["open", "close", "high", "low", "volume"]:
                    if col in df.columns:
                        df[col] = df[col].apply(_safe_float)
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date").reset_index(drop=True)
                return df.tail(days)
        except Exception:
            if attempt < retries - 1:
                continue
    return pd.DataFrame()


def _sina_hist(code: str, prefix: str, days: int) -> pd.DataFrame:
    """从新浪获取历史日线"""
    import json as _json
    url = (
        f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
        f"CN_MarketData.getKLineData?symbol={prefix}{code}&scale=240&ma=no&datalen={days + 10}"
    )
    resp = requests.get(
        url,
        headers={"Referer": "https://finance.sina.com.cn"},
        timeout=15,
    )
    resp.encoding = "gbk"
    data = _json.loads(resp.text)
    if not data or not isinstance(data, list):
        return pd.DataFrame()
    
    rows = []
    for item in data:
        rows.append({
            "date": item.get("day", ""),
            "open": _safe_float(item.get("open")),
            "high": _safe_float(item.get("high")),
            "low": _safe_float(item.get("low")),
            "close": _safe_float(item.get("close")),
            "volume": _safe_float(item.get("volume")),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days)


def _tencent_hist(code: str, prefix: str, days: int) -> pd.DataFrame:
    """从腾讯获取历史日线"""
    import json as _json
    url = (
        f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        f"?param={prefix}{code},day,,,{days + 10},qfq"
    )
    resp = requests.get(url, timeout=15)
    data = _json.loads(resp.text)
    
    qfqday = data.get("data", {}).get(f"{prefix}{code}", {}).get("qfqday", [])
    if not qfqday:
        return pd.DataFrame()
    
    rows = []
    for item in qfqday:
        if len(item) < 6:
            continue
        rows.append({
            "date": item[0],
            "open": _safe_float(item[1]),
            "close": _safe_float(item[2]),
            "high": _safe_float(item[3]),
            "low": _safe_float(item[4]),
            "volume": _safe_float(item[5]),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df.tail(days)



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
