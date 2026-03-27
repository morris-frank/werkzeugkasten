from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

PLAN_BLOCK_RE = re.compile(r"<proposed_plan>\s*(.*?)\s*</proposed_plan>", re.DOTALL)
TOOL_CALL_TYPES = {"function_call", "custom_tool_call", "web_search_call"}


@dataclass
class CompletedTurn:
    prompt: str
    plan: str | None
    answer: str
    image_count: int
    duration_seconds: int | None
    total_tokens: int | None
    tool_call_count: int


@dataclass
class TurnState:
    prompt: str = ""
    image_count: int = 0
    plan: str | None = None
    final_answer: str | None = None
    last_agent_message: str | None = None
    started_at: datetime | None = None
    token_total_start: int | None = None
    token_total_end: int | None = None
    tool_call_count: int = 0


def _parse_codex_log(path: str | Path) -> list[CompletedTurn]:
    log_path = Path(path).expanduser()
    if log_path.suffix.lower() != ".jsonl":
        raise ValueError("Expected a `.jsonl` Codex log file.")
    if not log_path.is_file():
        raise FileNotFoundError(f"File not found: {log_path}")

    turns: list[CompletedTurn] = []
    current_turn_id: str | None = None
    active_turn: TurnState | None = None
    previous_total_tokens: int | None = None

    with log_path.open(encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc

            record_type = record.get("type")
            payload = record.get("payload", {})
            if not isinstance(payload, dict):
                continue

            timestamp = _parse_timestamp(record.get("timestamp"))
            total_tokens = _extract_total_tokens(payload)

            if record_type == "event_msg":
                event_type = payload.get("type")
                if event_type == "task_started":
                    current_turn_id = payload.get("turn_id")
                    active_turn = TurnState(
                        started_at=timestamp,
                        token_total_start=previous_total_tokens,
                    )
                    continue
                if event_type == "turn_aborted":
                    if payload.get("turn_id") == current_turn_id:
                        current_turn_id = None
                        active_turn = None
                    continue
                if active_turn is None:
                    if total_tokens is not None:
                        previous_total_tokens = total_tokens
                    continue
                if total_tokens is not None:
                    if active_turn.token_total_start is None:
                        active_turn.token_total_start = total_tokens
                    active_turn.token_total_end = total_tokens
                    previous_total_tokens = total_tokens
                if event_type == "user_message":
                    active_turn.prompt = payload.get("message", "") or active_turn.prompt
                    active_turn.image_count = len(payload.get("images") or []) + len(payload.get("local_images") or [])
                    continue
                if event_type == "task_complete":
                    if payload.get("turn_id") != current_turn_id:
                        continue
                    active_turn.last_agent_message = payload.get("last_agent_message") or active_turn.last_agent_message
                    active_turn.token_total_end = previous_total_tokens
                    turns.append(_finalize_turn(active_turn, timestamp))
                    current_turn_id = None
                    active_turn = None
                    continue
                continue

            if record_type != "response_item" or active_turn is None:
                if total_tokens is not None:
                    previous_total_tokens = total_tokens
                continue

            item_type = payload.get("type")
            if item_type in TOOL_CALL_TYPES:
                active_turn.tool_call_count += 1
                continue
            if item_type != "message" or payload.get("role") != "assistant":
                continue

            text = _extract_message_text(payload)
            if not text:
                continue

            if active_turn.plan is None:
                active_turn.plan = _extract_plan(text)
            if payload.get("phase") == "final_answer":
                active_turn.final_answer = text

            if total_tokens is not None:
                previous_total_tokens = total_tokens

    return turns


@dataclass(frozen=True)
class CodexLogResult:
    output_path: Path
    completed_turn_count: int
    image_count: int
    tool_call_count: int
    total_token_count: int | None


def prettify_codex_log(path: str | Path) -> CodexLogResult:
    log_path = Path(path).expanduser()
    turns = _parse_codex_log(log_path)
    output_path = log_path.with_name(log_path.name + ".transcript.md")
    output_path.write_text(_render_transcript(turns), encoding="utf-8")
    return CodexLogResult(
        output_path=output_path,
        completed_turn_count=len(turns),
        image_count=sum(turn.image_count for turn in turns),
        tool_call_count=sum(turn.tool_call_count for turn in turns),
        total_token_count=sum(turn.total_tokens or 0 for turn in turns) or None,
    )


def _finalize_turn(turn: TurnState, completed_at: datetime | None) -> CompletedTurn:
    prompt = turn.prompt.strip() or "_No user prompt captured._"
    answer = turn.final_answer or turn.last_agent_message or "_No final answer captured._"
    answer = _strip_plan_block(answer).strip() or turn.last_agent_message or "_No final answer captured._"
    duration_seconds = None
    if turn.started_at and completed_at:
        duration_seconds = max(int((completed_at - turn.started_at).total_seconds()), 0)
    total_tokens = None
    if turn.token_total_start is not None and turn.token_total_end is not None:
        total_tokens = max(turn.token_total_end - turn.token_total_start, 0)
    elif turn.token_total_end is not None:
        total_tokens = max(turn.token_total_end, 0)

    return CompletedTurn(
        prompt=prompt,
        plan=turn.plan.strip() if turn.plan else None,
        answer=answer.strip(),
        image_count=turn.image_count,
        duration_seconds=duration_seconds,
        total_tokens=total_tokens,
        tool_call_count=turn.tool_call_count,
    )


def _render_transcript(turns: list[CompletedTurn]) -> str:
    if not turns:
        return "# Codex Transcript\n\n_No completed turns were found in this session._\n"

    blocks = ["# Codex Transcript", ""]
    for index, turn in enumerate(turns, start=1):
        prompt_header = "### 🎙️ Prompt"
        if turn.image_count:
            image_label = "image" if turn.image_count == 1 else "images"
            prompt_header += f" — `🖼️ w/ {turn.image_count} {image_label}`"
        blocks.append(prompt_header)
        blocks.append("")
        blocks.append(_to_blockquote(turn.prompt))
        blocks.append("")

        if turn.plan:
            blocks.append("### 📝 Plan")
            blocks.append("")
            blocks.append(_to_blockquote(turn.plan))
            blocks.append("")

        answer_header = "### 🤖 Answer"
        metadata: list[str] = []
        if turn.total_tokens is not None:
            metadata.append(f"`🏷️ {_format_token_count(turn.total_tokens)} tokens`")
        if turn.duration_seconds is not None:
            metadata.append(f"`⌛ {_format_duration(turn.duration_seconds)}`")
        if turn.tool_call_count:
            metadata.append(f"`🧰 {turn.tool_call_count} tool call{'s' if turn.tool_call_count != 1 else ''}`")
        if metadata:
            answer_header += " — " + " — ".join(metadata)
        blocks.append(answer_header)
        blocks.append("")
        blocks.append(_format_answer_body(turn.answer))
        if index != len(turns):
            blocks.append("")
            blocks.append("---")
            blocks.append("")

    return "\n".join(blocks).rstrip() + "\n"


def _format_answer_body(text: str) -> str:
    stripped = text.strip()
    if not stripped:
        return "> _No final answer captured._"
    if _should_preserve_markdown(stripped):
        return stripped
    return _to_blockquote(stripped)


def _should_preserve_markdown(text: str) -> bool:
    stripped = text.lstrip()
    markdown_prefixes = ("#", "-", "*", "1.", "```", ">", "|", "::", "<details", "![", "[")
    return "\n\n" in stripped or stripped.startswith(markdown_prefixes)


def _to_blockquote(text: str) -> str:
    lines = text.strip().splitlines() or [""]
    return "\n".join("> " + line if line else ">" for line in lines)


def _extract_plan(text: str) -> str | None:
    match = PLAN_BLOCK_RE.search(text)
    if not match:
        return None
    return match.group(1).strip() or None


def _strip_plan_block(text: str) -> str:
    return PLAN_BLOCK_RE.sub("", text).strip()


def _extract_message_text(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for content in payload.get("content", []):
        if not isinstance(content, dict):
            continue
        content_type = content.get("type")
        if content_type in {"output_text", "input_text"}:
            text = content.get("text")
        elif content_type == "text":
            text = content.get("text")
            if isinstance(text, dict):
                text = text.get("value")
        else:
            text = None
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts).strip()


def _extract_total_tokens(payload: dict[str, Any]) -> int | None:
    if payload.get("type") != "token_count":
        return None
    info = payload.get("info")
    if not isinstance(info, dict):
        return None
    total_usage = info.get("total_token_usage")
    if not isinstance(total_usage, dict):
        return None
    total_tokens = total_usage.get("total_tokens")
    return total_tokens if isinstance(total_tokens, int) else None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_token_count(count: int) -> str:
    if count >= 1000:
        whole = count / 1000
        if whole.is_integer():
            return f"{int(whole)}k"
        return f"{whole:.1f}k"
    return str(count)


def _format_duration(seconds: int) -> str:
    minutes, remainder = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}min")
    if remainder and not hours:
        parts.append(f"{remainder}s")
    return " ".join(parts) if parts else "0s"
