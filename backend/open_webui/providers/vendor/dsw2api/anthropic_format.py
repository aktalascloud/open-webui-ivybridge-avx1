"""
Anthropic /v1/messages format adapter for DeepSeek Chat proxy.
Maps Anthropic request/response format to/from the internal token stream.
"""
import json
import time
import uuid
from typing import Optional, Any

from pydantic import BaseModel

from .tool_dsml import (
    parse_dsml_tool_calls,
    format_tool_calls_for_prompt,
    build_dsml_tool_prompt,
)
from .tool_sieve import StreamSieve

# ---- Pydantic models for Anthropic request ----

class AnthropicThinkingParam(BaseModel):
    type: str = "enabled"
    budget_tokens: Optional[int] = None


class AnthropicToolDef(BaseModel):
    name: str
    description: Optional[str] = ""
    input_schema: Optional[dict] = None


class ContentBlock(BaseModel):
    type: str
    source: Optional[dict] = None
    text: Optional[str] = None
    id: Optional[str] = None
    name: Optional[str] = None
    input: Optional[dict] = None
    tool_use_id: Optional[str] = None
    content: Optional[Any] = None
    thinking: Optional[str] = None
    signature: Optional[str] = None


class AnthropicMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str | list[ContentBlock]


class AnthropicRequest(BaseModel):
    model: Optional[str] = "claude-3-5-sonnet-20241022"
    max_tokens: Optional[int] = None
    messages: list[AnthropicMessage]
    system: Optional[str | list[ContentBlock]] = None
    stream: Optional[bool] = False
    thinking: Optional[AnthropicThinkingParam] = None
    tools: Optional[list[AnthropicToolDef]] = None
    metadata: Optional[dict] = None
    stop_sequences: Optional[list[str]] = None
    temperature: Optional[float] = None
    top_p: Optional[float] = None


# ---- Prompt building ----

def _extract_text_from_blocks(content: Any) -> str:
    """Extract plain text from Anthropic content (string or content block list)."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    texts = []
    for block in content:
        if isinstance(block, dict):
            t = block.get("type", "")
            if t == "text":
                texts.append(block.get("text", ""))
            elif t == "tool_result":
                tc = block.get("content", "")
                texts.append(tc if isinstance(tc, str) else _extract_text_from_blocks(tc))
        elif isinstance(block, ContentBlock):
            if block.type == "text":
                texts.append(block.text or "")
            elif block.type == "tool_result":
                texts.append(block.content if isinstance(block.content, str) else _extract_text_from_blocks(block.content))
    return "".join(texts)


def _tool_use_blocks_to_dsml(content: Any) -> str:
    """Convert Anthropic tool_use blocks to DSML format string."""
    tool_uses = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_uses.append(block)
            elif isinstance(block, ContentBlock) and block.type == "tool_use":
                tool_uses.append({"id": block.id, "name": block.name, "input": block.input})
    if not tool_uses:
        return ""
    openai_tcs = []
    for tu in tool_uses:
        openai_tcs.append({
            "id": tu.get("id") or f"call_{uuid.uuid4().hex[:24]}",
            "type": "function",
            "function": {
                "name": tu.get("name", ""),
                "arguments": json.dumps(tu.get("input", {}), ensure_ascii=False),
            },
        })
    return format_tool_calls_for_prompt(openai_tcs)


def _has_tool_use(content: Any) -> bool:
    """Check if content contains tool_use blocks."""
    if not isinstance(content, list):
        return False
    for block in content:
        t = block.type if isinstance(block, ContentBlock) else (block.get("type") if isinstance(block, dict) else "")
        if t == "tool_use":
            return True
    return False


def _extract_system_text(system: Any) -> str:
    if system is None:
        return ""
    if isinstance(system, str):
        return system
    return _extract_text_from_blocks(system)


def build_anthropic_prompt(
    messages: list[dict],
    tools: list[dict] | None = None,
    system_str: str | None = None,
) -> str:
    """Convert Anthropic messages to internal prompt format."""
    parts = []

    tool_prompt_text = None
    if tools:
        tool_prompt_text = build_dsml_tool_prompt(tools)

    if system_str:
        text = system_str
        if tool_prompt_text:
            text = text + "\n\n" + tool_prompt_text if text else tool_prompt_text
        parts.append(f"System: {text}")

    for m in messages:
        role = m.get("role", "")
        content = m.get("content", "")

        if role == "user":
            # Check for tool_result blocks within user content
            if isinstance(content, list):
                text_parts = []
                for block in content:
                    if isinstance(block, dict):
                        bt = block.get("type", "")
                        if bt == "tool_result":
                            tc = block.get("content", "")
                            tool_use_id = block.get("tool_use_id", "")
                            prefix = f"Tool result (call_id={tool_use_id}):" if tool_use_id else "Tool result:"
                            if isinstance(tc, str):
                                text_parts.append(f"{prefix} {tc}")
                            elif isinstance(tc, list):
                                text_parts.append(f"{prefix} {_extract_text_from_blocks(tc)}")
                        elif bt == "text":
                            text_parts.append(block.get("text", ""))
                    elif isinstance(block, ContentBlock):
                        if block.type == "tool_result":
                            tc = block.content
                            prefix = f"Tool result (call_id={block.tool_use_id}):" if block.tool_use_id else "Tool result:"
                            if isinstance(tc, str):
                                text_parts.append(f"{prefix} {tc}")
                            elif isinstance(tc, list):
                                text_parts.append(f"{prefix} {_extract_text_from_blocks(tc)}")
                        elif block.type == "text":
                            text_parts.append(block.text or "")
                if text_parts:
                    parts.append(f"User: {''.join(text_parts)}")
            else:
                parts.append(f"User: {content}")
        elif role == "assistant":
            segs = []
            if isinstance(content, str):
                segs.append(content)
            elif isinstance(content, list):
                text = _extract_text_from_blocks(content)
                if text:
                    segs.append(text)
                if _has_tool_use(content):
                    dsml = _tool_use_blocks_to_dsml(content)
                    if dsml:
                        segs.append(dsml)
            if segs:
                parts.append(f"Assistant: {' '.join(segs)}")

    if tool_prompt_text and not system_str:
        parts.insert(0, f"System: {tool_prompt_text}")

    return "\n".join(parts)


# ---- Tool call format conversion ----

def _dsml_toolcalls_to_anthropic(tool_calls: list[dict]) -> list[dict]:
    """Convert DSML/OpenAI tool_calls format to Anthropic tool_use blocks."""
    blocks = []
    for tc in tool_calls:
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except (json.JSONDecodeError, ValueError):
            args = {}
        blocks.append({
            "type": "tool_use",
            "id": tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}"),
            "name": fn.get("name", ""),
            "input": args,
        })
    return blocks


# ---- Anthropic SSE helpers ----

def _msg_id() -> str:
    return f"msg_{uuid.uuid4().hex[:24]}"


def _message_start(msg_id: str, model: str) -> str:
    msg = {
        "id": msg_id, "type": "message", "role": "assistant",
        "content": [], "model": model,
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": -1, "output_tokens": -1},
    }
    return f"event: message_start\ndata: {json.dumps({'type': 'message_start', 'message': msg}, ensure_ascii=False)}\n\n"


def _block_start(index: int, block_type: str, **kw) -> str:
    block = {"type": block_type, **kw}
    return f"event: content_block_start\ndata: {json.dumps({'type': 'content_block_start', 'index': index, 'content_block': block}, ensure_ascii=False)}\n\n"


def _block_delta(index: int, delta_type: str, **kw) -> str:
    delta = {"type": delta_type, **kw}
    return f"event: content_block_delta\ndata: {json.dumps({'type': 'content_block_delta', 'index': index, 'delta': delta}, ensure_ascii=False)}\n\n"


def _block_stop(index: int) -> str:
    return f"event: content_block_stop\ndata: {json.dumps({'type': 'content_block_stop', 'index': index})}\n\n"


def _message_delta(stop_reason: str = "end_turn") -> str:
    return f"event: message_delta\ndata: {json.dumps({'type': 'message_delta', 'delta': {'stop_reason': stop_reason, 'stop_sequence': None}, 'usage': {'output_tokens': -1}}, ensure_ascii=False)}\n\n"


def _message_stop() -> str:
    return "event: message_stop\ndata: {}\n\n"


# ---- Non-streaming response builder ----

def build_nonstream_response(
    msg_id: str, model: str,
    content_text: str | None,
    tool_calls: list[dict] | None = None,
    thinking_text: str | None = None,
) -> dict:
    """Build Anthropic non-streaming response dict.

    Order of content blocks follows Anthropic's convention:
      1. ``thinking`` (if any) — appears first when expert mode was used.
      2. ``text`` (if any)
      3. ``tool_use`` blocks (if any)

    The previous version accepted a ``need_thinking_content`` flag but
    never actually returned thinking. The thinking text is now passed
    explicitly via ``thinking_text`` from the caller.
    """
    content = []
    if thinking_text:
        content.append({"type": "thinking", "thinking": thinking_text})
    if content_text:
        content.append({"type": "text", "text": content_text})
    if tool_calls:
        content.extend(_dsml_toolcalls_to_anthropic(tool_calls))

    return {
        "id": msg_id, "type": "message", "role": "assistant",
        "content": content, "model": model,
        "stop_reason": "tool_use" if tool_calls else "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": -1, "output_tokens": -1},
    }


# ---- Streaming response generator ----

def stream_response(
    msg_id: str, model: str, token_stream,
    tool_names: list[str],
    thinking_mode: bool = False,
):
    """Generate Anthropic SSE events from adapter token stream."""
    yield _message_start(msg_id, model)

    idx = 0          # current content block index
    in_thinking = False
    in_text = False
    stop_reason = "end_turn"

    def _close():
        nonlocal in_thinking, in_text, idx
        if in_thinking or in_text:
            yield _block_stop(idx)
            idx += 1
            in_thinking = False
            in_text = False

    def _open_text():
        nonlocal in_text
        yield _block_start(idx, "text", text="")
        in_text = True

    def _open_thinking():
        nonlocal in_thinking
        yield _block_start(idx, "thinking", thinking="")
        in_thinking = True

    parse_fn = lambda text: parse_dsml_tool_calls(text, tool_names)
    sieve = StreamSieve(parse_fn=parse_fn)
    full_buf = ""

    for token in token_stream:
        if isinstance(token, dict):
            tt = token.get("__type")
            if tt == "status":
                if token["status"] == "FINISHED":
                    break
                continue
            elif tt == "thinking":
                content = token.get("content", "")
                if content:
                    if in_text:
                        yield from _close()
                    if not in_thinking:
                        yield from _open_thinking()
                    yield _block_delta(idx, "thinking_delta", thinking=content)
                continue

        # Normal text token — feed to sieve
        full_buf += token
        for evt in sieve.feed(token):
            if evt.type == "text" and evt.data:
                if in_thinking:
                    yield from _close()
                if not in_text:
                    yield from _open_text()
                yield _block_delta(idx, "text_delta", text=evt.data)
            elif evt.type == "tool_calls":
                yield from _close()
                yield from _emit_tool_use_blocks(evt.data, idx)
                idx += len(evt.data)
                yield _message_delta("tool_use")
                yield _message_stop()
                return

    # Flush sieve
    for evt in sieve.flush():
        if evt.type == "text" and evt.data:
            if in_thinking:
                yield from _close()
            if not in_text:
                yield from _open_text()
            yield _block_delta(idx, "text_delta", text=evt.data)
        elif evt.type == "tool_calls":
            yield from _close()
            yield from _emit_tool_use_blocks(evt.data, idx)
            yield _message_delta("tool_use")
            yield _message_stop()
            return

    # Fallback: full-buf parse
    if full_buf:
        tc_result, _ = parse_dsml_tool_calls(full_buf, tool_names)
        if tc_result:
            yield from _close()
            yield from _emit_tool_use_blocks(tc_result, idx)
            yield _message_delta("tool_use")
            yield _message_stop()
            return

    # Close remaining blocks and finish
    yield from _close()
    yield _message_delta(stop_reason)
    yield _message_stop()


def _emit_tool_use_blocks(tool_calls: list[dict], start_index: int):
    """Yield Anthropic SSE events for tool_use content blocks."""
    for i, tc in enumerate(tool_calls):
        fn = tc.get("function", {})
        args_str = fn.get("arguments", "{}")
        try:
            args = json.loads(args_str)
        except (json.JSONDecodeError, ValueError):
            args = {}
        tool_id = tc.get("id", f"toolu_{uuid.uuid4().hex[:24]}")
        yield _block_start(start_index + i, "tool_use", id=tool_id,
                           name=fn.get("name", ""), input={})
        json_input = json.dumps(args, ensure_ascii=False)
        yield _block_delta(start_index + i, "input_json_delta", partial_json=json_input)
        yield _block_stop(start_index + i)
