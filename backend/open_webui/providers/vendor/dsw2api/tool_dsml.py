"""
DSML — DeepSeek Markup Language 工具调用格式解析器

格式：
  <|DSML|tool_calls>
    <|DSML|invoke name="TOOL_NAME">
      <|DSML|parameter name="ARG_NAME"><![CDATA[VALUE]]></|DSML|parameter>
    </|DSML|invoke>
  </|DSML|tool_calls>
"""
import json
import re
import uuid
from typing import Any

_CDATA_OPEN = "<![CDATA["
_CDATA_CLOSE = "]]>"
_WRAPPERS = {'tool_calls', 'tool_call', 'calls'}
_DSML_PREFIX = r'[|｜]+\s*DSML\s*[|｜]+'
# Only try the beginning of a separator run. Retrying at every pipe would
# make a long ordinary run without DSML quadratic in a single search.
_DSML_START = re.compile(r'(?:<|(?<![|｜]))' + _DSML_PREFIX, re.IGNORECASE | re.ASCII)
_DSML_PARTIAL = re.compile(r'<?[|｜]+\s*(?:D(?:S(?:M(?:L\s*)?)?)?)?\Z', re.IGNORECASE | re.ASCII)
_PREFIX_CANDIDATES = re.compile(r'<|(?<![|｜])[|｜]')
# Consume CDATA as one token, so markup inside commands stays literal.
_CONTENTS = r'((?:<!\[CDATA\[.*?\]\]>|(?!<!\[CDATA\[).)*?)'
_TAG_TOKENS = re.compile(
    r'<!\[CDATA\[.*?(?:\]\]>|$)|<(/?)(?:' + _DSML_PREFIX + r'\s*)?'
    r'(tool_calls|tool_call|calls|invoke)\b[^>]*>', re.DOTALL | re.IGNORECASE)


def find_dsml_start(text: str) -> int:
    """Find a complete DSML marker using the same separators as block closure."""
    match = _DSML_START.search(text)
    return match.start() if match else -1


def dsml_prefix_tail(text: str) -> int | None:
    """Original offset of an incomplete marker that a later chunk can finish."""
    for candidate in _PREFIX_CANDIDATES.finditer(text):
        if _DSML_PARTIAL.fullmatch(text, candidate.start()):
            return candidate.start()
    return None


def tool_block_end(text: str) -> int | None:
    """Original-text end offset of the first closed wrapper/bare invoke."""
    outer = None
    for match in _TAG_TOKENS.finditer(text):
        closing, name = match.groups()
        if name is None: continue  # CDATA
        name = name.lower()
        name = 'tool_calls' if name in _WRAPPERS else name
        if outer is None:
            if closing: return None
            outer = name
        elif closing and name == outer:
            return match.end()
    return None


def strip_dsml_markup(text: str) -> str:
    """去除 DSML 前缀，保留原始 XML 结构。"""
    if not text:
        return text
    parts = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith(_CDATA_OPEN, i):
            close = text.find(_CDATA_CLOSE, i + len(_CDATA_OPEN))
            if close == -1:
                parts.append(text[i:])
                break
            parts.append(text[i:close + len(_CDATA_CLOSE)])
            i = close + len(_CDATA_CLOSE)
            continue
        if c != '<':
            parts.append(c)
            i += 1
            continue
        end = text.find('>', i)
        if end == -1:
            parts.append(text[i:])
            break
        inner = text[i + 1:end]
        rest = inner[1:] if inner.startswith('/') else inner
        # Check for |DSML| prefix (with or without leading <)
        j = 0
        dsml = False
        while j < len(rest):
            ch = rest[j]
            if ch in ('|', '｜', ' ', '\t', '\r', '\n'):
                j += 1
                if ch in ('|', '｜'):
                    dsml = True
            elif rest[j:j+4].lower() == 'dsml':
                j += 4
                dsml = True
            else:
                break
        if dsml or rest.lower() in _WRAPPERS:
            name_end = j
            while name_end < len(rest) and (rest[name_end].isalnum() or rest[name_end] == '_'):
                name_end += 1
            tag_name = rest[j:name_end].lower()
            if tag_name in _WRAPPERS or tag_name in ("invoke", "parameter"):
                prefix = '</' if inner.startswith('/') else '<'
                canonical = 'tool_calls' if tag_name in _WRAPPERS else tag_name
                parts.append(prefix + canonical + rest[name_end:] + '>')
                i = end + 1
                continue
        parts.append(text[i:end + 1])
        i = end + 1
    return ''.join(parts)


def extract_cdata(text: str) -> str:
    text = text.strip()
    if text.startswith(_CDATA_OPEN) and text.endswith(_CDATA_CLOSE):
        inner = text[len(_CDATA_OPEN):-len(_CDATA_CLOSE)]
        return inner
    return text


def parse_dsml_tool_calls(text: str, tool_names: list[str] | None = None) -> tuple[list[dict], str]:
    """从文本中解析 DSML 工具调用，返回 (tool_calls, cleaned_text)"""
    if not text:
        return [], text

    normalized = strip_dsml_markup(text)
    tool_calls = []

    # Wrapper aliases have already been normalized to tool_calls.
    blocks = re.findall(r"<tool_calls>" + _CONTENTS + r"</tool_calls>",
                        normalized, re.DOTALL | re.IGNORECASE)

    if not blocks:
        # 裸 <invoke> 无外层 wrapper
        invoke_bare = re.findall(
            r"<invoke\s+name=[\"']([^\"']+)[\"']>" + _CONTENTS + r"</invoke>",
            normalized, re.DOTALL | re.IGNORECASE
        )
        for name, inner in invoke_bare:
            tc = _format_tool_call(name.strip(), _parse_parameters(inner))
            if tc:
                tool_calls.append(tc)

    for block_text in blocks:
        for name, inner in re.findall(
            r"<invoke\s+name=[\"']([^\"']+)[\"']>" + _CONTENTS + r"</invoke>",
            block_text, re.DOTALL | re.IGNORECASE
        ):
            tc = _format_tool_call(name.strip(), _parse_parameters(inner))
            if tc:
                tool_calls.append(tc)

    cleaned = _clean_dsml_text(normalized)
    return tool_calls, cleaned


def _parse_parameters(inner_text: str) -> dict:
    args = {}
    for m in re.finditer(
        r"<parameter\b([^>]*)>" + _CONTENTS + r"</parameter>",
        inner_text, re.DOTALL | re.IGNORECASE
    ):
        attributes = {name.lower(): value for name, value in
            re.findall(r'''([\w]+)\s*=\s*["']([^"']*)["']''', m.group(1))}
        key = attributes.get('name', '').strip()
        if not key: continue
        raw = m.group(2)
        if attributes.get('string', '').lower() == 'true':
            trimmed = raw.strip()
            args[key] = extract_cdata(trimmed) if trimmed.startswith(_CDATA_OPEN) and trimmed.endswith(_CDATA_CLOSE) else raw
            continue
        val_raw = extract_cdata(raw.strip())
        try:
            val = json.loads(val_raw)
        except (json.JSONDecodeError, ValueError):
            val = _auto_type(val_raw)
        args[key] = val
    return args


def _auto_type(val: str) -> Any:
    if val.lower() in ("true",): return True
    if val.lower() in ("false",): return False
    if val.lower() in ("null", "none"): return None
    try: return int(val)
    except ValueError: pass
    try: return float(val)
    except ValueError: pass
    return val


def _format_tool_call(name: str, args: dict) -> dict | None:
    if not name:
        return None
    return {
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(args, ensure_ascii=False)},
    }


def _clean_dsml_text(text: str) -> str:
    text = re.sub(r"<tool_calls>" + _CONTENTS + r"</tool_calls>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<invoke[^>]*>" + _CONTENTS + r"</invoke>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<parameter[^>]*>" + _CONTENTS + r"</parameter>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<!\[CDATA\[.*?\]\]>", "", text, flags=re.DOTALL)
    text = re.sub(r"\[citation:\d+\]", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def format_tool_calls_for_prompt(tool_calls_raw: Any) -> str:
    """将 OpenAI tool_calls 格式化为 DSML 提示词格式。"""
    if isinstance(tool_calls_raw, str):
        try:
            tool_calls_raw = json.loads(tool_calls_raw)
        except (json.JSONDecodeError, ValueError):
            return ""
    if not isinstance(tool_calls_raw, list) or not tool_calls_raw:
        return ""

    blocks = []
    for tc in tool_calls_raw:
        if not isinstance(tc, dict):
            continue
        fn = tc.get("function", {})
        name = tc.get("name") or fn.get("name", "")
        if not name:
            continue
        args = tc.get("arguments") or tc.get("input") or fn.get("arguments") or "{}"
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except (json.JSONDecodeError, ValueError):
                pass
        params = _format_params_dsml(args)
        block = f'  <|DSML|invoke name="{_escape_xml_attr(name)}">'
        if params.strip():
            block += "\n" + params + "\n  </|DSML|invoke>"
        else:
            block += "</|DSML|invoke>"
        blocks.append(block)

    if not blocks:
        return ""
    return "<|DSML|tool_calls>\n" + "\n".join(blocks) + "\n</|DSML|tool_calls>"


def _format_params_dsml(args: Any, indent: str = "    ") -> str:
    if isinstance(args, dict):
        if not args:
            return ""
        return "\n".join(_format_param_node(k, v, indent) for k, v in sorted(args.items()))
    elif isinstance(args, list):
        return "\n".join(_format_param_node("item", item, indent) for item in args)
    elif isinstance(args, str):
        return f'{indent}<|DSML|parameter name="content">{_cdata(args)}</|DSML|parameter>'
    else:
        return f'{indent}<|DSML|parameter name="value">{str(args)}</|DSML|parameter>'


def _format_param_node(name: str, value: Any, indent: str) -> str:
    open_tag = f'<|DSML|parameter name="{_escape_xml_attr(name)}">'
    close = "</|DSML|parameter>"
    if value is None:
        return f"{indent}{open_tag}{close}"
    if isinstance(value, (dict, list)):
        serialized = json.dumps(value, ensure_ascii=False)
        return f"{indent}{open_tag}{_cdata(serialized)}{close}"
    if isinstance(value, (bool, int, float)):
        return f"{indent}{open_tag}{str(value)}{close}"
    return f"{indent}{open_tag}{_cdata(str(value))}{close}"


def _cdata(text: str) -> str:
    if "]]>" in text:
        text = text.replace("]]>", "]]]]><![CDATA[>")
    return f"<![CDATA[{text}]]>"


def _escape_xml_attr(text: str) -> str:
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;").replace(">", "&gt;")


def build_dsml_tool_prompt(tools: list[dict], tool_choice: str | dict | None = None) -> str:
    """构建工具调用提示词，附加到 system message。"""
    if not tools:
        return ""

    choice_instruction = ""
    if tool_choice is not None:
        if tool_choice == "none":
            return ""
        elif tool_choice == "required":
            choice_instruction = (
                "You MUST call at least one of the available tools. "
                "Do not answer the user directly — always use a tool call.\n\n"
            )
        elif isinstance(tool_choice, dict):
            fn_name = tool_choice.get("function", {}).get("name", "")
            if fn_name:
                choice_instruction = (
                    f"You MUST call the tool '{fn_name}'. "
                    f"Do not call any other tool and do not answer the user directly.\n\n"
                )
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "required", "none"):
            choice_instruction = (
                f"You MUST call the tool '{tool_choice}'. "
                f"Do not call any other tool and do not answer the user directly.\n\n"
            )

    prompt = """You have access to tools. When you need to call a tool, respond with EXACTLY this format — no markdown fences, no extra text before or after:

<|DSML|tool_calls>
  <|DSML|invoke name="TOOL_NAME">
    <|DSML|parameter name="PARAMETER_NAME"><![CDATA[PARAMETER_VALUE]]></|DSML|parameter>
  </|DSML|invoke>
</|DSML|tool_calls>

RULES:
- Use <|DSML|tool_calls> wrapper with one or more <|DSML|invoke> entries
- Tool name in invoke name attribute
- String values MUST use <![CDATA[...]]>
- Numbers, booleans, null stay plain text
- First non-whitespace character must be < for tool calls
- NO explanations, NO markdown fences, NO extra text

""" + choice_instruction + "Available tools:\n"
    for tool in tools:
        fn = tool.get("function", {})
        name = fn.get("name") or tool.get("name", "")
        desc = (fn.get("description") or tool.get("description", "")).split("\n")[0].strip()
        prompt += f"  - {name}: {desc}\n" if desc and name else f"  - {name}\n"
    return prompt.strip()
