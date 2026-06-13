"""TradingAgents 多智能体框架的 HTTP 接口。

- POST /api/v1/trading-agents/analyze         同步跑（保留，便于脚本/排查）
- GET  /api/v1/trading-agents/health          当前 LLM / 数据源摘要
- POST /api/v1/trading-agents/tasks           异步创建分析任务（推荐前端用）
- GET  /api/v1/trading-agents/tasks           任务列表
- GET  /api/v1/trading-agents/tasks/{id}      任务详情（含 markdown 正文）
- DELETE /api/v1/trading-agents/tasks/{id}    删除任务（同步清理报告文件）
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.api.settings import get_ai_settings_dict
from backend.config import settings as bs
from backend.services.trading_agents_runner import run_single
from backend.services import trading_agents_tasks as ta_tasks

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/trading-agents", tags=["trading-agents"])


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    trade_date: str = Field(default_factory=lambda: date.today().isoformat())
    depth: int = Field(1, ge=1, le=3, description="辩论轮数 1=fast 3=deep")
    online_tools: bool = True


class CreateTaskRequest(AnalyzeRequest):
    stock_name: str = Field("", max_length=120)
    provider_override: str = Field("", max_length=32)
    model_override: str = Field("", max_length=64)
    analysis_tool: str = Field("trading", pattern=r"^(trading|cli)$")


@router.get("/health")
def health():
    ai = get_ai_settings_dict()
    return {
        "provider": ai.get("provider"),
        "deep_think_llm": ai.get("ta_deep_think_llm") or ai.get("openai_model"),
        "quick_think_llm": ai.get("ta_quick_think_llm") or ai.get("openai_model"),
        "backend_url": ai.get("ta_backend_url") or ai.get("openai_base_url"),
        "data_source": bs.active_data_source,
    }


@router.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        return run_single(
            ticker=req.ticker.strip().upper(),
            trade_date=req.trade_date.strip(),
            depth=req.depth,
            online_tools=req.online_tools,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        msg = str(e)
        if "Authentication Fails" in msg or "Incorrect API key" in msg or "invalid_api_key" in msg or "401" in msg[:80]:
            logger.warning("trading-agents auth rejected by upstream LLM: %s", msg[:200])
            raise HTTPException(
                status_code=401,
                detail="上游 LLM 鉴权失败：API Key 无效或已过期。请到「设置 → AI 配置」更新 Key 后重试。",
            )
        logger.exception("trading-agents analyze failed: ticker=%s", req.ticker)
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")


@router.post("/tasks")
def create_task(req: CreateTaskRequest):
    try:
        return ta_tasks.create_task(
            ticker=req.ticker.strip().upper(),
            stock_name=req.stock_name.strip(),
            trade_date=req.trade_date.strip(),
            depth=req.depth,
            online_tools=req.online_tools,
            provider_override=(req.provider_override or "").strip(),
            model_override=(req.model_override or "").strip(),
            analysis_tool=req.analysis_tool,
        )
    except Exception as e:
        logger.exception("create TA task failed")
        raise HTTPException(status_code=500, detail=f"创建任务失败: {e}")


@router.get("/tasks")
def list_tasks(
    limit: int = Query(50, ge=1, le=200),
    status: str | None = Query(None),
    ticker: str | None = Query(None),
):
    return {"items": ta_tasks.list_tasks(limit=limit, status=status, ticker=ticker)}


@router.get("/tasks/{task_id}")
def get_task(task_id: str, with_md: bool = Query(False)):
    data = ta_tasks.get_task(task_id, with_md=with_md)
    if not data:
        raise HTTPException(status_code=404, detail="任务不存在")
    return data


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str):
    ok = ta_tasks.delete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"ok": True}
