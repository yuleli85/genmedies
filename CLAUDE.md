# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Quick Start

```bash
# Backend (FastAPI + Uvicorn, Python 3.12, venv)
./start_backend.sh
# Or manually:
cd backend && source venv/bin/activate && uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Frontend (React + Vite)
./start_frontend.sh
# Or manually:
cd frontend && npm run dev -- --host 0.0.0.0 --port 5173

# Frontend build
cd frontend && npm run build

# Lint frontend
cd frontend && npm run lint
```

No test suite exists. No Docker or CI/CD pipeline.

## Architecture

GenVoid is an AI video generation platform. Two separate processes: a FastAPI backend (port 8000) and a React/Vite frontend (port 5173).

### Backend (`backend/`)

Entry point: `main.py`. Configuration via pydantic-settings in `config.py`, reads from `backend/.env`.

**Routers** (`routers/`): Each router is a self-contained feature module with its own prefix:
- `projects.py` — Project CRUD (`/api/projects`)
- `upload.py` — File uploads: portrait, article, scene images (`/api/upload`)
- `scenes.py` — Article → scene splitting via LLM (`/api/scenes`)
- `images.py` — Image generation across multiple providers (`/api/images`)
- `videos.py` — Video generation and merging (`/api/videos`)
- `ppt.py` — PPT → video pipeline: scripts, TTS, animation, merge (`/api/ppt`)
- `drama.py` — Multi-character drama pipeline (`/api/drama`)
- `md2ppt.py` — Markdown → PowerPoint (`/api/md2ppt`)
- `pdf2word.py` — PDF → Word with OCR fallback for scanned pages (`/api/pdf2word`)

**Services** (`services/`): Shared business logic and external API adapters:
- `llm_service.py` — OpenAI-compatible LLM calls + local Tesseract OCR
- `kling_service.py`, `jimeng_service.py`, `hunyuan_service.py`, `siliconflow_service.py`, `stability_service.py` — Image/video generation providers
- `tts_service.py` — Edge TTS text-to-speech
- `lipsync_service.py` — Lip-sync processing
- `video_service.py` — FFmpeg video operations
- `pptx_builder.py` — python-pptx PowerPoint generation
- `task_store.py` — In-memory async task state (create/update/poll pattern)
- `project_store.py` — JSON-file project persistence
- `image_cache.py`, `video_cache.py`, `scenes_cache.py` — Redis-backed caching

**Async task pattern**: Long-running operations return a `task_id` immediately. Frontend polls `GET /api/{module}/task/{task_id}` until `status` is `done` or `error`. Task state lives in memory (lost on restart).

**Static files**: `uploads/` is mounted at `/uploads` for direct browser access to generated media.

### Frontend (`frontend/`)

Single-page React app. No router library — screen state managed in `App.jsx` via `useState`.

- `api.js` — Axios client. Base URL defaults to `${window.location.hostname}:8000` (override with `VITE_API_BASE_URL`). Contains a generic `poll()` helper for task polling.
- `components/ProjectList.jsx` — Home screen with feature cards
- `steps/` — One component per feature workflow (StepDrama, StepPPT, StepPdf2Word, etc.)

### Key Patterns

- All AI service calls go through OpenAI-compatible `chat/completions` endpoint (configurable base URL)
- PDF-to-Word uses dual-path: `pdf2docx` for text PDFs, PyMuPDF + Tesseract OCR + python-docx rebuild for scanned/image pages
- Drama pipeline is the most complex flow: script → shots → keyframes → videos → dub → lipsync → merge
- Frontend uses `react-hot-toast` for notifications, `lucide-react` for icons

## Environment

Backend requires `backend/.env` with API keys. Key variables:
- `OPENAI_API_KEY` / `OPENAI_BASE_URL` / `LLM_MODEL` — Primary LLM
- `KLING_ACCESS_KEY` / `KLING_SECRET_KEY` — Video generation
- `JIMENG_API_KEY` / `JIMENG_IMAGE_MODEL` / `JIMENG_VIDEO_MODEL` — Image/video via 火山方舟
- `REDIS_URL` — Caching (default `redis://127.0.0.1:6379/0`)

System dependencies: `tesseract-ocr` + `tesseract-ocr-chi-sim` (for PDF OCR), `ffmpeg` (video processing).

## Language

All UI text, comments, and documentation are in Chinese. Maintain this convention.
