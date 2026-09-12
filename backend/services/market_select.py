"""行情选股服务：大盘环境过滤 → 分轨制初筛 → 四大策略严格匹配。

流程
  第一段 大环境过滤（analyze_index_regime）
      读取大盘指数（默认上证指数 sh000001）日线：
        · 当日跌幅超过 1%                        → 终止选股，输出空仓
        · 均线空头排列(MA5<MA10<MA20) 且 MA20 下行且收盘在 MA20 下方
          （明显的单边下跌趋势）                  → 终止选股，输出空仓
      仅在「震荡企稳 / 温和上涨」状态下才进入下一段。

  第二段 分轨制初筛（两条轨道互斥，各自独立，不共享初筛条件）
      · 顺势轨道（TRACK_TREND，主力，仓位 100%）
          初筛：MA60 连续 10 天上涨 + 收盘价 > MA60 + 偏离 MA20 ≤ 20%
                + 250 日区间位置 < 85%
          只匹配：上升回调策略（低吸）→ 单边上升策略（追涨）
      · 逆势轨道（TRACK_COUNTER，小仓位试错，仓位上限 30%）
          初筛：MA60 走平或向下 + (股价 < MA60×0.8 或 RSI 历史低位)
          只匹配：震荡盘整策略 → 单边下跌策略

  第三段 策略匹配：轨道内「逐级按优先级取首个命中」，严格遵循
      「能低吸就不追涨」——同时符合上升回调与单边上升时，优先回调买入。
      全局优先级：顺势轨道整体优先于逆势轨道。

  第四段 若一只都没命中 → 输出空仓建议并终止。

候选池来自本地股票列表（backend/data/stock_list.json），不依赖新浪全市场分页接口
—— 该接口无缓存、每次约 60 次请求，实测会触发 IP 封禁。
"""

import math
import re
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from services.akshare_service import data_service

# ── 通用 ──────────────────────────────
_MAX_WORKERS = 16
_BATCH = 16
# 需要 250 日区间 + MA60 + 连续10日判定，取 260 根；不足 260 根说明上市不久
_KLINE_COUNT = 260
_MIN_BARS = 70                   # MA60(60) + 连续10日比较(11) 的最低根数

# ── 第一段：大环境过滤 ─────────────────
_INDEX_SYMBOL = "sh000001"
_INDEX_NAME = "上证指数"
_MAX_INDEX_DROP_PCT = 1.0        # 大盘当日跌幅阈值（%）
_INDEX_MA20_DOWN_WINDOW = 5      # MA20 下行判定回看窗口（交易日）

# ── 第二段：分轨制初筛 ─────────────────
TRACK_TREND = "trend"            # 顺势轨道
TRACK_COUNTER = "counter"        # 逆势 / 震荡轨道
TRACK_LABELS = {TRACK_TREND: "顺势轨道", TRACK_COUNTER: "逆势轨道"}
# 每条轨道内的策略顺序 —— 低吸优先于追涨
TRACK_STRATEGIES = {
    TRACK_TREND: ("pullback", "uptrend"),
    TRACK_COUNTER: ("oscillation", "downtrend"),
}
# 全局优先级：顺势轨道整体优先于逆势轨道
STRATEGY_ORDER = TRACK_STRATEGIES[TRACK_TREND] + TRACK_STRATEGIES[TRACK_COUNTER]
# 逆势轨道仓位上限（总资金的 30%），两个策略都必须遵守
_COUNTER_MAX_POSITION = 0.30
# 顺势轨道仓位
_TREND_POSITION = 1.0

# 顺势轨道初筛参数
_PRESCREEN_MA60_UP_DAYS = 10     # MA60 连续上涨天数
_PRESCREEN_POSITION_MAX = 0.85   # 250 日区间位置上限
_PRESCREEN_DEVIATION_MAX = 0.20  # 相对 MA20 的偏离上限

# 逆势轨道初筛参数
_COUNTER_MA60_FLAT_PCT = 0.01    # MA60 近 10 日涨幅 < 1% 视为走平
_COUNTER_MA60_DEVIATION = 0.80   # 股价低于 MA60 的 0.8 倍视为严重偏离
_COUNTER_RSI_OVERSOLD = 30       # RSI 绝对超卖线
_COUNTER_RSI_PCTL = 0.10         # RSI 处于近 250 日区间下方 10% 分位

# 两轨共有
_MIN_LIST_DAYS = 60              # 上市天数下限（自然日）

# ── 第三段：策略参数 ───────────────────
_MAX_GAIN_PCT = 9.5              # 当日涨幅上限（%），涨停买不进
_PULLBACK_J_TURN = 40            # J 值低位拐头阈值
_PULLBACK_RSI_LOW = 35
_PULLBACK_RSI_HIGH = 50
_PULLBACK_BAND_LOW = 0.95        # 股价可低于 MA20 5%
_PULLBACK_BAND_HIGH = 1.03       # 股价可高于 MA20 3%
_PULLBACK_FORCE_LOW = 1.05       # 高于 MA20 5% 时强制要求跌至布林下轨
_OSC_RSI_OVERSOLD = 30
_OSC_MA20_FLAT_PCT = 0.02        # MA20 近 10 日变动小于 2% 视为走平
_DOWNTREND_RSI_OVERSOLD = 20

# 被剔除的板块：创业板(300/301/302)、科创板(688/689，689 为 CDR)、北交所(920/43/83/87)
_EXCLUDED_CODE_PREFIXES = ("300", "301", "302", "688", "689", "920", "43", "83", "87")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

STRATEGY_LABELS = {
    "pullback": "上升回调策略",
    "uptrend": "单边上升策略",
    "oscillation": "震荡盘整策略",
    "downtrend": "单边下跌策略",
}


def is_excluded_board(code: str) -> bool:
    """是否属于被剔除的板块（创业板 / 科创板 / 北交所）

    用三位前缀而非 "300"/"688"：创业板还有 301xxx、302xxx，科创板还有 689xxx(CDR)，
    只匹配 "300"/"688" 会漏掉约 470 只。
    """
    return code.startswith(_EXCLUDED_CODE_PREFIXES)


# ═══════════ 数据获取 ═══════════

def _fetch_klines(code: str, count: int = _KLINE_COUNT) -> tuple[list[dict], str]:
    """拉取日线，返回 (klines, 数据源)。

    数据源为 "tencent"（前复权）或 "sina"（**不复权**，仅腾讯失败时兜底）。
    新浪兜底数据未复权，除权股的均线会失真，调用方应统计并提示。
    """
    for source, fetcher in (("tencent", data_service._kline_from_tencent),
                            ("sina", data_service._kline_from_sina)):
        try:
            k = fetcher(code, "daily", count)
            if k and len(k) >= _MIN_BARS:
                return k, source
        except Exception:
            continue
    return [], ""


# ═══════════ 第一段：大环境过滤 ═══════════

def analyze_index_regime(index_klines: list[dict]) -> dict:
    """判断大盘环境。

    返回 dict：
      available  指数数据是否可用
      blocked    是否应终止今日选股（空仓）
      regime     uptrend / range / downtrend / unknown
      label      「温和上涨」「震荡企稳」「单边下跌」「数据不可用」
      reason     可读说明
      close / change_pct / ma5 / ma10 / ma20 / ma60   指标快照
    """
    if not index_klines or len(index_klines) < 20:
        return {
            "available": False, "blocked": False, "regime": "unknown",
            "label": "数据不可用",
            "reason": "大盘指数数据不足，已跳过大环境过滤（结果可能偏乐观）",
            "symbol": _INDEX_SYMBOL, "name": _INDEX_NAME,
            "close": None, "change_pct": None,
            "ma5": None, "ma10": None, "ma20": None, "ma60": None,
        }

    s = pd.Series([float(k["close"]) for k in index_klines])
    c = float(s.iloc[-1])
    prev = float(s.iloc[-2])
    change_pct = (c / prev - 1) * 100 if prev else 0.0

    ma5 = float(s.rolling(5).mean().iloc[-1])
    ma10 = float(s.rolling(10).mean().iloc[-1])
    ma20_series = s.rolling(20).mean()
    ma20 = float(ma20_series.iloc[-1])
    ma60 = float(s.rolling(60).mean().iloc[-1]) if len(s) >= 60 else None

    w = _INDEX_MA20_DOWN_WINDOW
    ma20_prev = float(ma20_series.iloc[-1 - w]) if len(s) > w else ma20

    bear_align = ma5 < ma10 < ma20           # 均线空头排列
    ma20_down = ma20 < ma20_prev             # MA20 走低
    below_ma20 = c < ma20                    # 收盘在 MA20 下方
    downtrend = bear_align and ma20_down and below_ma20

    base = {
        "available": True, "symbol": _INDEX_SYMBOL, "name": _INDEX_NAME,
        "close": round(c, 2), "change_pct": round(change_pct, 2),
        "ma5": round(ma5, 2), "ma10": round(ma10, 2), "ma20": round(ma20, 2),
        "ma60": round(ma60, 2) if ma60 is not None else None,
    }

    if change_pct < -_MAX_INDEX_DROP_PCT:
        return {**base, "blocked": True, "regime": "downtrend", "label": "单边下跌",
                "reason": f"大盘当日跌幅 {change_pct:.2f}%，超过 {_MAX_INDEX_DROP_PCT:.1f}% 阈值"}

    if downtrend:
        return {**base, "blocked": True, "regime": "downtrend", "label": "单边下跌",
                "reason": "大盘呈均线空头排列（MA5<MA10<MA20）、MA20 下行且收盘在 MA20 下方的单边下跌趋势"}

    if c > ma20 and ma5 > ma10:
        return {**base, "blocked": False, "regime": "uptrend", "label": "温和上涨",
                "reason": f"大盘 {change_pct:+.2f}%，站上 MA20 且 MA5>MA10，环境允许选股"}

    return {**base, "blocked": False, "regime": "range", "label": "震荡企稳",
            "reason": f"大盘 {change_pct:+.2f}%，未跌破 1% 且非空头单边下跌，环境允许选股"}


# ═══════════ 指标计算 ═══════════

def _compute_indicators(klines: list[dict]) -> dict | None:
    """计算最后一根 K 线所需的全部指标；数据不足或异常返回 None"""
    n = len(klines)
    if n < _MIN_BARS:
        return None
    try:
        dates = [str(k.get("date") or "")[:10] for k in klines]
        s = pd.Series([float(k["close"]) for k in klines])
        hi = pd.Series([float(k["high"]) for k in klines])
        lo = pd.Series([float(k["low"]) for k in klines])
        vo = pd.Series([float(k.get("volume") or 0) for k in klines])
    except (TypeError, ValueError, KeyError):
        return None

    ma5, ma10 = s.rolling(5).mean(), s.rolling(10).mean()
    ma20, ma60 = s.rolling(20).mean(), s.rolling(60).mean()
    std20 = s.rolling(20).std()
    boll_up, boll_low = ma20 + 2 * std20, ma20 - 2 * std20

    ema12 = s.ewm(span=12, adjust=False).mean()
    ema26 = s.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)

    low9, high9 = lo.rolling(9).min(), hi.rolling(9).max()
    rsv = (s - low9) / (high9 - low9).replace(0, np.nan) * 100
    kdj_k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    kdj_d = kdj_k.ewm(alpha=1 / 3, adjust=False).mean()
    kdj_j = 3 * kdj_k - 2 * kdj_d

    delta = s.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss)

    high250 = hi.rolling(250, min_periods=20).max()
    low250 = lo.rolling(250, min_periods=20).min()
    vol5 = vo.rolling(5).mean()

    rsi_last = float(rsi.iloc[-1])
    rsi_min250 = float(rsi.rolling(250, min_periods=60).min().iloc[-1])
    rsi_max250 = float(rsi.rolling(250, min_periods=60).max().iloc[-1])
    # RSI 历史低位：绝对超卖，或处于近 250 日 RSI 区间下方 10% 分位
    if math.isfinite(rsi_min250) and math.isfinite(rsi_max250) and rsi_max250 > rsi_min250:
        rsi_pctl_low = rsi_last <= rsi_min250 + _COUNTER_RSI_PCTL * (rsi_max250 - rsi_min250)
    else:
        rsi_pctl_low = False
    rsi_historic_low = bool(rsi_last < _COUNTER_RSI_OVERSOLD or rsi_pctl_low)

    v = {
        "close": float(s.iloc[-1]), "prev_close": float(s.iloc[-2]),
        "high": float(hi.iloc[-1]), "low": float(lo.iloc[-1]),
        "ma5": float(ma5.iloc[-1]), "ma10": float(ma10.iloc[-1]),
        "ma20": float(ma20.iloc[-1]), "ma60": float(ma60.iloc[-1]),
        "ma5_prev": float(ma5.iloc[-2]), "ma20_prev": float(ma20.iloc[-2]),
        "boll_up": float(boll_up.iloc[-1]), "boll_low": float(boll_low.iloc[-1]),
        "dif": float(dif.iloc[-1]), "dea": float(dea.iloc[-1]),
        "hist": float(hist.iloc[-1]), "hist_prev": float(hist.iloc[-2]),
        "j": float(kdj_j.iloc[-1]), "j_prev": float(kdj_j.iloc[-2]),
        "k": float(kdj_k.iloc[-1]), "d": float(kdj_d.iloc[-1]),
        "rsi": rsi_last, "rsi_historic_low": rsi_historic_low,
        "vol5": float(vol5.iloc[-1]), "vol5_prev": float(vo.iloc[-10:-5].mean()),
        "high250": float(high250.iloc[-1]), "low250": float(low250.iloc[-1]),
        "high10": float(s.iloc[-10:].max()),
        "highest20_prev": float(s.rolling(20).max().shift(1).iloc[-1]),
        "low20_prev": float(lo.rolling(20).min().shift(1).iloc[-1]),
        "ma20_10ago": float(ma20.iloc[-11]), "ma60_10ago": float(ma60.iloc[-11]),
        "ma60_up10": bool(np.all(np.diff(ma60.iloc[-11:].to_numpy()) > 0)),
        "first_date": dates[0], "last_date": dates[-1],
        "bars": n,
    }

    required = ("close", "prev_close", "ma5", "ma10", "ma20", "ma60", "boll_up",
                "boll_low", "dif", "dea", "hist", "hist_prev", "j", "j_prev",
                "rsi", "high250", "low250", "ma20_10ago", "ma60_10ago")
    if any(not math.isfinite(v[k]) for k in required):
        return None
    return v


def _list_days(first_date: str, last_date: str) -> int | None:
    """两个日期之间的自然日跨度"""
    try:
        return int((pd.Timestamp(last_date) - pd.Timestamp(first_date)).days)
    except Exception:
        return None


# ═══════════ 第二段：分轨制初筛 ═══════════

def _prescreen_trend(v: dict) -> tuple[bool, str]:
    """顺势轨道初筛：MA60连涨10天 + close>MA60 + 偏离MA20≤20% + 250日位置<85%"""
    c = v["close"]

    if not v["ma60_up10"]:
        return False, f"MA60 未连续 {_PRESCREEN_MA60_UP_DAYS} 天上涨"

    rng = v["high250"] - v["low250"]
    if rng <= 0:
        return False, "250 日区间无波动"
    position = (c - v["low250"]) / rng
    if position >= _PRESCREEN_POSITION_MAX:
        return False, f"250 日区间位置 {position * 100:.1f}% ≥ {_PRESCREEN_POSITION_MAX * 100:.0f}%"

    if c <= v["ma60"]:
        return False, "收盘价未站上 MA60"

    deviation = (c - v["ma20"]) / v["ma20"]
    if deviation > _PRESCREEN_DEVIATION_MAX:
        return False, f"偏离 MA20 {deviation * 100:.1f}% > {_PRESCREEN_DEVIATION_MAX * 100:.0f}%"

    return True, ""


def _prescreen_counter(v: dict) -> tuple[bool, str]:
    """逆势轨道初筛：MA60走平或向下 + (股价 < MA60×0.8 或 RSI 历史低位)

    与顺势轨道完全独立，不共享任何初筛条件（250 日位置 / 偏离 MA20 均不适用）。
    """
    if not (v["ma60"] <= v["ma60_10ago"] * (1 + _COUNTER_MA60_FLAT_PCT)):
        return False, "MA60 仍在明显上行（不属逆势轨道）"

    deep = v["close"] < v["ma60"] * _COUNTER_MA60_DEVIATION
    if not (deep or v["rsi_historic_low"]):
        return False, "既未严重偏离 MA60，RSI 也不在历史低位"

    return True, ""


_PRESCREENS = {TRACK_TREND: _prescreen_trend, TRACK_COUNTER: _prescreen_counter}


# ═══════════ 第三段：四大策略 ═══════════

def _match_pullback(v: dict) -> tuple[bool, str]:
    """上升回调策略（低吸，优先级最高）

    上升趋势 + 近期缩量回调 + DIFF>0 + (J低位拐头 或 RSI 35~50)
    + 股价在 MA20 的 -5%~+3% 区间内。
    若股价高于 MA20 超过 5%，则不满足区间条件，只能通过「跌破布林下轨」这一路径入选。
    """
    c, ma20 = v["close"], v["ma20"]

    if not (ma20 > v["ma60"]):
        return False, "MA20 未站上 MA60（非上升趋势）"

    # 近期缩量回调：近 5 日均量低于前 5 日，且已从近 10 日高点回落
    if not (v["vol5"] > 0 and v["vol5_prev"] > 0 and v["vol5"] < v["vol5_prev"]):
        return False, "近期未缩量"
    if not (c < v["high10"]):
        return False, "股价仍处于近 10 日高点（未回调）"

    if not (v["dif"] > 0):
        return False, "MACD 的 DIFF 未在 0 轴上方"

    j_turn = v["j"] < _PULLBACK_J_TURN and v["j"] > v["j_prev"]
    rsi_pull = _PULLBACK_RSI_LOW <= v["rsi"] <= _PULLBACK_RSI_HIGH
    if not (j_turn or rsi_pull):
        return False, f"动能不足（J={v['j']:.1f}，RSI={v['rsi']:.1f}）"

    in_band = ma20 * _PULLBACK_BAND_LOW <= c <= ma20 * _PULLBACK_BAND_HIGH
    below_lower = c <= v["boll_low"]
    if not (in_band or below_lower):
        if c > ma20 * _PULLBACK_FORCE_LOW:
            return False, f"股价高于 MA20 超过 {(_PULLBACK_FORCE_LOW - 1) * 100:.0f}%，且未跌至布林下轨"
        return False, "股价不在 MA20 的 -5%~+3% 区间内"

    parts = ["缩量回调", "DIFF>0"]
    if j_turn:
        parts.append(f"J={v['j']:.1f}低位拐头")
    if rsi_pull:
        parts.append(f"RSI={v['rsi']:.1f}回落区间")
    parts.append("跌破布林下轨" if below_lower else "贴近MA20")
    return True, " + ".join(parts)


def _match_uptrend(v: dict) -> tuple[bool, str]:
    """单边上升策略（追涨）：均线多头发散 + MACD 刚翻红 + (站上MA5 或 突破20日最高收盘价) + 涨幅<9.5%"""
    c = v["close"]

    if not (v["ma5"] > v["ma10"] > v["ma20"] > v["ma60"]):
        return False, "均线未形成多头排列"

    spread_now = v["ma5"] - v["ma20"]
    spread_prev = v["ma5_prev"] - v["ma20_prev"]
    if not (spread_now > spread_prev):
        return False, "均线未发散（MA5 与 MA20 距离未扩大）"

    if not (v["hist_prev"] <= 0 < v["hist"]):
        return False, "MACD 未刚翻红"

    gain_pct = (c / v["prev_close"] - 1) * 100 if v["prev_close"] else 0.0
    if gain_pct >= _MAX_GAIN_PCT:
        return False, f"当日涨幅 {gain_pct:.2f}% ≥ {_MAX_GAIN_PCT}%"

    above_ma5 = c > v["ma5"]
    h20 = v["highest20_prev"]
    breakout = math.isfinite(h20) and c > h20
    if not (above_ma5 or breakout):
        return False, "未站上 MA5 且未突破 20 日最高收盘价"

    return True, " + ".join(["均线多头发散", "MACD刚翻红",
                             "站上MA5" if above_ma5 else "突破20日新高"])


def _match_oscillation(v: dict) -> tuple[bool, str]:
    """震荡盘整策略：MA20>MA60 且均线走平 + 三项买点满足至少两项

    三项：触及布林下轨 / RSI<30 / J<0 且拐头向上
    """
    c = v["close"]

    if not (v["ma20"] > v["ma60"]):
        return False, "MA20 未站上 MA60"
    if not (abs(v["ma20"] / v["ma20_10ago"] - 1) < _OSC_MA20_FLAT_PCT):
        return False, "MA20 未走平"

    c1 = c <= v["boll_low"]
    c2 = v["rsi"] < _OSC_RSI_OVERSOLD
    c3 = v["j"] < 0 and v["j"] > v["j_prev"]
    count = int(c1) + int(c2) + int(c3)
    if count < 2:
        return False, f"买点仅满足 {count}/3 项"

    parts = []
    if c1:
        parts.append("触及布林下轨")
    if c2:
        parts.append(f"RSI={v['rsi']:.1f}<30")
    if c3:
        parts.append(f"J={v['j']:.1f}<0拐头")
    return True, f"{count}/3 项：" + " + ".join(parts)


def _match_downtrend(v: dict) -> tuple[bool, str]:
    """单边下跌策略：RSI<20 + 最低价创20日新低 + MACD绿柱缩短 + 当日收阳

    四条件缺一不可，仓位受逆势轨道上限约束（30%）。
    """
    c = v["close"]
    if not (v["rsi"] < _DOWNTREND_RSI_OVERSOLD):
        return False, f"RSI={v['rsi']:.1f} 未低于 {_DOWNTREND_RSI_OVERSOLD}"
    low20 = v["low20_prev"]
    if not (math.isfinite(low20) and v["low"] <= low20):
        return False, "最低价未创 20 日新低"
    if not (v["hist"] < 0 and v["hist"] > v["hist_prev"]):
        return False, "MACD 绿柱未缩短"
    if not (c > v["prev_close"]):
        return False, "当日未收阳"
    return True, "RSI<20 + 创20日新低 + 绿柱缩短 + 收阳"


_MATCHERS = {
    "pullback": _match_pullback,
    "uptrend": _match_uptrend,
    "oscillation": _match_oscillation,
    "downtrend": _match_downtrend,
}


# ═══════════ 单只股票评估 ═══════════

def _evaluate(code: str, name: str) -> tuple[dict | None, str | None, str]:
    """返回 (选股结果或 None, 最后一根K线日期或 None, 数据源)。

    先走顺势轨道（低吸优先于追涨），不通过再走逆势轨道（小仓位）。
    日期为 None 表示取数失败；返回日期供调用方判定停牌。
    """
    klines, source = _fetch_klines(code)
    if not klines:
        return None, None, ""

    last_date = str(klines[-1].get("date") or "")[:10]
    if not _DATE_RE.match(last_date):
        return None, None, ""

    v = _compute_indicators(klines)
    if v is None:
        return None, last_date, source

    # 上市天数 > 60 天：未取满 _KLINE_COUNT 根说明是次新股，首根即上市首日
    if v["bars"] < _KLINE_COUNT:
        days = _list_days(v["first_date"], last_date)
        if days is None or days <= _MIN_LIST_DAYS:
            return None, last_date, source

    # 轨道顺序即优先级：顺势（主力，100% 仓位）→ 逆势（试错，≤30% 仓位）
    for track in (TRACK_TREND, TRACK_COUNTER):
        ok, _reason = _PRESCREENS[track](v)
        if not ok:
            continue
        # 轨道内策略顺序同样遵循「能低吸就不追涨」
        for key in TRACK_STRATEGIES[track]:
            hit, detail = _MATCHERS[key](v)
            if not hit:
                continue
            gain_pct = (v["close"] / v["prev_close"] - 1) * 100 if v["prev_close"] else 0.0
            position = _TREND_POSITION if track == TRACK_TREND else _COUNTER_MAX_POSITION
            return {
                "code": code,
                "name": name,
                "track": track,
                "track_label": TRACK_LABELS[track],
                "strategy": key,
                "strategy_label": STRATEGY_LABELS[key],
                "reason": detail,
                "position_size": position,
                "gain_pct": round(gain_pct, 2),
                "close": round(v["close"], 2),
                "ma5": round(v["ma5"], 2),
                "ma10": round(v["ma10"], 2),
                "ma20": round(v["ma20"], 2),
                "ma60": round(v["ma60"], 2),
                "dif": round(v["dif"], 3),
                "j": round(v["j"], 2),
                "rsi": round(v["rsi"], 2),
                "date": last_date,
                "source": source,
            }, last_date, source

    return None, last_date, source


# ═══════════ 主流程 ═══════════

def _payload(action: str, message: str, market: dict, results: list, stats: dict) -> dict:
    return {"action": action, "message": message, "market": market,
            "results": results, "stats": stats}


def market_select(progress_callback=None, stats_out: dict | None = None) -> dict:
    """全市场行情选股（大盘过滤 → 分轨初筛 → 四大策略匹配）。

    Returns:
        {
          "action": "select" | "empty",
          "message": 空仓原因 / 完成说明,
          "market": 大盘环境快照,
          "results": 命中标的列表（顺势轨道优先，其次逆势轨道）,
          "stats": 各阶段统计,
        }
    """
    if stats_out is not None:
        stats_out.clear()

    # ── 第一段：大环境过滤 ──
    if progress_callback:
        progress_callback(2)
    market = analyze_index_regime(data_service.get_index_kline(_INDEX_SYMBOL, _KLINE_COUNT))

    if market["blocked"]:
        stats = {"terminated_at": "market_regime", "candidates": 0,
                 "prescreen_passed": 0, "matched": 0}
        if stats_out is not None:
            stats_out.update(stats)
        if progress_callback:
            progress_callback(100)
        return _payload("empty",
                        f"今日空仓：{market['reason']}。大环境不适合入场，已终止本次选股。",
                        market, [], stats)

    # ── 候选池（本地列表，剔除 ST / 创业板 / 科创板 / 北交所）──
    if progress_callback:
        progress_callback(6)
    all_stocks = data_service.get_all_stocks()
    if not all_stocks:
        raise ValueError("股票列表不可用（本地缓存缺失且 akshare 拉取失败），无法选股")

    candidates: list[tuple[str, str]] = []
    skipped_st = skipped_board = 0
    for r in all_stocks:
        if r.get("type") != "stock":
            continue
        code = str(r.get("code") or "")
        name = str(r.get("name") or "")
        if not code:
            continue
        if "ST" in name.upper():
            skipped_st += 1
            continue
        if is_excluded_board(code):
            skipped_board += 1
            continue
        candidates.append((code, name))

    if not candidates:
        raise ValueError("无候选股票")

    # ── 第二、三段：并发初筛 + 策略匹配 ──
    total = len(candidates)
    # (code, name, 最后一根K线日期, 选股结果或 None, 数据源)
    entries: list[tuple[str, str, str, dict | None, str]] = []
    fetch_failed = 0

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as ex:
        for start in range(0, total, _BATCH):
            end = min(start + _BATCH, total)
            chunk = candidates[start:end]
            for (code, name), (res, last_date, source) in zip(
                chunk, ex.map(lambda cn: _evaluate(cn[0], cn[1]), chunk)
            ):
                if last_date is None:
                    fetch_failed += 1
                else:
                    entries.append((code, name, last_date, res, source))
            if progress_callback:
                progress_callback(6 + int(end / total * 94))

    if not entries:
        raise ValueError(
            f"全部 {total} 只股票取数失败（数据源可能限流或网络不可用），未做任何有效判定"
        )

    # 数据新鲜度：以观测到的最新日期为基准，早于它的视为停牌/长期无成交
    reference_date = max(e[2] for e in entries)
    results = [e[3] for e in entries if e[3] and e[2] == reference_date]
    stale = sum(1 for e in entries if e[2] < reference_date)

    results.sort(key=lambda r: (STRATEGY_ORDER.index(r["strategy"]), r["code"]))
    fallback_sina = sum(1 for e in entries if e[4] == "sina")

    stats = {
        "candidates": total,
        "skipped_st": skipped_st,
        "skipped_board": skipped_board,
        "fetch_failed": fetch_failed,
        "stale": stale,
        "evaluated": len(entries),
        "matched": len(results),
        "reference_date": reference_date,
        "fallback_sina": fallback_sina,
        "by_track": {k: sum(1 for r in results if r["track"] == k) for k in TRACK_LABELS},
        "by_strategy": {k: sum(1 for r in results if r["strategy"] == k) for k in STRATEGY_ORDER},
    }
    if stats_out is not None:
        stats_out.update(stats)
    if progress_callback:
        progress_callback(100)

    # ── 第四段：无命中 → 空仓 ──
    if not results:
        return _payload(
            "empty",
            f"今日空仓：{total} 只候选、{len(entries)} 只完成判定，但无一满足四大策略的严格条件，建议空仓等待。",
            market, [], stats)

    trend_n = stats["by_track"].get(TRACK_TREND, 0)
    counter_n = stats["by_track"].get(TRACK_COUNTER, 0)
    return _payload(
        "select",
        f"大盘{market['label']}，共命中 {len(results)} 只（顺势 {trend_n} / 逆势 {counter_n}）。",
        market, results, stats)
