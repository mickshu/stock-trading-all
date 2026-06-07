"""TradingAgents 异步任务队列与后台 Worker。

- SQLite 存任务元数据（ta_tasks 表）。
- 单线程 worker 串行消费内存 Queue，保证 LLM 调用不并发。
- 报告 Markdown 落盘到 data/reports/trading-agents/{YYYY-MM-DD}_{name}.md，
  通过已挂载的 /reports 静态目录可下载。
"""

from __future__ import annotations

import atexit
import importlib
import logging
import queue
import re
import subprocess
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
from datetime import datetime, timezone
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
_SHUTDOWN = threading.Event()

# 优雅关闭：收到 SIGTERM/SIGINT 后，拒绝新任务入队 + 等待当前任务完成后退出。
_SHUTDOWN_GRACE_SEC = 180  # 给正在跑的 LLM 调用最多 3 分钟收尾

# 整体任务超时（秒）：防止单个任务因多次 LLM 重试无限运行。
# 默认 60 分钟，可在「设置 → AI 配置 → 整体任务超时」调整。
_TASK_HARD_TIMEOUT_DEFAULT_SEC = 60 * 60

# 线程池用于给 run_single 加硬超时
_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ta-run")


def _get_task_timeout_sec() -> int:
    """从 AI 配置读取整体任务超时（秒），未配置则用默认值。"""
    try:
        from backend.api.settings import get_ai_settings_dict
        ai = get_ai_settings_dict()
        val = int(ai.get("ta_task_timeout") or _TASK_HARD_TIMEOUT_DEFAULT_SEC)
        return max(val, 300)  # 下限 5 分钟，防止误设过小
    except Exception:
        return _TASK_HARD_TIMEOUT_DEFAULT_SEC


def _utcnow() -> datetime:
    """返回 naive UTC datetime，替代已弃用的 datetime.utcnow()。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


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
        f"- 生成时间：{(task.finished_at or _utcnow()).isoformat(timespec='seconds')}\n\n"
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
        "provider_override": getattr(t, "provider_override", "") or "",
        "model_override": getattr(t, "model_override", "") or "",
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
    provider_override: str = "",
    model_override: str = "",
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
            provider_override=(provider_override or "").strip(),
            model_override=(model_override or "").strip(),
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
                path = (REPORTS_ROOT / t.report_filename).resolve()
                # 防止路径穿越：确保解析后的绝对路径仍在 REPORTS_ROOT 下
                if not str(path).startswith(str(REPORTS_ROOT.resolve())):
                    logger.warning("refusing to delete file outside reports dir: %s", t.report_filename)
                else:
                    path.unlink(missing_ok=True)
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
    provider_override: str = "",
    model_override: str = "",
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
            ticker=ticker,
            trade_date=trade_date,
            depth=depth,
            online_tools=online_tools,
            provider_override=provider_override,
            model_override=model_override,
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
        t.started_at = _utcnow()
        db.commit()
        ticker = t.ticker
        trade_date = t.trade_date
        depth = t.depth
        online_tools = bool(t.online_tools)
        provider_override = getattr(t, "provider_override", "") or ""
        model_override = getattr(t, "model_override", "") or ""
    finally:
        db.close()

    started = _utcnow()
    error_msg = ""
    result: dict[str, Any] | None = None
    try:
        importlib.invalidate_caches()
        # 用线程池包裹 run_single，加整体任务硬超时，防止多次 LLM 重试
        # 累加后任务无限运行（之前有任务跑了 40+ 分钟仍失败）。
        future = _EXECUTOR.submit(
            run_single,
            ticker=ticker,
            trade_date=trade_date,
            depth=depth,
            online_tools=online_tools,
            provider_override=provider_override,
            model_override=model_override,
        )
        result = future.result(timeout=_get_task_timeout_sec())
    except FuturesTimeoutError:
        timeout_min = _get_task_timeout_sec() // 60
        error_msg = (
            f"任务整体超时（已运行超过 {timeout_min} 分钟），已强制终止。"
            f"建议：① 减少辩论轮数；② 在「设置」里调大单次 LLM 超时或换更快的接入点；"
            f"③ 在「设置」里调大「整体任务超时」。"
        )
        logger.warning("TA task %s exceeded hard timeout", task_id)
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
            provider_override=provider_override,
            model_override=model_override,
        )
    except Exception as e:  # noqa: BLE001
        error_msg = _friendly_error(e)
        logger.exception("TA task %s failed", task_id)

    finished = _utcnow()
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
    while not _SHUTDOWN.is_set():
        try:
            task_id = _QUEUE.get(timeout=2)
        except queue.Empty:
            continue
        if _SHUTDOWN.is_set():
            # 被唤醒后发现正在关闭，把未处理的任务放回队列
            _QUEUE.put(task_id)
            break
        try:
            _process(task_id)
        except Exception:
            logger.exception("TA worker fatal error on %s", task_id)
        finally:
            _QUEUE.task_done()
    logger.info("TA worker thread stopped")


def _ensure_worker() -> None:
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(
            target=_worker_loop, name="ta-worker", daemon=False
        )
        _WORKER_THREAD.start()


def _shutdown_worker() -> None:
    """atexit 回调：通知 worker 停止，等待当前任务收尾。"""
    if not _WORKER_THREAD or not _WORKER_THREAD.is_alive():
        return
    logger.info("TA worker shutting down gracefully (grace=%ss)…", _SHUTDOWN_GRACE_SEC)
    _SHUTDOWN.set()
    _WORKER_THREAD.join(timeout=_SHUTDOWN_GRACE_SEC)
    if _WORKER_THREAD.is_alive():
        logger.warning("TA worker did not exit within grace period; abandoning")


atexit.register(_shutdown_worker)


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
