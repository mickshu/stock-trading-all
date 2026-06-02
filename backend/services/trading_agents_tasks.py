"""TradingAgents 异步任务队列与后台 Worker。

- SQLite 存任务元数据（ta_tasks 表）。
- 单线程 worker 串行消费内存 Queue，保证 LLM 调用不并发。
- 报告 Markdown 落盘到 data/reports/trading-agents/{YYYY-MM-DD}_{name}.md，
  通过已挂载的 /reports 静态目录可下载。
"""

from __future__ import annotations

import importlib
import logging
import queue
import re
import subprocess
import sys
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


_TIMEOUT_HINTS = (
    "read operation timed out",
    "readtimeout",
    "connecttimeout",
    "timed out",
    "request timed out",
    "apitimeout",
)


def _friendly_error(e: BaseException) -> str:
    """把底层 socket/httpx 报文翻译成给前端看的中文提示。"""
    raw = str(e) or e.__class__.__name__
    low = raw.lower()
    if any(h in low for h in _TIMEOUT_HINTS):
        return (
            f"调用 LLM 超时（已自动重试仍失败）。建议：① 稍后重试；"
            f"② 在「设置」里把「多智能体」段落的 base_url 切到响应更稳定的接入点；"
            f"③ 把 ta_request_timeout 调大。原始错误：{raw}"
        )
    return raw


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


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
# 半成品模块清理范围。worker 自愈时把这些命名空间从 sys.modules 里整体掀掉，
# 让重试那次走全新的 import 栈。
_PURGE_PREFIXES = ("tradingagents", "langchain_openai", "langchain_anthropic",
                   "langchain_google_genai", "langchain_experimental", "langgraph")


def _purge_modules(missing: str) -> None:
    targets = set(_PURGE_PREFIXES)
    if missing:
        targets.add(missing)
    for name in list(sys.modules):
        if any(name == p or name.startswith(p + ".") for p in targets):
            sys.modules.pop(name, None)


def _retry_after_install(
    *,
    ticker: str,
    trade_date: str,
    depth: int,
    online_tools: bool,
    original_error: ModuleNotFoundError,
) -> tuple[dict[str, Any] | None, str]:
    """ModuleNotFoundError 自愈：pip install + 清缓存 + 重试一次。"""
    pip_tail = ""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-r", "backend/requirements.txt"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True, text=True, timeout=600,
        )
        pip_tail = (proc.stderr or proc.stdout or "").strip()[-300:]
        if proc.returncode != 0:
            logger.error("self-heal pip install failed: %s", pip_tail)
            return None, (
                f"缺少依赖：{original_error.name}，自动 pip install 也失败了，"
                f"请到部署机手动执行 `pip install -r backend/requirements.txt`。"
                f"pip 输出尾部：{pip_tail}"
            )
    except Exception as pip_err:  # noqa: BLE001
        logger.exception("self-heal pip install raised")
        return None, (
            f"缺少依赖：{original_error.name}，调用 pip 时异常：{pip_err}。"
            f"请到部署机手动执行 `pip install -r backend/requirements.txt`。"
        )

    importlib.invalidate_caches()
    _purge_modules(original_error.name or "")

    try:
        result = run_single(
            ticker=ticker, trade_date=trade_date, depth=depth, online_tools=online_tools
        )
        logger.info("TA task self-healed after installing %s", original_error.name)
        return result, ""
    except ModuleNotFoundError as e2:
        logger.exception("self-heal retry still missing %s", e2.name)
        return None, (
            f"缺少依赖：{e2.name}，自动 pip install 已执行但仍无法 import。"
            f"请检查部署机的 Python 解释器与 uvicorn 是否同一 venv。"
            f"pip 输出尾部：{pip_tail}"
        )
    except Exception as e2:  # noqa: BLE001
        logger.exception("self-heal retry failed with non-ModuleNotFoundError")
        return None, str(e2)


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
        importlib.invalidate_caches()
        result = run_single(
            ticker=ticker, trade_date=trade_date, depth=depth, online_tools=online_tools
        )
    except ModuleNotFoundError as e:
        # 长跑的 uvicorn worker 上一次 import langchain_openai 失败后，sys.modules
        # 里残留了 tradingagents.* 的半成品模块。即便 redeploy 期间已经 pip install
        # 过依赖，本进程内的下一次 from tradingagents.graph.trading_graph import ...
        # 仍然会顺着旧的导入栈再次抛 ModuleNotFoundError。
        # 这里 worker 自愈一次：自动 pip install + 清掉污染过的 sys.modules + 重试。
        logger.warning("TA task %s missing dep %s; self-healing", task_id, e.name)
        result, error_msg = _retry_after_install(
            ticker=ticker,
            trade_date=trade_date,
            depth=depth,
            online_tools=online_tools,
            original_error=e,
        )
    except Exception as e:  # noqa: BLE001
        error_msg = _friendly_error(e)
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
