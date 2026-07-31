"""资金流 + 当日 AI 收盘总结 router。"""
from __future__ import annotations

import json
import logging
from datetime import date
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy.orm import Session

from backend.api.settings import get_ai_settings_dict
from backend.data_sources.factory import get_data_source
from backend.database import get_db
from backend.models.models import DailySummary
from backend.services.ai_summary import generate_daily_summary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/summary", tags=["summary"])


@router.get("/fund-flow/stocks")
def fund_flow_stocks(n: int = Query(10, ge=1, le=50)):
    ds = get_data_source()
    return ds.get_fund_flow_top(n)


@router.get("/fund-flow/sectors")
def fund_flow_sectors(n: int = Query(5, ge=1, le=30)):
    ds = get_data_source()
    return ds.get_sector_fund_flow_top(n)


def _generate_and_cache(force: bool = False) -> dict[str, Any]:
    today = date.today()
    db: Session = next(get_db())
    try:
        if not force:
            row = db.get(DailySummary, today)
            if row is not None and row.payload:
                try:
                    return json.loads(row.payload)
                except Exception:
                    pass
        settings = get_ai_settings_dict()
        provider = settings.get("provider") or "hermes"
        from backend.services.ai_summary import LOCAL_AGENT_NAMES
        if provider in LOCAL_AGENT_NAMES:
            from backend.services.ai_agent import (
                get_agent as _get_agent,
                _resolve_binary as _which,
            )
            spec = _get_agent(provider)
            if spec is None or not _which(spec):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"未检测到本地 {provider} CLI，请安装后再生成；"
                        f"或在设置 → AI 配置切换 provider"
                    ),
                )
        else:
            key_field = "openai_api_key" if provider == "openai" else "anthropic_api_key"
            if not (settings.get(key_field) or "").strip():
                raise HTTPException(status_code=400, detail=f"未配置 AI（{provider}）API Key，请前往设置 → AI 配置")
        ds = get_data_source()
        indices = ds.get_index_data()
        stock_flow = ds.get_fund_flow_top(10)
        sector_flow = ds.get_sector_fund_flow_top(5)
        try:
            payload = generate_daily_summary(indices, stock_flow, sector_flow, settings)
        except HTTPException:
            raise
        except Exception as e:
            logger.exception("generate_daily_summary failed")
            raise HTTPException(status_code=502, detail=f"AI 生成失败：{e}") from e
        row = db.get(DailySummary, today)
        text = json.dumps(payload, ensure_ascii=False)
        if row is None:
            db.add(DailySummary(trade_date=today, payload=text, model=payload.get("model")))
        else:
            row.payload = text
            row.model = payload.get("model")
        db.commit()
        return payload
    finally:
        db.close()


@router.get("/daily")
def get_daily(force: bool = Query(False)):
    return _generate_and_cache(force=force)


@router.post("/daily/refresh")
def refresh_daily():
    return _generate_and_cache(force=True)


@router.get("/opportunities")
def get_opportunities():
    """获取最近一次「关注机会」扫描结果。"""
    from backend.services.opportunity_scanner import get_latest_opportunities
    result = get_latest_opportunities()
    if result is None:
        return {"date": None, "candidates": [], "ai_evaluation": "", "generated_at": None}
    return result


@router.post("/opportunities/scan")
def trigger_opportunity_scan():
    """手动触发一次机会扫描。"""
    from backend.services.opportunity_scanner import run_opportunity_scan
    return run_opportunity_scan()
