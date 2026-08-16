# A股交易系统 · 技术设计文档

## 1. 系统架构

```
┌──────────────────────────────────────────────┐
│              浏览器 / Web 前端                 │
│   React 19 + TypeScript + Ant Design 6        │
└──────────────┬───────────────────────────────┘
               │ HTTP (REST, JSON)
               ▼
┌──────────────────────────────────────────────┐
│              FastAPI 后端 (uvicorn)           │
│  ┌─────────┐  ┌─────────┐  ┌─────────────┐  │
│  │ routers │→ │ services│→ │ 数据源/外部  │  │
│  │ (7组API)│  │ (业务)  │  │ 新浪/腾讯/东财│  │
│  └─────────┘  └─────────┘  └─────────────┘  │
│       │              │            ↑           │
│       ▼              ▼            │           │
│  ┌──────────── SQLAlchemy(async) ─┘           │
│  │        SQLite (trading.db)                 │
│  └────────────────────────────────────────────┘
│  ┌──────────── 后台调度器 ────────────┐        │
│  │ scheduler_loop (30s 检查, 14:50)   │        │
│  └────────────────────────────────────┘        │
└──────────────────────────────────────────────┘
```

## 2. 技术选型

| 层级 | 技术 | 说明 |
|------|------|------|
| 前端框架 | React 19 + TypeScript | 组件化、类型安全 |
| UI 组件 | Ant Design 6 | 中文友好、表格/表单能力强 |
| 图表 | ECharts 6 + echarts-for-react | K线、资金曲线、日历图 |
| Markdown | react-markdown + remark-gfm | AI 分析结果渲染 |
| 路由 | react-router-dom 7 | SPA 路由 |
| HTTP | axios | 请求封装 + 拦截器 |
| 后端 | FastAPI + uvicorn | 异步、自动 API 文档 |
| ORM | SQLAlchemy 2.0 (async) | 异步引擎 |
| 数据库 | SQLite (aiosqlite) | 零配置、轻量 |
| 配置 | pydantic-settings | .env 加载 |
| 数据源 | 新浪 / 腾讯 / 东方财富 / akshare | 多源 fallback |
| AI | DeepSeek (OpenAI 兼容) | 选股分析 |

## 3. 数据库设计

共 **12 张表**，均使用 SQLAlchemy 声明式模型（`backend/models/`）。

### 3.1 用户与认证

**user（用户表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| username | VARCHAR(50) UNIQUE | 用户名 |
| password_hash | VARCHAR(128) | PBKDF2 密码哈希 |
| salt | VARCHAR(64) | 盐 |
| created_at | DATETIME | 注册时间 |

**auth_token（认证令牌表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| token | VARCHAR(64) PK | token |
| user_id | INTEGER FK | 用户ID |
| created_at | DATETIME | 创建时间 |
| expires_at | DATETIME | 过期时间 |

### 3.2 自选股

**watchlist（自选股表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| user_id | INTEGER FK | 用户ID |
| code | VARCHAR(10) | 股票/ETF代码 |
| name | VARCHAR(50) | 名称 |
| type | VARCHAR(10) | stock / etf |
| group | VARCHAR(50) | 分组名称 |
| sort_order | INTEGER | 排序序号 |
| created_at | DATETIME | 添加时间 |

### 3.3 模拟交易

**account（账户表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| user_id | INTEGER FK | 用户ID |
| name | VARCHAR(50) | 账户名称 |
| initial_capital | FLOAT | 初始资金 |
| available_cash | FLOAT | 可用资金 |
| created_at | DATETIME | 创建时间 |

**position（持仓表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| account_id | INTEGER FK | 账户ID |
| code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(50) | 股票名称 |
| quantity | INTEGER | 持仓数量 |
| avg_cost | FLOAT | 持仓成本 |
| strategy_name | VARCHAR(100) | 使用的策略名称 |
| updated_at | DATETIME | 更新时间 |

**transaction（成交记录表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| account_id | INTEGER FK | 账户ID |
| code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(50) | 股票名称 |
| direction | VARCHAR(4) | buy / sell |
| price | FLOAT | 成交价格 |
| quantity | INTEGER | 成交数量 |
| amount | FLOAT | 成交金额 |
| fee | FLOAT | 手续费 |
| strategy_name | VARCHAR(100) | 策略名称 |
| traded_at | DATETIME | 成交时间 |

**asset_snapshot（资产快照表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| account_id | INTEGER FK | 账户ID |
| total_asset | FLOAT | 总资产 |
| snapshot_date | DATE | 快照日期 |

### 3.4 策略与回测

**strategy（策略表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| user_id | INTEGER FK | 用户ID |
| name | VARCHAR(100) | 策略名称 |
| type | VARCHAR(50) | 策略类型 |
| params | TEXT(JSON) | 策略参数JSON |
| enabled | BOOLEAN | 是否启用 |
| created_at | DATETIME | 创建时间 |

**backtest（回测记录表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| strategy_id | INTEGER FK | 策略ID |
| code | VARCHAR(10) | 回测标的 |
| start_date | DATE | 起始日 |
| end_date | DATE | 结束日 |
| initial_capital | FLOAT | 初始资金 |
| status | VARCHAR(20) | pending/running/completed/failed |
| result | TEXT(JSON) | 回测结果JSON |
| created_at | DATETIME | 创建时间 |

**backtest_trade（回测交易明细表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| backtest_id | INTEGER FK | 回测ID |
| date | DATE | 交易日期 |
| code | VARCHAR(10) | 标的代码 |
| direction | VARCHAR(4) | buy / sell |
| price | FLOAT | 交易价格 |
| quantity | INTEGER | 交易数量 |
| reason | VARCHAR(255) | 交易原因 |

### 3.5 自动交易

**auto_trade_item（自动交易清单表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| user_id | INTEGER FK | 用户ID |
| code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(50) | 股票名称 |
| strategy_id | INTEGER FK | 策略ID |
| strategy_name | VARCHAR(100) | 策略名称快照 |
| strategy_type | VARCHAR(50) | 策略类型快照 |
| strategy_params | TEXT(JSON) | 策略参数快照 |
| quantity | INTEGER | 买入股数 |
| started_at | DATETIME | 策略启动时间 = 买入时刻 |
| entry_price | FLOAT | 买入成交价 |
| enabled | BOOLEAN | 单只开关 |
| created_at | DATETIME | 创建时间 |

**auto_trade_log（自动交易日志表）**

| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 主键 |
| user_id | INTEGER FK | 用户ID |
| code | VARCHAR(10) | 股票代码 |
| name | VARCHAR(50) | 股票名称 |
| strategy | VARCHAR(100) | 策略名称 |
| trigger | VARCHAR(20) | manual_add / manual_remove / daily / reset |
| signal | INTEGER | 信号值 1 / -1 / 0 |
| action | VARCHAR(10) | buy / sell / skip |
| price | FLOAT | 成交价 |
| quantity | INTEGER | 成交数量 |
| result | VARCHAR(255) | 结果 / 原因 |
| created_at | DATETIME | 时间 |

## 4. API 设计

所有接口返回统一结构 `{code, data?, message?, count?}`，认证接口通过 `Authorization: Bearer <token>` 头鉴权。

### 4.1 认证 `/api/auth`

| Method | 路径 | 说明 |
|--------|------|------|
| POST | /api/auth/register | 注册 |
| POST | /api/auth/login | 登录 |
| POST | /api/auth/logout | 注销 |
| POST | /api/auth/change-password | 修改密码 |
| GET | /api/auth/me | 当前用户信息 |

### 4.2 行情 `/api/market`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/market/realtime?codes= | 批量实时行情 |
| GET | /api/market/realtime/etf?codes= | ETF 实时行情 |
| GET | /api/market/kline?code=&period= | K线 |
| GET | /api/market/index/{code} | 指数日线 |

### 4.3 股票查询 `/api/stock`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/stock/search?keyword= | 搜索 |
| GET | /api/stock/minute/{code} | 分时 |
| GET | /api/stock/fundflow/{code} | 资金流向 |
| GET | /api/stock/detail/{code} | 个股详情 + 行情 |
| GET | /api/stock/financial/{code} | 财务指标 |

### 4.4 自选股 `/api/watchlist`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/watchlist | 列表 |
| POST | /api/watchlist | 添加 |
| POST | /api/watchlist/batch | 批量添加 |
| DELETE | /api/watchlist/{id} | 删除 |
| PUT | /api/watchlist/reorder | 拖拽排序 |
| PUT | /api/watchlist/{id}/group | 修改分组 |

### 4.5 模拟交易 `/api/trade`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/trade/account | 账户信息 |
| POST | /api/trade/account/reset | 重置账户 |
| POST | /api/trade/order | 下单 |
| GET | /api/trade/positions | 持仓列表 |
| GET | /api/trade/transactions | 成交记录 |
| GET | /api/trade/stats | 收益统计 + 盈亏日历 |
| GET | /api/trade/snapshots | 资产快照 / 资金曲线 |

### 4.6 策略 `/api/strategy`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/strategy/presets | 预设策略模板 |
| GET / POST | /api/strategy | 列表 / 创建 |
| PUT / DELETE | /api/strategy/{id} | 更新 / 删除 |
| PUT | /api/strategy/{id}/toggle | 启用 / 停用 |
| GET | /api/strategy/pullback/signal/{code} | 上升回调实时买入信号 |
| POST | /api/strategy/backtest | 回测 |
| POST | /api/strategy/multifactor | 多因子选股 |
| POST | /api/strategy/multifactor/full/start | 全市场选股 |
| GET | /api/strategy/multifactor/full/progress/{task_id} | 选股进度 |
| GET | /api/strategy/multifactor/full/result/{task_id} | 选股结果 |
| POST | /api/strategy/ai-analysis | AI 分析 |
| POST | /api/strategy/analyze-batch | 个股批量分析 |
| POST | /api/strategy/market-regime | 市场状态判断 |

### 4.7 自动交易 `/api/auto-trade`

| Method | 路径 | 说明 |
|--------|------|------|
| GET | /api/auto-trade | 清单列表 |
| POST | /api/auto-trade/item | 加入（立即买入） |
| PUT | /api/auto-trade/item/{id} | 更新 |
| DELETE | /api/auto-trade/item/{id} | 删除（卖出） |
| POST | /api/auto-trade/run | 手动触发调仓 |
| POST | /api/auto-trade/reset | 重置 |
| GET | /api/auto-trade/logs | 执行日志 |
| DELETE | /api/auto-trade/logs | 清空日志 |

## 5. 核心模块设计

### 5.1 数据服务（akshare_service.py）

`DataService` 单例，多数据源封装 + fallback：

| 功能 | 主源 | 兜底 |
|------|------|------|
| 实时行情 | 新浪 hq.sinajs.cn | 腾讯 qt.gtimg.cn |
| K线 | 腾讯 ifzq.gtimg.cn | 新浪 |
| ETF 行情 | 东方财富（akshare） | - |
| 估值数据 | 腾讯 | - |
| 分时 | 腾讯 | - |
| 资金流向 | 东方财富 | - |
| 财务数据 | 东方财富业绩报表 | - |
| 行业 | 东方财富 | - |
| 股票 / ETF 列表 | akshare 内存缓存 | - |

### 5.2 回测引擎（backtest_engine.py）

`BacktestEngine` 类，输入 K 线数据，输出信号 + 绩效：

- **13 种策略信号**：`signals_ma_cross`（双均线）、`signals_macd`（MACD）、`signals_bollinger`（布林带）、`signals_rsi`（RSI）、`signals_kdj`（KDJ）、`signals_turtle`（海龟）、`signals_momentum`（动量）、`signals_grid`（网格）、`signals_funnel`（漏斗建仓）、`signals_uptrend`（单边上升）、`signals_oscillation`（震荡盘整）、`signals_pullback`（上升回调）、`signals_downtrend`（单边下跌）
- **9 种 UI 预设模板**（`routers/strategy.py` PRESETS）：双均线交叉、MACD、布林带突破、RSI、KDJ、单边上升、震荡盘整、上升回调、单边下跌（海龟 / 动量 / 网格 / 漏斗为引擎内置，未列入 UI 预设）
- **回测执行**：逐日模拟买卖，含手续费、T+1
- **多策略组合**：separate（各自）/ filter（过滤）/ and（共振）/ vote（投票）
- **11 项绩效指标**：总收益、年化、最大回撤、胜率、夏普、波动率、盈亏比、利润因子、交易次数、最终资产、每日净值

### 5.3 多因子选股（multifactor.py）

四因子加权打分模型：

| 因子 | 含义 | 方向 |
|------|------|------|
| EP | 1/PE 盈利收益率 | 越大越好 |
| ROE | PB/PE 近似 | 越大越好 |
| momentum | 20日涨幅 | 越大越好 |
| market_cap | 总市值 | 越小越好 |

流程：估值 → 硬性门槛（ROE>10% 且 EP>0.03 且 ROE≤35%）→ 剔除次新股 → 精确动量 → 剔除涨幅>20% → 百分位标准化 → 一票否决（后 20% 剔除）→ 加权求和 → Top N。

### 5.4 自动交易调度（autotrade_service.py）

- `scheduler_loop()`：后台协程，每 30 秒检查，`14:50` 后触发当日首次调仓
- `is_trading_day()`：周末 + akshare 交易日历双判断
- `compute_latest_signal()`：历史 K 线 + 今日实时价拼最新 K 线 → 取最后一根信号
- `run_daily_autotrade()`：遍历所有用户启用清单执行调仓
- 网格策略特殊处理：以买入价为基准判断 ±grid_pct

### 5.5 认证（services/auth.py）

- `hash_password`：PBKDF2-SHA256，10 万次迭代，随机盐
- `verify_password`：`secrets.compare_digest` 防时序攻击
- token 用 `uuid4().hex`，持久化到数据库，30 天过期
- `get_current_user`：FastAPI 依赖，从 Header 解析 token 并校验

### 5.6 AI 分析（services/ai_analysis.py）

调用 DeepSeek OpenAI 兼容接口 `/chat/completions`，构造多因子选股结果 prompt，返回中文分析文本。

## 6. 业务规则

### 6.1 交易规则

| 规则 | 说明 |
|------|------|
| T+1 | 当日买入不可当日卖出（`execute_sell_all` 中通过当日买入数量校验） |
| 涨跌停 | 主板 ±10%，创业板(3) / 科创板(68) ±20%，北交所 ±30% |
| 交易单位 | 100 股（1 手）整数倍 |
| 手续费 | 印花税 0.1%（卖）、佣金万2.5（最低 5 元）、过户费万0.1 |
| 市价单 | 以当前实时价为成交价 |

### 6.2 自动交易规则

- 加入清单 = 立即按指定价格 / 股数买入，绑定策略
- 每日 14:50 调度器遍历所有用户启用清单
- 信号 1 = 买入（无持仓时）、-1 = 卖出（有持仓时）、0 = 持有
- 删除 = 卖出全部可卖数量（T+1 限制，剩余次日可再删）
- 重置 = 清空持仓 / 成交 / 快照 / 清单

## 7. 前端设计

### 7.1 页面与路由

| 路由 | 组件 | 说明 |
|------|------|------|
| /login | Login.tsx | 登录 / 注册 |
| /query | StockQuery.tsx | 股票查询 |
| /watchlist | Watchlist.tsx | 自选股 |
| /simulation | Simulation.tsx | 模拟交易 |
| /strategy | Strategy.tsx | 策略 / 回测 / 选股 / AI |
| /selection | StockSelection.tsx | 选股分析 |

### 7.2 认证与请求

- token + 用户信息存 `localStorage`（`services/auth.ts`）
- axios 实例 `baseURL: /api`，请求拦截器自动带 `Authorization: Bearer <token>`
- 响应拦截器：401 时清除认证并跳转 `/login`
- 开发环境由 Vite proxy 将 `/api` 转发到 `127.0.0.1:8000`

## 8. 部署架构

```
浏览器 ──▶ nginx(80)
            ├── /        → 前端 dist 静态文件（SPA fallback）
            └── /api/*   → 反代 127.0.0.1:8000 (uvicorn/FastAPI)
                              └── SQLite + 数据源 + 调度器
```

- 后端由 systemd（`deploy/trading.service`）守护，开机自启
- 前端 `npm run build` 生成静态文件由 nginx 托管
- 一键部署：`sudo bash deploy/deploy.sh`

## 9. 注意事项

1. **时区**：自动交易依赖服务器本地时间，须为 `Asia/Shanghai`
2. **数据源**：免费接口可能限流 / 延迟，服务内已做多源 fallback
3. **数据库迁移**：`database.py` 的 `init_db()` 包含轻量迁移（补列、重建旧表）
4. **敏感信息**：`.env`（API Key）与 `*.db`（数据）均被 gitignore 排除
5. **并发**：全市场选股使用 `ThreadPoolExecutor` 并发拉取，东财接口可能限流，失败自动降级
