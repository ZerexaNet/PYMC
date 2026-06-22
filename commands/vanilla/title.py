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
                await _send_title_packet(player, {"text": ""}, action=0)
            return SUCCESS

        if action == "reset":
            for player in players:
                await _send_title_packet(player, {"text": ""}, action=0)
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

            action_map = {"title": 0, "subtitle": 1, "actionbar": 2}
            for player in players:
                await _send_title_packet(player, component, action=action_map[action])

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


async def _send_title_packet(conn: Connection, component: dict, action: int = 0):
    """Send a title/subtitle/actionbar packet."""
    from protocol.nbt import encode_nbt
    from protocol.data_types import write_varint

    payload = bytearray()
    payload.extend(write_varint(action))
    if action in (0, 1, 2):  # title, subtitle, actionbar need text
        payload.extend(encode_nbt(component, with_type=True))
    await conn.send_packet(0x6B, bytes(payload))


async def _send_title_times(conn: Connection, fade_in: int, stay: int, fade_out: int):
    """Send title times packet."""
    from protocol.data_types import write_varint, write_int

    payload = bytearray()
    payload.extend(write_varint(3))  # Set title times action
    payload.extend(write_int(fade_in))
    payload.extend(write_int(stay))
    payload.extend(write_int(fade_out))
    await conn.send_packet(0x6B, bytes(payload))
