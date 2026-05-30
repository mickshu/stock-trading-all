from pathlib import Path
import subprocess

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import logging

from backend.database import init_db
from backend.api.market import router as market_router
from backend.api.analysis import router as analysis_router
from backend.api.stocks import router as stocks_router
from backend.api.datasource import router as datasource_router
from backend.api.screener import router as screener_router
from backend.api.settings import router as settings_router
from backend.api.summary import router as summary_router, _generate_and_cache
from backend.api.ai_agent import router as ai_agent_router
from backend.api.trading_agents import router as trading_agents_router

app = FastAPI(title="Stock Analysis Tool", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(market_router)
app.include_router(analysis_router)
app.include_router(stocks_router)
app.include_router(datasource_router)
app.include_router(screener_router)
app.include_router(settings_router)
app.include_router(summary_router)
app.include_router(ai_agent_router)
app.include_router(trading_agents_router)


_scheduler_logger = logging.getLogger("backend.scheduler")


def _safe_daily_summary_job():
    try:
        _generate_and_cache(force=True)
        _scheduler_logger.info("Daily summary generated")
    except Exception:
        _scheduler_logger.exception("Daily summary scheduled job failed")


@app.on_event("startup")
def on_startup():
    init_db()
    try:
        from backend.services import trading_agents_tasks as _ta_tasks
        n = _ta_tasks.resume_pending_on_startup()
        _ta_tasks.start_worker()
        if n:
            _scheduler_logger.info("Resumed %d pending TradingAgents tasks", n)
    except Exception:
        _scheduler_logger.exception("TradingAgents worker startup failed")
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        _scheduler_logger.warning("APScheduler not installed; daily summary auto-generation disabled")
        return
    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    # A 股交易日 15:30 收盘后；周一至周五（节假日不区分，失败容忍）
    scheduler.add_job(
        _safe_daily_summary_job,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=30),
        id="daily_summary",
        replace_existing=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler


@app.get("/api/health")
def health():
    return {"status": "ok"}


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


@app.post("/api/updatereload")
async def update_and_reload():
    """Webhook: git pull + 前端构建。后端因 uvicorn --reload 会自动重启。"""
    results = {}
    try:
        r = subprocess.run(
            ["git", "pull"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True, text=True, timeout=120,
        )
        results["git_pull"] = {"exit_code": r.returncode, "stdout": r.stdout.strip(), "stderr": r.stderr.strip()}
        if r.returncode != 0:
            return {"status": "git_pull_failed", "details": results}
    except Exception as e:
        return {"status": "git_pull_error", "error": str(e)}

    try:
        r = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(_PROJECT_ROOT / "frontend"),
            capture_output=True, text=True, timeout=300,
        )
        results["frontend_build"] = {"exit_code": r.returncode, "stdout": r.stdout.strip()[-500:], "stderr": r.stderr.strip()[-500:]}
    except Exception as e:
        results["frontend_build"] = {"error": str(e)}

    return {"status": "done", "details": results}


# AI 分析报告静态目录：<repo>/data/reports/，浏览器可直接访问 /reports/xxx.md。
# 必须挂在 SPA fallback 之前，否则会被 catch-all 抢路由。
REPORTS_STATIC = Path(__file__).resolve().parent.parent / "data" / "reports"
REPORTS_STATIC.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORTS_STATIC, html=False), name="reports")

# 把 frontend 构建产物挂到根路径，并对所有非 /api 路径回退到 index.html，
# 让 React Router 直接访问 /stock/xxx 等深链接刷新时仍可工作。
FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
INDEX_HTML = FRONTEND_DIST / "index.html"

if FRONTEND_DIST.is_dir():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not Found")

        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)

        if INDEX_HTML.is_file():
            return FileResponse(INDEX_HTML)
        raise HTTPException(status_code=404, detail="Frontend build not found")
