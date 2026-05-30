"""AI 分析模块统一接口。

PR-1：scope 仅支持 single；多 scope/收藏/标签/导出留给后续 PR。
工具链沿用 ai_agent.run_agent（本地 CLI：claude/codex/gemini/hermes）。
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.services.ai_agent import (
    DEFAULT_TIMEOUT,
    build_prompt_v2,
    report_filename_v2,
    run_agent,
)
from backend.services.ai_report_store import (
    create_report,
    delete_report,
    get_report,
    list_reports,
    serialize,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai-analysis", tags=["ai-analysis"])


class RunRequest(BaseModel):
    scope: Literal["single", "multi", "sector", "market", "pick"]
    targets: list[dict] = Field(default_factory=list)
    dimensions: list[str] = Field(default_factory=list)
    agent: str = Field(..., description="本地 CLI 名（claude/codex/gemini/hermes）")
    timeout: int = Field(DEFAULT_TIMEOUT, ge=10, le=900)


@router.post("/run")
def run(req: RunRequest, db: Session = Depends(get_db)):
    if not req.targets:
        raise HTTPException(status_code=400, detail="targets 不能为空")

    try:
        prompt = build_prompt_v2(req.scope, req.targets, req.dimensions)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = run_agent(req.agent, prompt, timeout=req.timeout)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("ai-analysis run failed: agent=%s scope=%s", req.agent, req.scope)
        raise HTTPException(status_code=500, detail="AI 调用失败")

    filename = report_filename_v2(req.scope, req.targets)
    try:
        row = create_report(
            db,
            scope=req.scope,
            targets=req.targets,
            dimensions=req.dimensions,
            agent=req.agent,
            prompt=prompt,
            filename=filename,
            run_result=result,
        )
    except Exception:
        logger.exception("ai-analysis persist failed: filename=%s", filename)
        raise HTTPException(status_code=500, detail="入库失败")

    data = serialize(row, with_content=True)
    # 透出执行原始输出/stderr，方便前端首屏直接渲染
    data["output"] = result.get("output") or ""
    data["stderr"] = (result.get("stderr") or "") if not result.get("ok") else ""
    return data


@router.get("/reports")
def reports(
    db: Session = Depends(get_db),
    scope: str | None = None,
    agent: str | None = None,
    starred: bool | None = None,
    q: str | None = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    items, total = list_reports(
        db,
        scope=scope,
        agent=agent,
        starred=starred,
        q=q,
        page=page,
        size=size,
    )
    return {
        "items": [serialize(it) for it in items],
        "total": total,
        "page": page,
        "size": size,
    }


@router.get("/reports/{report_id}")
def report_detail(report_id: int, db: Session = Depends(get_db)):
    row = get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    return serialize(row, with_content=True)


class UpdateRequest(BaseModel):
    starred: bool | None = None
    tags: list[str] | None = None


@router.patch("/reports/{report_id}")
def patch_report(report_id: int, req: UpdateRequest, db: Session = Depends(get_db)):
    row = get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if req.starred is not None:
        row.starred = bool(req.starred)
    if req.tags is not None:
        row.tags = [t.strip() for t in req.tags if t and t.strip()]
    db.commit()
    db.refresh(row)
    return serialize(row)


@router.delete("/reports/{report_id}")
def delete_route(report_id: int, db: Session = Depends(get_db)):
    row = get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    delete_report(db, row)
    return {"ok": True}


@router.post("/reports/{report_id}/rerun")
def rerun_report(report_id: int, db: Session = Depends(get_db)):
    """用原 row 的 scope/targets/dimensions/agent 重新跑一次，落新 row。"""
    row = get_report(db, report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")

    targets = row.targets or []
    dimensions = row.dimensions or []
    try:
        prompt = build_prompt_v2(row.scope, targets, dimensions)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = run_agent(row.agent, prompt, timeout=DEFAULT_TIMEOUT)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("ai-analysis rerun failed: id=%s", report_id)
        raise HTTPException(status_code=500, detail="重跑失败")

    filename = report_filename_v2(row.scope, targets)
    try:
        new_row = create_report(
            db,
            scope=row.scope,
            targets=targets,
            dimensions=dimensions,
            agent=row.agent,
            prompt=prompt,
            filename=filename,
            run_result=result,
        )
    except Exception:
        logger.exception("ai-analysis rerun persist failed")
        raise HTTPException(status_code=500, detail="入库失败")

    data = serialize(new_row, with_content=True)
    data["output"] = result.get("output") or ""
    data["stderr"] = (result.get("stderr") or "") if not result.get("ok") else ""
    return data
