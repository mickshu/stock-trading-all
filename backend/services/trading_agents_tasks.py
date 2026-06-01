"""TradingAgents 异步任务队列与后台 Worker。

- SQLite 存任务元数据（ta_tasks 表）。
- 单线程 worker 串行消费内存 Queue，保证 LLM 调用不并发。
- 报告 Markdown 落盘到 data/reports/trading-agents/{YYYY-MM-DD}_{name}.md，
  通过已挂载的 /reports 静态目录可下载。
"""

from __future__ import annotations

import logging
import queue
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from backend.database import SessionLocal
from backend.models.ta_task import TATask
from backend.services.trading_agents_runner import run_single

logger = logging.getLogger(__name__)

REPORTS_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "reports"
TA_REPORTS_SUBDIR = "trading-agents"

_QUEUE: "queue.Queue[str]" = queue.Queue()
_WORKER_THREAD: threading.Thread | None = None
_WORKER_LOCK = threading.Lock()


_SAFE_NAME_RE = re.compile(r"[\\/:*?\"<>|\s]+")


def _safe_filename(s: str) -> str:
    s = _SAFE_NAME_RE.sub("_", (s or "").strip())
    return s[:64] or "stock"


def _decision_label(raw: str) -> str:
    u = (raw or "").upper()
    if "BUY" in u:
        return "BUY"
    if "SELL" in u:
        return "SELL"
    if "HOLD" in u:
        return "HOLD"
    return ""


def _render_markdown(result: dict[str, Any], task: TATask) -> str:
    name = task.stock_name or task.ticker
    head = (
        f"# TradingAgents 分析报告 — {name} ({task.ticker})\n\n"
        f"- 分析日期：{task.trade_date}\n"
        f"- 辩论轮数：{task.depth}\n"
        f"- 在线数据：{'是' if task.online_tools else '否'}\n"
        f"- 生成时间：{(task.finished_at or datetime.utcnow()).isoformat(timespec='seconds')}\n\n"
    )
    decision = result.get("decision", "")
    reports = result.get("reports", {}) or {}
    debate = result.get("debate", {}) or {}
    risk = result.get("risk", {}) or {}

    parts = [head, "## 最终决策\n\n", str(decision), "\n\n"]
    if reports.get("market"):
        parts += ["## 市场分析\n\n", reports["market"], "\n\n"]
    if reports.get("sentiment"):
        parts += ["## 舆情分析\n\n", reports["sentiment"], "\n\n"]
    if reports.get("news"):
        parts += ["## 新闻分析\n\n", reports["news"], "\n\n"]
    if reports.get("fundamentals"):
        parts += ["## 基本面分析\n\n", reports["fundamentals"], "\n\n"]
    if debate.get("judge_decision"):
        parts += ["## 多空辩论裁定\n\n", debate["judge_decision"], "\n\n"]
    if risk.get("current_response"):
        parts += ["## 风险评估\n\n", risk["current_response"], "\n\n"]
    return "".join(parts)


def _write_report(md: str, task: TATask) -> str:
    out_dir = REPORTS_ROOT / TA_REPORTS_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{task.trade_date}_{_safe_filename(task.stock_name or task.ticker)}"
    filename = f"{base}.md"
    path = out_dir / filename
    if path.exists():
        filename = f"{base}-{task.id[:6]}.md"
        path = out_dir / filename
    path.write_text(md, encoding="utf-8")
    return f"{TA_REPORTS_SUBDIR}/{filename}"


def _task_to_dict(t: TATask) -> dict[str, Any]:
    return {
        "id": t.id,
        "ticker": t.ticker,
        "stock_name": t.stock_name or "",
        "trade_date": t.trade_date,
        "depth": t.depth,
        "online_tools": bool(t.online_tools),
        "status": t.status,
        "decision": t.decision or "",
        "decision_raw": t.decision_raw or "",
        "report_filename": t.report_filename or "",
        "report_url": f"/reports/{t.report_filename}" if t.report_filename else "",
        "error": t.error or "",
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "started_at": t.started_at.isoformat() if t.started_at else None,
        "finished_at": t.finished_at.isoformat() if t.finished_at else None,
        "duration_sec": t.duration_sec,
    }


def create_task(
    *,
    ticker: str,
    stock_name: str,
    trade_date: str,
    depth: int,
    online_tools: bool,
) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    db = SessionLocal()
    try:
        t = TATask(
            id=task_id,
            ticker=ticker,
            stock_name=stock_name or "",
            trade_date=trade_date,
            depth=depth,
            online_tools=online_tools,
            status="pending",
        )
        db.add(t)
        db.commit()
        db.refresh(t)
        data = _task_to_dict(t)
    finally:
        db.close()
    _QUEUE.put(task_id)
    _ensure_worker()
    return data


def list_tasks(limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    db = SessionLocal()
    try:
        q = db.query(TATask).order_by(TATask.created_at.desc())
        if status:
            q = q.filter(TATask.status == status)
        rows: Iterable[TATask] = q.limit(min(max(limit, 1), 200)).all()
        return [_task_to_dict(r) for r in rows]
    finally:
        db.close()


def get_task(task_id: str, *, with_md: bool = False) -> dict[str, Any] | None:
    db = SessionLocal()
    try:
        t = db.query(TATask).filter(TATask.id == task_id).first()
        if not t:
            return None
        data = _task_to_dict(t)
        if with_md:
            data["report_md"] = t.report_md or ""
        return data
    finally:
        db.close()


def delete_task(task_id: str) -> bool:
    db = SessionLocal()
    try:
        t = db.query(TATask).filter(TATask.id == task_id).first()
        if not t:
            return False
        if t.report_filename:
            try:
                (REPORTS_ROOT / t.report_filename).unlink(missing_ok=True)
            except Exception:
                logger.warning("delete report file failed: %s", t.report_filename)
        db.delete(t)
        db.commit()
        return True
    finally:
        db.close()


def _process(task_id: str) -> None:
    db = SessionLocal()
    try:
        t = db.query(TATask).filter(TATask.id == task_id).first()
        if not t:
            return
        t.status = "running"
        t.started_at = datetime.utcnow()
        db.commit()
        ticker = t.ticker
        trade_date = t.trade_date
        depth = t.depth
        online_tools = bool(t.online_tools)
    finally:
        db.close()

    started = datetime.utcnow()
    error_msg = ""
    result: dict[str, Any] | None = None
    try:
        # 一次性刷新 import 缓存。如果上次 redeploy 刚装好依赖却没重启 uvicorn，
        # 这一步能让本进程立即看到新装的 langchain_openai / langgraph 等包，
        # 避免「明明 pip 装好了 worker 仍然 ModuleNotFoundError」。
        import importlib as _il
        _il.invalidate_caches()
        result = run_single(
            ticker=ticker, trade_date=trade_date, depth=depth, online_tools=online_tools
        )
    except ModuleNotFoundError as e:
        error_msg = (
            f"缺少依赖：{e.name}。请到部署机执行 `pip install -r backend/requirements.txt` "
            f"或调用 POST /api/updatereload 后重启后端。原始错误：{e}"
        )
        logger.exception("TA task %s failed: missing dep %s", task_id, e.name)
    except Exception as e:  # noqa: BLE001
        error_msg = str(e)
        logger.exception("TA task %s failed", task_id)

    finished = datetime.utcnow()
    duration = (finished - started).total_seconds()

    db = SessionLocal()
    try:
        t = db.query(TATask).filter(TATask.id == task_id).first()
        if not t:
            return
        t.finished_at = finished
        t.duration_sec = duration
        if error_msg or result is None:
            t.status = "failed"
            t.error = error_msg or "未知错误"
        else:
            t.status = "success"
            t.decision_raw = str(result.get("decision") or "")
            t.decision = _decision_label(t.decision_raw)
            md = _render_markdown(result, t)
            t.report_md = md
            try:
                t.report_filename = _write_report(md, t)
            except Exception:
                logger.exception("write report failed for %s", task_id)
        db.commit()
    finally:
        db.close()


def _worker_loop() -> None:
    logger.info("TA worker thread started")
    while True:
        task_id = _QUEUE.get()
        try:
            _process(task_id)
        except Exception:
            logger.exception("TA worker fatal error on %s", task_id)
        finally:
            _QUEUE.task_done()


def _ensure_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop, name="ta-worker", daemon=True
        )
        _WORKER_THREAD.start()


def resume_pending_on_startup() -> int:
    """启动时把残留的 pending/running 任务重新入队（running 视为崩溃后未完成）。"""
    db = SessionLocal()
    try:
        rows = (
            db.query(TATask)
            .filter(TATask.status.in_(["pending", "running"]))
            .order_by(TATask.created_at.asc())
            .all()
        )
        ids: list[str] = []
        for r in rows:
            if r.status == "running":
                r.status = "pending"
                r.started_at = None
            ids.append(r.id)
        db.commit()
    finally:
        db.close()
    for i in ids:
        _QUEUE.put(i)
    if ids:
        _ensure_worker()
    return len(ids)


def start_worker() -> None:
    _ensure_worker()
