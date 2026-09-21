#!/bin/bash
set -e
cd "$(dirname "$0")/frontend"

if [ ! -d node_modules ]; then
  echo "📦 安装前端依赖 ..."
  npm install
fi

# 端口预检,被占时提示并退出
if ss -tln 2>/dev/null | grep -q ":5173 "; then
  echo "⚠  端口 5173 已被占用,请先停止占用进程:"
  ss -tlnp 2>/dev/null | grep ":5173 " || true
  exit 1
fi

LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "✅ 启动前端开发服务器 ..."
echo "   本机访问: http://localhost:5173/"
[ -n "$LOCAL_IP" ] && echo "   局域网访问: http://$LOCAL_IP:5173/"

exec npm run dev -- --host 0.0.0.0
