"""AI 配置等通用设置 kv 读写。

设计：单条 AppSetting 行 key="ai_config"，value 为 JSON 字符串。
返回给前端时把 *_api_key 脱敏为 "****abcd"（仅显示末 4 位）；
写入时若收到的 *_api_key 为 "" 或脱敏占位符，则保留原值（避免误清空）。
"""
from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.models import AppSetting
from backend.services.ai_agent import AGENTS, detect_agents
from backend.services.ai_summary import DEFAULT_HERMES_PROMPT, probe_llm, probe_tavily
from backend.services.news_aggregator import (
    AVAILABLE_SOURCES as NEWS_AVAILABLE_SOURCES,
    DEFAULT_ENABLED_SOURCES as NEWS_DEFAULT_SOURCES,
)

# 自选股「重要资讯」AI 检索默认提示词。可在「设置 → 资讯」中改写并保存。
DEFAULT_NEWS_PROMPT = (
    "你是 A 股自选股资讯助理。下方「自选股清单」给出当前关注的代码与名称。\n"
    "请：\n"
    "1. 主动联网检索过去 24 小时内与这些股票/行业相关的政策、公告、行业要闻；\n"
    "2. 用 markdown 输出一份「自选股重要资讯简报」，分三段：\n"
    "   ① 公司/个股关键事件  ② 行业/政策事件  ③ 大盘/资金面要点；\n"
    "3. 每条要点 1-2 句，并以 markdown 链接 [标题](URL) 注明出处；总长度 ≤ 800 字；\n"
    "4. 仅整理消息并简评，不要给出具体买卖建议。"
)

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

AI_KEY = "ai_config"
SECRET_FIELDS = ("openai_api_key", "anthropic_api_key", "tavily_api_key")

# 本地 Agent CLI 名称（与 services.ai_agent.AGENTS 保持一致）。
LOCAL_AGENT_PROVIDERS = tuple(spec.name for spec in AGENTS)
# 原生 API 入口。
NATIVE_PROVIDERS = ("openai", "anthropic")
VALID_PROVIDERS = NATIVE_PROVIDERS + LOCAL_AGENT_PROVIDERS
DEFAULT_AI: dict[str, Any] = {
    "provider": "hermes",
    "openai_base_url": "https://api.openai.com/v1",
    "openai_api_key": "",
    "openai_model": "gpt-4o-mini",
    "anthropic_api_key": "",
    "anthropic_model": "claude-sonnet-4-6",
    "search_provider": "none",
    "tavily_api_key": "",
    "daily_summary_prompt": DEFAULT_HERMES_PROMPT,
    # === 自选股「重要资讯」AI 检索配置 ===
    "news_prompt": DEFAULT_NEWS_PROMPT,
    "news_sources": list(NEWS_DEFAULT_SOURCES),
    # === TradingAgents (LangGraph 多智能体) ===
    "ta_deep_think_llm": "deepseek-v4-pro",
    "ta_quick_think_llm": "deepseek-v4-pro",
    "ta_backend_url": "https://api.deepseek.com/v1",
    "ta_max_debate_rounds": 1,
}


def _load_raw() -> dict[str, Any]:
    db: Session = next(get_db())
    try:
        row = db.get(AppSetting, AI_KEY)
        if row is None or not row.value:
            return dict(DEFAULT_AI)
        try:
            cfg = json.loads(row.value)
        except Exception:
            cfg = {}
        merged = dict(DEFAULT_AI)
        merged.update({k: v for k, v in cfg.items() if v is not None})
        return merged
    finally:
        db.close()


def _mask(secret: str) -> str:
    if not secret:
        return ""
    if len(secret) <= 4:
        return "****"
    return "****" + secret[-4:]


def get_ai_settings_dict() -> dict[str, Any]:
    """供 summary router / scheduler 使用：返回明文 dict（含 api_key 原值）。"""
    return _load_raw()


class AiSettingsIn(BaseModel):
    provider: str
    openai_base_url: str | None = None
    openai_api_key: str | None = None
    openai_model: str | None = None
    anthropic_api_key: str | None = None
    anthropic_model: str | None = None
    search_provider: str | None = None
    tavily_api_key: str | None = None
    daily_summary_prompt: str | None = None
    ta_deep_think_llm: str | None = None
    ta_quick_think_llm: str | None = None
    ta_backend_url: str | None = None
    ta_max_debate_rounds: int | None = None
    ta_request_timeout: int | None = None
    ta_max_retries: int | None = None


@router.get("/ai")
def get_ai_settings():
    cfg = _load_raw()
    out = dict(cfg)
    for k in SECRET_FIELDS:
        out[k] = _mask(cfg.get(k) or "")
    return out


def _merge_for_test(payload: "AiSettingsIn") -> dict[str, Any]:
    """合并表单值与已存明文配置：占位符/空字符串保留原值。用于测试不强制写库。"""
    current = _load_raw()
    incoming = payload.model_dump(exclude_none=True)
    for k in SECRET_FIELDS:
        v = incoming.get(k)
        if v is None:
            continue
        if v == "" or v.startswith("****"):
            incoming.pop(k)
    current.update(incoming)
    return current


class AiTestIn(AiSettingsIn):
    pass


@router.post("/ai/test")
def test_ai_settings(payload: AiTestIn):
    """对当前表单（合并已存密钥）发起最小调用，验证 LLM / Tavily 联通。

    provider 命中本地 Agent CLI 时不发 HTTP，仅核对该 CLI 是否已安装。
    """
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"provider must be one of {VALID_PROVIDERS}")
    if payload.provider in LOCAL_AGENT_PROVIDERS:
        detected = {a["name"]: a for a in detect_agents()}
        info = detected.get(payload.provider)
        if info:
            return {
                "llm": {
                    "ok": True,
                    "provider": payload.provider,
                    "model": info.get("version") or info.get("path") or payload.provider,
                },
                "search": None,
            }
        return {
            "llm": {
                "ok": False,
                "error": (
                    f"未检测到本地 CLI：{payload.provider}。"
                    f"已检测到：{', '.join(detected.keys()) or '无'}"
                ),
            },
            "search": None,
        }
    cfg = _merge_for_test(payload)
    out: dict[str, Any] = {"llm": None, "search": None}
    try:
        out["llm"] = probe_llm(cfg)
    except Exception as e:
        out["llm"] = {"ok": False, "error": str(e)}
    if (cfg.get("search_provider") or "none") == "tavily":
        try:
            out["search"] = probe_tavily(cfg)
        except Exception as e:
            out["search"] = {"ok": False, "error": str(e)}
    return out


@router.put("/ai")
def put_ai_settings(payload: AiSettingsIn):
    if payload.provider not in VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"provider must be one of {VALID_PROVIDERS}")
    if payload.search_provider and payload.search_provider not in ("none", "tavily"):
        raise HTTPException(status_code=400, detail="search_provider must be none or tavily")
    current = _load_raw()
    incoming = payload.model_dump(exclude_none=True)
    for k in SECRET_FIELDS:
        v = incoming.get(k)
        if v is None:
            continue
        if v == "" or v.startswith("****"):
            incoming.pop(k)
    current.update(incoming)
    _write_raw(current)
    return get_ai_settings()


def _write_raw(cfg: dict[str, Any]) -> None:
    db: Session = next(get_db())
    try:
        row = db.get(AppSetting, AI_KEY)
        text = json.dumps(cfg, ensure_ascii=False)
        if row is None:
            db.add(AppSetting(key=AI_KEY, value=text))
        else:
            row.value = text
        db.commit()
    finally:
        db.close()


class DailySummaryPromptIn(BaseModel):
    prompt: str


@router.get("/daily-summary-prompt")
def get_daily_summary_prompt():
    cfg = _load_raw()
    return {
        "prompt": cfg.get("daily_summary_prompt") or DEFAULT_HERMES_PROMPT,
        "default": DEFAULT_HERMES_PROMPT,
    }


@router.put("/daily-summary-prompt")
def put_daily_summary_prompt(payload: DailySummaryPromptIn):
    text = (payload.prompt or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="prompt 不能为空")
    cfg = _load_raw()
    cfg["daily_summary_prompt"] = text
    _write_raw(cfg)
    return {"prompt": text, "default": DEFAULT_HERMES_PROMPT}


@router.post("/daily-summary-prompt/reset")
def reset_daily_summary_prompt():
    cfg = _load_raw()
    cfg["daily_summary_prompt"] = DEFAULT_HERMES_PROMPT
    _write_raw(cfg)
    return {"prompt": DEFAULT_HERMES_PROMPT, "default": DEFAULT_HERMES_PROMPT}


# ---------------------------------------------------------------------------
# 自选股「重要资讯」AI 检索 提示词 + 数据源开关
# ---------------------------------------------------------------------------

class NewsSettingsIn(BaseModel):
    prompt: str | None = None
    sources: list[str] | None = None


def _normalize_sources(values: list[str] | None) -> list[str]:
    if not values:
        return list(NEWS_DEFAULT_SOURCES)
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in NEWS_AVAILABLE_SOURCES and v not in seen:
            seen.add(v)
            out.append(v)
    # 全部传非法 → 兜底用默认全启用，避免空集合直接禁掉资讯
    return out or list(NEWS_DEFAULT_SOURCES)


@router.get("/news")
def get_news_settings():
    cfg = _load_raw()
    sources = _normalize_sources(cfg.get("news_sources"))
    return {
        "prompt": cfg.get("news_prompt") or DEFAULT_NEWS_PROMPT,
        "default_prompt": DEFAULT_NEWS_PROMPT,
        "sources": sources,
        "available_sources": list(NEWS_AVAILABLE_SOURCES),
        "default_sources": list(NEWS_DEFAULT_SOURCES),
    }


@router.put("/news")
def put_news_settings(payload: NewsSettingsIn):
    cfg = _load_raw()
    if payload.prompt is not None:
        text = payload.prompt.strip()
        if not text:
            raise HTTPException(status_code=400, detail="prompt 不能为空")
        cfg["news_prompt"] = text
    if payload.sources is not None:
        cfg["news_sources"] = _normalize_sources(payload.sources)
    _write_raw(cfg)
    return get_news_settings()


@router.post("/news/reset-prompt")
def reset_news_prompt():
    cfg = _load_raw()
    cfg["news_prompt"] = DEFAULT_NEWS_PROMPT
    _write_raw(cfg)
    return get_news_settings()
