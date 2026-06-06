# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Backend dev: `uvicorn backend.main:app --reload` (port 8000, SQLite `data/stocktool.db`)
- Backend deps: `pip install -r backend/requirements.txt`
- Frontend dev: `cd frontend && npm run dev` (port 5173, proxies `/api` + `/reports` → :8000)
- Frontend build: `cd frontend && npm run build` (output: `frontend/dist/`, served by FastAPI in prod)
- Frontend lint: `cd frontend && npm run lint`
- TradingAgents CLI (standalone): `python -m cli.main`
- Redeploy webhook: `GET/POST /api/updatereload` → `git pull` + touch `backend/main.py` (reload) + `npm run build`

## Architecture

Three subsystems in one repo:

**`backend/` — FastAPI app (the product).** `backend/main.py` mounts routers from `backend/api/*` (market, analysis, stocks, datasource, screener, settings, summary, ai_agent, trading_agents), serves `frontend/dist/` at `/` with SPA fallback, exposes `data/reports/` at `/reports`. Startup: `init_db()` (SQLAlchemy + lightweight `ALTER TABLE` migrations in `database.py`), resume pending TradingAgents tasks, start worker, schedule daily 15:30 Asia/Shanghai summary (APScheduler).

**`backend/data_sources/` + `backend/services/` — A-share data + analysis.** `data_sources/factory.py` switches between `akshare` (default) and `tushare` via mutable `active_data_source`. `services/` holds indicators, screener, signals, AI summaries, and the **single-threaded TradingAgents task queue** (`trading_agents_tasks.py` — SQLite `ta_tasks` table backs an in-memory `Queue`; survives restarts via `resume_pending_on_startup()`; renders markdown to `data/reports/trading-agents/`; auto-heals `ModuleNotFoundError` via `importlib.invalidate_caches()`).

**`tradingagents/` — vendored LangGraph multi-agent framework** (upstream: TauricResearch/TradingAgents). `graph/trading_graph.py::TradingAgentsGraph` orchestrates analysts → bull/bear researchers → trader → risk debators. Supports `openai`/`anthropic`/`google` + `akshare`/`yfinance`/`tushare`. Backend wraps it in `services/trading_agents_runner.py`, which merges UI-configured `AppSetting` (provider/key/model/base_url) into `DEFAULT_CONFIG` and `os.environ` before `.propagate(ticker, date)`.

**Frontend** (React 19 + AntD + Zustand + Vite). 6 routes under `AppLayout`: `/` Dashboard, `/stocks`, `/stock/:code`, `/screener`, `/trading-agents` (with `/ai` redirect), `/settings`. All API calls go to `/api/*` (proxied in dev, same-origin in prod).

## Conventions

- **Version watermark (mandatory):** every UI-visible change must bump the gray watermark under "AI 股票分析" in `frontend/src/components/AppLayout.tsx`, format `v.YY.MM.DD_N`.
- **AI settings flow:** provider/keys/models stored via `/api/settings` (not env vars). `trading_agents_runner._build_ta_config` reads via `get_ai_settings_dict()`.
- **`backend/config.py`** uses pydantic-settings with `extra = "ignore"` so `tradingagents`-specific `.env` keys don't break the backend.
- **Gitignored runtime state:** `data/stocktool.db`, `data/reports/*.md`, `.env`, `frontend/dist/`, `frontend/node_modules/` — never commit.
