# GenVoid 用户安装手册

AI 视频生成平台 —— 本文档介绍如何在本地部署并运行 GenVoid 前后端服务。

---

## 一、环境要求

| 组件 | 最低版本 | 备注 |
|------|----------|------|
| 操作系统 | Linux / macOS / Windows（WSL2） | 推荐 Ubuntu 22.04+ |
| Python | 3.10+ | 用于后端 FastAPI 服务 |
| Node.js | 18+ | 推荐 20 LTS |
| npm | 9+ | 随 Node.js 安装 |
| Git | 任意 | 用于拉取代码 |
| 磁盘空间 | ≥ 5 GB | 用于缓存生成的图片/视频 |

### 依赖检查

```bash
python3 --version    # 应 >= 3.10
node -v              # 应 >= 18
npm -v               # 应 >= 9
```

---

## 二、获取源码

```bash
git clone <仓库地址> genvoid
cd genvoid
```

目录结构：

```
genvoid/
├── backend/            # FastAPI 后端
├── frontend/           # React + Vite 前端
├── start_backend.sh    # 后端一键启动脚本
├── start_frontend.sh   # 前端一键启动脚本
└── void.md             # 产品设计文档
```

---

## 三、配置 API 密钥

后端需要调用多个第三方 AI 服务，首次运行前必须配置密钥。

### 1. 创建配置文件

```bash
cd backend
cp .env.example .env
```

### 2. 编辑 `backend/.env`

根据实际使用的服务填写对应密钥，未使用的保持默认空值即可：

```bash
# 可灵 AI（图生视频，必填）
KLING_ACCESS_KEY=your_kling_access_key
KLING_SECRET_KEY=your_kling_secret_key

# OpenAI（剧本/分镜生成，必填）
OPENAI_API_KEY=your_openai_api_key
OPENAI_BASE_URL=https://api.openai.com/v1
# 如使用国内兼容接口，可替换为：
# OPENAI_BASE_URL=https://api.deepseek.com/v1

# 模型选择（可选，默认 gpt-4o / gpt-4o-mini）
LLM_MODEL=gpt-4o
LLM_MODEL_MINI=gpt-4o-mini

# 即梦 AI（火山方舟，可选）
JIMENG_API_KEY=
JIMENG_IMAGE_MODEL=
JIMENG_VIDEO_MODEL=

# Stability AI（可选）
STABILITY_API_KEY=

# SiliconFlow（可选）
SILICONFLOW_API_KEY=

# 腾讯云（可选）
TENCENT_SECRET_ID=
TENCENT_SECRET_KEY=

# 火山引擎对象存储 TOS（可选，用于视频托管）
TOS_ACCESS_KEY=
TOS_SECRET_KEY=
TOS_BUCKET=
TOS_ENDPOINT=https://tos-cn-beijing.volces.com
TOS_REGION=cn-beijing

# 应用配置
UPLOAD_DIR=uploads
MAX_FILE_SIZE_MB=50
```

### 3. 配置前端 API 地址（可选）

前端默认访问同主机的 8000 端口。如后端部署在其他机器，请修改 [frontend/.env](frontend/.env)：

```bash
VITE_API_BASE_URL=http://your-backend-host:8000
```

---

## 四、启动后端

### 方式 A：一键脚本（推荐）

```bash
cd genvoid
bash start_backend.sh
```

脚本会自动完成：
1. 检查 `.env`，不存在则从 `.env.example` 创建并退出提示填写
2. 创建 Python 虚拟环境 `backend/venv/`
3. 安装 [requirements.txt](backend/requirements.txt) 中的依赖
4. 启动 `uvicorn`，监听 `0.0.0.0:8000`

### 方式 B：手动启动

```bash
cd backend
python3 -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 验证后端

浏览器访问：<http://localhost:8000/api/health>

预期返回：

```json
{"status": "ok", "service": "GenVoid"}
```

---

## 五、启动前端

### 方式 A：一键脚本（推荐）

新开一个终端：

```bash
cd genvoid
bash start_frontend.sh
```

脚本会自动完成：
1. `npm install` 安装依赖（仅首次）
2. `npm run dev` 启动 Vite 开发服务器

### 方式 B：手动启动

```bash
cd frontend
npm install
npm run dev
```

### 访问应用

默认地址：<http://localhost:5173>

Vite 启动后会在终端打印实际端口，以终端输出为准。

---

## 六、生产环境部署

### 前端构建

```bash
cd frontend
npm run build
```

构建产物位于 `frontend/dist/`，可用 Nginx、Caddy 等静态服务器托管。

### 后端生产部署

去掉 `--reload`，建议配合 `gunicorn` 或 `systemd` 管理进程：

```bash
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Nginx 反向代理示例

```nginx
server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    location / {
        root /path/to/genvoid/frontend/dist;
        try_files $uri /index.html;
    }

    # 后端 API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # 静态资源（生成的图片/视频）
    location /uploads/ {
        proxy_pass http://127.0.0.1:8000;
    }
}
```

---

## 七、常见问题

### Q1：启动后端报 `ModuleNotFoundError`

未激活虚拟环境。运行：

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
```

### Q2：前端访问 API 出现 CORS 错误

检查后端是否启动，以及 `frontend/.env` 中 `VITE_API_BASE_URL` 是否指向正确的后端地址。修改 `.env` 后必须重启 `npm run dev`。

### Q3：调用 AI 服务返回 401 / 403

密钥未配置或已过期。检查 `backend/.env` 对应服务的 KEY，修改后重启后端服务。

### Q4：生成的视频/图片无法访问

检查 `backend/uploads/` 目录权限，确保后端进程有读写权限：

```bash
chmod -R u+rw backend/uploads
```

### Q5：端口被占用

后端：修改启动命令中的 `--port 8000` 为其他端口。
前端：Vite 会自动寻找可用端口，或在 [frontend/vite.config.js](frontend/vite.config.js) 中显式指定。

### Q6：Windows 环境下脚本无法运行

`start_backend.sh` / `start_frontend.sh` 是 Bash 脚本，Windows 用户请：
- 使用 WSL2（推荐）
- 或参照"方式 B：手动启动"逐条执行

---

## 八、目录说明

| 路径 | 说明 |
|------|------|
| [backend/main.py](backend/main.py) | FastAPI 入口，注册所有路由 |
| [backend/config.py](backend/config.py) | 环境变量与全局配置 |
| [backend/routers/](backend/routers/) | 各业务路由（上传、场景、图片、视频等） |
| [backend/services/](backend/services/) | 第三方 AI 服务适配层 |
| [backend/uploads/](backend/uploads/) | 生成产物存储目录 |
| [frontend/src/](frontend/src/) | 前端源码 |
| [frontend/dist/](frontend/dist/) | 生产构建产物 |

---

## 九、下一步

- 阅读 [void.md](void.md) 了解完整产品设计与流水线架构
- 打开前端页面创建第一个项目，按"剧本 → 分镜 → 关键帧 → 视频 → 合成"的顺序体验流程
- 生产部署建议配合 HTTPS 与访问鉴权
