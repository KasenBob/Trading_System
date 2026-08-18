"""行情选股服务：按单边上升技术条件筛选全市场股票。

选股条件（全部满足才进入候选池）：
  1. 均线多头排列：MA5 > MA10 > MA20（硬前提）
  2. 通道1：站上MA5 + MACD翻红（柱线由绿转红）
     或 通道2：突破过去20日最高收盘价 + 当日涨幅 < 9.5%
  3. 收盘价 > MA60（生命线之上）
"""

import math
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from services.akshare_service import data_service


def _fetch_klines(code: str, count: int = 120) -> list[dict]:
    """拉取最近 count 根日线（腾讯优先、新浪兜底），返回时间升序列表"""
    for fetcher in (data_service._kline_from_tencent, data_service._kline_from_sina):
        try:
            k = fetcher(code, "daily", count)
            if k and len(k) >= 60:
                return k
        except Exception:
            continue
    return []


def _check_uptrend(code: str, name: str) -> dict | None:
    """判断单只股票是否满足单边上升选股条件，满足返回展示字段，否则返回 None"""
    klines = _fetch_klines(code)
    if not klines:
        return None

    closes = []
    for k in klines:
        v = k.get("close")
        if v is None:
            return None
        closes.append(float(v))
    if len(closes) < 60:
        return None

    close = pd.Series(closes)
    c = float(close.iloc[-1])
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma60 = float(close.rolling(60).mean().iloc[-1])
    if any(pd.isna(x) for x in (ma5, ma10, ma20, ma60)):
        return None

    # 条件1：均线多头排列 MA5 > MA10 > MA20
    if not (ma5 > ma10 > ma20):
        return None
    # 条件3：收盘价 > MA60
    if not (c > ma60):
        return None

    # 条件2：通道1（站上MA5 + MACD翻红）或 通道2（突破20日最高 + 当日涨幅<9.5%）
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)
    h = float(hist.iloc[-1])
    hp = float(hist.iloc[-2])
    channel1 = c > ma5 and hp <= 0 < h

    highest20 = float(close.rolling(20).max().shift(1).iloc[-1])
    prev_close = float(close.iloc[-2])
    gain_pct = (c / prev_close - 1) * 100 if prev_close else 0.0
    channel2 = (not math.isnan(highest20)) and c > highest20 and gain_pct < 9.5

    if not (channel1 or channel2):
        return None

    return {
        "code": code,
        "name": name,
        "channel": "通道1·站上MA5+MACD翻红" if channel1 else "通道2·突破20日新高",
        "channel1": bool(channel1),
        "channel2": bool(channel2),
        "gain_pct": round(gain_pct, 2),
        "close": round(c, 2),
        "ma5": round(ma5, 2),
        "ma10": round(ma10, 2),
        "ma20": round(ma20, 2),
        "ma60": round(ma60, 2),
    }


def market_select(progress_callback=None) -> list[dict]:
    """全市场行情选股：筛选满足单边上升条件的股票（全部满足才进入候选池）"""
    def _map_progress(p):
        if progress_callback:
            progress_callback(int(p * 15 / 80))

    records = data_service.get_full_market_data(progress_callback=_map_progress)
    if not records:
        raise ValueError("无法获取全市场数据")
    if progress_callback:
        progress_callback(15)

    # 过滤候选：仅股票，剔除 ST、科创板(688)、创业板(300)
    candidates = []
    for r in records:
        if r.get("type") != "stock":
            continue
        code = str(r.get("code") or "")
        name = str(r.get("name") or "")
        if not code:
            continue
        if "ST" in name.upper():
            continue
        if code.startswith(("688", "300")):
            continue
        candidates.append((code, name))
    if not candidates:
        raise ValueError("无候选股票")

    total = len(candidates)
    results: list[dict] = []
    batch = 16
    for start in range(0, total, batch):
        end = min(start + batch, total)
        with ThreadPoolExecutor(max_workers=batch) as ex:
            for r in ex.map(lambda cn: _check_uptrend(cn[0], cn[1]), candidates[start:end]):
                if r:
                    results.append(r)
        if progress_callback:
            progress_callback(15 + int(end / total * 85))

    if progress_callback:
        progress_callback(100)
    return results
