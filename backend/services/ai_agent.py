"""本地 AI CLI 探测与调用服务。

通过 subprocess 非交互式调用 Claude Code / Codex / Gemini / Hermes 等本地
AI Agent CLI，把股票上下文 + 用户填写的「分析维度」拼成 prompt 喂进去，
让 CLI 自带的工具与知识完成分析，再把 stdout 原样返回前端渲染。

设计上保持 CLI 中立：白名单里只声明 `argv` 模板和版本探测命令，新加 CLI
只需在 AGENTS 列表里加一条即可。
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 180  # 秒
MAX_OUTPUT_CHARS = 64_000

# 报告落盘目录：<repo>/data/reports/，由 FastAPI 静态挂载到 /reports/。
REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"
REPORT_URL_PREFIX = "/reports"

# 文件名安全字符集：去掉路径分隔符、控制字符、Windows 保留符号。
_UNSAFE_FILENAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')


@dataclass(frozen=True)
class AgentSpec:
    name: str           # 唯一 key，前端透传
    label: str          # 展示名
    binary: str         # 可执行文件名（用于 shutil.which）
    prompt_argv: Sequence[str]  # prompt 拼接前的参数模板，最后一项之后追加 prompt 字符串
    version_argv: Sequence[str] = ("--version",)


AGENTS: list[AgentSpec] = [
    AgentSpec(
        name="claude",
        label="Claude Code",
        binary="claude",
        prompt_argv=("claude", "-p"),
    ),
    AgentSpec(
        name="codex",
        label="Codex CLI",
        binary="codex",
        prompt_argv=("codex", "exec"),
    ),
    AgentSpec(
        name="gemini",
        label="Gemini CLI",
        binary="gemini",
        prompt_argv=("gemini", "-p"),
    ),
    AgentSpec(
        name="hermes",
        label="Hermes",
        binary="hermes",
        # Hermes 用 -z PROMPT 进入非交互模式；--yolo 跳过工具确认。
        prompt_argv=("hermes", "--yolo", "-z"),
    ),
]


def _resolve_binary(spec: AgentSpec) -> str | None:
    return shutil.which(spec.binary)


def _probe_version(path: str, version_argv: Sequence[str]) -> str:
    try:
        out = subprocess.run(
            [path, *version_argv],
            capture_output=True,
            text=True,
            timeout=8,
        )
        text = (out.stdout or out.stderr or "").strip().splitlines()
        return text[0] if text else ""
    except Exception:
        return ""


def detect_agents() -> list[dict]:
    """返回当前可用的 CLI 列表（按 AGENTS 顺序）。"""
    result: list[dict] = []
    for spec in AGENTS:
        path = _resolve_binary(spec)
        if not path:
            continue
        result.append({
            "name": spec.name,
            "label": spec.label,
            "binary": spec.binary,
            "path": path,
            "version": _probe_version(path, spec.version_argv),
        })
    return result


def get_agent(name: str) -> AgentSpec | None:
    for spec in AGENTS:
        if spec.name == name:
            return spec
    return None


def build_prompt(code: str, stock_name: str, dimension: str) -> str:
    """把用户填写的维度拼成中文分析指令。"""
    name_part = f"{code} {stock_name}".strip() if stock_name else code
    dim = (dimension or "综合").strip()
    return (
        f"你是 A 股投研助手。请针对以下股票给出客观的「{dim}」维度分析，"
        f"用中文 markdown 输出，控制在 600 字以内，必要时附信息来源链接：\n\n"
        f"- 股票：{name_part}\n"
        f"- 分析维度：{dim}\n\n"
        f"如果你具备联网或数据查询能力，请主动获取最近的行情、公告、研报与资金面信息。"
        f"输出请包含：核心结论、关键证据、潜在风险、可关注信号；"
        f"避免提供具体买卖建议。"
    )


def run_agent(
    name: str,
    prompt: str,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """以非交互模式运行指定 CLI，返回 {ok, agent, output, stderr, duration, exit_code}。

    抛出 ValueError 表示 agent 不在白名单或未安装。
    """
    spec = get_agent(name)
    if spec is None:
        raise ValueError(f"unknown agent: {name}")
    path = _resolve_binary(spec)
    if not path:
        raise ValueError(f"agent not installed: {name}")

    argv = [path, *list(spec.prompt_argv)[1:], prompt]
    started = time.monotonic()
    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("TERM", "dumb")

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            cwd=os.path.expanduser("~"),
        )
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False,
            "agent": name,
            "output": (e.stdout or "") if isinstance(e.stdout, str) else "",
            "stderr": f"调用超时（>{timeout}s）",
            "duration": time.monotonic() - started,
            "exit_code": None,
        }
    except FileNotFoundError:
        raise ValueError(f"agent binary missing: {spec.binary}")

    output = (proc.stdout or "")
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n\n…[输出截断]"
    return {
        "ok": proc.returncode == 0,
        "agent": name,
        "output": output,
        "stderr": (proc.stderr or "")[-2000:],
        "duration": time.monotonic() - started,
        "exit_code": proc.returncode,
    }


def _safe_filename_part(text: str) -> str:
    cleaned = _UNSAFE_FILENAME.sub("", (text or "").strip())
    cleaned = cleaned.replace(" ", "")
    return cleaned[:60] or "unknown"


def report_filename(code: str, stock_name: str | None, *, today: str | None = None) -> str:
    """`日期_公司名.md`；公司名缺失时回退到代码。"""
    date_str = today or datetime.now().strftime("%Y-%m-%d")
    name = _safe_filename_part(stock_name or code)
    return f"{date_str}_{name}.md"


def save_report(
    code: str,
    stock_name: str | None,
    dimension: str,
    agent: str,
    content: str,
) -> dict:
    """落盘 markdown 报告并返回 {filename, url, path}。同名覆盖。"""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    filename = report_filename(code, stock_name)
    path = REPORTS_DIR / filename
    header = (
        f"# {stock_name or code} · {dimension or '综合'}\n\n"
        f"- 代码：{code}\n"
        f"- 维度：{dimension or '综合'}\n"
        f"- 生成工具：{agent}\n"
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"---\n\n"
    )
    path.write_text(header + (content or ""), encoding="utf-8")
    return {
        "filename": filename,
        "url": f"{REPORT_URL_PREFIX}/{filename}",
        "path": str(path),
    }


def _parse_filename(filename: str) -> dict:
    """从 `YYYY-MM-DD_name.md` 反解出日期与名字。无法解析时尽力填充。"""
    stem = filename[:-3] if filename.endswith(".md") else filename
    parts = stem.split("_", 1)
    if len(parts) == 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", parts[0]):
        return {"date": parts[0], "name": parts[1]}
    return {"date": "", "name": stem}


def list_reports(name_filter: str | None = None) -> list[dict]:
    """按 mtime 倒序返回 reports 目录下所有 .md，可选按公司名过滤。"""
    if not REPORTS_DIR.is_dir():
        return []
    items: list[dict] = []
    needle = _safe_filename_part(name_filter) if name_filter else ""
    for p in REPORTS_DIR.glob("*.md"):
        meta = _parse_filename(p.name)
        if needle and needle not in meta["name"]:
            continue
        stat = p.stat()
        items.append({
            "filename": p.name,
            "url": f"{REPORT_URL_PREFIX}/{p.name}",
            "date": meta["date"],
            "name": meta["name"],
            "size": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def read_report(filename: str) -> str | None:
    """读取报告内容；防穿越目录。文件不存在返回 None。"""
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return None
    path = REPORTS_DIR / filename
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return None


# ===== v2: 多 scope 支持（PR-1 仅 single；其它 scope 留给 PR-2）=====


def _stock_list_lines(targets: list[dict]) -> str:
    lines = []
    for t in targets or []:
        code = (t.get("code") or "").strip()
        name = (t.get("name") or "").strip()
        label = f"{code} {name}".strip() if (code and name) else (name or code)
        if label:
            lines.append(f"  - {label}")
    return "\n".join(lines)


def build_prompt_v2(scope: str, targets: list[dict], dimensions: list[str]) -> str:
    """按 scope 拼 prompt。支持 single / multi / sector / market / pick。"""
    dim_text = "、".join(d.strip() for d in (dimensions or []) if d and d.strip()) or "综合"

    if scope == "single":
        if not targets:
            raise ValueError("single scope requires one target")
        t = targets[0]
        code = (t.get("code") or "").strip()
        name = (t.get("name") or "").strip()
        name_part = f"{code} {name}".strip() if name else code
        return (
            f"你是 A 股投研助手。请针对以下股票给出客观的「{dim_text}」维度分析，"
            f"用中文 markdown 输出，控制在 600 字以内，必要时附信息来源链接：\n\n"
            f"- 股票：{name_part}\n"
            f"- 分析维度：{dim_text}\n\n"
            f"如果你具备联网或数据查询能力，请主动获取最近的行情、公告、研报与资金面信息。"
            f"输出请包含：核心结论、关键证据、潜在风险、可关注信号；"
            f"避免提供具体买卖建议。"
        )

    if scope == "multi":
        if len(targets or []) < 2:
            raise ValueError("multi scope requires at least 2 targets")
        return (
            f"你是 A 股投研助手。请对以下 {len(targets)} 只股票从「{dim_text}」维度做横向对比，"
            f"用中文 markdown 输出，控制在 800 字以内，必要时附信息来源链接：\n\n"
            f"股票列表：\n{_stock_list_lines(targets)}\n\n"
            f"如果你具备联网或数据查询能力，请主动获取相关行情、公告、研报与资金面信息。\n"
            f"输出请包含：①横向对比表  ②各家亮点与隐患  ③综合排序与理由  ④共同风险；"
            f"避免提供具体买卖建议。"
        )

    if scope == "sector":
        if not targets:
            raise ValueError("sector scope requires at least 1 target")
        names = [(t.get("sector") or t.get("name") or "").strip() for t in targets]
        sector_list = "、".join(n for n in names if n) or "—"
        return (
            f"你是 A 股投研助手。请对以下行业/板块从「{dim_text}」给出研判，"
            f"用中文 markdown 输出，控制在 800 字以内，必要时附信息来源链接：\n\n"
            f"- 板块：{sector_list}\n"
            f"- 分析维度：{dim_text}\n\n"
            f"如果你具备联网或数据查询能力，请主动获取板块最近的政策、龙头公司动态、资金流向。\n"
            f"输出请包含：①基本面/政策面催化  ②资金面动向  ③龙头与潜力个股梳理  ④风险点；"
            f"避免提供具体买卖建议。"
        )

    if scope == "market":
        if not targets:
            raise ValueError("market scope requires at least 1 target")
        names = [(t.get("name") or t.get("index") or "").strip() for t in targets]
        idx_list = "、".join(n for n in names if n) or "大盘"
        return (
            f"你是 A 股投研助手。请对以下大盘指数做近期复盘，分析维度「{dim_text}」，"
            f"用中文 markdown 输出，控制在 800 字以内，必要时附信息来源链接：\n\n"
            f"- 指数：{idx_list}\n"
            f"- 分析维度：{dim_text}\n\n"
            f"如果你具备联网或数据查询能力，请主动获取最近的指数行情、资金面、消息面、热点板块。\n"
            f"输出请包含：①指数表现  ②资金面与情绪  ③主要驱动/拖累板块  ④后市关注点；"
            f"避免提供具体买卖建议。"
        )

    if scope == "pick":
        if not targets:
            raise ValueError("pick scope requires at least 1 target")
        return (
            f"你是 A 股投研助手。请对下列 {len(targets)} 只股票做批量诊断，每只从「{dim_text}」"
            f"维度给出 100–200 字简评，最后给出整体排行与重点关注名单。"
            f"用中文 markdown 输出，必要时附信息来源链接：\n\n"
            f"股票列表：\n{_stock_list_lines(targets)}\n\n"
            f"如果你具备联网或数据查询能力，请主动获取相关行情、公告、资金面信息。\n"
            f"输出格式：①各股简评（小标题=股票名+代码）  ②整体排行表  ③重点关注理由  ④共同风险；"
            f"避免提供具体买卖建议。"
        )

    raise ValueError(f"unknown scope: {scope}")


def report_filename_v2(
    scope: str,
    targets: list[dict],
    *,
    now: datetime | None = None,
) -> str:
    """`YYYY-MM-DD_HHMMSS_<scope>_<slug>.md`，slug ≤ 60 字符。

    保留时间戳，避免同日多次分析覆盖。
    """
    ts = (now or datetime.now()).strftime("%Y-%m-%d_%H%M%S")
    parts: list[str] = []
    if scope in ("single", "multi", "pick"):
        for t in targets or []:
            label = (t.get("name") or t.get("code") or "").strip()
            if label:
                parts.append(label)
    elif scope == "sector":
        for t in targets or []:
            label = (t.get("sector") or t.get("name") or "").strip()
            if label:
                parts.append(label)
    elif scope == "market":
        parts.append("market")
    slug = _safe_filename_part("+".join(parts) if parts else "unknown")
    return f"{ts}_{scope}_{slug}.md"

