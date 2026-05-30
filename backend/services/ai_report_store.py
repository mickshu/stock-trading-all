"""AIReport 仓库层：DB 入库 + markdown 落盘 + 查询/序列化。

API 路由只与本模块打交道，避免直接操作 ORM/文件。
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.models.ai_report import AIReport
from backend.services.ai_agent import REPORT_URL_PREFIX, REPORTS_DIR

logger = logging.getLogger(__name__)


def _label_targets(scope: str, targets: list[dict]) -> str:
    """生成对象的人类可读标签，用于列表展示与 markdown 头部。"""
    if not targets:
        return "—"
    if scope == "market":
        names = [t.get("name") or t.get("index") for t in targets if (t.get("name") or t.get("index"))]
        return "、".join([n for n in names if n]) if names else "大盘"
    if scope == "sector":
        names = [t.get("sector") or t.get("name") for t in targets if (t.get("sector") or t.get("name"))]
        return "、".join([n for n in names if n]) if names else "—"
    out = []
    for t in targets:
        code = (t.get("code") or "").strip()
        name = (t.get("name") or "").strip()
        if name and code:
            out.append(f"{code} {name}")
        else:
            out.append(name or code or "—")
    return "、".join(out)


def _write_markdown(filename: str, header_meta: dict, content: str) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / filename
    title = header_meta.pop("title", filename)
    lines = [f"# {title}", ""]
    for k, v in header_meta.items():
        lines.append(f"- {k}：{v}")
    lines += ["", "---", ""]
    path.write_text("\n".join(lines) + (content or ""), encoding="utf-8")
    return path


def _empty_output_placeholder(agent: str, run_result: dict) -> str:
    """Agent 实际输出为空时，把 stderr / 退出码 / 耗时整成一段诊断 markdown，
    避免详情页只剩头部、正文一片空白让用户无从排查。"""
    stderr = (run_result.get("stderr") or "").strip()
    exit_code = run_result.get("exit_code")
    duration = run_result.get("duration") or 0.0
    ok = bool(run_result.get("ok"))
    lines = [
        "> ⚠️ 本次分析未产生正文输出。以下为运行诊断信息：",
        "",
        f"- 工具：`{agent}`",
        f"- 退出码：`{exit_code if exit_code is not None else '—'}`（{'成功' if ok else '失败/异常'}）",
        f"- 耗时：{duration:.1f}s",
    ]
    if stderr:
        lines += [
            "",
            "**stderr（截断 2000 字符）：**",
            "",
            "```text",
            stderr[-2000:],
            "```",
        ]
    else:
        lines += [
            "",
            "stderr 也为空。常见原因：CLI 把响应输出到了交互式 TUI、被超时打断、或需要登录授权。",
            "可尝试在终端手动执行同一命令复现，或更换 agent 重新生成。",
        ]
    return "\n".join(lines) + "\n"


def create_report(
    db: Session,
    *,
    scope: str,
    targets: list[dict],
    dimensions: list[str],
    agent: str,
    prompt: str,
    filename: str,
    run_result: dict,
) -> AIReport:
    """落盘 markdown + DB 入库。filename 由调用方保证唯一（已带时间戳）。"""
    output = (run_result.get("output") or "").strip()
    body = output or _empty_output_placeholder(agent, run_result)
    target_label = _label_targets(scope, targets)
    dim_text = "、".join(dimensions) if dimensions else "综合"
    header = {
        "title": f"{target_label} · {dim_text}",
        "范围": scope,
        "对象": target_label,
        "维度": dim_text,
        "生成工具": agent,
        "生成时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _write_markdown(filename, header, body)

    row = AIReport(
        scope=scope,
        targets=targets,
        dimensions=dimensions,
        agent=agent,
        prompt=prompt,
        filename=filename,
        output_chars=len(output),
        duration=float(run_result.get("duration") or 0.0),
        exit_code=run_result.get("exit_code"),
        ok=bool(run_result.get("ok")),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_reports(
    db: Session,
    *,
    scope: str | None = None,
    agent: str | None = None,
    starred: bool | None = None,
    q: str | None = None,
    page: int = 1,
    size: int = 20,
) -> tuple[list[AIReport], int]:
    qy = db.query(AIReport)
    if scope:
        qy = qy.filter(AIReport.scope == scope)
    if agent:
        qy = qy.filter(AIReport.agent == agent)
    if starred is not None:
        qy = qy.filter(AIReport.starred == bool(starred))
    if q:
        like = f"%{q}%"
        qy = qy.filter(AIReport.filename.ilike(like))
    total = qy.count()
    items = (
        qy.order_by(desc(AIReport.created_at))
        .offset((max(page, 1) - 1) * size)
        .limit(size)
        .all()
    )
    return items, total


def get_report(db: Session, report_id: int) -> AIReport | None:
    return db.query(AIReport).filter(AIReport.id == report_id).first()


def delete_report(db: Session, row: AIReport) -> None:
    """删 DB 记录 + 物理 md 文件。"""
    filename = row.filename
    db.delete(row)
    db.commit()
    if filename:
        path = REPORTS_DIR / filename
        if path.is_file():
            try:
                path.unlink()
            except Exception:
                logger.warning("delete file failed: %s", filename)


def read_markdown(filename: str) -> str | None:
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = REPORTS_DIR / filename
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


def serialize(row: AIReport, *, with_content: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": row.id,
        "scope": row.scope,
        "targets": row.targets or [],
        "target_label": _label_targets(row.scope, row.targets or []),
        "dimensions": row.dimensions or [],
        "agent": row.agent,
        "filename": row.filename,
        "url": f"{REPORT_URL_PREFIX}/{row.filename}",
        "output_chars": row.output_chars or 0,
        "duration": row.duration or 0.0,
        "exit_code": row.exit_code,
        "ok": bool(row.ok),
        "starred": bool(row.starred),
        "tags": row.tags or [],
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
    if with_content:
        data["content"] = read_markdown(row.filename) or ""
        data["prompt"] = row.prompt
    return data
