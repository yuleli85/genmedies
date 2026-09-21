#!/bin/bash
set -e
cd "$(dirname "$0")/backend"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "⚠  已创建 backend/.env,请填入 API Key 后重新运行"
  exit 1
fi

# venv 不存在或残缺(缺 activate)时,用系统 python 重建
if [ ! -f venv/bin/activate ]; then
  echo "🔧 venv 不存在或已损坏,正在重建 ..."
  rm -rf venv
  /usr/bin/python3 -m venv venv
fi

source venv/bin/activate
pip install -q -r requirements.txt

# 若 8000 端口已被占用,提示并退出,避免无声失败
if ss -tln 2>/dev/null | grep -q ":8000 "; then
  echo "⚠  端口 8000 已被占用,请先停止占用进程:"
  ss -tlnp 2>/dev/null | grep ":8000 " || true
  exit 1
fi

echo "✅ 后端依赖安装完毕,启动 FastAPI ..."
exec uvicorn main:app --reload --host 0.0.0.0 --port 8000
