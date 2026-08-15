"""多因子选股服务

因子：
  - EP（市盈率倒数）: 1/PE，盈利收益率，越大越好
  - ROE: 净资产收益率，用 PB/PE 近似，越大越好
  - 20日收益率（动量）: 越大越好
  - 总市值: 越小越好（小市值效应），取负
"""

from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
import math
import pandas as pd

from services.akshare_service import data_service


def _nan_to_none(v):
    """把 NaN 转为 None（避免 JSON 序列化失败）"""
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except Exception:
        pass
    return v


def rank_pct(series: pd.Series, ascending: bool = True) -> pd.Series:
    """百分位排名标准化，返回 0~1 之间的分数"""
    return series.rank(pct=True, ascending=ascending)


def _calc_momentum_20d(code: str) -> Optional[float]:
    """计算20日收益率（%），腾讯K线优先，新浪兜底（只拉最近25根K线）"""
    try:
        kline = data_service._kline_from_tencent(code, "daily", 25)
        if kline and len(kline) >= 21:
            return round((kline[-1]["close"] / kline[-21]["close"] - 1) * 100, 2)
    except Exception:
        pass
    try:
        kline = data_service._kline_from_sina(code, "daily", 25)
        if kline and len(kline) >= 21:
            return round((kline[-1]["close"] / kline[-21]["close"] - 1) * 100, 2)
    except Exception:
        pass
    return None


def _get_list_dates() -> dict:
    """获取 A 股上市日期 {code: 上市日期字符串}（新浪接口，尽力而为）"""
    import akshare as ak

    def _add(df, code_kw: str, date_kw: str):
        """按列名关键词定位代码列和上市日期列"""
        code_col = date_col = None
        for c in df.columns:
            s = str(c)
            if code_col is None and code_kw in s:
                code_col = c
            if date_col is None and date_kw in s:
                date_col = c
        if code_col is None or date_col is None:
            return
        for _, row in df.iterrows():
            code = str(row[code_col]).zfill(6)
            dates[code] = str(row[date_col])

    dates = {}
    # 上交所：主板 + 科创板（代码列「证券代码」，日期列「上市日期」）
    for symbol in ["主板A股", "科创板"]:
        try:
            df = ak.stock_info_sh_name_code(symbol=symbol)
            _add(df, "证券代码", "上市日期")
        except Exception:
            pass
    # 深交所（代码列「A股代码」，日期列「A股上市日期」）
    try:
        df = ak.stock_info_sz_name_code(symbol="A股列表")
        _add(df, "A股代码", "A股上市日期")
    except Exception:
        pass
    return dates


def _get_recent_ipos(days: int = 60) -> set:
    """获取最近 days 日内上市的新股代码集合（用于剔除次新股）"""
    dates = _get_list_dates()
    if not dates:
        return set()
    cutoff = datetime.now() - timedelta(days=days)
    recent = set()
    for code, date_str in dates.items():
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d")
            if d >= cutoff:
                recent.add(code)
        except Exception:
            continue
    return recent


def multifactor_select(
    codes: list[str],
    weights: dict,
    top_n: int = 10,
) -> list[dict]:
    """多因子选股：计算各因子得分，加权排序，返回 Top N

    Args:
        codes: 候选股票代码列表
        weights: 各因子权重，如 {"ep": 0.35, "roe": 0.3, "momentum": 0.1, "market_cap": 0.25}
        top_n: 返回前 N 只
    """
    if not codes:
        raise ValueError("候选股票列表为空")

    # 1) 获取估值数据
    valuations = data_service.get_market_valuation(codes=codes)
    if not valuations:
        raise ValueError("无法获取估值数据（东方财富可能限流）")

    val_map = {v["code"]: v for v in valuations}

    # 2) 对每只股票计算因子
    rows = []
    for code in codes:
        v = val_map.get(code)
        if not v:
            continue
        pe = v.get("pe")
        pb = v.get("pb")
        mkt_cap = v.get("total_market_cap")
        name = v.get("name") or code

        # EP = 1/PE（PE 需 > 0）
        ep = 1.0 / pe if pe and pe > 0 else None
        # ROE ≈ PB / PE（动态近似）
        roe = (pb / pe * 100) if pe and pb and pe > 0 and pb > 0 else None

        # 20日收益率：拉近20日K线计算
        momentum = None
        try:
            kline = data_service.get_kline(code, start_date=None, end_date=None)
            if len(kline) >= 21:
                closes = [k["close"] for k in kline]
                momentum = (closes[-1] / closes[-21] - 1) * 100  # 百分比
            elif len(kline) >= 2:
                closes = [k["close"] for k in kline]
                momentum = (closes[-1] / closes[0] - 1) * 100
        except Exception:
            momentum = None

        rows.append({
            "code": code,
            "name": name,
            "pe": pe,
            "pb": pb,
            "ep": round(ep, 4) if ep is not None else None,
            "roe": round(roe, 2) if roe is not None else None,
            "momentum": round(momentum, 2) if momentum is not None else None,
            "market_cap": round(mkt_cap / 1e8, 2) if mkt_cap else None,  # 转亿元
        })

    if not rows:
        raise ValueError("无有效股票数据")

    df = pd.DataFrame(rows)

    # 3) 硬性门槛：ROE > 10% 且 EP > 0.03
    df = df[
        (df["roe"].notna()) & (df["roe"] > 10) &
        (df["ep"].notna()) & (df["ep"] > 0.03)
    ].reset_index(drop=True)
    if df.empty:
        raise ValueError("没有股票满足硬性门槛（ROE>10% 且 EP>0.03）")

    # 4) 各因子标准化（百分位排名）
    scores = pd.DataFrame(index=df.index)
    # EP：越大越好
    if df["ep"].notna().any():
        scores["ep"] = rank_pct(df["ep"].fillna(df["ep"].min()), ascending=True)
    # ROE：越大越好
    if df["roe"].notna().any():
        scores["roe"] = rank_pct(df["roe"].fillna(df["roe"].min()), ascending=True)
    # 动量：越大越好
    if df["momentum"].notna().any():
        scores["momentum"] = rank_pct(df["momentum"].fillna(0), ascending=True)
    # 市值：越小越好 → 反向排名
    if df["market_cap"].notna().any():
        scores["market_cap"] = rank_pct(df["market_cap"].fillna(df["market_cap"].max()), ascending=False)

    # 5) 一票否决：任一因子得分在后 20%（得分 ≤ 0.2）直接剔除
    veto_threshold = 0.2
    keep = pd.Series(True, index=df.index)
    for col in scores.columns:
        keep = keep & (scores[col] > veto_threshold)
    df = df[keep].reset_index(drop=True)
    scores = scores[keep].reset_index(drop=True)
    if df.empty:
        raise ValueError("一票否决后无剩余股票")

    # 6) 加权求和
    w_ep = weights.get("ep", 0.35)
    w_roe = weights.get("roe", 0.3)
    w_mom = weights.get("momentum", 0.1)
    w_cap = weights.get("market_cap", 0.25)
    total_w = w_ep + w_roe + w_mom + w_cap
    if total_w <= 0:
        total_w = 1.0

    df["total_score"] = 0.0
    if "ep" in scores:
        df["total_score"] += scores["ep"].fillna(0) * w_ep
    if "roe" in scores:
        df["total_score"] += scores["roe"].fillna(0) * w_roe
    if "momentum" in scores:
        df["total_score"] += scores["momentum"].fillna(0) * w_mom
    if "market_cap" in scores:
        df["total_score"] += scores["market_cap"].fillna(0) * w_cap
    df["total_score"] = df["total_score"] / total_w

    # 7) 排序返回 Top N
    df = df.sort_values("total_score", ascending=False).head(top_n)

    # 获取行业
    industry_map = data_service.get_stock_industry(df["code"].tolist())

    result = []
    for i, row in df.iterrows():
        item = {
            "code": row["code"],
            "name": row["name"],
            "pe": _nan_to_none(row["pe"]),
            "pb": _nan_to_none(row["pb"]),
            "ep": _nan_to_none(row["ep"]),
            "roe": _nan_to_none(row["roe"]),
            "momentum": _nan_to_none(row["momentum"]),
            "market_cap": _nan_to_none(row["market_cap"]),
            "industry": industry_map.get(row["code"], ""),
            "total_score": round(row["total_score"], 4),
        }
        result.append(item)

    return result


def _rank_with_neutral(series: pd.Series, ascending: bool = True) -> pd.Series:
    """对非缺失值做百分位排名，缺失值填中性分 0.5（用于 ETF 缺失财务因子）"""
    result = pd.Series(0.5, index=series.index)
    valid = series.notna()
    if valid.any():
        result[valid] = rank_pct(series[valid], ascending=ascending)
    return result


def multifactor_select_full(
    weights: dict,
    top_n: int = 10,
    progress_callback=None,
) -> list[dict]:
    """全市场多因子选股：股票 + ETF

    Args:
        weights: 各因子权重
        top_n: 返回前 N 只
        progress_callback: 进度回调（0~100）
    """
    # 1) 获取全市场数据（进度 0~60）
    def _cb(p):
        if progress_callback:
            progress_callback(int(p * 0.75))  # get_full_market_data 报 0~80 → 映射到 0~60
    records = data_service.get_full_market_data(progress_callback=_cb)
    if not records:
        raise ValueError("无法获取全市场数据")
    if progress_callback:
        progress_callback(60)

    df = pd.DataFrame(records)

    # 1.5) 剔除基金（ETF/LOF/指数）、ST/*ST、科创板（688）、创业板（300）、上市不满 60 日的次新股
    df = df[
        (df["type"] == "stock") &
        ~df["name"].str.contains("ST", case=False, na=False) &
        ~df["code"].str.startswith("688") &
        ~df["code"].str.startswith("300")
    ].reset_index(drop=True)
    recent_ipos = _get_recent_ipos(days=60)
    if recent_ipos:
        df = df[~df["code"].isin(recent_ipos)].reset_index(drop=True)
    if df.empty:
        raise ValueError("剔除基金/ST/次新股/科创创业板后无剩余股票")

    # 2) 计算估值因子
    df["ep"] = df["pe"].apply(lambda x: 1.0 / x if x and x > 0 else None)
    df["roe"] = df.apply(
        lambda r: r["pb"] / r["pe"] * 100 if r["pe"] and r["pb"] and r["pe"] > 0 and r["pb"] > 0 else None,
        axis=1,
    )
    df["market_cap_yi"] = df["market_cap"].apply(lambda x: round(x / 1e8, 2) if x else None)

    # 2.1) 只保留总市值 < 300 亿的公司
    df = df[df["market_cap_yi"].notna() & (df["market_cap_yi"] < 300)].reset_index(drop=True)
    if df.empty:
        raise ValueError("剔除总市值>=300亿后无剩余股票")

    # 2.5) 两套方案：东财可用用财报精确值，不可用用 PB/PE 近似值
    finance_data = data_service.get_financial_data()
    use_precise_finance = bool(finance_data)
    if use_precise_finance:
        # 用财报 ROE 替代近似 ROE（有财报值的用财报值，否则保留近似值）
        df["roe_precise"] = df["code"].map(lambda c: finance_data.get(c, {}).get("roe"))
        df["roe"] = df["roe_precise"].where(df["roe_precise"].notna(), df["roe"])
        # 净利润同比增速
        df["profit_yoy"] = df["code"].map(lambda c: finance_data.get(c, {}).get("profit_yoy"))
    else:
        df["profit_yoy"] = None

    # 3) 硬性门槛：ROE>10% 且 EP>0.03 且 ROE≤35%
    stock_pass = (df["roe"] > 10) & (df["ep"] > 0.03) & (df["roe"] <= 35)
    # 东财可用时：额外剔除净利润同比>1000% 的财务异常股（缺失值不剔除）
    if use_precise_finance:
        stock_pass = stock_pass & ~(df["profit_yoy"].notna() & (df["profit_yoy"] > 1000))
    df = df[stock_pass].reset_index(drop=True)
    if df.empty:
        raise ValueError("没有股票满足硬性门槛")

    # 4) 对筛选后的候选并发拉20日K线计算精确动量（进度 60~90）
    codes = df["code"].tolist()
    momentums: list[Optional[float]] = [None] * len(codes)
    total = len(codes)
    batch = 20
    for start in range(0, total, batch):
        end = min(start + batch, total)
        with ThreadPoolExecutor(max_workers=batch) as executor:
            momentums[start:end] = list(executor.map(_calc_momentum_20d, codes[start:end]))
        if progress_callback:
            progress_callback(60 + int(end / total * 30))
    df["momentum"] = momentums
    if progress_callback:
        progress_callback(90)

    # 4.5) 规则2：剔除 20日涨幅 > 20% 的股票
    df = df[~(df["momentum"].notna() & (df["momentum"] > 20))].reset_index(drop=True)
    if df.empty:
        raise ValueError("剔除20日涨幅>20%后无剩余股票")

    # 5) 标准化（缺失因子给中性分 0.5）
    scores = pd.DataFrame(index=df.index)
    scores["ep"] = _rank_with_neutral(df["ep"], ascending=True)
    scores["roe"] = _rank_with_neutral(df["roe"], ascending=True)
    scores["momentum"] = _rank_with_neutral(df["momentum"], ascending=True)
    scores["market_cap"] = _rank_with_neutral(df["market_cap"], ascending=False)

    # 6) 一票否决：任一有效因子得分在后 20% 剔除
    veto_threshold = 0.2
    keep = pd.Series(True, index=df.index)
    for col in scores.columns:
        keep = keep & (scores[col] > veto_threshold)
    df = df[keep].reset_index(drop=True)
    scores = scores[keep].reset_index(drop=True)
    if df.empty:
        raise ValueError("一票否决后无剩余股票")

    # 6) 加权求和
    w_ep = weights.get("ep", 0.35)
    w_roe = weights.get("roe", 0.3)
    w_mom = weights.get("momentum", 0.1)
    w_cap = weights.get("market_cap", 0.25)
    total_w = w_ep + w_roe + w_mom + w_cap
    if total_w <= 0:
        total_w = 1.0

    df["total_score"] = (
        scores["ep"].fillna(0.5) * w_ep
        + scores["roe"].fillna(0.5) * w_roe
        + scores["momentum"].fillna(0.5) * w_mom
        + scores["market_cap"].fillna(0.5) * w_cap
    ) / total_w

    # 7) 排序返回 Top N
    df = df.sort_values("total_score", ascending=False).head(top_n).reset_index(drop=True)

    if progress_callback:
        progress_callback(95)

    # 行业（东财可能限流，降级为空）
    industry_map = {}
    try:
        industry_map = data_service.get_stock_industry(df["code"].tolist())
    except Exception:
        pass

    result = []
    for _, row in df.iterrows():
        result.append({
            "code": row["code"],
            "name": row["name"],
            "type": row["type"],
            "pe": _nan_to_none(row["pe"]),
            "pb": _nan_to_none(row["pb"]),
            "ep": _nan_to_none(round(row["ep"], 4)) if row["ep"] is not None else None,
            "roe": _nan_to_none(round(row["roe"], 2)) if row["roe"] is not None else None,
            "momentum": _nan_to_none(row["momentum"]),
            "market_cap": _nan_to_none(row["market_cap_yi"]),
            "industry": industry_map.get(row["code"], ""),
            "total_score": round(row["total_score"], 4),
        })

    if progress_callback:
        progress_callback(100)
    return result, use_precise_finance
