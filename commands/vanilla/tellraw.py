# ============================================================
# PyMC - /tellraw Command
# Send JSON text components to players
# ============================================================

import json

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from commands.arguments import parse_text_component


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        from handlers.play.chat import send_system_message
        from network.connection import Connection

        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: tellraw <目标> <JSON文本>")
            return FAILURE

        target_spec = args[0]
        message_str = ' '.join(args[1:])

        # Parse the message component
        try:
            component = parse_text_component(message_str)
        except Exception:
            component = {"text": message_str}

        # Resolve targets
        targets = resolve_selector(ctx.server, ctx.sender, target_spec)
        players = [t for t in targets if isinstance(t, Connection)]

        if not players:
            # Maybe it's a player name
            player = ctx.server.find_player(target_spec)
            if player:
                players = [player]

        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {target_spec}")
            return FAILURE

        # Send the component as a system message
        component_str = json.dumps(component, ensure_ascii=False)
        for player in players:
            await send_system_message(player, component_str)

        return SUCCESS

    cmd = Command(
        name="tellraw",
        description="发送 JSON 文本消息",
        usage="tellraw <目标> <JSON文本>",
        permission="command.tellraw",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
