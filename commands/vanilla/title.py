# ============================================================
# PyMC - /title Command
# Display titles, subtitles, and action bars
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: title <目标> <title|subtitle|actionbar|clear|reset|times> <内容>")
            return FAILURE

        target_spec = args[0]
        action = args[1].lower()

        # Resolve targets
        targets = resolve_selector(ctx.server, ctx.sender, target_spec)
        players = [t for t in targets if isinstance(t, Connection)]

        if not players:
            player = ctx.server.find_player(target_spec)
            if player:
                players = [player]

        if not players and action not in ("clear", "reset"):
            await ctx.reply(f"[PyMC] 未找到目标: {target_spec}")
            return FAILURE

        # Handle different title actions
        if action == "clear":
            for player in players:
                await _send_title_clear(player, reset=False)
            return SUCCESS

        if action == "reset":
            for player in players:
                await _send_title_clear(player, reset=True)
                await _send_title_times(player, 10, 70, 20)
            return SUCCESS

        if action == "times":
            if len(args) < 5:
                await ctx.reply("[PyMC] 用法: title <目标> times <淡入> <停留> <淡出>")
                return FAILURE
            try:
                fade_in = int(args[2])
                stay = int(args[3])
                fade_out = int(args[4])
            except ValueError:
                await ctx.reply("[PyMC] 时间格式无效（单位：tick）")
                return FAILURE
            for player in players:
                await _send_title_times(player, fade_in, stay, fade_out)
            return SUCCESS

        if action in ("title", "subtitle", "actionbar"):
            if len(args) < 3:
                await ctx.reply(f"[PyMC] 用法: title <目标> {action} <文本>")
                return FAILURE

            from commands.arguments import parse_text_component
            message_str = ' '.join(args[2:])
            try:
                component = parse_text_component(message_str)
            except Exception:
                component = {"text": message_str}

            for player in players:
                if action == "title":
                    await _send_title_text(player, component)
                elif action == "subtitle":
                    await _send_title_subtitle(player, component)
                elif action == "actionbar":
                    await _send_action_bar(player, component)

            return SUCCESS

        await ctx.reply(f"[PyMC] 未知操作: {action}. 可用: title, subtitle, actionbar, clear, reset, times")
        return FAILURE

    def _suggest(ctx: CommandContext) -> list[str]:
        tokens = ctx.input_string.split()
        if len(tokens) == 3:
            return ["title", "subtitle", "actionbar", "clear", "reset", "times"]
        return []

    cmd = Command(
        name="title",
        description="显示标题、副标题或动作栏文本",
        usage="title <目标> <title|subtitle|actionbar|clear|reset|times> <内容>",
        permission="command.title",
    )
    cmd._execute_func = _execute
    cmd._suggest_func = _suggest
    manager.register(cmd)


async def _send_title_text(conn: Connection, component: dict):
    """Send set_title_text packet (0x65 in 1.21.1)."""
    from protocol.nbt import encode_nbt
    payload = bytearray()
    payload.extend(encode_nbt(component, with_type=True))
    await conn.send_packet(0x65, bytes(payload))


async def _send_title_subtitle(conn: Connection, component: dict):
    """Send set_title_subtitle packet (0x63 in 1.21.1)."""
    from protocol.nbt import encode_nbt
    payload = bytearray()
    payload.extend(encode_nbt(component, with_type=True))
    await conn.send_packet(0x63, bytes(payload))


async def _send_action_bar(conn: Connection, component: dict):
    """Send action_bar packet (0x4C in 1.21.1)."""
    from protocol.nbt import encode_nbt
    payload = bytearray()
    payload.extend(encode_nbt(component, with_type=True))
    await conn.send_packet(0x4C, bytes(payload))


async def _send_title_clear(conn: Connection, reset: bool = False):
    """Send clear_titles packet (0x0F in 1.21.1)."""
    from protocol.data_types import write_boolean
    payload = bytearray()
    payload.extend(write_boolean(reset))
    await conn.send_packet(0x0F, bytes(payload))


async def _send_title_times(conn: Connection, fade_in: int, stay: int, fade_out: int):
    """Send set_title_time packet (0x66 in 1.21.1)."""
    from protocol.data_types import write_int
    payload = bytearray()
    payload.extend(write_int(fade_in))
    payload.extend(write_int(stay))
    payload.extend(write_int(fade_out))
    await conn.send_packet(0x66, bytes(payload))
