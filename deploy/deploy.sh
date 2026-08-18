#!/usr/bin/env bash
# ============================================================
# A股交易系统 - Ubuntu 一键部署脚本
#
# 用法：
#   1. 将项目代码放到服务器，例如 /opt/trading
#   2. cd /opt/trading
#   3. sudo bash deploy/deploy.sh
#
# 运行时会交互式询问「服务器地址」和「启动端口」；也可用环境变量跳过交互：
#   SERVER_IP        服务器公网 IP 或域名（如 your-domain.com）
#   PORT             对外启动端口（默认 80）
#   DEEPSEEK_API_KEY DeepSeek API Key（用于 AI 分析，可留空）
#   SKIP_FRONTEND=1  跳过前端构建（已在本地构建好 dist 时）
#   PIP_INDEX        pip 镜像源（默认清华镜像）
# ============================================================

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="${APP_DIR}/backend"
FRONTEND_DIR="${APP_DIR}/frontend"
DEPLOY_DIR="${APP_DIR}/deploy"
SERVER_IP="${SERVER_IP:-}"
if [ -z "${SERVER_IP}" ]; then
  read -rp "请输入服务器地址（IP 或域名）: " SERVER_IP || true
fi
if [ -z "${SERVER_IP}" ]; then
  echo "错误：服务器地址不能为空"
  exit 1
fi

PORT="${PORT:-}"
if [ -z "${PORT}" ]; then
  read -rp "请输入启动端口（回车默认 80）: " PORT || true
  PORT="${PORT:-80}"
fi
case "${PORT}" in
  ''|*[!0-9]*) echo "错误：启动端口必须是数字"; exit 1 ;;
esac
if [ "${PORT}" -lt 1 ] || [ "${PORT}" -gt 65535 ]; then
  echo "错误：启动端口范围 1-65535"
  exit 1
fi

PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

log() { echo -e "\n\033[1;34m[$(date +%H:%M:%S)]\033[0m $*"; }

if [ "${EUID}" -ne 0 ]; then
  echo "请用 root 运行：sudo bash deploy/deploy.sh"
  exit 1
fi

log "===== A股交易系统部署开始 ====="
echo "  项目目录:   ${APP_DIR}"
echo "  服务器地址: ${SERVER_IP}"
echo "  启动端口:   ${PORT}"

# ---------- 1. 系统依赖 ----------
log "[1/6] 安装系统依赖（python/nginx/时区）..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get install -y -qq python3 python3-venv python3-pip nginx curl git ca-certificates
timedatectl set-timezone Asia/Shanghai || true

# ---------- 2. 后端 venv + 依赖 ----------
log "[2/6] 创建后端虚拟环境并安装依赖..."
if [ ! -x "${BACKEND_DIR}/.venv/bin/uvicorn" ]; then
  python3 -m venv "${BACKEND_DIR}/.venv"
fi
"${BACKEND_DIR}/.venv/bin/pip" install --upgrade pip -q
"${BACKEND_DIR}/.venv/bin/pip" install -i "${PIP_INDEX}" -r "${BACKEND_DIR}/requirements.txt" -q

# ---------- 3. .env 配置 ----------
log "[3/6] 配置 .env ..."
if [ ! -f "${BACKEND_DIR}/.env" ]; then
  DS_KEY="${DEEPSEEK_API_KEY:-}"
  if [ -z "${DS_KEY}" ] && [ -t 0 ]; then
    read -rp "请输入 DEEPSEEK_API_KEY（回车跳过）: " DS_KEY
  fi
  cat > "${BACKEND_DIR}/.env" <<EOF
DEEPSEEK_API_KEY=${DS_KEY}
EOF
  echo "DEBUG=False" >> "${BACKEND_DIR}/.env"
  echo "已创建 .env（DEBUG=False）"
else
  echo "已存在 .env，跳过（如需修改请手动编辑）"
fi

# ---------- 4. 前端构建 ----------
if [ "${SKIP_FRONTEND:-0}" = "1" ]; then
  log "[4/6] 跳过前端构建（SKIP_FRONTEND=1）..."
else
  log "[4/6] 安装 Node.js 并构建前端..."
  if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
    apt-get install -y -qq nodejs
  fi
  cd "${FRONTEND_DIR}"
  rm -rf dist                     # 删除旧构建产物，确保更新代码后前端重建
  npm install --registry=https://registry.npmmirror.com
  npm run build
  cd "${APP_DIR}"
fi

# ---------- 5. systemd ----------
log "[5/6] 配置并启动 systemd 服务..."
sed "s|__APP_DIR__|${APP_DIR}|g" "${DEPLOY_DIR}/trading.service" > /etc/systemd/system/trading.service
systemctl daemon-reload
systemctl enable trading            # 设置开机自启（幂等）
systemctl restart trading           # 重启后端，确保加载最新代码
sleep 2

# ---------- 6. nginx ----------
log "[6/6] 配置 nginx..."
sed "s|__APP_DIR__|${APP_DIR}|g; s|__SERVER_IP__|${SERVER_IP}|g; s|__PORT__|${PORT}|g" \
  "${DEPLOY_DIR}/nginx.conf" > /etc/nginx/sites-available/trading
ln -sf /etc/nginx/sites-available/trading /etc/nginx/sites-enabled/trading
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

log "===== 部署完成 ====="
echo "  后端健康检查: curl http://127.0.0.1:8000/api/health"
if [ "${PORT}" = "80" ]; then
  echo "  访问地址:     http://${SERVER_IP}/"
else
  echo "  访问地址:     http://${SERVER_IP}:${PORT}/"
fi
echo "  后端状态:     systemctl status trading"
echo "  后端日志:     journalctl -u trading -f"
