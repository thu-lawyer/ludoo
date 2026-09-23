#!/bin/bash
# 律读公网暴露脚本：通过 Cloudflare 免费快速隧道映射本机 8765 端口。
# 地址为随机 trycloudflare.com，每次重启会变；电脑关机/休眠即离线。
set -e
cd "$(dirname "$0")"

PORT="${LUDOO_PORT:-8765}"
LOCAL="http://127.0.0.1:$PORT"
LOG="/tmp/ludoo-tunnel.log"

# 1. 本地服务须在运行
if ! curl -s -o /dev/null "$LOCAL/api/stats"; then
  echo "[律读] 本地服务未运行，先启动…"
  ./start.sh >/tmp/ludoo-server.log 2>&1 &
  for i in $(seq 1 30); do
    curl -s -o /dev/null "$LOCAL/api/stats" && break
    sleep 1
  done
  curl -s -o /dev/null "$LOCAL/api/stats" || { echo "[律读] 服务启动失败，请查看 /tmp/ludoo-server.log"; exit 1; }
fi

# 2. 未设口令时强烈警告
if ! grep -q "^LUDOO_PASSWORD=..*" .env 2>/dev/null; then
  echo "⚠️  警告：未设置访问口令（.env 的 LUDOO_PASSWORD 为空）。"
  echo "   公网地址一旦泄露，任何人都能读写你的文献库并消耗 AI 额度。"
  read -r "回复?继续裸奔请输入 y，其他任意键退出去设置口令: " REPLY
  [[ "$REPLY" == "y" ]] || { echo "已退出。请编辑 .env 设置 LUDOO_PASSWORD 后重启服务再运行本脚本。"; exit 1; }
fi

# 3. cloudflared：优先项目自带 bin/，其次系统安装，最后尝试自动下载
CF=./bin/cloudflared
if ! [ -x "$CF" ]; then
  if command -v cloudflared >/dev/null; then
    CF=cloudflared
  else
    echo "[律读] 未找到 cloudflared，尝试下载到 bin/…"
    mkdir -p bin
    ARCH=$(uname -m)
    case "$ARCH" in
      arm64) URL_ARCH=darwin-arm64 ;;
      x86_64) URL_ARCH=darwin-amd64 ;;
      *) echo "不支持的架构 $ARCH，请手动安装：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/" >&2; exit 1 ;;
    esac
    curl -sL "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-${URL_ARCH}.tgz" | tar xz -C bin
    chmod +x "$CF" || { echo "下载失败，请手动安装"; exit 1; }
  fi
fi

# 4. 起隧道并等待公网地址
echo "[律读] 建立隧道…（地址每次重启会变）"
"$CF" tunnel --url "$LOCAL" >"$LOG" 2>&1 &
TUNNEL_PID=$!

cleanup() {
  echo ""
  echo "[律读] 关闭隧道。"
  kill "$TUNNEL_PID" 2>/dev/null
}
trap cleanup INT TERM EXIT

URL=""
for i in $(seq 1 30); do
  URL=$(grep -oE "https://[a-z0-9-]+\.trycloudflare\.com" "$LOG" | head -1)
  [ -n "$URL" ] && break
  if ! kill -0 "$TUNNEL_PID" 2>/dev/null; then
    echo "[律读] 隧道启动失败，日志："; tail -5 "$LOG"; exit 1
  fi
  sleep 1
done
[ -n "$URL" ] || { echo "[律读] 30 秒内未获取到公网地址，日志："; tail -5 "$LOG"; exit 1; }

echo ""
echo "════════════════════════════════════════════"
echo "  🌐 律读已上线：$URL"
echo "════════════════════════════════════════════"
if grep -q "^LUDOO_PASSWORD=..*" .env 2>/dev/null; then
  echo "  首次访问需输入 .env 中设置的 LUDOO_PASSWORD 口令"
fi
echo "  Ctrl+C 结束公网访问（本地服务不受影响）"
echo "  提示：电脑休眠/关机后地址失效，重跑本脚本获取新地址"
echo "════════════════════════════════════════════"

wait "$TUNNEL_PID"
