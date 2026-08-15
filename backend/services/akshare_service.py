"""数据服务封装 — 多数据源 fallback

实时行情: 新浪 > 腾讯 > 东方财富
K线数据:   akshare > 新浪
ETF行情:   akshare
"""

from datetime import datetime, timedelta
from typing import Optional

import akshare as ak
import pandas as pd
import requests

HEADERS = {"Referer": "https://finance.sina.com.cn"}


class DataService:
    """多数据源行情服务"""

    # ── 市场前缀 ────────────────────────────

    @staticmethod
    def _market_prefix(code: str) -> str:
        """返回 sh/sz 前缀"""
        if code.startswith(("6", "51", "58")):
            return "sh"
        return "sz"

    @staticmethod
    def _market_id(code: str) -> str:
        """返回东方财富市场ID: 1=沪, 0=深"""
        return "1" if code.startswith(("6", "51", "58")) else "0"

    # 缓存
    _stock_cache: list[dict] = []
    _etf_cache: list[dict] = []
    _cache_loaded = False

    @classmethod
    def _ensure_cache(cls):
        """启动时预加载股票和ETF列表到内存缓存"""
        if cls._cache_loaded:
            return
        # ETF 列表
        try:
            df = ak.fund_etf_spot_em()
            cls._etf_cache = [
                {"code": str(r["代码"]), "name": str(r["名称"]), "type": "etf"}
                for _, r in df.iterrows()
            ]
        except Exception:
            pass
        # A股列表
        try:
            df = ak.stock_info_a_code_name()
            cls._stock_cache = [
                {"code": str(r["code"]), "name": str(r["name"]), "type": "stock"}
                for _, r in df.iterrows()
            ]
        except Exception:
            pass
        cls._cache_loaded = True

    @staticmethod
    def search_stocks(keyword: str) -> list[dict]:
        """模糊搜索 股票+ETF（从缓存秒搜）"""
        DataService._ensure_cache()
        kw = keyword.lower().strip()
        results: list[dict] = []
        for items in [DataService._etf_cache, DataService._stock_cache]:
            for item in items:
                if kw in item["code"].lower() or kw in item["name"].lower():
                    if not any(r["code"] == item["code"] for r in results):
                        results.append(item)
                        if len(results) >= 20:
                            return results
        return results

    # ═══════════ 实时行情 ═══════════

    @staticmethod
    def _quote_from_sina(codes: list[str]) -> list[dict]:
        """新浪财经实时行情"""
        symbols = ",".join(codes)
        url = f"https://hq.sinajs.cn/list={symbols}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        resp.encoding = "gbk"
        results = []
        for line in resp.text.strip().split("\n"):
            if "=" not in line:
                continue
            raw = line.split('"')[1] if '"' in line else ""
            if not raw:
                continue
            f = raw.split(",")
            if len(f) < 10:
                continue
            results.append({
                "code": codes[len(results)] if len(results) < len(codes) else "",
                "name": f[0],
                "open": float(f[1]) if f[1] else None,
                "pre_close": float(f[2]) if f[2] else None,
                "price": float(f[3]) if f[3] else None,
                "high": float(f[4]) if f[4] else None,
                "low": float(f[5]) if f[5] else None,
                "volume": float(f[8]) if f[8] else None,
                "amount": float(f[9]) if f[9] else None,
            })
        # 补字段
        for r in results:
            if r["price"] and r["pre_close"] and r["pre_close"] != 0:
                r["change_pct"] = round((r["price"] - r["pre_close"]) / r["pre_close"] * 100, 2)
                r["change_amount"] = round(r["price"] - r["pre_close"], 3)
        return results

    @staticmethod
    def _quote_from_tencent(codes: list[str]) -> list[dict]:
        """腾讯财经实时行情"""
        symbols = ",".join(codes)
        url = f"https://qt.gtimg.cn/q={symbols}"
        resp = requests.get(url, timeout=10)
        resp.encoding = "gbk"
        results = []
        for line in resp.text.strip().split("\n"):
            if "~" not in line:
                continue
            raw = line.split('"')[1] if '"' in line else ""
            if not raw:
                continue
            f = raw.split("~")
            if len(f) < 10:
                continue
            results.append({
                "code": f[2],
                "name": f[1],
                "price": float(f[3]) if f[3] else None,
                "pre_close": float(f[4]) if f[4] else None,
                "open": float(f[5]) if f[5] else None,
                "volume": float(f[6]) if f[6] else None,
                "change_pct": float(f[32]) if len(f) > 32 and f[32] else None,
                "high": float(f[33]) if len(f) > 33 and f[33] else None,
                "low": float(f[34]) if len(f) > 34 and f[34] else None,
                "amount": float(f[37]) if len(f) > 37 and f[37] else None,
                "turnover_rate": float(f[38]) if len(f) > 38 and f[38] else None,
                "pe_dynamic": float(f[39]) if len(f) > 39 and f[39] else None,
            })
        return results

    @classmethod
    def get_realtime_quotes(cls, codes: Optional[list[str]] = None) -> list[dict]:
        """获取 A股实时行情（新浪 > 腾讯 fallback）"""
        if not codes:
            return []
        prefixed = []
        for c in codes:
            prefixed.append(f"{cls._market_prefix(c)}{c}")
        for fetcher in [cls._quote_from_sina, cls._quote_from_tencent]:
            try:
                data = fetcher(prefixed)
                if data:
                    # 去掉 sh/sz 前缀
                    for d in data:
                        raw = d.get("code", "")
                        if raw.startswith("sh") or raw.startswith("sz"):
                            d["code"] = raw[2:]
                    return data
            except Exception:
                continue
        raise RuntimeError("所有数据源均无法获取实时行情")

    # ═══════════ K线数据 ═══════════

    # 新浪 scale 值映射
    _SINA_SCALE = {"daily": 240, "weekly": 1200, "monthly": 4800, "60": 60}

    @staticmethod
    def _kline_from_sina(code: str, period: str = "daily", days: int = 365) -> list[dict]:
        """新浪 K线"""
        prefix = DataService._market_prefix(code)
        scale = DataService._SINA_SCALE.get(period, 240)
        url = (
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={prefix}{code}"
            f"&scale={scale}&ma=no&datalen={days}"
        )
        resp = requests.get(url, headers=HEADERS, timeout=8)
        data = resp.json()
        return [
            {
                "date": item["day"],
                "open": float(item["open"]),
                "close": float(item["close"]),
                "high": float(item["high"]),
                "low": float(item["low"]),
                "volume": float(item["volume"]),
            }
            for item in data
        ]

    @staticmethod
    def _kline_from_tencent(code: str, period: str = "daily", count: int = 320) -> list[dict]:
        """腾讯 K线（前复权）"""
        prefix = DataService._market_prefix(code)
        # 腾讯用 day/week/month, 映射 daily→day, weekly→week, monthly→month
        tx_period = {"daily": "day", "weekly": "week", "monthly": "month"}.get(period, period)
        url = (
            "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            f"?param={prefix}{code},{tx_period},,,{count},qfq"
        )
        resp = requests.get(url, timeout=8)
        data = resp.json()
        stock_key = f"{prefix}{code}"
        stock_info = data.get("data", {}).get(stock_key, {})
        if not stock_info:
            return []
        stock_data = stock_info.get(tx_period) or stock_info.get(f"qfq{tx_period}", [])
        if not stock_data:
            return []
        return [
            {
                "date": item[0],
                "open": float(item[1]),
                "close": float(item[2]),
                "high": float(item[3]),
                "low": float(item[4]),
                "volume": float(item[5]) if len(item) > 5 else 0,
            }
            for item in stock_data
        ]

    @classmethod
    def get_kline(
        cls,
        code: str,
        period: str = "daily",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        adjust: str = "qfq",
    ) -> list[dict]:
        """获取 K线（akshare > 腾讯 > 新浪 fallback），并按日期范围过滤"""
        result: list[dict] = []
        # 优先 akshare
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period=period,
                start_date=start_date or "20000101",
                end_date=end_date or datetime.now().strftime("%Y%m%d"),
                adjust=adjust,
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "日期": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                    "成交额": "amount", "振幅": "amplitude",
                    "涨跌幅": "change_pct", "涨跌额": "change_amount",
                    "换手率": "turnover_rate",
                })
                df["date"] = df["date"].astype(str)
                df = df.where(df.notna(), None)
                result = df.to_dict(orient="records")
        except Exception:
            pass
        # fallback: 腾讯
        if not result:
            try:
                result = cls._kline_from_tencent(code, period)
            except Exception:
                pass
        # fallback: 新浪
        if not result:
            try:
                result = cls._kline_from_sina(code, period)
            except Exception:
                pass

        # 统一按日期范围过滤（腾讯/新浪 fallback 不认日期参数）
        if result and (start_date or end_date):
            s = (start_date or "19000101").replace("-", "")
            e = (end_date or "99991231").replace("-", "")
            result = [d for d in result if s <= (d.get("date") or "").replace("-", "") <= e]

        if not result:
            raise RuntimeError(f"无法获取K线数据 [{code}]")
        return result

    @classmethod
    def get_kline_60min(cls, code: str, adjust: str = "qfq", days: int = 90) -> list[dict]:
        """获取 60 分钟 K 线（东财 min_em 优先，新浪 scale=60 兜底）

        返回字段与日线一致：date/open/close/high/low/volume，
        其中 date 为 "YYYY-MM-DD HH:MM:SS" 的 60 分钟柱结束时间。
        """
        result: list[dict] = []
        # 1) 东财（akshare）：股票 / ETF 分时
        try:
            end = datetime.now()
            start = end - timedelta(days=days)
            is_etf = code.startswith(("51", "15", "58"))
            fetcher = ak.fund_etf_hist_min_em if is_etf else ak.stock_zh_a_hist_min_em
            df = fetcher(
                symbol=code,
                start_date=start.strftime("%Y-%m-%d 09:30:00"),
                end_date=end.strftime("%Y-%m-%d 15:00:00"),
                period="60",
                adjust=adjust,
            )
            if df is not None and not df.empty:
                df = df.rename(columns={
                    "时间": "date", "开盘": "open", "收盘": "close",
                    "最高": "high", "最低": "low", "成交量": "volume",
                })
                df["date"] = df["date"].astype(str)
                df = df.where(df.notna(), None)
                result = df.to_dict(orient="records")
        except Exception:
            result = []
        # 2) 新浪兜底（scale=60，约 200 根 60 分钟柱）
        if not result:
            try:
                result = cls._kline_from_sina(code, "60", days=200)
            except Exception:
                result = []
        if not result:
            raise RuntimeError(f"无法获取60分钟K线数据 [{code}]")
        # 按时间升序
        result.sort(key=lambda d: d.get("date") or "")
        return result

    # ═══════════ 详情 & ETF ═══════════

    @classmethod
    def get_stock_detail(cls, code: str) -> dict:
        """个股详情"""
        quote = {}
        try:
            quotes = cls.get_realtime_quotes(codes=[code])
            quote = quotes[0] if quotes else {}
        except Exception:
            pass
        info = {}
        try:
            info_df = ak.stock_individual_info_em(symbol=code)
            if info_df is not None and not info_df.empty:
                for _, row in info_df.iterrows():
                    info[row["item"]] = row["value"]
        except Exception:
            pass
        return {"code": code, "quote": quote, "info": info}

    @staticmethod
    def get_etf_realtime_quotes(codes: Optional[list[str]] = None) -> list[dict]:
        """ETF 实时行情"""
        try:
            df = ak.fund_etf_spot_em()
            df = df.rename(columns={
                "代码": "code", "名称": "name", "最新价": "price",
                "涨跌幅": "change_pct", "涨跌额": "change_amount",
                "成交量": "volume", "成交额": "amount",
                "开盘价": "open", "最高价": "high",
                "最低价": "low", "昨收": "pre_close",
                "换手率": "turnover_rate",
            })
            if codes:
                df = df[df["code"].isin(codes)]
            df = df.where(df.notna(), None)
            return df.to_dict(orient="records")
        except Exception as e:
            raise RuntimeError(f"获取ETF行情失败: {e}")

    # ═══════════ 分时数据 ═══════════

    @staticmethod
    def get_minute_data(code: str) -> list[dict]:
        """获取当日分时数据（腾讯接口）"""
        prefix = DataService._market_prefix(code)
        url = f"https://ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data&code={prefix}{code}"
        resp = requests.get(url, timeout=10)
        # 格式: min_data={json}
        json_str = resp.text.split("=", 1)[1].strip() if "=" in resp.text else resp.text
        data = __import__("json").loads(json_str)
        raw = data.get("data", {}).get(f"{prefix}{code}", {}).get("data", {}).get("data", [])
        if not raw:
            return []
        result = []
        cum_vol = 0
        for item in raw:
            parts = item.split(" ")
            if len(parts) < 3:
                continue
            time_str = parts[0]
            price = float(parts[1])
            vol = int(parts[2])
            cum_vol += vol
            result.append({
                "time": f"{time_str[:2]}:{time_str[2:]}",
                "price": price,
                "volume": vol,
                "cum_volume": cum_vol,
                "avg_price": float(parts[3]) if len(parts) > 3 else 0,
            })
        return result

    # ═══════════ 资金流向 ═══════════

    @staticmethod
    def get_fund_flow(code: str, days: int = 60) -> list[dict]:
        """获取资金流向（东方财富，含散户/主力净流入）
        注：东方财富可能限流，失败时返回空列表不影响主流程。
        """
        try:
            market = DataService._market_id(code)
            secid = f"{market}.{code}"
            url = "https://push2.eastmoney.com/api/qt/stock/fflow/daykline/get"
            params = {
                "lmt": str(days), "klt": "1", "secid": secid,
                "fields1": "f1,f2,f3",
                "fields2": "f51,f52,f53,f54,f55,f56,f57",
            }
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            klines = data.get("data", {}).get("klines", []) or []
            result = []
            for line in klines:
                parts = line.split(",")
                if len(parts) < 7:
                    continue
                result.append({
                    "date": parts[0],
                    "main_net_inflow": float(parts[1]),
                    "retail_net_inflow": float(parts[2]),
                    "mid_net_inflow": float(parts[3]),
                    "large_net_inflow": float(parts[4]),
                    "super_large_net_inflow": float(parts[5]),
                    "main_pct": float(parts[6]),
                })
            return result
        except Exception:
            return []  # 东方财富限流时优雅降级

    # ═══════════ 估值数据（多因子用） ═══════════

    @staticmethod
    def get_market_valuation(codes: Optional[list[str]] = None) -> list[dict]:
        """获取指定股票的估值数据（PE、PB、市值）

        用腾讯接口（比东财稳定）：f[39]=市盈率, f[46]=市净率, f[45]=总市值(亿)
        返回：code, name, pe, pb, total_market_cap(元), price
        """
        if not codes:
            return []
        symbols = ",".join(
            f"{DataService._market_prefix(c)}{c}" for c in codes
        )
        url = f"https://qt.gtimg.cn/q={symbols}"
        try:
            resp = requests.get(url, timeout=10)
            resp.encoding = "gbk"
        except Exception:
            return []

        records: list[dict] = []
        for line in resp.text.strip().split("\n"):
            if "~" not in line:
                continue
            raw = line.split('"')[1] if '"' in line else ""
            f = raw.split("~")
            if len(f) < 47:
                continue
            pe = None
            pb = None
            mkt_cap = None
            try:
                if f[39]:
                    pe = float(f[39])
            except Exception:
                pass
            try:
                if f[46]:
                    pb = float(f[46])
            except Exception:
                pass
            try:
                if f[45]:
                    mkt_cap = float(f[45]) * 1e8  # 亿 → 元
            except Exception:
                pass
            records.append({
                "code": f[2],
                "name": f[1],
                "price": float(f[3]) if f[3] else None,
                "pe": pe,
                "pb": pb,
                "total_market_cap": mkt_cap,
            })
        return records

    # ═══════════ 行业板块（多因子用） ═══════════

    _industry_cache: dict[str, str] = {}

    @classmethod
    def get_stock_industry(cls, codes: list[str]) -> dict[str, str]:
        """获取股票所属行业（东方财富 f100 字段），带内存缓存

        返回 {code: 行业名称}。东财限流时返回空 dict。
        """
        if not codes:
            return {}
        # 命中缓存
        missing = [c for c in codes if c not in cls._industry_cache]
        if missing:
            try:
                url = "https://push2.eastmoney.com/api/qt/clist/get"
                page = 1
                while True:
                    params = {
                        "pn": str(page), "pz": "500", "po": "1", "np": "1",
                        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
                        "fltt": "2", "invt": "2", "fid": "f12",
                        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
                        "fields": "f12,f100",
                    }
                    resp = requests.get(url, params=params, timeout=20)
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("data") is None:
                        break
                    for item in data["data"].get("diff") or []:
                        code = item.get("f12")
                        ind = item.get("f100")
                        if code and ind:
                            cls._industry_cache[code] = ind
                    total = data["data"].get("total", 0)
                    if page * 500 >= total:
                        break
                    page += 1
            except Exception:
                pass  # 东财限流时静默
        return {c: cls._industry_cache.get(c, "") for c in codes}

    # ═══════════ 全市场数据（多因子全市场选股用） ═══════════

    @classmethod
    def get_full_market_data(cls, progress_callback=None) -> list[dict]:
        """获取全市场股票 + ETF 数据（新浪接口，分页）

        Args:
            progress_callback: 回调函数，接收 0~80 的进度值

        Returns:
            [{code, name, price, pe, pb, market_cap(元), change_pct(%), type}]
        """
        headers = {"Referer": "https://finance.sina.com.cn"}
        base = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        nodes = [("hs_a", "stock"), ("etf_hq_fund", "etf")]
        records: list[dict] = []

        # 估算总页数（A股约5000只=50页, ETF约1000只=10页），用于进度
        estimated_total = 60
        processed = 0

        for node, type_ in nodes:
            page = 1
            num = 100
            while True:
                params = {
                    "page": str(page), "num": str(num), "sort": "symbol",
                    "asc": "1", "node": node, "symbol": "", "_s_r_a": "page",
                }
                try:
                    resp = requests.get(base, params=params, headers=headers, timeout=15)
                    data = resp.json()
                except Exception:
                    break
                if not data:
                    break
                for item in data:
                    code = item.get("code")
                    if not code:
                        continue
                    # 跳过北交所股票（92开头，流动性差，涨跌停30%）
                    if code.startswith("92"):
                        continue
                    per = item.get("per")
                    pb = item.get("pb")
                    mktcap = item.get("mktcap")
                    records.append({
                        "code": code,
                        "name": item.get("name", ""),
                        "price": item.get("trade"),
                        "pe": float(per) if per and float(per) > 0 else None,
                        "pb": float(pb) if pb and float(pb) > 0 else None,
                        "market_cap": float(mktcap) * 1e4 if mktcap else None,  # 万元→元
                        "change_pct": float(item["changepercent"]) if item.get("changepercent") is not None else None,
                        "type": type_,
                    })
                processed += 1
                if progress_callback:
                    progress_callback(min(80, int(processed / estimated_total * 80)))
                if len(data) < num:
                    break
                page += 1

        if progress_callback:
            progress_callback(80)
        return records

    # ═══════════ 财务数据（东财业绩报表，降级近似） ═══════════

    @classmethod
    def get_financial_data(cls) -> dict:
        """获取全市场财务数据（净利润同比增速 + 财报ROE）

        优先用东财业绩报表（免费），失败降级返回空 dict。
        优先返回"净利润同比字段有值"的报告期（一季报）。
        返回 {code: {"profit_yoy": 净利润同比%, "roe": 财报ROE%}}
        """
        import akshare as ak
        # 一季报优先（净利润同比字段有值），中报次之，年报兜底
        for date in ["20260331", "20260630", "20251231"]:
            try:
                df = ak.stock_yjbb_em(date=date)
                if df is None or df.empty:
                    continue
                # 动态匹配列名（避免中文编码问题）
                code_col = None
                profit_col = None
                roe_col = None
                for c in df.columns:
                    if c in ("股票代码", "代码") or "代码" in c:
                        code_col = c
                    if "净利润" in c and "同比" in c:
                        profit_col = c
                    if "净资产" in c and "收益率" in c:
                        roe_col = c
                if not code_col:
                    continue
                result: dict = {}
                has_profit_yoy = False
                for _, row in df.iterrows():
                    code = str(row.get(code_col, "")).zfill(6)
                    if not code or code == "nan":
                        continue

                    def _to_float(v):
                        try:
                            if v is None or str(v) in ("nan", "None", ""):
                                return None
                            return float(v)
                        except Exception:
                            return None

                    profit_yoy = _to_float(row.get(profit_col)) if profit_col else None
                    roe = _to_float(row.get(roe_col)) if roe_col else None
                    if profit_yoy is not None:
                        has_profit_yoy = True
                    result[code] = {"profit_yoy": profit_yoy, "roe": roe}
                # 该报告期有净利润同比数据，直接返回
                if has_profit_yoy:
                    return result
            except Exception:
                continue
        return {}


# 单例
data_service = DataService()
