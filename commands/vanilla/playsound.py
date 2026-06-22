# ============================================================
# PyMC - /playsound Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_sound_name, parse_sound_source
from commands.selector import resolve_selector
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 2:
            await ctx.reply("[PyMC] 用法: playsound <声音> <来源> [目标] [x] [y] [z] [音量] [音调] [最小音量]")
            return FAILURE

        try:
            sound_name = parse_sound_name(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        try:
            source = parse_sound_source(args[1])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        # Parse target
        target = ctx.sender
        if len(args) >= 3:
            targets = resolve_selector(ctx.server, ctx.sender, args[2])
            players = [t for t in targets if isinstance(t, Connection)]
            if players:
                target = players[0]

        if target is None or not isinstance(target, Connection):
            await ctx.reply("[PyMC] 未找到目标玩家")
            return FAILURE

        # Parse position
        x, y, z = target.x, target.y, target.z
        if len(args) >= 6:
            try:
                from commands.arguments import parse_coordinate, resolve_coordinate
                x = resolve_coordinate(parse_coordinate(args[3]), target.x)
                y = resolve_coordinate(parse_coordinate(args[4]), target.y)
                z = resolve_coordinate(parse_coordinate(args[5]), target.z)
            except ValueError:
                pass

        volume = 1.0
        if len(args) >= 7:
            try:
                volume = max(0.0, min(1.0, float(args[6])))
            except ValueError:
                pass

        pitch = 1.0
        if len(args) >= 8:
            try:
                pitch = max(0.5, min(2.0, float(args[7])))
            except ValueError:
                pass

        min_volume = 0.0
        if len(args) >= 9:
            try:
                min_volume = max(0.0, min(1.0, float(args[8])))
            except ValueError:
                pass

        # Send sound packet (0x5E = Custom Sound Effect in 1.21.1)
        from protocol.data_types import write_varint, write_string, write_boolean, write_double, write_float

        source_map = {"master": 0, "music": 1, "record": 2, "weather": 3,
                       "block": 4, "hostile": 5, "neutral": 6, "player": 7,
                       "ambient": 8, "voice": 9}
        source_id = source_map.get(source, 0)

        payload = bytearray()
        payload.extend(write_string(sound_name))
        payload.extend(write_varint(source_id))
        payload.extend(write_boolean(False))  # Not from server-side event
        payload.extend(write_double(x))
        payload.extend(write_double(y))
        payload.extend(write_double(z))
        payload.extend(write_float(volume))
        payload.extend(write_float(pitch))
        payload.extend(write_varint(0))  # Seed

        await target.send_packet(0x5E, bytes(payload))
        await ctx.reply(f"[PyMC] 已播放声音: {sound_name}")
        return SUCCESS

    cmd = Command(
        name="playsound",
        description="播放声音",
        usage="playsound <声音> <来源> [目标] [x] [y] [z] [音量] [音调] [最小音量]",
        permission="command.playsound",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
