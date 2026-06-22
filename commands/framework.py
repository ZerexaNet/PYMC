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

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable

logger = logging.getLogger("PyMC.命令")


# --- Result codes ---
SUCCESS = 1
FAILURE = 0
ERROR = -1


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

    @property
    def is_console(self) -> bool:
        """True if the command was issued from the console."""
        return self.sender is None

    @property
    def is_player(self) -> bool:
        """True if the command was issued by an in-game player."""
        from network.connection import Connection
        return isinstance(self.sender, Connection)

    def get_sender_position(self) -> tuple[float, float, float]:
        """Get the sender's position, defaulting to world spawn."""
        if self.sender and hasattr(self.sender, 'x'):
            return (self.sender.x, self.sender.y, self.sender.z)
        spawn = getattr(self.server, 'spawn_position', (0, 100, 0))
        return (float(spawn[0]), float(spawn[1]), float(spawn[2]))

    def get_sender_rotation(self) -> tuple[float, float]:
        """Get the sender's rotation (yaw, pitch)."""
        if self.sender and hasattr(self.sender, 'yaw'):
            return (self.sender.yaw, self.sender.pitch)
        return (0.0, 0.0)

    # ---- Messaging ----

    async def reply(self, text: str):
        """Send a reply to the command sender."""
        from handlers.play.chat import send_system_message
        if self.sender is not None:
            await send_system_message(self.sender, text)
        else:
            logger.info(text)

    async def broadcast(self, text: str):
        """Broadcast a message to all online players."""
        self.server.broadcast_system_message(text)

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

    def arg_int(self, name: str, default: int = 0) -> int:
        """Get a named argument as int."""
        val = self.arguments.get(name, default)
        try:
            return int(val)
        except (ValueError, TypeError):
            return default

    def arg_float(self, name: str, default: float = 0.0) -> float:
        """Get a named argument as float."""
        val = self.arguments.get(name, default)
        try:
            return float(val)
        except (ValueError, TypeError):
            return default

    def arg_str(self, name: str, default: str = "") -> str:
        """Get a named argument as string."""
        val = self.arguments.get(name, default)
        return str(val) if val is not None else default

    def greedy_string(self) -> str:
        """Get the remaining greedy string argument (everything after the command name)."""
        return self.arguments.get("_raw_remaining", "") or self.remaining_input


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
                await context.reply(f"\u00a7cCommand error: {e}")
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


class IntArg(ArgumentType):
    """An integer argument with optional range constraints."""

    def __init__(self, name: str, required: bool = True, min_val: int | None = None, max_val: int | None = None):
        super().__init__(name, required)
        self.min_val = min_val
        self.max_val = max_val

    def parse(self, raw: str) -> int:
        value = int(raw)
        if self.min_val is not None and value < self.min_val:
            raise ValueError(f"{self.name} must be >= {self.min_val}")
        if self.max_val is not None and value > self.max_val:
            raise ValueError(f"{self.name} must be <= {self.max_val}")
        return value


class FloatArg(ArgumentType):
    """A float argument with optional range constraints."""

    def __init__(self, name: str, required: bool = True, min_val: float | None = None, max_val: float | None = None):
        super().__init__(name, required)
        self.min_val = min_val
        self.max_val = max_val

    def parse(self, raw: str) -> float:
        value = float(raw)
        if self.min_val is not None and value < self.min_val:
            raise ValueError(f"{self.name} must be >= {self.min_val}")
        if self.max_val is not None and value > self.max_val:
            raise ValueError(f"{self.name} must be <= {self.max_val}")
        return value


class BoolArg(ArgumentType):
    """A boolean argument (true/false)."""

    def parse(self, raw: str) -> bool:
        if raw.lower() in ("true", "1", "yes"):
            return True
        if raw.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Invalid boolean: {raw}")

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        return ["true", "false"]


class EnumArg(ArgumentType):
    """An enum argument from a set of allowed values."""

    def __init__(self, name: str, values: list[str], required: bool = True, case_insensitive: bool = True):
        super().__init__(name, required)
        self.values = values
        self.case_insensitive = case_insensitive

    def parse(self, raw: str) -> str:
        check = raw.lower() if self.case_insensitive else raw
        for v in self.values:
            v_check = v.lower() if self.case_insensitive else v
            if v_check == check:
                return v
        raise ValueError(f"Invalid value '{raw}', expected one of: {', '.join(self.values)}")

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        if self.case_insensitive:
            return [v for v in self.values if v.lower().startswith(partial.lower())]
        return [v for v in self.values if v.startswith(partial)]


class PlayerArg(ArgumentType):
    """A player name or selector argument."""

    def parse(self, raw: str) -> str:
        return raw

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        players = context.server.get_online_players()
        names = [p.username for p in players]
        if partial.startswith("@"):
            return ["@a", "@p", "@e", "@s", "@r"]
        return [n for n in names if n.lower().startswith(partial.lower())]


class BlockPosArg(ArgumentType):
    """A block position argument (x y z), supporting relative (~) notation.

    Consumes 3 tokens when parsed.
    """

    def __init__(self, name: str = "pos", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> tuple:
        """Parse a single coordinate component. Returns (value, is_relative)."""
        raw = raw.strip()
        if raw.startswith("~"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        if raw.startswith("^"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        return (float(raw), False)

    @staticmethod
    def resolve_relative(coords: list[tuple], base_x: float, base_y: float, base_z: float) -> tuple[float, float, float]:
        """Resolve relative coordinates to absolute positions."""
        x = base_x + coords[0][0] if coords[0][1] else coords[0][0]
        y = base_y + coords[1][0] if coords[1][1] else coords[1][0]
        z = base_z + coords[2][0] if coords[2][1] else coords[2][0]
        return (x, y, z)


class ColumnPosArg(ArgumentType):
    """A column position argument (x z), only 2D.

    Consumes 2 tokens when parsed.
    """

    def __init__(self, name: str = "column_pos", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> tuple:
        raw = raw.strip()
        if raw.startswith("~"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        return (float(raw), False)


class SelectorArg(ArgumentType):
    """An entity selector argument (@a, @p, @e, @s, @r with optional args)."""

    def parse(self, raw: str) -> str:
        # Validate but return the raw string; resolution happens at execution time
        return raw

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        if partial.startswith("@"):
            return ["@a", "@p", "@e", "@s", "@r"]
        players = context.server.get_online_players()
        names = [p.username for p in players]
        return [n for n in names if n.lower().startswith(partial.lower())]


class ItemArg(ArgumentType):
    """An item identifier argument (minecraft:stone)."""

    def parse(self, raw: str) -> str:
        if ":" not in raw:
            return f"minecraft:{raw}"
        return raw


class BlockStateArg(ArgumentType):
    """A block state identifier argument with optional properties.

    Supports: minecraft:stone, stone[half=top], minecraft:stone[half=top,waterlogged=true]
    """

    def __init__(self, name: str = "block_state", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> str:
        if ":" not in raw.split("[")[0]:
            # Add namespace before any bracket
            if "[" in raw:
                base = raw[:raw.index("[")]
                rest = raw[raw.index("["):]
                return f"minecraft:{base}{rest}"
            return f"minecraft:{raw}"
        return raw


class ItemStackArg(ArgumentType):
    """An item stack argument with optional count and NBT.

    Supports: minecraft:diamond_sword, diamond_sword{count:5}
    """

    def __init__(self, name: str = "item_stack", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> dict:
        from commands.arguments import parse_item_stack
        return parse_item_stack(raw)


class JsonArg(ArgumentType):
    """A JSON text component argument (greedy)."""

    def __init__(self, name: str = "json", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> Any:
        import json
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # May be plain text
            return {"text": raw}


class CoordinateArg(ArgumentType):
    """A single coordinate component with relative (~) support."""

    def parse(self, raw: str) -> tuple[float, bool]:
        raw = raw.strip()
        if raw.startswith("^"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        if raw.startswith("~"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        return (float(raw), False)


class TimeArg(ArgumentType):
    """A time argument with unit support (10s, 5m, 1d, 0t)."""

    def __init__(self, name: str = "time", required: bool = True, min_val: int = 0):
        super().__init__(name, required)
        self.min_val = min_val

    def parse(self, raw: str) -> int:
        from commands.arguments import parse_time_value
        value = parse_time_value(raw)
        if value < self.min_val:
            raise ValueError(f"{self.name} must be >= {self.min_val}")
        return value

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        from commands.arguments import TIME_PRESETS
        return [k for k in TIME_PRESETS if k.startswith(partial.lower())]


class ColorArg(ArgumentType):
    """A color argument for Minecraft formatting codes."""

    VALID_COLORS = {
        "black", "dark_blue", "dark_green", "dark_aqua", "dark_red",
        "dark_purple", "gold", "gray", "dark_gray", "blue", "green",
        "aqua", "red", "light_purple", "yellow", "white",
    }

    def parse(self, raw: str) -> str:
        raw = raw.strip().lower()
        if raw.startswith("minecraft:"):
            raw = raw[10:]
        if raw not in self.VALID_COLORS:
            raise ValueError(f"Invalid color: {raw}. Expected one of: {', '.join(sorted(self.VALID_COLORS))}")
        return raw

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        return [c for c in sorted(self.VALID_COLORS) if c.startswith(partial.lower())]


class IdentifierArg(ArgumentType):
    """A namespaced identifier argument (minecraft:stone)."""

    def __init__(self, name: str = "identifier", required: bool = True, namespace: str = "minecraft"):
        super().__init__(name, required)
        self.default_namespace = namespace

    def parse(self, raw: str) -> str:
        raw = raw.strip()
        if ":" not in raw:
            return f"{self.default_namespace}:{raw}"
        return raw


class AngleArg(ArgumentType):
    """A rotation angle argument with relative (~) support."""

    def parse(self, raw: str) -> tuple[float, bool]:
        raw = raw.strip()
        if raw.startswith("~"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        return (float(raw), False)


class RotationArg(ArgumentType):
    """A rotation argument (yaw pitch), consuming 2 tokens."""

    def __init__(self, name: str = "rotation", required: bool = True):
        super().__init__(name, required)

    def parse_yaw(self, raw: str) -> tuple[float, bool]:
        raw = raw.strip()
        if raw.startswith("~"):
            offset = float(raw[1:]) if len(raw) > 1 else 0.0
            return (offset, True)
        return (float(raw), False)

    def parse_pitch(self, raw: str) -> tuple[float, bool]:
        return self.parse_yaw(raw)


class ScoreHolderArg(ArgumentType):
    """A score holder argument (player name or selector)."""

    def parse(self, raw: str) -> str:
        return raw

    def suggest(self, partial: str, context: CommandContext) -> list[str]:
        if partial.startswith("@"):
            return ["@a", "@p", "@e", "@s", "@r"]
        players = context.server.get_online_players()
        names = [p.username for p in players]
        return [n for n in names if n.lower().startswith(partial.lower())]


class ComponentArg(ArgumentType):
    """A JSON text component argument (same as JsonArg but with better name)."""

    def __init__(self, name: str = "component", required: bool = True):
        super().__init__(name, required)

    def parse(self, raw: str) -> Any:
        import json
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw}


# --- Utility ---

async def _noop():
    """No-op coroutine for console reply."""
    pass


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
