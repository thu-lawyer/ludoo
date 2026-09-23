#!/bin/bash
# 律读 LuDoo 一键启动：准备环境 → 启动服务 → 打开浏览器
set -e
cd "$(dirname "$0")"

PORT="${LUDOO_PORT:-8765}"
URL="http://127.0.0.1:$PORT"

# 0. 已在运行则直接打开
if curl -s -o /dev/null "$URL/api/stats"; then
  echo "[律读] 已在运行：$URL"
  command -v open >/dev/null && open "$URL" || command -v xdg-open >/dev/null && xdg-open "$URL"
  exit 0
fi

# 1. Python 虚拟环境与依赖
if [ ! -d .venv ]; then
  echo "[律读] 创建虚拟环境…"
  python3 -m venv .venv
fi
source .venv/bin/activate
echo "[律读] 安装/检查依赖…"
pip install -q -r requirements.txt

# 2. 首次运行时生成演示样例
if [ ! -f samples/论高空抛物致害责任.docx ]; then
  echo "[律读] 生成演示样例文献…"
  python scripts/make_samples.py || true
fi

# 3. 启动服务（后台），就绪后打开浏览器
echo "[律读] 启动服务：$URL"
uvicorn app.main:app --host 127.0.0.1 --port "$PORT" &
SERVER_PID=$!

cleanup() { kill "$SERVER_PID" 2>/dev/null; }
trap cleanup INT TERM

for i in $(seq 1 40); do
  if curl -s -o /dev/null "$URL"; then
    break
  fi
  sleep 0.5
done

echo "[律读] 就绪！浏览器即将打开（Ctrl+C 退出）"
( sleep 1; if command -v open >/dev/null; then open "$URL";
  elif command -v xdg-open >/dev/null; then xdg-open "$URL";
  fi ) &

wait "$SERVER_PID"
