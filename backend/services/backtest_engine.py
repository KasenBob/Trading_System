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

            if sig == 1 and cash > 0:
                qty = int(cash * 0.95 / exec_price / 100) * 100
                if qty >= 100:
                    amt = exec_price * qty; fee = max(amt * comm, min_fee)
                    if cash >= amt + fee:
                        cash -= amt + fee; shares += qty
                        trades.append({"date": exec_date, "direction": "buy", "price": round(exec_price, 3),
                                        "quantity": qty, "amount": round(amt, 2), "fee": round(fee, 2)})
            elif sig == -1 and shares > 0:
                amt = exec_price * shares; fee = max(amt * comm, min_fee) + amt * tax
                cash += amt - fee
                trades.append({"date": exec_date, "direction": "sell", "price": round(exec_price, 3),
                                "quantity": shares, "amount": round(amt, 2), "fee": round(fee, 2)})
                shares = 0

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

