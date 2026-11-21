# ============================================================
# PyMC - Command Framework
# Command registration, parsing, dispatch, context, and
# argument types for the Minecraft command system
# ============================================================

"""
Command framework providing structured command registration,
argument parsing, permission checking, tab completion, and
execution context with helper methods for common operations.

Result codes:
  SUCCESS = 1   Command executed successfully
  FAILURE = 0   Command failed (invalid args, target not found, etc.)
  ERROR   = -1  Internal error or no permission
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import math
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

logger = logging.getLogger("PyMC.命令")


# --- Result codes ---
SUCCESS = 1
FAILURE = 0
ERROR = -1


# ------------------------------------------------------------------
# Console output (server console / RCON)
# ------------------------------------------------------------------

_console_capture: contextvars.ContextVar = contextvars.ContextVar(
    "pymc_console_capture", default=None)
_console_source: contextvars.ContextVar = contextvars.ContextVar(
    "pymc_console_source", default="Server")


def console_source_name() -> str:
    """Display name of the non-player command source ("Server" or "Rcon")."""
    return _console_source.get()


def console_output(message) -> None:
    """Print command feedback for a non-player source.

    On the server console this is a normal log line; while an RCON command
    runs the text is captured and returned to the RCON client instead.
    """
    from protocol.text import plain_text
    text = plain_text(message)
    captured = _console_capture.get()
    if captured is not None:
        captured.append(text)
    else:
        logging.getLogger("minecraft.server").info(text)


@contextlib.contextmanager
def capture_console_output(source: str = "Rcon"):
    """Collect console feedback produced inside the ``with`` block."""
    lines: list[str] = []
    capture_token = _console_capture.set(lines)
    source_token = _console_source.set(source)
    try:
        yield lines
    finally:
        _console_capture.reset(capture_token)
        _console_source.reset(source_token)


@dataclass
class CommandContext:
    """Context passed to every command execution.

    Provides helper methods for common operations like replying to
    the sender, resolving selectors, parsing coordinates, and
    checking permissions.
    """

    sender: Any           # Connection or None (console)
    command: 'Command'    # The resolved command
    arguments: dict       # Parsed arguments
    input_string: str     # Raw input string
    server: Any           # MinecraftServer reference
    source_name: str = "" # Display name of sender

    # ---- Convenience properties ----

    @property
    def raw_tokens(self) -> list[str]:
        """The raw tokenized input (including command name)."""
        return self.arguments.get("_raw_tokens", [])

    @property
    def args(self) -> list[str]:
        """Arguments after the command name."""
        tokens = self.raw_tokens
        return tokens[1:] if len(tokens) > 1 else []

    @property
    def remaining_input(self) -> str:
        """The raw input after the command name."""
        tokens = self.raw_tokens
        if len(tokens) <= 1:
            return ""
        return self.input_string[len(tokens[0]) + 1:] if self.input_string.startswith(tokens[0]) else " ".join(tokens[1:])

    # ---- Sender helpers ----

    def get_sender_position(self) -> tuple[float, float, float]:
        """Get the sender's position, defaulting to world spawn."""
        if self.sender and hasattr(self.sender, 'x'):
            return (self.sender.x, self.sender.y, self.sender.z)
        spawn = getattr(self.server, 'spawn_position', (0, 100, 0))
        return (float(spawn[0]), float(spawn[1]), float(spawn[2]))

    # ---- Messaging ----

    async def reply(self, text):
        """Send a reply (string or text component) to the command sender."""
        from handlers.play.chat import send_system_message
        if self.sender is not None:
            await send_system_message(self.sender, text)
        else:
            console_output(text)

    async def broadcast(self, text):
        """Broadcast a message to all online players."""
        self.server.broadcast_system_message(text)

    @property
    def source_component(self) -> dict:
        """Text component naming the command source (player name or "Server")."""
        if self.sender is not None:
            from protocol.text import player_name
            return player_name(self.sender)
        return {"text": console_source_name()}

    async def success(self, message, broadcast_to_ops: bool = True):
        """
        Vanilla ``sendSuccess``: feedback to the source, plus (optionally) the
        gray italic ``[Source: message]`` notification to other operators and
        the console log line.
        """
        from protocol.text import to_component, plain_text
        component = to_component(message)
        gamerules = getattr(self.server, "gamerules", {})
        if self.sender is None:
            console_output(component)
        elif gamerules.get("sendCommandFeedback", True):
            await self.reply(component)
        if not broadcast_to_ops:
            return

        admin = {"translate": "chat.type.admin",
                 "with": [self.source_component, component],
                 "color": "gray", "italic": True}
        config = getattr(self.server, "config", {})
        if self.sender is None:
            key = ("broadcast-rcon-to-ops" if console_source_name() == "Rcon"
                   else "broadcast-console-to-ops")
            notify_ops = bool(config.get(key, True))
        else:
            notify_ops = True
            if gamerules.get("logAdminCommands", True):
                logging.getLogger("minecraft.server").info(plain_text(admin))
        if notify_ops and gamerules.get("sendCommandFeedback", True):
            from handlers.play.chat import send_system_message
            permissions = self.server.permissions
            for player in self.server.get_online_players():
                if player is self.sender or not permissions.is_op(player.username):
                    continue
                await send_system_message(player, admin)

    async def fail(self, message) -> int:
        """Vanilla ``sendFailure``: a red error message; returns FAILURE."""
        from protocol.text import to_component
        component = dict(to_component(message))
        component.setdefault("color", "red")
        await self.reply(component)
        return FAILURE

    # ---- Permission ----

    def has_permission(self, node: str) -> bool:
        """Check if sender has a permission node."""
        if self.sender is None:
            return True  # Console has all permissions
        return self.server.permissions.has_permission(self.sender.username, node)

    # ---- Selector resolution ----

    def resolve_selector(self, selector_str: str) -> list:
        """Resolve an entity selector to a list of targets.

        Supports:
          - Player names: "Steve"
          - Vanilla selectors: @a, @p, @e, @s, @r
          - Selectors with args: @a[distance=..10,gamemode=creative]
        """
        from commands.selector import resolve_selector
        return resolve_selector(self.server, self.sender, selector_str)

    def resolve_one_target(self, selector_str: str, fallback_to_self: bool = False):
        """Resolve a selector to a single target. Returns None if not found."""
        targets = self.resolve_selector(selector_str)
        if targets:
            return targets[0]
        # Try as player name
        player = self.server.find_player(selector_str)
        if player:
            return player
        if fallback_to_self and self.sender:
            return self.sender
        return None

    # ---- Coordinate parsing ----

    def parse_coordinates(self, tokens: list[str], start: int = 0) -> tuple[float, float, float] | None:
        """Parse three coordinate values from tokens starting at the given index.

        Supports relative (~) and local (^) notation.
        Returns absolute (x, y, z) or None on failure.
        """
        if start + 2 >= len(tokens):
            return None
        try:
            from commands.arguments import parse_coordinate, resolve_coordinate
            bx, by, bz = self.get_sender_position()
            px = parse_coordinate(tokens[start])
            py = parse_coordinate(tokens[start + 1])
            pz = parse_coordinate(tokens[start + 2])
            return (
                resolve_coordinate(px, bx),
                resolve_coordinate(py, by),
                resolve_coordinate(pz, bz),
            )
        except (ValueError, IndexError):
            return None

    def parse_int_coordinates(self, tokens: list[str], start: int = 0) -> tuple[int, int, int] | None:
        """Like parse_coordinates but rounds to int."""
        result = self.parse_coordinates(tokens, start)
        if result is None:
            return None
        return (int(math.floor(result[0])), int(math.floor(result[1])), int(math.floor(result[2])))

    # ---- Argument access ----

    def arg(self, name: str, default: Any = None) -> Any:
        """Get a named argument value, with optional default."""
        return self.arguments.get(name, default)

class Command:
    """
    Represents a registered command with metadata and execution handler.
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        usage: str = "",
        aliases: list[str] | None = None,
        permission: str = "",
        arguments: list['ArgumentType'] | None = None,
        category: str = "general",
    ):
        self.name = name
        self.description = description
        self.usage = usage
        self.aliases = aliases or []
        self.permission = permission
        self.arguments = arguments or []
        self.category = category
        self._execute_func: Callable[[CommandContext], Awaitable[int]] | None = None
        self._suggest_func: Callable[[CommandContext], list[str]] | None = None

    def execute(self, func: Callable[[CommandContext], Awaitable[int]]):
        """Decorator-style: set the execution handler."""
        self._execute_func = func
        return func

    def suggest(self, func: Callable[[CommandContext], list[str]]):
        """Set the tab-completion handler."""
        self._suggest_func = func
        return func

    async def run(self, context: CommandContext) -> int:
        """Execute this command with the given context."""
        if self._execute_func is not None:
            try:
                return await self._execute_func(context)
            except Exception as e:
                logger.error(f"Command /{self.name} execution error: {e}", exc_info=True)
                await context.fail({"translate": "command.failed"})
                return ERROR
        logger.warning(f"Command /{self.name} has no execute handler")
        return FAILURE

    def get_suggestions(self, context: CommandContext) -> list[str]:
        """Get tab-completion suggestions."""
        if self._suggest_func is not None:
            try:
                return self._suggest_func(context)
            except Exception:
                return []
        return []


# ============================================================
# Argument Types
# ============================================================

class ArgumentType:
    """Base class for command argument types.

    Each argument type defines how to parse and suggest values
    for a specific kind of command argument.
    """

    def __init__(self, name: str, required: bool = True):
        self.name = name
        self.required = required

    def parse(self, raw: str) -> Any:
        """Parse a raw string value. Raises ValueError on failure."""
        return raw

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        """Return completion suggestions for a partial input."""
        return []


class StringArg(ArgumentType):
    """A plain string argument."""

    def __init__(self, name: str, required: bool = True, greedy: bool = False):
        super().__init__(name, required)
        self.greedy = greedy

    def parse(self, raw: str) -> str:
        return raw


def _parse_coord_component(raw: str, caret: bool = False) -> tuple[float, bool]:
    """Parse one coordinate: ``~offset`` (and ``^offset`` when caret is allowed) is relative."""
    raw = raw.strip()
    if raw.startswith("~") or (caret and raw.startswith("^")):
        offset = float(raw[1:]) if len(raw) > 1 else 0.0
        return (offset, True)
    return (float(raw), False)


class BlockPosArg(ArgumentType):
    """A block position argument (x y z), supporting relative (~) notation.

    Consumes 3 tokens when parsed.
    """

    def __init__(self, name: str = "pos", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> tuple:
        """Parse a single coordinate component. Returns (value, is_relative)."""
        return _parse_coord_component(raw, caret=True)


class ColumnPosArg(ArgumentType):
    """A column position argument (x z), only 2D.

    Consumes 2 tokens when parsed.
    """

    def __init__(self, name: str = "column_pos", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> tuple:
        return _parse_coord_component(raw)


class RotationArg(ArgumentType):
    """A rotation argument (yaw pitch), consuming 2 tokens."""

    def __init__(self, name: str = "rotation", required: bool = True):
        super().__init__(name, required)

    def parse_yaw(self, raw: str) -> tuple[float, bool]:
        return _parse_coord_component(raw)

    def parse_pitch(self, raw: str) -> tuple[float, bool]:
        return self.parse_yaw(raw)


# --- Utility ---

def tokenize_command(command_string: str) -> list[str]:
    """
    Tokenize a command string, respecting quoted strings and brackets.
    Returns a list of tokens.
    """
    tokens = []
    current = []
    in_quotes = False
    escape = False
    i = 0

    while i < len(command_string):
        ch = command_string[i]
        if escape:
            current.append(ch)
            escape = False
        elif ch == '\\':
            escape = True
        elif ch == '"':
            in_quotes = not in_quotes
        elif ch == ' ' and not in_quotes:
            if current:
                tokens.append(''.join(current))
                current = []
        else:
            current.append(ch)
        i += 1

    if current:
        tokens.append(''.join(current))

    return tokens


def parse_command_arguments(
    tokens: list[str],
    arg_defs: list[ArgumentType],
    start_index: int = 0,
) -> tuple[dict[str, Any], list[str]]:
    """
    Parse tokens into named arguments based on argument definitions.
    Returns (parsed_args, remaining_tokens).
    """
    parsed = {}
    remaining = tokens[start_index:]
    token_idx = 0

    for arg_def in arg_defs:
        if token_idx >= len(remaining):
            if arg_def.required:
                raise ValueError(f"Missing required argument: {arg_def.name}")
            break

        if isinstance(arg_def, StringArg) and arg_def.greedy:
            # Greedy string consumes all remaining tokens
            parsed[arg_def.name] = ' '.join(remaining[token_idx:])
            token_idx = len(remaining)
            break
        elif isinstance(arg_def, (BlockPosArg,)):
            # Block position needs 3 tokens
            if token_idx + 2 < len(remaining):
                try:
                    x = arg_def.parse(remaining[token_idx])
                    y = arg_def.parse(remaining[token_idx + 1])
                    z = arg_def.parse(remaining[token_idx + 2])
                    parsed[f"{arg_def.name}_x"] = x
                    parsed[f"{arg_def.name}_y"] = y
                    parsed[f"{arg_def.name}_z"] = z
                    token_idx += 3
                except (ValueError, IndexError):
                    if arg_def.required:
                        raise ValueError(f"Invalid block position for {arg_def.name}")
            elif arg_def.required:
                raise ValueError(f"Missing block position for {arg_def.name}")
        elif isinstance(arg_def, ColumnPosArg):
            # Column position needs 2 tokens
            if token_idx + 1 < len(remaining):
                try:
                    x = arg_def.parse(remaining[token_idx])
                    z = arg_def.parse(remaining[token_idx + 1])
                    parsed[f"{arg_def.name}_x"] = x
                    parsed[f"{arg_def.name}_z"] = z
                    token_idx += 2
                except (ValueError, IndexError):
                    if arg_def.required:
                        raise ValueError(f"Invalid column position for {arg_def.name}")
            elif arg_def.required:
                raise ValueError(f"Missing column position for {arg_def.name}")
        elif isinstance(arg_def, RotationArg):
            # Rotation needs 2 tokens
            if token_idx + 1 < len(remaining):
                try:
                    yaw = arg_def.parse_yaw(remaining[token_idx])
                    pitch = arg_def.parse_pitch(remaining[token_idx + 1])
                    parsed[f"{arg_def.name}_yaw"] = yaw
                    parsed[f"{arg_def.name}_pitch"] = pitch
                    token_idx += 2
                except (ValueError, IndexError):
                    if arg_def.required:
                        raise ValueError(f"Invalid rotation for {arg_def.name}")
            elif arg_def.required:
                raise ValueError(f"Missing rotation for {arg_def.name}")
        else:
            try:
                parsed[arg_def.name] = arg_def.parse(remaining[token_idx])
                token_idx += 1
            except ValueError:
                if arg_def.required:
                    raise
                break

    # Collect remaining tokens
    rest = remaining[token_idx:]
    return parsed, rest
