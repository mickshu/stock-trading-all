"""AI 收盘总结服务。

主路径：本地 AI Agent CLI（subprocess，自带联网/工具）——可选 hermes/claude/codex/gemini 之一。
保留：OpenAI / Anthropic 直连 + Tavily 工具循环，作为没有本地 CLI 时的备选。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from backend.services.ai_agent import AGENTS, get_agent, run_agent

LOCAL_AGENT_NAMES = tuple(spec.name for spec in AGENTS)

logger = logging.getLogger(__name__)

MAX_TOOL_LOOPS = 5
WEB_FETCH_MAX_CHARS = 8000
TAVILY_URL = "https://api.tavily.com/search"
HERMES_TIMEOUT = 300

SYSTEM_PROMPT = (
    "你是 A 股每日收盘资讯总结助手。基于用户给出的指数行情、个股资金流 TOP10、行业板块"
    "资金流 TOP5 数据，结合 web_search 与 web_fetch 获取的最新新闻，给出当日中文收盘综"
    "述：①大盘表现 ②资金动向 ③热点板块/个股 ④消息面要点 ⑤明日关注。要求：客观、紧扣"
    "数据、注明信息来源（用 markdown 链接），不超过 600 字。"
)

DEFAULT_HERMES_PROMPT = (
    "你是 A 股每日收盘资讯总结助手。下方「当日数据」由系统给出（指数行情、主力资金 TOP、"
    "行业板块资金 TOP）。请：\n"
    "1. 主动联网检索今日 A 股相关的政策面、消息面、热点板块、龙头个股动态；\n"
    "2. 综合数据与新闻，给出一份中文 markdown 收盘综述，分五段：\n"
    "   ① 大盘表现  ② 资金动向  ③ 热点板块 / 个股  ④ 消息面要点  ⑤ 明日关注；\n"
    "3. 客观、紧扣数据，全文不超过 600 字；引用新闻请用 markdown 链接形式注明出处；\n"
    "4. 不要给出具体买卖建议。"
)

TOOLS_OPENAI_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "在互联网上搜索与 A 股收盘行情、政策、个股新闻相关的内容。返回 5 条左右标题+摘要+URL。",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "搜索关键词"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_fetch",
            "description": "抓取指定 URL 的网页正文。用于在 web_search 之后深入了解感兴趣的新闻。",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "要抓取的网址"}},
                "required": ["url"],
            },
        },
    },
]

TOOLS_CLAUDE_SCHEMA = [
    {
        "name": "web_search",
        "description": "在互联网上搜索与 A 股收盘行情、政策、个股新闻相关的内容。返回 5 条左右标题+摘要+URL。",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "搜索关键词"}},
            "required": ["query"],
        },
    },
    {
        "name": "web_fetch",
        "description": "抓取指定 URL 的网页正文。用于在 web_search 之后深入了解感兴趣的新闻。",
        "input_schema": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "要抓取的网址"}},
            "required": ["url"],
        },
    },
]


def _tool_web_search(query: str, settings: dict) -> dict:
    provider = (settings or {}).get("search_provider") or "none"
    if provider != "tavily":
        return {"error": "未配置联网搜索 provider；可在设置 → AI 配置 启用 Tavily。"}
    api_key = (settings or {}).get("tavily_api_key") or ""
    if not api_key:
        return {"error": "Tavily API Key 未配置。"}
    try:
        resp = requests.post(
            TAVILY_URL,
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": 5,
                "include_answer": False,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json() or {}
        results = [
            {"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in (data.get("results") or [])
        ]
        return {"results": results}
    except Exception as e:
        logger.exception("web_search failed")
        return {"error": str(e)}


def _tool_web_fetch(url: str) -> dict:
    if not url or not url.startswith(("http://", "https://")):
        return {"error": "URL 非法"}
    try:
        resp = requests.get(
            url,
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; StockSummaryBot/1.0)"},
        )
        resp.raise_for_status()
        text = resp.text or ""
        try:
            from bs4 import BeautifulSoup  # 延迟 import，未装时给出明确提示
            soup = BeautifulSoup(text, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            content = " ".join(soup.get_text(separator=" ", strip=True).split())
        except Exception:
            content = text
        if len(content) > WEB_FETCH_MAX_CHARS:
            content = content[:WEB_FETCH_MAX_CHARS] + "…[truncated]"
        return {"url": url, "content": content}
    except Exception as e:
        logger.exception("web_fetch failed for %s", url)
        return {"error": str(e)}


def _dispatch_tool(name: str, args: dict, settings: dict, sources: list[str]) -> str:
    if name == "web_search":
        out = _tool_web_search(args.get("query", ""), settings)
        for r in (out.get("results") or []):
            if r.get("url"):
                sources.append(r["url"])
        return json.dumps(out, ensure_ascii=False)
    if name == "web_fetch":
        out = _tool_web_fetch(args.get("url", ""))
        if out.get("url"):
            sources.append(out["url"])
        return json.dumps(out, ensure_ascii=False)
    return json.dumps({"error": f"unknown tool: {name}"})


def _user_context(indices: list[dict], stock_flow: dict, sector_flow: dict) -> str:
    today = stock_flow.get("date") or sector_flow.get("date") or time.strftime("%Y-%m-%d")
    lines = [f"## 当日数据（{today}）", "", "### 指数行情"]
    for idx in indices or []:
        price = idx.get("price") or 0
        cp = idx.get("change_pct") or 0
        lines.append(f"- {idx.get('name')} {price:.2f} ({cp:+.2f}%)")
    lines += ["", f"### 主力资金净流入 TOP{len(stock_flow.get('inflow') or [])}"]
    for s in (stock_flow.get("inflow") or []):
        mn = (s.get("main_net") or 0) / 1e8
        lines.append(f"- {s.get('code')} {s.get('name')} 主力净流入 {mn:+.2f} 亿元，涨跌 {(s.get('change_pct') or 0):+.2f}%")
    lines += ["", f"### 主力资金净流出 TOP{len(stock_flow.get('outflow') or [])}"]
    for s in (stock_flow.get("outflow") or []):
        mn = (s.get("main_net") or 0) / 1e8
        lines.append(f"- {s.get('code')} {s.get('name')} 主力净流出 {mn:+.2f} 亿元，涨跌 {(s.get('change_pct') or 0):+.2f}%")
    lines += ["", f"### 行业板块资金净流入 TOP{len(sector_flow.get('inflow') or [])}"]
    for s in (sector_flow.get("inflow") or []):
        mn = (s.get("main_net") or 0) / 1e8
        lines.append(f"- {s.get('name')} 净流入 {mn:+.2f} 亿元，板块涨跌 {(s.get('change_pct') or 0):+.2f}%")
    lines += ["", f"### 行业板块资金净流出 TOP{len(sector_flow.get('outflow') or [])}"]
    for s in (sector_flow.get("outflow") or []):
        mn = (s.get("main_net") or 0) / 1e8
        lines.append(f"- {s.get('name')} 净流出 {mn:+.2f} 亿元，板块涨跌 {(s.get('change_pct') or 0):+.2f}%")
    lines += ["", "请基于以上数据，必要时联网检索新闻面，给出今日 A 股收盘综述（中文 markdown，≤600 字）。"]
    return "\n".join(lines)


def _import_openai():
    try:
        from openai import OpenAI  # type: ignore
        return OpenAI
    except ImportError as e:
        raise RuntimeError(
            "openai 模块未安装。请在后端虚拟环境中执行：.venv/bin/pip install -r backend/requirements.txt 并以 .venv 启动 uvicorn"
        ) from e


def _import_anthropic():
    try:
        import anthropic  # type: ignore
        return anthropic
    except ImportError as e:
        raise RuntimeError(
            "anthropic 模块未安装。请在后端虚拟环境中执行：.venv/bin/pip install -r backend/requirements.txt 并以 .venv 启动 uvicorn"
        ) from e


def _run_openai(
    settings: dict,
    user_msg: str,
    system_prompt: str | None = None,
) -> tuple[str, str, list[str]]:
    OpenAI = _import_openai()
    api_key = settings.get("openai_api_key") or ""
    if not api_key:
        raise RuntimeError("OpenAI API Key 未配置")
    base_url = settings.get("openai_base_url") or "https://api.openai.com/v1"
    model = settings.get("openai_model") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=60)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt or SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ]
    sources: list[str] = []
    for _ in range(MAX_TOOL_LOOPS):
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=TOOLS_OPENAI_SCHEMA, tool_choice="auto",
            temperature=0.4,
        )
        msg = resp.choices[0].message
        if not msg.tool_calls:
            return (msg.content or "").strip(), model, sources
        assistant_msg: dict[str, Any] = {
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in msg.tool_calls
            ],
        }
        # thinking 模型（DeepSeek-R1 / Qwen3-thinking 等）会返回 reasoning_content，
        # 多轮工具回传时必须原样回传，否则 API 报 invalid_request_error。
        # 优先从 model_dump()（兼容最新 SDK 字段名映射），再 fallback 到 getattr、
        # model_extra、model_dump 的驼峰变体，覆盖不同 SDK 版本的字段名差异。
        raw = msg.model_dump() if hasattr(msg, "model_dump") else {}
        for key in ("reasoning_content", "reasoning", "reasoningContent"):
            val = None
            if isinstance(raw, dict):
                val = raw.get(key)
            if val is None:
                val = getattr(msg, key, None)
            if val is None and hasattr(msg, "model_extra"):
                extra = msg.model_extra or {}
                val = extra.get(key)
            if val:
                assistant_msg[key] = val
        messages.append(assistant_msg)
        for tc in msg.tool_calls:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except Exception:
                args = {}
            tool_result = _dispatch_tool(tc.function.name, args, settings, sources)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": tool_result})
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0.4)
    return (resp.choices[0].message.content or "").strip(), model, sources


def _run_anthropic(
    settings: dict,
    user_msg: str,
    system_prompt: str | None = None,
) -> tuple[str, str, list[str]]:
    anthropic = _import_anthropic()
    api_key = settings.get("anthropic_api_key") or ""
    if not api_key:
        raise RuntimeError("Anthropic API Key 未配置")
    model = settings.get("anthropic_model") or "claude-sonnet-4-6"
    client = anthropic.Anthropic(api_key=api_key, timeout=60)
    sys_prompt = system_prompt or SYSTEM_PROMPT

    messages: list[dict[str, Any]] = [{"role": "user", "content": user_msg}]
    sources: list[str] = []
    for _ in range(MAX_TOOL_LOOPS):
        resp = client.messages.create(
            model=model, max_tokens=2048, system=sys_prompt,
            tools=TOOLS_CLAUDE_SCHEMA, messages=messages, temperature=0.4,
        )
        if resp.stop_reason != "tool_use":
            parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
            return "".join(parts).strip(), model, sources
        messages.append({"role": "assistant", "content": [b.model_dump() for b in resp.content]})
        tool_results = []
        for b in resp.content:
            if getattr(b, "type", "") == "tool_use":
                tool_result = _dispatch_tool(b.name, dict(b.input or {}), settings, sources)
                tool_results.append({"type": "tool_result", "tool_use_id": b.id, "content": tool_result})
        messages.append({"role": "user", "content": tool_results})
    resp = client.messages.create(
        model=model, max_tokens=2048, system=sys_prompt, messages=messages, temperature=0.4,
    )
    parts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]
    return "".join(parts).strip(), model, sources


def _run_local_agent(
    agent_name: str,
    settings: dict,
    user_msg: str,
    prompt_template: str | None = None,
) -> tuple[str, str, list[str]]:
    spec = get_agent(agent_name)
    if spec is None:
        raise RuntimeError(f"{agent_name} agent 未注册")
    if prompt_template is None:
        prompt_template = (settings or {}).get("daily_summary_prompt") or DEFAULT_HERMES_PROMPT
    prompt = f"{prompt_template.strip()}\n\n{user_msg}"
    result = run_agent(agent_name, prompt, timeout=HERMES_TIMEOUT)
    if not result.get("ok"):
        stderr = (result.get("stderr") or "").strip()
        raise RuntimeError(
            f"{spec.label} 执行失败 (exit={result.get('exit_code')})：{stderr or '无输出'}"
        )
    output = (result.get("output") or "").strip()
    if not output:
        raise RuntimeError(f"{spec.label} 无输出")
    return output, agent_name, []


def generate_daily_summary(
    indices: list[dict],
    stock_flow: dict,
    sector_flow: dict,
    settings: dict,
) -> dict:
    """主入口。settings 来自 AppSetting kv（已解密的明文 dict）。

    provider 命中本地 Agent CLI 时走 subprocess；openai/anthropic 走 HTTP 直连。
    返回 {model, content, sources, generated_at}。
    """
    provider = (settings or {}).get("provider") or "hermes"
    user_msg = _user_context(indices, stock_flow, sector_flow)

    if provider in LOCAL_AGENT_NAMES:
        content, model, sources = _run_local_agent(provider, settings, user_msg)
    elif provider == "anthropic":
        content, model, sources = _run_anthropic(settings, user_msg)
    else:
        content, model, sources = _run_openai(settings, user_msg)
    seen, dedup = set(), []
    for u in sources:
        if u and u not in seen:
            seen.add(u)
            dedup.append(u)
    return {
        "model": model,
        "content": content,
        "sources": dedup,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def probe_llm(settings: dict) -> dict:
    """最小调用以验证 LLM 联通。返回 {ok, provider, model, sample, error?}。"""
    provider = (settings or {}).get("provider") or "openai"

    # 本地 CLI 模式不发起 HTTP，仅核对 CLI 是否已安装（由 settings API 层提前校验）。
    if provider in LOCAL_AGENT_NAMES:
        from backend.services.ai_agent import get_agent as _get_agent, _resolve_binary as _which
        spec = _get_agent(provider)
        if spec is None or not _which(spec):
            raise RuntimeError(f"本地 CLI {provider} 未安装或不在 PATH")
        return {"ok": True, "provider": provider, "model": spec.label, "sample": ""}

    if provider == "anthropic":
        anthropic = _import_anthropic()
        api_key = (settings or {}).get("anthropic_api_key") or ""
        if not api_key:
            raise RuntimeError("Anthropic API Key 未配置")
        model = (settings or {}).get("anthropic_model") or "claude-sonnet-4-6"
        client = anthropic.Anthropic(api_key=api_key, timeout=20)
        resp = client.messages.create(
            model=model,
            max_tokens=16,
            messages=[{"role": "user", "content": "ping，请用中文回复一个字。"}],
        )
        sample = "".join(getattr(b, "text", "") for b in resp.content).strip()
        return {"ok": True, "provider": "anthropic", "model": model, "sample": sample}
    OpenAI = _import_openai()
    api_key = (settings or {}).get("openai_api_key") or ""
    if not api_key:
        raise RuntimeError("OpenAI API Key 未配置")
    base_url = (settings or {}).get("openai_base_url") or "https://api.openai.com/v1"
    model = (settings or {}).get("openai_model") or "gpt-4o-mini"
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=20)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=16,
        temperature=0,
        messages=[{"role": "user", "content": "ping，请用中文回复一个字。"}],
    )
    sample = (resp.choices[0].message.content or "").strip()
    return {"ok": True, "provider": "openai", "model": model, "sample": sample, "base_url": base_url}


def generate_news_digest(
    code_to_name: dict[str, str],
    prompt: str,
    settings: dict,
) -> dict:
    """自选股「重要资讯」AI 检索入口。

    与 generate_daily_summary 共用 LLM provider / 工具循环，但：
    - system 提示词使用调用方传入的 prompt（来自 AppSetting.news_prompt）
    - user 消息只塞入「自选股清单」，让 LLM 自行联网检索
    """
    provider = (settings or {}).get("provider") or "hermes"
    if not code_to_name:
        raise RuntimeError("自选股清单为空，无法生成资讯简报")
    lines = ["## 自选股清单", ""]
    for code, name in code_to_name.items():
        lines.append(f"- {code} {name}".rstrip())
    lines += [
        "",
        "请基于以上清单与 web_search / web_fetch 工具检索到的最新公开信息，"
        "按系统提示词的要求输出 markdown 简报。",
    ]
    user_msg = "\n".join(lines)

    sys_prompt = (prompt or "").strip() or SYSTEM_PROMPT
    if provider in LOCAL_AGENT_NAMES:
        content, model, sources = _run_local_agent(
            provider, settings, user_msg, prompt_template=sys_prompt,
        )
    elif provider == "anthropic":
        content, model, sources = _run_anthropic(settings, user_msg, system_prompt=sys_prompt)
    else:
        content, model, sources = _run_openai(settings, user_msg, system_prompt=sys_prompt)
    seen, dedup = set(), []
    for u in sources:
        if u and u not in seen:
            seen.add(u)
            dedup.append(u)
    return {
        "model": model,
        "content": content,
        "sources": dedup,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


def probe_tavily(settings: dict) -> dict:
    """最小调用验证 Tavily 联通。"""
    api_key = (settings or {}).get("tavily_api_key") or ""
    if not api_key:
        raise RuntimeError("Tavily API Key 未配置")
    resp = requests.post(
        TAVILY_URL,
        json={"api_key": api_key, "query": "A股", "search_depth": "basic", "max_results": 1},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json() or {}
    n = len(data.get("results") or [])
    return {"ok": True, "provider": "tavily", "results": n}
