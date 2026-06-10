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
                time.sleep(8)
        except Exception:
            if attempt < 1:
                time.sleep(8)
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
            time.sleep(0.3)
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
            time.sleep(0.3)
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
                "high", "low", "open", "pre_close"]:
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
