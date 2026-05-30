"""TradingAgents 多智能体框架的 HTTP 接口。

POST /api/v1/trading-agents/analyze 同步跑单股分析；
GET  /api/v1/trading-agents/health  返回当前生效的 LLM 与数据源摘要。
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.settings import get_ai_settings_dict
from backend.config import settings as bs
from backend.services.trading_agents_runner import run_single

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/trading-agents", tags=["trading-agents"])


class AnalyzeRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=10)
    trade_date: str = Field(default_factory=lambda: date.today().isoformat())
    depth: int = Field(1, ge=1, le=3, description="辩论轮数 1=fast 3=deep")
    online_tools: bool = True


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
        logger.exception("trading-agents analyze failed: ticker=%s", req.ticker)
        raise HTTPException(status_code=500, detail=f"分析失败: {e}")
