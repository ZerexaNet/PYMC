# ============================================================
# PyMC - Command Manager
# Central command registration, dispatch, and management
# ============================================================

"""
CommandManager: Registers commands, resolves aliases,
parses input, checks permissions, and dispatches execution.

Execute flow:
  1. Parse command name from input string
  2. Resolve aliases (e.g., "teleport" → "tp")
  3. Check sender has permission
  4. Parse arguments using the command's argument definitions
  5. Execute the command handler
  6. Return result code (1=success, 0=error, -1=no permission)

The legacy if-elif chain in chat.py has been removed;
CommandManager handles everything.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from commands.framework import (
    Command, CommandContext, tokenize_command,
    parse_command_arguments, SUCCESS, FAILURE, ERROR,
)

# NOT_FOUND result code for when a command is not recognized
NOT_FOUND = -2

logger = logging.getLogger("PyMC.命令")

# --- Recognized but unsupported commands ---
RECOGNIZED_BUT_UNSUPPORTED = {
    "debug", "jfr", "loot", "perf", "publish", "random",
    "return", "setidletimeout", "spectate", "teammsg", "transfer",
}

# --- Command aliases (supplementary to per-command aliases) ---
GLOBAL_ALIASES = {
    "teleport": "tp",
    "experience": "xp",
    "tell": "msg",
    "w": "msg",
    "tm": "teammsg",
    "?": "help",
    "gm": "gamemode",
}


class CommandManager:
    """Manages command registration, parsing, dispatch, and tab completion."""

    def __init__(self, server):
        self.server = server
        self.commands: dict[str, Command] = {}
        self.aliases: dict[str, str] = {}

    def register(self, command: Command):
        """Register a command and its aliases."""
        self.commands[command.name] = command
        for alias in command.aliases:
            self.aliases[alias] = command.name
        logger.debug(f"Registered command: /{command.name} (aliases: {command.aliases})")

    def unregister(self, name: str):
        """Unregister a command by name."""
        cmd = self.commands.pop(name, None)
        if cmd:
            for alias in cmd.aliases:
                self.aliases.pop(alias, None)

    def get_command(self, name: str) -> Command | None:
        """Get a command by name or alias.

        Resolution order:
          1. Direct command name
          2. Per-command aliases
          3. Global aliases
        """
        # Check direct name first
        if name in self.commands:
            return self.commands[name]
        # Check per-command aliases
        resolved = self.aliases.get(name)
        if resolved:
            return self.commands.get(resolved)
        # Check global aliases
        global_resolved = GLOBAL_ALIASES.get(name)
        if global_resolved:
            return self.commands.get(global_resolved)
        return None

    def get_all_commands(self) -> list[Command]:
        """Return all registered commands."""
        return list(self.commands.values())

    def get_commands_for_sender(self, sender) -> list[Command]:
        """Return commands the sender has permission to use."""
        result = []
        for cmd in self.commands.values():
            if cmd.permission:
                if sender is None:
                    # Console has all permissions
                    result.append(cmd)
                elif self.server.permissions.has_permission(sender.username, cmd.permission):
                    result.append(cmd)
            else:
                result.append(cmd)
        return result

    def get_commands_by_category(self) -> dict[str, list[Command]]:
        """Return commands grouped by category."""
        categories: dict[str, list[Command]] = {}
        for cmd in self.commands.values():
            cat = getattr(cmd, 'category', 'general')
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(cmd)
        return categories

    async def execute(self, sender, command_string: str) -> int:
        """
        Parse and execute a command string.

        Execute flow:
          1. Parse command name from input string
          2. Resolve aliases (e.g., "teleport" → "tp")
          3. Check sender has permission
          4. Parse arguments using the command's argument definitions
          5. Execute the command handler
          6. Return result code (1=success, 0=error, -1=no permission)

        Args:
            sender: Connection or None (console)
            command_string: The raw command string (without leading /)

        Returns:
            Result code: SUCCESS(1), FAILURE(0), ERROR(-1)
        """
        command_string = command_string.strip()
        if not command_string:
            return FAILURE

        # Step 1: Parse command name
        tokens = tokenize_command(command_string)
        if not tokens:
            return FAILURE

        cmd_name = tokens[0].lower()

        # Step 2: Resolve command (check per-command aliases, then global aliases)
        command = self.get_command(cmd_name)

        # Step 3: unknown command or missing permission -> the same vanilla
        # error (players never learn which commands exist but are locked).
        allowed = command is not None and (
            not command.permission or sender is None
            or self.server.permissions.has_permission(sender.username, command.permission))
        if not allowed:
            await self._send_unknown_command(sender, command_string)
            return FAILURE if command is None else ERROR

        # Step 4: Parse arguments
        arguments = {}
        remaining_tokens = []
        if command.arguments:
            try:
                arguments, remaining_tokens = parse_command_arguments(
                    tokens, command.arguments, start_index=1
                )
            except ValueError as e:
                await self._send_message(sender, {"text": str(e), "color": "red"})
                return FAILURE
        else:
            remaining_tokens = tokens[1:]

        # Store remaining raw tokens
        arguments["_raw_remaining"] = remaining_tokens
        arguments["_raw_input"] = command_string
        arguments["_raw_tokens"] = tokens

        # Step 5: Build context and execute
        source_name = sender.username if sender else "Console"
        context = CommandContext(
            sender=sender,
            command=command,
            arguments=arguments,
            input_string=command_string,
            server=self.server,
            source_name=source_name,
        )

        # Step 6: Execute and return result
        return await command.run(context)

    async def _send_message(self, sender, message):
        if sender is not None:
            from handlers.play.chat import send_system_message
            await send_system_message(sender, message)
        else:
            from commands.framework import console_output
            console_output(message)

    async def _send_unknown_command(self, sender, command_string: str):
        """Vanilla two-line error: message + the input with ``<--[HERE]``."""
        await self._send_message(sender, {"translate": "command.unknown.command", "color": "red"})
        shown = command_string if len(command_string) <= 10 else "..." + command_string[-10:]
        await self._send_message(sender, {
            "text": "",
            "color": "gray",
            "extra": [
                {"text": shown, "color": "red", "underlined": True,
                 "clickEvent": {"action": "suggest_command", "value": "/" + command_string}},
                {"translate": "command.context.here", "color": "red", "italic": True},
            ],
        })

    def get_suggestions(self, sender, input_string: str) -> list[str]:
        """Get tab-completion suggestions for a partial command input."""
        input_string = input_string.strip()
        if not input_string:
            # Suggest all available commands
            return [f"/{cmd.name}" for cmd in self.get_commands_for_sender(sender)]

        tokens = input_string.split()
        first_token = tokens[0].lower()

        # If typing the command name
        if len(tokens) == 1 and not input_string.endswith(" "):
            suggestions = []
            for cmd in self.get_commands_for_sender(sender):
                if cmd.name.startswith(first_token):
                    suggestions.append(f"/{cmd.name}")
                for alias in cmd.aliases:
                    if alias.startswith(first_token):
                        suggestions.append(f"/{alias}")
            # Check global aliases
            for alias, resolved in GLOBAL_ALIASES.items():
                if alias.startswith(first_token) and resolved in self.commands:
                    suggestions.append(f"/{alias}")
            return suggestions

        # Resolve command
        command = self.get_command(first_token)
        if command is None:
            return []

        # Get argument-level suggestions
        source_name = sender.username if sender else "Console"
        context = CommandContext(
            sender=sender,
            command=command,
            arguments={},
            input_string=input_string,
            server=self.server,
            source_name=source_name,
        )
        return command.get_suggestions(context)


def register_all_vanilla_commands(manager: CommandManager):
    """Register all vanilla commands with the manager."""
    from commands.vanilla import register_all
    register_all(manager)
