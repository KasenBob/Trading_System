# 📈 A股交易系统

一个支持 **股票 + ETF** 的网页版 A 股量化交易系统。提供自选股、模拟交易、策略回测、多因子选股、AI 分析、自动交易等完整功能，数据源全部免费（新浪 / 腾讯 / 东方财富 / akshare），可一键部署到自己的服务器。

## ✨ 功能特性

### 1. 用户认证
- 注册 / 登录 / 注销 / 修改密码
- 密码 PBKDF2-SHA256 加盐哈希存储
- Token 持久化到数据库（服务器重启不失效，有效期 30 天）

### 2. 股票查询
- 股票 / ETF 搜索（代码、名称，内存缓存秒搜）
- 实时行情（新浪 → 腾讯多源 fallback）
- K 线（日 / 周 / 月，MA5/20/60，前复权 / 后复权）
- 分时走势、资金流向、财务指标

### 3. 自选股
- 增删改查、批量添加、拖拽排序、自定义分组
- 行情自动刷新、涨跌家数统计

### 4. 模拟交易
- 账户管理（初始资金、一键重置）
- 限价 / 市价下单，完整模拟 T+1、涨跌停、手续费
- 持仓、成交记录、盈亏日历、资金曲线（对比沪深300）
- 收益统计：总 / 年化 / 日 / 周 / 月收益、最大回撤、夏普比率、胜率

### 5. 策略 + 回测
- 9 种预设策略模板：双均线交叉、MACD、布林带、RSI、KDJ、海龟、动量、网格、三层过滤漏斗
- 单策略 / 多策略组合回测（separate / filter / and / vote 四种组合方式）
- 11 项回测指标 + 交易明细 + 当日信号

### 6. 选股分析 + AI
- 多因子选股：EP、ROE、20日动量、小市值 四因子加权打分
- 硬性门槛 + 一票否决 + 次新股剔除
- 全市场选股（带进度查询）
- DeepSeek AI 对选股结果做智能分析

### 7. 自动交易
- 加入股票（指定价格 + 股数 + 策略）→ 立即买入
- 每个交易日 **14:50** 自动按策略调仓
- 删除 → 卖出（遵守 T+1）
- 完整执行日志

## 🖥 页面导航

| 路由 | 页面 | 说明 |
|------|------|------|
| /login | 登录 / 注册 | 用户认证 |
| /query | 股票查询 | 行情、K线、财务 |
| /watchlist | 自选股 | 自选管理 + 行情 |
| /simulation | 模拟交易 | 下单、持仓、收益 |
| /strategy | 策略 | 策略、回测、多因子、AI |
| /selection | 选股分析 | 个股批量分析 |

## 🛠 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | React 19 + TypeScript + Vite 8 + Ant Design 6 + ECharts 6 + react-markdown + axios |
| 后端 | Python + FastAPI + SQLAlchemy(async) + pydantic-settings |
| 数据库 | SQLite（aiosqlite） |
| 数据源 | 新浪（行情）、腾讯（K线/分时）、东方财富（财务/资金流/估值）、akshare（日历/指数/ETF） |
| AI | DeepSeek（OpenAI 兼容接口） |

## 📁 目录结构

```
Trading/
├── backend/                 # FastAPI 后端
│   ├── main.py              # 应用入口（注册路由、启动调度器）
│   ├── config.py            # 配置（读 .env）
│   ├── database.py          # SQLite 连接 + 表初始化 + 轻量迁移
│   ├── models/              # SQLAlchemy 模型（12 张表）
│   ├── routers/             # API 路由（7 组）
│   ├── services/            # 业务逻辑
│   │   ├── akshare_service.py   # 多数据源行情封装
│   │   ├── backtest_engine.py   # 回测引擎
│   │   ├── multifactor.py       # 多因子选股
│   │   ├── autotrade_service.py # 自动交易调度
│   │   ├── ai_analysis.py       # DeepSeek AI
│   │   └── auth.py              # 认证服务
│   └── requirements.txt
├── frontend/                # React 前端
│   ├── src/pages/           # 6 个页面
│   ├── src/services/        # API 封装 + 认证
│   └── vite.config.ts
├── deploy/                  # 服务器部署
│   ├── deploy.sh            # Ubuntu 一键部署脚本
│   ├── trading.service      # systemd 守护
│   └── nginx.conf           # nginx 配置
├── run.py                   # 本地一键启动
├── README.md
└── DESIGN.md                # 技术设计文档
```

## 🚀 本地运行

```bash
# 1. 后端依赖（建议使用 conda 环境）
cd backend
pip install -r requirements.txt

# 2. 配置 .env（AI 分析需要）
#    创建 backend/.env，内容：DEEPSEEK_API_KEY=sk-xxx

# 3. 前端依赖
cd ../frontend
npm install

# 4. 一键启动（后端 8000 + 前端 5173）
cd ..
python run.py
```

访问 http://127.0.0.1:5173 ，API 文档 http://127.0.0.1:8000/docs

## ☁️ 服务器部署（Ubuntu）

```bash
# 1. 上传代码到服务器（git 或 scp）
sudo mkdir -p /opt/trading && cd /opt/trading
# git clone <仓库地址> .  或  scp -r 本地目录 user@服务器:/opt/trading

# 2. 一键部署（装依赖 → venv → 构建前端 → systemd → nginx）
sudo bash deploy/deploy.sh

# 3. 验证
curl http://127.0.0.1:8000/api/health
# 浏览器访问 http://服务器IP/
```

常用运维命令：

```bash
systemctl status trading          # 后端状态
systemctl restart trading         # 重启后端
journalctl -u trading -f          # 实时日志
nginx -t && systemctl reload nginx  # 重载 nginx
```

部署脚本可选环境变量：

```bash
sudo SERVER_IP=your-domain.com bash deploy/deploy.sh   # 指定域名/IP
sudo DEEPSEEK_API_KEY=sk-xxx bash deploy/deploy.sh      # 传 API Key
sudo SKIP_FRONTEND=1 bash deploy/deploy.sh             # 跳过前端构建
```

## ⚙️ 配置说明

| 配置项 | 位置 | 默认值 | 说明 |
|--------|------|--------|------|
| DEEPSEEK_API_KEY | backend/.env | 空 | AI 分析必需 |
| DATABASE_URL | config.py | sqlite+aiosqlite:///./trading.db | 数据库路径 |
| HOST / PORT | config.py | 127.0.0.1 / 8000 | 后端监听 |
| STAMP_TAX | config.py | 0.001 | 印花税（卖出单向） |
| COMMISSION_RATE | config.py | 0.00025 | 佣金（万2.5） |
| MIN_COMMISSION | config.py | 5.0 | 最低佣金（元） |

## 📏 业务规则

- **T+1**：当日买入不可当日卖出
- **涨跌停**：主板 ±10%，创业板 / 科创板 ±20%
- **交易单位**：100 股（1 手）整数倍
- **手续费**：印花税 0.1%（卖）、佣金万2.5（最低5元）、过户费万0.1

## ⚠️ 注意事项

1. 首次运行 akshare 会拉取数据，较慢属正常；需服务器可访问公网
2. `backend/.env`（API Key）与 `backend/trading.db`（数据）均被 gitignore 排除，不会上传到 GitHub，请自行备份
3. 自动交易依赖服务器本地时间，部署时请确保时区为 `Asia/Shanghai`
4. 生产环境建议将 `DEBUG` 置为 `False`
