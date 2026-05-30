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
