# ============================================================
# PyMC - 文本组件 (Text Component)
# ============================================================

"""
Text component helpers.

Every chat-like payload in the protocol carries a *text component*:

  * 1.20.3+ (protocol >= 765): nameless network NBT
  * older versions:            a JSON string

Callers may pass a plain string, a component dict, a list of components or a
JSON string describing a component; ``encode_component`` picks the right wire
format for the connection. ``plain_text`` renders a component for the server
console using the bundled en_us table, the way the vanilla server logs
``Steve joined the game`` for ``multiplayer.player.joined``.
"""

from __future__ import annotations

import json
import re
from typing import Any

from protocol.data_types import write_string
from protocol.nbt import NbtByte, encode_nbt

NBT_TEXT_PROTOCOL = 765  # 1.20.3: text components became NBT on the wire

_COMPONENT_KEYS = ("text", "translate", "selector", "score", "keybind", "nbt")
_LEGACY_PREFIX = "[PyMC] "
_FORMAT_CODE_RE = re.compile("§[0-9a-fk-orA-FK-OR]")
_BOOL_STYLE_KEYS = ("bold", "italic", "underlined", "strikethrough", "obfuscated", "interpret")


def to_component(message: Any) -> dict:
    """Normalise anything message-like into a text component dict."""
    if isinstance(message, dict):
        return message
    if isinstance(message, (list, tuple)):
        parts = [to_component(part) for part in message]
        if not parts:
            return {"text": ""}
        if len(parts) == 1:
            return parts[0]
        return {"text": "", "extra": parts}
    text = "" if message is None else str(message)
    stripped = text.lstrip()
    if stripped.startswith("{") and stripped.endswith("}"):
        try:
            parsed = json.loads(stripped)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict) and any(key in parsed for key in _COMPONENT_KEYS):
            return parsed
    if text.startswith(_LEGACY_PREFIX):
        text = text[len(_LEGACY_PREFIX):]
    return {"text": text}


def translate(key: str, *args: Any, **style: Any) -> dict:
    """Build a translatable component: ``translate("chat.type.text", name, msg)``."""
    component: dict = {"translate": key}
    if args:
        component["with"] = [
            arg if isinstance(arg, dict) else {"text": str(arg)} for arg in args
        ]
    component.update(style)
    return component


def text(value: str, **style: Any) -> dict:
    component = {"text": str(value)}
    component.update(style)
    return component


def player_name(conn) -> dict:
    """Vanilla-style clickable/hoverable player name."""
    name = getattr(conn, "username", "") or "?"
    component: dict = {
        "text": name,
        "insertion": name,
        "clickEvent": {"action": "suggest_command", "value": f"/tell {name} "},
    }
    uuid = getattr(conn, "uuid", None)
    if uuid is not None:
        component["hoverEvent"] = {
            "action": "show_entity",
            "contents": {
                "type": "minecraft:player",
                "id": str(uuid),
                "name": {"text": name},
            },
        }
    return component


# ------------------------------------------------------------------
# Wire encoding
# ------------------------------------------------------------------

def _nbt_ready(value: Any, in_list: bool = False) -> Any:
    """Make a component tree encodable as NBT (homogeneous lists, byte bools)."""
    if isinstance(value, bool):
        return {"text": "true" if value else "false"} if in_list else NbtByte(1 if value else 0)
    if isinstance(value, dict):
        return {str(k): _nbt_ready(v) for k, v in value.items() if v is not None}
    if isinstance(value, (list, tuple)):
        return [_nbt_ready(v, in_list=True) for v in value]
    if in_list and not isinstance(value, dict):
        return {"text": str(value)}
    if isinstance(value, float):
        return value
    return value


def component_to_nbt(message: Any) -> bytes:
    component = to_component(message)
    if set(component.keys()) == {"text"} and isinstance(component["text"], str):
        # A bare string tag is a valid (and the smallest) text component.
        return encode_nbt(component["text"], with_type=True)
    return encode_nbt(_nbt_ready(component), with_type=True)


def component_to_json(message: Any) -> str:
    return json.dumps(to_component(message), ensure_ascii=False, separators=(",", ":"))


def encode_component(message: Any, protocol_version: int) -> bytes:
    """Encode a text component for the given protocol version."""
    if protocol_version >= NBT_TEXT_PROTOCOL:
        return component_to_nbt(message)
    return write_string(component_to_json(message))


# ------------------------------------------------------------------
# Console rendering
# ------------------------------------------------------------------

_ARG_RE = re.compile(r"%(?:(\d+)\$)?([s%d])")


def _format_translation(template: str, args: list[str]) -> str:
    counter = 0

    def repl(match: re.Match) -> str:
        nonlocal counter
        if match.group(2) == "%":
            return "%"
        if match.group(1):
            index = int(match.group(1)) - 1
        else:
            index = counter
            counter += 1
        return args[index] if 0 <= index < len(args) else ""

    return _ARG_RE.sub(repl, template)


def plain_text(message: Any, strip_formatting: bool = True) -> str:
    """Render a component as plain text (en_us) for logs and RCON."""
    component = to_component(message)
    out = []

    if "text" in component:
        out.append(str(component.get("text", "")))
    elif "translate" in component:
        from protocol.gamedata import language
        key = str(component["translate"])
        template = language().get(key, component.get("fallback", key))
        args = [plain_text(arg, strip_formatting) for arg in component.get("with", [])]
        out.append(_format_translation(template, args))
    elif "selector" in component:
        out.append(str(component["selector"]))
    elif "keybind" in component:
        out.append(str(component["keybind"]))

    for extra in component.get("extra", []) or []:
        out.append(plain_text(extra, strip_formatting))

    rendered = "".join(out)
    if strip_formatting:
        rendered = _FORMAT_CODE_RE.sub("", rendered)
    return rendered
