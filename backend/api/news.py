"""自选股相关重要资讯路由。

GET  /api/v1/news/watchlist?time_range=today&limit=50
  可选 codes 查询参数（逗号分隔）覆盖默认「整库自选股」。
POST /api/v1/news/ai-digest
  基于「设置 → 资讯」中的 prompt（可被 body.prompt 覆盖）+ AI 配置，
  让 LLM 联网生成 markdown 资讯简报。
"""
from __future__ import annotations

from datetime import timezone, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.api.settings import (
    DEFAULT_NEWS_PROMPT,
    NEWS_AVAILABLE_SOURCES,
    NEWS_DEFAULT_SOURCES,
    get_ai_settings_dict,
)
from backend.database import get_db
from backend.models.models import Watchlist
from backend.services.ai_summary import generate_news_digest
from backend.services.news_aggregator import (
    fetch_news_cached,
    refresh_cache_now,
)

_CST = timezone(timedelta(hours=8))

router = APIRouter(prefix="/api/v1/news", tags=["news"])

ALLOWED_RANGES = {"today", "week", "all"}


def _resolve_codes(db: Session, codes_param: str | None) -> dict[str, str]:
    """codes 参数优先，否则取整库自选股。"""
    rows = db.execute(select(Watchlist)).scalars().all()
    full_map = {w.code: w.name or "" for w in rows if w.code}
    if not codes_param:
        return full_map
    wanted = {c.strip() for c in codes_param.split(",") if c.strip()}
    if not wanted:
        return full_map
    return {c: full_map.get(c, "") for c in wanted if c}


def _enabled_sources_from_settings() -> list[str]:
    cfg = get_ai_settings_dict()
    raw = cfg.get("news_sources")
    if not isinstance(raw, list) or not raw:
        return list(NEWS_DEFAULT_SOURCES)
    valid = [s for s in raw if s in NEWS_AVAILABLE_SOURCES]
    return valid or list(NEWS_DEFAULT_SOURCES)


@router.get("/watchlist")
def list_watchlist_news(
    background_tasks: BackgroundTasks,
    time_range: str = Query("today", description="today | week | all"),
    codes: str | None = Query(None, description="逗号分隔股票代码，缺省 = 全部自选股"),
    limit: int = Query(50, ge=1, le=200),
):
    if time_range not in ALLOWED_RANGES:
        time_range = "today"

    db: Session = next(get_db())
    try:
        code_to_name = _resolve_codes(db, codes)
    finally:
        db.close()

    enabled_sources = _enabled_sources_from_settings()
    items, refreshed_at, stale = fetch_news_cached(
        code_to_name,
        time_range=time_range,
        limit=limit,
        enabled_sources=enabled_sources,
    )
    # stale → 立即返回旧 payload，并在后台异步刷新；前端轮询拿到 stale=false 即可
    if stale:
        background_tasks.add_task(
            refresh_cache_now, code_to_name, time_range, enabled_sources,
        )
    return {
        "time_range": time_range,
        "codes": list(code_to_name.keys()),
        "sources": enabled_sources,
        "count": len(items),
        "items": items,
        "stale": stale,
        "refreshed_at": (
            refreshed_at.replace(tzinfo=timezone.utc).astimezone(_CST).isoformat()
            if refreshed_at else None
        ),
    }


class AiDigestIn(BaseModel):
    codes: list[str] | None = None
    # 一次性自定义 prompt；缺省 = 使用 settings.news_prompt
    prompt: str | None = None


@router.post("/ai-digest")
def ai_digest(payload: AiDigestIn):
    db: Session = next(get_db())
    try:
        codes_param = ",".join(payload.codes) if payload.codes else None
        code_to_name = _resolve_codes(db, codes_param)
    finally:
        db.close()
    if not code_to_name:
        raise HTTPException(status_code=400, detail="自选股清单为空")
    settings = get_ai_settings_dict()
    prompt = (payload.prompt or "").strip() or (
        settings.get("news_prompt") or DEFAULT_NEWS_PROMPT
    )
    try:
        result = generate_news_digest(code_to_name, prompt=prompt, settings=settings)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # 第三方 SDK 异常 → 500
        raise HTTPException(status_code=500, detail=f"AI 资讯检索失败：{e}")
    return {
        "codes": list(code_to_name.keys()),
        "prompt": prompt,
        **result,
    }
