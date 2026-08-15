"""回测引擎 — 策略信号生成 + 模拟交易 + 绩效计算"""

import numpy as np
import pandas as pd


class BacktestEngine:
    def __init__(self, kline_data: list[dict], initial_capital: float = 100000):
        self.df = pd.DataFrame(kline_data)
        if self.df.empty: raise ValueError("K线数据为空")
        self.df["date"] = pd.to_datetime(self.df["date"])
        self.df = self.df.sort_values("date").reset_index(drop=True)
        self.initial_capital = initial_capital

    def signals_ma_cross(self, fast=5, slow=20):
        df = self.df
        df["ma_fast"] = df["close"].rolling(fast).mean()
        df["ma_slow"] = df["close"].rolling(slow).mean()
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "ma_fast"]) or pd.isna(df.loc[i, "ma_slow"]): continue
            if df.loc[i-1, "ma_fast"] <= df.loc[i-1, "ma_slow"] and df.loc[i, "ma_fast"] > df.loc[i, "ma_slow"]:
                sig.iloc[i] = 1
            elif df.loc[i-1, "ma_fast"] >= df.loc[i-1, "ma_slow"] and df.loc[i, "ma_fast"] < df.loc[i, "ma_slow"]:
                sig.iloc[i] = -1
        return sig

    def signals_macd(self, fast=12, slow=26, signal_period=9, ma_filter=60):
        """MACD 策略（含 60 日均线过滤器）：
        开仓：股价站在 MA_filter 上方，且 MACD 金叉（DIF 上穿 DEA）
        卖出：股价跌破 MA_filter，直接空仓不交易
        """
        df = self.df
        df["ema_fast"] = df["close"].ewm(span=fast, adjust=False).mean()
        df["ema_slow"] = df["close"].ewm(span=slow, adjust=False).mean()
        df["dif"] = df["ema_fast"] - df["ema_slow"]
        df["dea"] = df["dif"].ewm(span=signal_period, adjust=False).mean()
        df["ma_filter"] = df["close"].rolling(ma_filter).mean()
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "dif"]) or pd.isna(df.loc[i, "dea"]): continue
            ma = df.loc[i, "ma_filter"]
            prev_ma = df.loc[i - 1, "ma_filter"]
            if pd.isna(ma) or pd.isna(prev_ma): continue

            close = df.loc[i, "close"]
            prev_close = df.loc[i - 1, "close"]

            # 卖出：股价跌破 60 日均线 → 直接空仓，不交易
            if prev_close >= prev_ma and close < ma:
                sig.iloc[i] = -1
                continue

            # 开仓：股价在 60 日均线上方 + MACD 金叉
            if close > ma:
                if df.loc[i-1, "dif"] <= df.loc[i-1, "dea"] and df.loc[i, "dif"] > df.loc[i, "dea"]:
                    sig.iloc[i] = 1
        return sig

    def signals_bollinger(self, period=20, std=2.0):
        df = self.df
        df["ma"] = df["close"].rolling(period).mean()
        df["stdv"] = df["close"].rolling(period).std()
        df["upper"] = df["ma"] + std * df["stdv"]
        df["lower"] = df["ma"] - std * df["stdv"]
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "lower"]): continue
            if df.loc[i-1, "close"] >= df.loc[i-1, "lower"] and df.loc[i, "close"] < df.loc[i, "lower"]:
                sig.iloc[i] = 1
            elif df.loc[i-1, "close"] <= df.loc[i-1, "upper"] and df.loc[i, "close"] > df.loc[i, "upper"]:
                sig.iloc[i] = -1
        return sig

    def signals_rsi(self, period=14, oversold=30, overbought=70):
        """RSI 超买超卖：RSI 上穿超卖线买入，下穿超买线卖出"""
        df = self.df
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "rsi"]): continue
            if df.loc[i-1, "rsi"] < oversold and df.loc[i, "rsi"] >= oversold:
                sig.iloc[i] = 1
            elif df.loc[i-1, "rsi"] > overbought and df.loc[i, "rsi"] <= overbought:
                sig.iloc[i] = -1
        return sig

    def signals_kdj(self, n=9, k_period=3, d_period=3):
        """KDJ 随机指标：K上穿D买入，K下穿D卖出"""
        df = self.df
        low_n = df["low"].rolling(n).min()
        high_n = df["high"].rolling(n).max()
        rsv = (df["close"] - low_n) / (high_n - low_n) * 100
        df["k"] = rsv.ewm(alpha=1/k_period, adjust=False).mean()
        df["d"] = df["k"].ewm(alpha=1/d_period, adjust=False).mean()
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "k"]) or pd.isna(df.loc[i, "d"]): continue
            if df.loc[i-1, "k"] <= df.loc[i-1, "d"] and df.loc[i, "k"] > df.loc[i, "d"]:
                sig.iloc[i] = 1
            elif df.loc[i-1, "k"] >= df.loc[i-1, "d"] and df.loc[i, "k"] < df.loc[i, "d"]:
                sig.iloc[i] = -1
        return sig

    def signals_turtle(self, entry=20, exit_period=10):
        """海龟交易：突破N日高点买入，跌破M日低点卖出"""
        df = self.df
        df["high_n"] = df["high"].rolling(entry).max()
        df["exit_low"] = df["low"].rolling(exit_period).min()
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i-1, "high_n"]) or pd.isna(df.loc[i-1, "exit_low"]): continue
            if df.loc[i, "close"] > df.loc[i-1, "high_n"]:
                sig.iloc[i] = 1
            elif df.loc[i, "close"] < df.loc[i-1, "exit_low"]:
                sig.iloc[i] = -1
        return sig

    def signals_momentum(self, period=20, threshold=0.05):
        """动量策略：N日涨幅超阈值买入，跌破均线卖出"""
        df = self.df
        df["ret"] = df["close"].pct_change(period)
        df["ma"] = df["close"].rolling(period).mean()
        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            if pd.isna(df.loc[i, "ret"]) or pd.isna(df.loc[i, "ma"]): continue
            if df.loc[i, "ret"] > threshold and df.loc[i, "close"] > df.loc[i, "ma"]:
                sig.iloc[i] = 1
            elif df.loc[i-1, "close"] >= df.loc[i-1, "ma"] and df.loc[i, "close"] < df.loc[i, "ma"]:
                sig.iloc[i] = -1
        return sig

    def signals_grid(self, grid_pct=5):
        """网格交易：价格相对基准价下跌超过一格买入，上涨超过一格卖出"""
        df = self.df
        sig = pd.Series(0, index=df.index)
        base = float(df.loc[0, "close"])
        for i in range(1, len(df)):
            close = float(df.loc[i, "close"])
            if close <= base * (1 - grid_pct / 100):
                sig.iloc[i] = 1
                base = close
            elif close >= base * (1 + grid_pct / 100):
                sig.iloc[i] = -1
                base = close
        return sig

    def signals_funnel(self, ma_fast=5, ma_slow=20, j_oversold=20, j_mid=50, j_band=10):
        """三层过滤漏斗策略（有序漏斗）：
        第一层 双均线：MA_fast > MA_slow（多头）才允许开新仓；
                卖出信号锁定为 5日线下穿20日线（死叉离场），当天直接空仓，不看任何其他信号。
        第二层 MACD：在均线多头前提下，DIF > 0（零轴上方）或 红柱持续变长。
        第三层 KDJ：满足前两层后，J 值低位金叉 或 J 值在 50 附近回踩不破 → 买入。
        """
        df = self.df
        # 第一层：双均线
        df["f_ma_fast"] = df["close"].rolling(ma_fast).mean()
        df["f_ma_slow"] = df["close"].rolling(ma_slow).mean()
        # 第二层：MACD（12/26/9 标准参数）
        df["f_ema_fast"] = df["close"].ewm(span=12, adjust=False).mean()
        df["f_ema_slow"] = df["close"].ewm(span=26, adjust=False).mean()
        df["f_dif"] = df["f_ema_fast"] - df["f_ema_slow"]
        df["f_dea"] = df["f_dif"].ewm(span=9, adjust=False).mean()
        df["f_hist"] = 2 * (df["f_dif"] - df["f_dea"])  # MACD 柱（红正绿负）
        # 第三层：KDJ（9/3/3 标准参数）
        low_n = df["low"].rolling(9).min()
        high_n = df["high"].rolling(9).max()
        rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, 1) * 100
        df["f_k"] = rsv.ewm(alpha=1 / 3, adjust=False).mean()
        df["f_d"] = df["f_k"].ewm(alpha=1 / 3, adjust=False).mean()
        df["f_j"] = 3 * df["f_k"] - 2 * df["f_d"]

        sig = pd.Series(0, index=df.index)
        holding = False
        for i in range(1, len(df)):
            fast = df.loc[i, "f_ma_fast"]; slow = df.loc[i, "f_ma_slow"]
            prev_fast = df.loc[i - 1, "f_ma_fast"]; prev_slow = df.loc[i - 1, "f_ma_slow"]
            if pd.isna(slow) or pd.isna(prev_slow):
                continue
            ma_up = fast > slow
            prev_ma_up = prev_fast > prev_slow

            # 卖出信号（唯一）：5日线严格下穿20日线（死叉离场）
            # 前一天 MA_fast 在上方、今日 MA_fast 跌破 MA_slow → 当天直接空仓，不看任何其他信号
            if prev_ma_up and fast < slow:
                if holding:
                    sig.iloc[i] = -1
                    holding = False
                continue

            # 第一层：均线非多头 → 不允许开仓
            if not ma_up:
                continue

            # 第二层：MACD 过滤
            dif = df.loc[i, "f_dif"]; hist = df.loc[i, "f_hist"]; prev_hist = df.loc[i - 1, "f_hist"]
            if pd.isna(dif) or pd.isna(hist) or pd.isna(prev_hist):
                continue
            macd_ok = (dif > 0) or (hist > 0 and hist > prev_hist)
            if not macd_ok:
                continue

            # 第三层：KDJ 触发买入
            j = df.loc[i, "f_j"]; prev_j = df.loc[i - 1, "f_j"]
            if pd.isna(j) or pd.isna(prev_j):
                continue
            golden_cross = (prev_j <= j_oversold) and (j > j_oversold)          # J 低位金叉
            pullback = (j_mid - j_band) <= prev_j <= (j_mid + j_band) and j > prev_j  # J 50 附近回踩不破
            if (golden_cross or pullback) and not holding:
                sig.iloc[i] = 1
                holding = True

        return sig

    def signals_uptrend(self, fast=5, trail_pct=8):
        """单边上升策略：均线多头排列 + 追涨/突破买入 + 双条件移动止损

        前提：MA_fast > MA10 > MA20（均线多头排列）
        买入通道1：站上 fast 日均线 + MACD 翻红（柱线由绿转红）→ 追买满仓
        买入通道2（突破）：今日收盘价 > 过去20个交易日最高收盘价 且 今日涨幅 < 9.5% → 直接买入
        卖出（仅两条，其余一律持有）：
          ① 从20日最高收盘价回撤超过 trail_pct%（默认8%）
          ② 跌破 MA60
        """
        df = self.df
        close = df["close"].astype(float)

        ma_fast = close.rolling(fast).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        dif = ema12 - ema26
        dea = dif.ewm(span=9, adjust=False).mean()
        hist = 2 * (dif - dea)

        # 近20日最高收盘价（含当日，用于移动止损）
        rolling_max20 = close.rolling(20).max()
        # 过去20个交易日的最高收盘价（不含当日，用于突破买入）
        highest20 = rolling_max20.shift(1)

        sig = pd.Series(0.0, index=df.index)
        position = 0       # 0=空仓, 1=持仓

        for i in range(1, len(df)):
            if (pd.isna(ma_fast.iloc[i]) or pd.isna(ma10.iloc[i]) or pd.isna(ma20.iloc[i])
                    or pd.isna(hist.iloc[i]) or pd.isna(hist.iloc[i - 1])):
                continue
            c = close.iloc[i]
            mf = ma_fast.iloc[i]
            h = hist.iloc[i]
            hp = hist.iloc[i - 1]

            if position == 1:
                # 卖出仅两条：① 从20日最高点回撤超过 trail_pct%；② 跌破 MA60
                cond1 = c < rolling_max20.iloc[i] * (1 - trail_pct / 100)
                cond2 = c < ma60.iloc[i]
                if cond1 or cond2:
                    position = 0
                    sig.iloc[i] = -1.0
                # 其余情况返回 0（持有）
                continue

            # 空仓：均线多头排列（MA_fast > MA10 > MA20）才允许开新仓
            if not (mf > ma10.iloc[i] > ma20.iloc[i]):
                continue

            # 通道1：站上均线 + MACD 翻红（柱线由绿转红）
            channel1 = c > mf and hp <= 0 < h
            # 通道2（突破）：收盘价 > 过去20日最高收盘价 且 今日涨幅 < 9.5%
            prev_close = close.iloc[i - 1]
            gain_pct = (c / prev_close - 1) * 100 if prev_close else 0.0
            hh20 = highest20.iloc[i]
            channel2 = (not pd.isna(hh20)) and c > hh20 and gain_pct < 9.5

            if channel1 or channel2:
                position = 1
                sig.iloc[i] = 1.0

        return sig

    def signals_oscillation(self, boll_period=10, boll_std=2.0, rsi_period=14,
                            rsi_oversold=30, rsi_overbought=70, kdj_n=9, kdj_k=3, kdj_d=3,
                            j_oversold=0, j_overbought=100):
        """震荡盘整策略（适合箱体震荡行情）：

        买入（需 MA20 > MA60 趋势过滤，且三选二满足任意两项即买入）：
          1. 股价触及/跌破布林带下轨（close <= lower）
          2. RSI 低于超卖线
          3. KDJ 的 J 值低于超卖线并拐头向上（今日 J > 昨日 J）
        卖出（两条件同时满足才卖出）：
          1. 股价触及布林带上轨（close >= upper * 0.99）
          2. RSI > 50
        注：rsi_overbought 参数保留兼容，卖出不再使用（固定 RSI > 50）。
        """
        df = self.df
        # 布林带
        mid = df["close"].rolling(boll_period).mean()
        std = df["close"].rolling(boll_period).std()
        df["boll_upper"] = mid + boll_std * std
        df["boll_lower"] = mid - boll_std * std
        # 均线趋势过滤（MA20 > MA60 才允许买入）
        df["ma20"] = df["close"].rolling(20).mean()
        df["ma60"] = df["close"].rolling(60).mean()
        # RSI
        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss
        df["rsi"] = 100 - (100 / (1 + rs))
        # KDJ（J = 3K - 2D）
        low_n = df["low"].rolling(kdj_n).min()
        high_n = df["high"].rolling(kdj_n).max()
        rsv = (df["close"] - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        df["kdj_k"] = rsv.ewm(alpha=1 / kdj_k, adjust=False).mean()
        df["kdj_d"] = df["kdj_k"].ewm(alpha=1 / kdj_d, adjust=False).mean()
        df["kdj_j"] = 3 * df["kdj_k"] - 2 * df["kdj_d"]

        sig = pd.Series(0, index=df.index)
        for i in range(1, len(df)):
            c = df.loc[i, "close"]
            upper = df.loc[i, "boll_upper"]
            lower = df.loc[i, "boll_lower"]
            rsi = df.loc[i, "rsi"]
            j = df.loc[i, "kdj_j"]
            prev_j = df.loc[i - 1, "kdj_j"]
            ma20 = df.loc[i, "ma20"]
            ma60 = df.loc[i, "ma60"]
            if (pd.isna(c) or pd.isna(upper) or pd.isna(lower)
                    or pd.isna(rsi) or pd.isna(j) or pd.isna(prev_j)
                    or pd.isna(ma20) or pd.isna(ma60)):
                continue

            # 买入三条件（三选二）
            buy_c1 = c <= lower                          # 触及/跌破布林下轨
            buy_c2 = rsi < rsi_oversold                  # RSI 超卖
            buy_c3 = j < j_oversold and j > prev_j       # J 超卖且拐头向上
            buy_count = int(buy_c1) + int(buy_c2) + int(buy_c3)

            # 卖出两条件（同时满足才卖出）
            sell_c1 = c >= upper * 0.99                  # 触及布林上轨（>= 上轨*0.99）
            sell_c2 = rsi > 50                           # RSI > 50

            # 卖出优先：两条件同时满足才清仓；买入：MA20>MA60 过滤 + 三选二
            if sell_c1 and sell_c2:
                sig.iloc[i] = -1
            elif ma20 > ma60 and buy_count >= 2:
                sig.iloc[i] = 1
        return sig

    def signals_pullback(self, macd_fast=12, macd_slow=26, macd_signal=9,
                         boll_period=20, boll_std=2.0, kdj_n=9, kdj_k=3, kdj_d=3,
                         rsi_period=14, rsi_low=40, rsi_high=50,
                         stop_loss_ratio=0.98, trail_pct=8):
        """上升回调策略（上升趋势中的回调买入）：

        买入（5 个条件同时满足）：
          1. MACD 的 DIFF 线 > 0
          2. 收盘价在布林带中轨（MB）附近：MB*0.99 <= close <= MB*1.01
          3. KDJ 的 J 值从低位（<30）向上拐头（J > 前一日 J）
          4. RSI 回落至 40~50 区间
          5. 日线近似确认：MACD 绿柱持续缩短（hist<0 且今日>昨日）或 KDJ 刚金叉（K 上穿 D）
        卖出：
          1. 止损：close < 买入当日布林中轨 * stop_loss_ratio（默认 0.98）
          2. 移动止盈：买入后曾站上所有短期均线（MA5/MA10/MA20），
             之后从买入后最高点回撤超过 trail_pct%（默认 8%）或跌破 MA60 → 卖出
        """
        df = self.df
        close = df["close"].astype(float)

        # MACD
        ema_fast = close.ewm(span=macd_fast, adjust=False).mean()
        ema_slow = close.ewm(span=macd_slow, adjust=False).mean()
        dif = ema_fast - ema_slow
        dea = dif.ewm(span=macd_signal, adjust=False).mean()
        hist = 2 * (dif - dea)  # 红柱为正、绿柱为负

        # 布林带（中轨 MB = 均线）
        mb = close.rolling(boll_period).mean()
        std = close.rolling(boll_period).std()

        # KDJ
        low_n = df["low"].rolling(kdj_n).min()
        high_n = df["high"].rolling(kdj_n).max()
        rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
        k = rsv.ewm(alpha=1 / kdj_k, adjust=False).mean()
        d = k.ewm(alpha=1 / kdj_d, adjust=False).mean()
        j = 3 * k - 2 * d

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        # 短期均线 + 生命线
        ma5 = close.rolling(5).mean()
        ma10 = close.rolling(10).mean()
        ma20 = close.rolling(20).mean()
        ma60 = close.rolling(60).mean()

        sig = pd.Series(0, index=df.index)
        position = 0            # 0=空仓, 1=持仓
        buy_mb = None           # 买入当日布林中轨（用于止损）
        buy_high = None         # 买入后最高收盘价（用于移动止盈）
        armed = False           # 是否已站上所有短期均线（启用移动止盈）

        for i in range(1, len(df)):
            c = float(close.iloc[i])
            if (pd.isna(dif.iloc[i]) or pd.isna(hist.iloc[i]) or pd.isna(hist.iloc[i - 1])
                    or pd.isna(mb.iloc[i]) or pd.isna(j.iloc[i]) or pd.isna(j.iloc[i - 1])
                    or pd.isna(k.iloc[i]) or pd.isna(k.iloc[i - 1])
                    or pd.isna(d.iloc[i]) or pd.isna(d.iloc[i - 1])
                    or pd.isna(rsi.iloc[i])
                    or pd.isna(ma5.iloc[i]) or pd.isna(ma10.iloc[i])
                    or pd.isna(ma20.iloc[i]) or pd.isna(ma60.iloc[i])):
                continue

            if position == 1:
                # 更新买入后最高收盘价
                if c > buy_high:
                    buy_high = c
                # 1) 止损：跌破买入当日布林中轨 * 0.98
                if c < buy_mb * stop_loss_ratio:
                    sig.iloc[i] = -1
                    position = 0; buy_mb = None; buy_high = None; armed = False
                    continue
                # 一旦站上所有短期均线，启用移动止盈
                if c > ma5.iloc[i] and c > ma10.iloc[i] and c > ma20.iloc[i]:
                    armed = True
                # 2) 移动止盈（需已站上所有短期均线）
                if armed:
                    pullback = c < buy_high * (1 - trail_pct / 100)   # 从最高点回撤超 trail_pct%
                    below_ma60 = c < ma60.iloc[i]                       # 跌破 MA60 生命线
                    if pullback or below_ma60:
                        sig.iloc[i] = -1
                        position = 0; buy_mb = None; buy_high = None; armed = False
                continue

            # 空仓：5 个买入条件同时满足
            c1 = dif.iloc[i] > 0                                   # DIFF > 0
            c2 = mb.iloc[i] * 0.99 <= c <= mb.iloc[i] * 1.01       # 布林中轨附近
            c3 = j.iloc[i] < 30 and j.iloc[i] > j.iloc[i - 1]      # J 低位向上拐头
            c4 = rsi_low <= rsi.iloc[i] <= rsi_high                # RSI 回落 40~50
            macd_green_shrink = hist.iloc[i] < 0 and hist.iloc[i] > hist.iloc[i - 1]  # 绿柱缩短
            kdj_golden_cross = k.iloc[i - 1] <= d.iloc[i - 1] and k.iloc[i] > d.iloc[i]  # KDJ 金叉
            c5 = macd_green_shrink or kdj_golden_cross             # 日线近似 60 分钟确认

            if c1 and c2 and c3 and c4 and c5:
                sig.iloc[i] = 1
                position = 1
                buy_mb = float(mb.iloc[i])
                buy_high = c
                armed = False

        return sig

    def generate_signals(self, strategy_type: str, params: dict):
        if strategy_type == "ma_cross":
            return self.signals_ma_cross(params.get("fast", 5), params.get("slow", 20))
        elif strategy_type == "macd":
            return self.signals_macd(params.get("fast", 12), params.get("slow", 26),
                                     params.get("signal_period", 9), params.get("ma_filter", 60))
        elif strategy_type == "bollinger":
            return self.signals_bollinger(params.get("period", 20), params.get("std", 2.0))
        elif strategy_type == "rsi":
            return self.signals_rsi(params.get("period", 14),
                                    params.get("oversold", 30), params.get("overbought", 70))
        elif strategy_type == "kdj":
            return self.signals_kdj(params.get("n", 9),
                                    params.get("k_period", 3), params.get("d_period", 3))
        elif strategy_type == "turtle":
            return self.signals_turtle(params.get("entry", 20), params.get("exit_period", 10))
        elif strategy_type == "momentum":
            return self.signals_momentum(params.get("period", 20), params.get("threshold", 0.05))
        elif strategy_type == "grid":
            return self.signals_grid(params.get("grid_pct", 5))
        elif strategy_type == "funnel":
            return self.signals_funnel(
                params.get("ma_fast", 5), params.get("ma_slow", 20),
                params.get("j_oversold", 20), params.get("j_mid", 50), params.get("j_band", 10),
            )
        elif strategy_type == "uptrend":
            return self.signals_uptrend(
                params.get("fast", 5), params.get("trail_pct", 8),
            )
        elif strategy_type == "oscillation":
            return self.signals_oscillation(
                params.get("boll_period", 10), params.get("boll_std", 2.0),
                params.get("rsi_period", 14), params.get("rsi_oversold", 30),
                params.get("rsi_overbought", 70), params.get("kdj_n", 9),
                params.get("kdj_k", 3), params.get("kdj_d", 3),
                params.get("j_oversold", 0), params.get("j_overbought", 100),
            )
        elif strategy_type == "pullback":
            return self.signals_pullback(
                params.get("macd_fast", 12), params.get("macd_slow", 26),
                params.get("macd_signal", 9), params.get("boll_period", 20),
                params.get("boll_std", 2.0), params.get("kdj_n", 9),
                params.get("kdj_k", 3), params.get("kdj_d", 3),
                params.get("rsi_period", 14), params.get("rsi_low", 40),
                params.get("rsi_high", 50), params.get("stop_loss_ratio", 0.98),
                params.get("trail_pct", 8),
            )
        raise ValueError(f"未知策略: {strategy_type}")

    @staticmethod
    def combine_signals(signals: list, mode: str = "filter") -> pd.Series:
        """组合多个策略信号（多层过滤 / 共振 / 投票）

        基于「状态」过滤：每个策略在买入信号后进入「看多」状态并保持，
        直到出现卖出信号转为「看空」。

        filter: 多层过滤 — 所有层都处于看多状态才买(1)，任一层转看空即卖(-1)
        and:    严格共振 — 所有层在同一天同时看多才买，同时看空才卖
        vote:   投票制 — 多数层处于看多状态才买，多数看空才卖
        """
        if not signals:
            return pd.Series(dtype=int)
        combined = pd.Series(0, index=signals[0].index)
        n = len(signals)
        states = [0] * n  # 每层当前状态：1=看多, -1=看空, 0=中性
        for i in range(len(combined)):
            for j in range(n):
                v = int(signals[j].iloc[i])
                if v == 1:
                    states[j] = 1
                elif v == -1:
                    states[j] = -1
            buys = sum(1 for s in states if s == 1)
            sells = sum(1 for s in states if s == -1)
            if mode == "filter":
                if buys == n:
                    combined.iloc[i] = 1
                elif sells > 0:
                    combined.iloc[i] = -1
            elif mode == "and":
                vals = [int(s.iloc[i]) for s in signals]
                if all(v == 1 for v in vals):
                    combined.iloc[i] = 1
                elif all(v == -1 for v in vals):
                    combined.iloc[i] = -1
            elif mode == "vote":
                if buys > n // 2:
                    combined.iloc[i] = 1
                elif sells > n // 2:
                    combined.iloc[i] = -1
        return combined

    def run(self, signal: pd.Series) -> dict:
        cash = self.initial_capital; shares = 0
        trades: list[dict] = []; daily_values: list[dict] = []
        comm = 0.00025; tax = 0.001; min_fee = 5.0
        current_target = 0.0  # 当前目标仓位比例（支持部分仓位策略）

        # 信号基于当日收盘价产生，交易在次日开盘价执行（避免未来函数）
        for i in range(len(self.df)):
            price = self.df.loc[i, "close"]; dt = str(self.df.loc[i, "date"].date())
            sig = signal.iloc[i] if i < len(signal) else 0

            # 次日开盘价成交
            if i + 1 < len(self.df):
                exec_price = self.df.loc[i + 1, "open"]
                exec_date = str(self.df.loc[i + 1, "date"].date())
            else:
                exec_price = price
                exec_date = dt

            # 解析目标仓位：<0 清仓，>0 目标仓位(0~1)，0 不调仓（维持当前持股）
            target = None
            if sig < 0:
                target = 0.0
            elif sig > 0:
                target = min(float(sig), 1.0)

            # 仅在出现明确信号时按目标市值差额调仓
            diff = 0.0 if target is None else (cash + shares * exec_price) * target - shares * exec_price

            if target is not None and diff > 0 and cash > 0:
                budget = min(diff, cash * 0.95)
                qty = int(budget / exec_price / 100) * 100
                if qty >= 100:
                    amt = exec_price * qty; fee = max(amt * comm, min_fee)
                    if cash >= amt + fee:
                        cash -= amt + fee; shares += qty
                        trades.append({"date": exec_date, "direction": "buy", "price": round(exec_price, 3),
                                        "quantity": qty, "amount": round(amt, 2), "fee": round(fee, 2)})
            elif target is not None and diff < 0 and shares > 0:
                qty = shares if target <= 0.0 else int((-diff) / exec_price / 100) * 100
                qty = min(qty, shares)
                if qty > 0:
                    amt = exec_price * qty; fee = max(amt * comm, min_fee) + amt * tax
                    cash += amt - fee; shares -= qty
                    trades.append({"date": exec_date, "direction": "sell", "price": round(exec_price, 3),
                                    "quantity": qty, "amount": round(amt, 2), "fee": round(fee, 2)})

            if target is not None:
                current_target = target
            daily_values.append({"date": dt, "total_asset": round(cash + shares * price, 2)})

        last_close = self.df.iloc[-1]["close"]
        last_day = str(self.df.iloc[-1]["date"].date())

        if shares > 0:
            # 找出最后一笔买入日期，严格执行 T+1（当日买入不可当日卖出）
            last_buy_date = None
            for t in reversed(trades):
                if t["direction"] == "buy":
                    last_buy_date = t["date"]
                    break

            if last_buy_date == last_day:
                # 最后一天刚买入，T+1 规则下保留持仓，按市值计入最终资产
                final = cash + shares * last_close
                daily_values[-1]["total_asset"] = round(final, 2)
            else:
                amt = last_close * shares
                fee = max(amt * comm, min_fee) + amt * tax
                cash += amt - fee
                trades.append({"date": last_day, "direction": "sell",
                                "price": round(last_close, 3), "quantity": shares,
                                "amount": round(amt, 2), "fee": round(fee, 2)})
                final = cash
                daily_values[-1]["total_asset"] = round(cash, 2)
        else:
            final = cash

        total_ret = (final - self.initial_capital) / self.initial_capital
        peaks = pd.Series([d["total_asset"] for d in daily_values])
        dd = (peaks.cummax() - peaks) / peaks.cummax()
        max_dd = dd.max() if len(dd) > 0 else 0
        days = len(daily_values)
        ann_ret = (1 + total_ret) ** (252 / max(days, 1)) - 1

        # 日收益率 → 年化波动率 / 夏普比率（无风险利率 2%）
        assets = pd.Series([d["total_asset"] for d in daily_values], dtype=float)
        daily_returns = assets.pct_change().dropna()
        vol = float(daily_returns.std() * np.sqrt(252)) if len(daily_returns) > 1 else 0.0
        rf = 0.02
        sharpe = (ann_ret - rf) / vol if vol > 0 else 0.0

        # 按买卖配对计算每笔盈亏（满仓进出，买/卖交替出现）
        buy_prices = [t["price"] for t in trades if t["direction"] == "buy"]
        sell_prices = [t["price"] for t in trades if t["direction"] == "sell"]
        round_pnls = [sp - buy_prices[i] for i, sp in enumerate(sell_prices) if i < len(buy_prices)]
        wins = sum(1 for p in round_pnls if p > 0)
        wr = wins / len(round_pnls) * 100 if round_pnls else 0
        win_pnls = [p for p in round_pnls if p > 0]
        loss_pnls = [p for p in round_pnls if p < 0]
        win_avg = float(np.mean(win_pnls)) if win_pnls else 0.0
        loss_avg = abs(float(np.mean(loss_pnls))) if loss_pnls else 0.0
        pl_ratio = win_avg / loss_avg if loss_avg > 0 else 0.0
        gross_win = sum(win_pnls); gross_loss = abs(sum(loss_pnls))
        profit_factor = gross_win / gross_loss if gross_loss > 0 else None

        return {
            "initial_capital": self.initial_capital, "final_asset": round(final, 2),
            "total_return": round(total_ret * 100, 2), "annual_return": round(ann_ret * 100, 2),
            "max_drawdown": round(max_dd * 100, 2), "win_rate": round(wr, 1),
            "sharpe": round(sharpe, 2), "volatility": round(vol * 100, 2),
            "profit_loss_ratio": round(pl_ratio, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
            "trade_count": len(trades), "trades": trades, "daily_values": daily_values,
        }


def analyze_market_regime(kline_data: list[dict]) -> dict:
    """分析个股当前所处行情阶段（技术面，非AI）

    四种行情：
      1. 单边上升趋势：股价在20日均线上方，且MACD柱线持续变长
      2. 震荡盘整：股价在布林带上下轨之间来回摆动，且布林带收口
      3. 单边下跌趋势：股价在20日均线下方，且MACD柱线为绿色且持续变长
      4. 上升中的回调：股价在20日均线上方，但MACD红柱缩短，KDJ死叉向下
    """
    if not kline_data:
        return {"regime": "数据不足", "regime_key": "insufficient",
                "explanation": "无K线数据，无法判断行情。", "indicators": {}, "signals": []}

    df = pd.DataFrame(kline_data)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

    close = pd.to_numeric(df.get("close"), errors="coerce")
    high = pd.to_numeric(df.get("high"), errors="coerce")
    low = pd.to_numeric(df.get("low"), errors="coerce")
    valid = close.notna() & high.notna() & low.notna()
    close = close[valid].reset_index(drop=True)
    high = high[valid].reset_index(drop=True)
    low = low[valid].reset_index(drop=True)

    if len(close) < 30:
        return {"regime": "数据不足", "regime_key": "insufficient",
                "explanation": f"有效K线仅 {len(close)} 根（需至少30根），无法可靠判断行情。",
                "indicators": {}, "signals": []}

    # 20日均线
    ma20 = close.rolling(20).mean()
    # MACD (12, 26, 9)，柱线 = 2*(DIF - DEA)
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    dif = ema12 - ema26
    dea = dif.ewm(span=9, adjust=False).mean()
    macd_hist = 2 * (dif - dea)
    # 布林带 (20, 2)
    mid = close.rolling(20).mean()
    std = close.rolling(20).std()
    upper = mid + 2 * std
    lower = mid - 2 * std
    # KDJ (9, 3, 3)
    low9 = low.rolling(9).min()
    high9 = high.rolling(9).max()
    rng = (high9 - low9).replace(0, np.nan)
    rsv = ((close - low9) / rng * 100).fillna(50)
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()
    j = 3 * k - 2 * d

    i = len(close) - 1
    c = float(close.iloc[i])
    m20 = float(ma20.iloc[i])
    hist = float(macd_hist.iloc[i])
    hist1 = float(macd_hist.iloc[i - 1])
    hist3 = float(macd_hist.iloc[i - 3]) if i >= 3 else hist1
    k_now = float(k.iloc[i]); d_now = float(d.iloc[i])
    k_prev = float(k.iloc[i - 1]); d_prev = float(d.iloc[i - 1])
    up = float(upper.iloc[i]); lo = float(lower.iloc[i])
    band_now = up - lo
    band_prev = float(upper.iloc[i - 5]) - float(lower.iloc[i - 5]) if i >= 5 else band_now

    above_ma20 = c > m20
    below_ma20 = c < m20
    red_growing = hist > 0 and hist > hist1 > hist3        # 红柱持续变长
    red_shrinking = hist > 0 and hist < hist1              # 红柱缩短
    green_growing = hist < 0 and hist < hist1 < hist3      # 绿柱持续变长（负值递减）
    kdj_dead = k_prev > d_prev and k_now < d_now           # KDJ 死叉（K 下穿 D）
    inside_boll = lo <= c <= up                            # 股价在布林带内
    squeeze = band_now < band_prev * 0.97                  # 布林带收口（带宽收窄超3%）

    indicators = {
        "close": round(c, 2), "ma20": round(m20, 2),
        "macd_dif": round(float(dif.iloc[i]), 3), "macd_dea": round(float(dea.iloc[i]), 3),
        "macd_hist": round(hist, 3),
        "kdj_k": round(k_now, 1), "kdj_d": round(d_now, 1), "kdj_j": round(float(j.iloc[i]), 1),
        "boll_upper": round(up, 2), "boll_mid": round(float(mid.iloc[i]), 2), "boll_lower": round(lo, 2),
    }

    if above_ma20 and red_growing:
        regime, key = "单边上升趋势", "uptrend"
        signals = ["股价在20日均线上方", "MACD红柱持续变长"]
        explanation = (f"股价 {c:.2f} 运行在20日均线 {m20:.2f} 上方，MACD红柱逐日放大"
                       f"（最新 {hist:.3f}），多头动能持续增强，处于单边上升趋势。"
                       f"操作上以持有/逢回调低吸为主，跌破20日均线需警惕趋势转弱。")
    elif above_ma20 and red_shrinking and kdj_dead:
        regime, key = "上升中的回调", "pullback"
        signals = ["股价在20日均线上方", "MACD红柱缩短", "KDJ死叉向下"]
        explanation = (f"股价 {c:.2f} 仍在20日均线 {m20:.2f} 上方，但MACD红柱由 {hist1:.3f} 缩短至 {hist:.3f}，"
                       f"KDJ死叉（K {k_now:.1f} 下穿 D {d_now:.1f}），短线动能减弱，属于上升途中的回调。"
                       f"关注20日均线支撑，企稳后可重新走强。")
    elif below_ma20 and green_growing:
        regime, key = "单边下跌趋势", "downtrend"
        signals = ["股价在20日均线下方", "MACD绿柱持续变长"]
        explanation = (f"股价 {c:.2f} 运行在20日均线 {m20:.2f} 下方，MACD绿柱逐日放大"
                       f"（最新 {hist:.3f}），空头动能持续增强，处于单边下跌趋势。"
                       f"操作上以规避为主，勿盲目抄底，待企稳信号出现。")
    elif inside_boll and squeeze:
        regime, key = "震荡盘整", "range"
        signals = ["股价在布林带上下轨之间", "布林带收口"]
        explanation = (f"股价 {c:.2f} 在布林带上下轨（{lo:.2f} ~ {up:.2f}）之间运行，"
                       f"且布林带带宽由 {band_prev:.2f} 收窄至 {band_now:.2f}，处于震荡盘整阶段。"
                       f"波动收敛后通常面临方向选择，建议等待突破信号。")
    elif above_ma20:
        regime, key = "单边上升趋势", "uptrend"
        signals = ["股价在20日均线上方"]
        explanation = (f"股价 {c:.2f} 位于20日均线 {m20:.2f} 上方，整体偏多，"
                       f"但MACD动能信号尚不充分，暂按震荡偏强看待。")
    elif below_ma20:
        regime, key = "单边下跌趋势", "downtrend"
        signals = ["股价在20日均线下方"]
        explanation = (f"股价 {c:.2f} 位于20日均线 {m20:.2f} 下方，整体偏空，"
                       f"但MACD动能信号尚不充分，暂按震荡偏弱看待。")
    else:
        regime, key = "震荡盘整", "range"
        signals = ["股价贴近20日均线"]
        explanation = (f"股价 {c:.2f} 贴近20日均线 {m20:.2f}，多空力量均衡，处于震荡盘整阶段。")

    return {"regime": regime, "regime_key": key, "explanation": explanation,
            "indicators": indicators, "signals": signals}


def _pullback_min60_confirm(min60_kline: list[dict]):
    """60 分钟 K 线确认：MACD 绿柱持续缩短 或 KDJ 刚金叉

    返回 (是否确认, 明细dict)。
    """
    if not min60_kline or len(min60_kline) < 2:
        return False, {"error": "60分钟数据不足"}
    mdf = pd.DataFrame(min60_kline).sort_values("date").reset_index(drop=True)
    close = mdf["close"].astype(float)
    # 60分钟 MACD（12/26/9）
    dif = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    dea = dif.ewm(span=9, adjust=False).mean()
    hist = 2 * (dif - dea)
    # 60分钟 KDJ（9/3/3）
    low_n = mdf["low"].rolling(9).min()
    high_n = mdf["high"].rolling(9).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / 3, adjust=False).mean()
    d = k.ewm(alpha=1 / 3, adjust=False).mean()

    i = len(close) - 1
    if (pd.isna(hist.iloc[i]) or pd.isna(hist.iloc[i - 1])
            or pd.isna(k.iloc[i]) or pd.isna(d.iloc[i])
            or pd.isna(k.iloc[i - 1]) or pd.isna(d.iloc[i - 1])):
        return False, {"error": "60分钟指标数据不足"}
    macd_green_shrink = bool(hist.iloc[i] < 0 and hist.iloc[i] > hist.iloc[i - 1])
    kdj_golden_cross = bool(k.iloc[i - 1] <= d.iloc[i - 1] and k.iloc[i] > d.iloc[i])
    detail = {
        "macd_hist": round(float(hist.iloc[i]), 3),
        "macd_hist_prev": round(float(hist.iloc[i - 1]), 3),
        "macd_green_shrink": macd_green_shrink,
        "kdj_k": round(float(k.iloc[i]), 2),
        "kdj_d": round(float(d.iloc[i]), 2),
        "kdj_golden_cross": kdj_golden_cross,
    }
    return (macd_green_shrink or kdj_golden_cross), detail


def check_pullback_signal(daily_kline: list[dict], min60_kline: list[dict], params=None) -> dict:
    """上升回调策略实时信号检查（日线 + 真实 60 分钟数据）

    买入需同时满足 5 条件：前 4 个用日线、第 5 个用真实 60 分钟。
    返回 {buy_signal, conditions, indicators}。
    """
    p = params or {}
    macd_fast = p.get("macd_fast", 12); macd_slow = p.get("macd_slow", 26)
    macd_signal = p.get("macd_signal", 9); boll_period = p.get("boll_period", 20)
    kdj_n = p.get("kdj_n", 9); kdj_k = p.get("kdj_k", 3); kdj_d = p.get("kdj_d", 3)
    rsi_period = p.get("rsi_period", 14); rsi_low = p.get("rsi_low", 40)
    rsi_high = p.get("rsi_high", 50)

    result = {"buy_signal": False, "conditions": {}, "indicators": {}}
    if not daily_kline:
        result["error"] = "日线数据为空"
        return result

    ddf = pd.DataFrame(daily_kline).sort_values("date").reset_index(drop=True)
    close = ddf["close"].astype(float)

    # 日线 MACD
    dif = close.ewm(span=macd_fast, adjust=False).mean() - close.ewm(span=macd_slow, adjust=False).mean()
    # 布林中轨
    mb = close.rolling(boll_period).mean()
    # 日线 KDJ
    low_n = ddf["low"].rolling(kdj_n).min()
    high_n = ddf["high"].rolling(kdj_n).max()
    rsv = (close - low_n) / (high_n - low_n).replace(0, np.nan) * 100
    k = rsv.ewm(alpha=1 / kdj_k, adjust=False).mean()
    d = k.ewm(alpha=1 / kdj_d, adjust=False).mean()
    j = 3 * k - 2 * d
    # 日线 RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(rsi_period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    i = len(close) - 1
    if (pd.isna(dif.iloc[i]) or pd.isna(mb.iloc[i]) or pd.isna(j.iloc[i])
            or pd.isna(j.iloc[i - 1]) or pd.isna(rsi.iloc[i])):
        result["error"] = "日线指标数据不足"
        return result

    c = float(close.iloc[i])
    c1 = bool(dif.iloc[i] > 0)
    c2 = bool(mb.iloc[i] * 0.99 <= c <= mb.iloc[i] * 1.01)
    c3 = bool(j.iloc[i] < 30 and j.iloc[i] > j.iloc[i - 1])
    c4 = bool(rsi_low <= rsi.iloc[i] <= rsi_high)

    # 60 分钟确认
    c5, min60_detail = _pullback_min60_confirm(min60_kline)

    result["conditions"] = {
        "dif_above_zero": c1,
        "near_mb": c2,
        "kdj_turn_up": c3,
        "rsi_in_range": c4,
        "min60_confirm": c5,
    }
    result["indicators"] = {
        "close": round(c, 2),
        "dif": round(float(dif.iloc[i]), 3),
        "mb": round(float(mb.iloc[i]), 2),
        "j": round(float(j.iloc[i]), 2),
        "rsi": round(float(rsi.iloc[i]), 2),
        "min60": min60_detail,
    }
    result["buy_signal"] = c1 and c2 and c3 and c4 and c5
    return result

