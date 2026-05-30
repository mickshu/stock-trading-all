"""本地 AI Agent CLI 接口：探测可用 CLI + 触发分析。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.ai_agent import (
    DEFAULT_TIMEOUT,
    build_prompt,
    detect_agents,
    list_reports,
    read_report,
    run_agent,
    save_report,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/ai-agent", tags=["ai-agent"])


class AnalyzeRequest(BaseModel):
    agent: str = Field(..., description="CLI 名称，必须在 probe 返回列表里")
    code: str = Field(..., description="股票代码")
    name: str | None = Field(None, description="股票名称（可选）")
    dimension: str = Field("综合", description="用户填写的分析维度")
    timeout: int = Field(DEFAULT_TIMEOUT, ge=10, le=600)


@router.get("/probe")
def probe():
    return {"agents": detect_agents()}


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    prompt = build_prompt(req.code, req.name or "", req.dimension)
    try:
        result = run_agent(req.agent, prompt, timeout=req.timeout)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("ai-agent analyze failed: agent=%s code=%s", req.agent, req.code)
        raise HTTPException(status_code=500, detail="AI Agent 调用失败")

    report: dict | None = None
    if result["ok"] and (result.get("output") or "").strip():
        try:
            report = save_report(
                req.code,
                req.name,
                req.dimension,
                result["agent"],
                result["output"],
            )
        except Exception:
            logger.exception("ai-agent save report failed: code=%s", req.code)

    return {
        "agent": result["agent"],
        "ok": result["ok"],
        "exit_code": result["exit_code"],
        "duration": round(result["duration"], 2),
        "output": result["output"],
        "stderr": result["stderr"] if not result["ok"] else "",
        "prompt": prompt,
        "report_filename": report["filename"] if report else None,
        "report_url": report["url"] if report else None,
    }


@router.get("/reports")
def reports(name: str | None = None):
    """历史报告列表；可选 ?name= 过滤公司名。"""
    return {"items": list_reports(name)}


@router.get("/reports/{filename}")
def report_content(filename: str):
    """读取报告 markdown 原文（前端可直接渲染）。"""
    text = read_report(filename)
    if text is None:
        raise HTTPException(status_code=404, detail="report not found")
    return {"filename": filename, "content": text}
