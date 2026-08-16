# 部署指南（Ubuntu）

本文档说明如何将「A股交易系统」部署到 Ubuntu 服务器，使用项目自带的一键部署脚本 `deploy/deploy.sh`。

## 部署架构

```
浏览器 ──▶ nginx(80)
            ├── /        → 前端 dist 静态文件（SPA fallback）
            └── /api/*   → 反向代理 127.0.0.1:8000 (uvicorn/FastAPI)
                              └── SQLite + 数据源 + 自动交易调度器
```

- 前端：`npm run build` 生成静态文件，由 nginx 托管
- 后端：uvicorn 常驻，systemd 守护，仅监听 `127.0.0.1`
- 自动交易调度器挂在 FastAPI 生命周期中，随后端进程运行

## 前置条件

- Ubuntu 20.04 / 22.04 / 24.04
- 服务器可访问公网（GitHub、pypi/npm 镜像、新浪/腾讯/东方财富行情源）
- 安全组 / 防火墙已开放 80 端口
- 仓库已上传到 GitHub（公开仓库，HTTPS 克隆即可）

## 部署步骤

### 1. 登录服务器

```bash
ssh root@<服务器IP>
```

（换成实际登录用户名和服务器 IP，如 `ubuntu@<服务器IP>`）

### 2. 克隆仓库

```bash
sudo apt update
sudo apt install -y git

sudo git clone https://github.com/KasenBob/Trading_System.git /opt/trading
```

> 若 `/opt/trading` 已存在且非空，先执行 `sudo rm -rf /opt/trading`（确认无重要数据）。

### 3. 一键部署

```bash
cd /opt/trading
sudo bash deploy/deploy.sh
```

脚本自动完成以下步骤（幂等，失败可重复执行）：

1. 安装系统依赖（python3、nginx、curl、git 等）
2. 设置时区 `Asia/Shanghai`（自动交易 14:50 依赖本地时间）
3. 创建 Python 虚拟环境并安装后端依赖（清华 pip 镜像）
4. 生成 `backend/.env`（交互式询问 DeepSeek API Key，回车跳过）
5. 安装 Node.js 22 并构建前端（npmmirror 镜像）
6. 配置 systemd 服务 `trading` 并启动
7. 配置 nginx 并重载

耗时约 5–15 分钟。

### 4. 开放 80 端口

云厂商安全组（阿里云 / 腾讯云控制台）：入方向规则允许 **TCP 80**。

服务器防火墙（若启用 ufw）：

```bash
sudo ufw allow 22/tcp
sudo ufw allow 80/tcp
```

### 5. 验证

```bash
curl http://127.0.0.1:8000/api/health   # 应返回 {"status":"ok",...}
systemctl status trading                 # 应显示 active (running)
```

浏览器访问 `http://<服务器IP>/`。

## deploy.sh 可选环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| SERVER_IP | 无 | 服务器公网 IP / 域名（必填）|
| DEEPSEEK_API_KEY | 空 | AI 分析 API Key |
| SKIP_FRONTEND | 0 | 设为 1 跳过前端构建 |
| PIP_INDEX | 清华镜像 | pip 源 |

示例：

```bash
sudo SERVER_IP=your-domain.com bash deploy/deploy.sh
sudo DEEPSEEK_API_KEY=sk-xxx bash deploy/deploy.sh
sudo SKIP_FRONTEND=1 bash deploy/deploy.sh
```

## 日常运维

```bash
systemctl status trading            # 后端状态
systemctl restart trading           # 重启后端
systemctl stop trading              # 停止后端
journalctl -u trading -f            # 后端实时日志
nginx -t && systemctl reload nginx  # 重载 nginx
```

## 更新代码

```bash
cd /opt/trading
sudo git pull                       # 拉取最新代码（如有本地改动先 sudo git stash）
sudo bash deploy/deploy.sh          # 重新安装依赖 + 构建前端 + 重启
```

说明：

- `deploy.sh` 幂等，可重复执行；更新时会删除旧 `dist` 并重新构建前端，保证前端代码生效。
- `.env`（API Key）与 `trading.db`（数据）均不在 git 里，更新不会覆盖，无需重新配置。
- 若只想重启后端（确认代码未变），可执行：
  ```bash
  sudo systemctl restart trading
  ```
- 更新后验证：
  ```bash
  curl http://127.0.0.1:8000/api/health
  systemctl status trading
  ```

## 常见问题排查

| 现象 | 排查方法 |
|------|---------|
| 80 端口访问不通 | 检查云安全组是否开放 80；`systemctl status nginx` |
| 后端启动失败 | `journalctl -u trading -f` 查看报错 |
| 前端页面 404 | nginx 是否正确托管 dist；`nginx -t` |
| AI 分析不可用 | 检查 `backend/.env` 的 DEEPSEEK_API_KEY |
| 行情获取失败 | 服务器是否能访问外网（新浪 / 腾讯 / 东财） |

## 注意事项

1. 时区必须为 `Asia/Shanghai`，自动交易 14:50 依赖本地时间
2. `.env`（API Key）与 `trading.db`（数据）不在 git 里，部署后按需配置，并定期备份数据库
3. 生产环境建议 `DEBUG=False`（deploy.sh 生成 `.env` 时已自动写入）
4. 数据源为免费接口，可能限流 / 延迟，服务内已做多源 fallback
