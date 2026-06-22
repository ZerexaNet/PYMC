# ============================================================
# PyMC - /particle Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.arguments import parse_particle_name
from network.connection import Connection


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if not args:
            await ctx.reply("[PyMC] 用法: particle <粒子类型> [x] [y] [z] [dx] [dy] [dz] [速度] [数量] [模式]")
            return FAILURE

        try:
            particle_name = parse_particle_name(args[0])
        except ValueError as e:
            await ctx.reply(f"[PyMC] {e}")
            return FAILURE

        # Parse position
        bx, by, bz = 0.0, 100.0, 0.0
        if ctx.sender and hasattr(ctx.sender, 'x'):
            bx, by, bz = ctx.sender.x, ctx.sender.y, ctx.sender.z

        from commands.arguments import parse_coordinate, resolve_coordinate
        try:
            x = resolve_coordinate(parse_coordinate(args[1]), bx) if len(args) >= 2 else bx
            y = resolve_coordinate(parse_coordinate(args[2]), by) if len(args) >= 3 else by
            z = resolve_coordinate(parse_coordinate(args[3]), bz) if len(args) >= 4 else bz
        except ValueError:
            await ctx.reply("[PyMC] 坐标格式无效")
            return FAILURE

        dx = float(args[4]) if len(args) >= 5 else 0.0
        dy = float(args[5]) if len(args) >= 6 else 0.0
        dz = float(args[6]) if len(args) >= 7 else 0.0
        speed = float(args[7]) if len(args) >= 8 else 0.0
        count = int(args[8]) if len(args) >= 9 else 1
        mode = args[9].lower() if len(args) >= 10 else "normal"

        # Send particle packet to nearby players
        # Packet ID 0x24 = Particle (1.21.1)
        from protocol.data_types import write_varint, write_double, write_boolean

        for player in ctx.server.get_online_players():
            dist = ((player.x - x) ** 2 + (player.y - y) ** 2 + (player.z - z) ** 2) ** 0.5
            if dist > 256:  # 16 blocks range
                continue

            payload = bytearray()
            payload.extend(write_varint(0))  # Particle ID (0 = ambient_entity_effect, simplified)
            payload.extend(write_boolean(mode == "force"))
            payload.extend(write_double(x))
            payload.extend(write_double(y))
            payload.extend(write_double(z))
            payload.extend(write_double(dx))
            payload.extend(write_double(dy))
            payload.extend(write_double(dz))
            payload.extend(write_double(speed))
            payload.extend(write_varint(count))
            # No extra data for most particles

            await player.send_packet(0x24, bytes(payload))

        await ctx.reply(f"[PyMC] 已生成粒子: {particle_name} 在 ({x:.1f}, {y:.1f}, {z:.1f})")
        return SUCCESS

    cmd = Command(
        name="particle",
        description="生成粒子效果",
        usage="particle <粒子类型> [x] [y] [z] [dx] [dy] [dz] [速度] [数量] [模式]",
        permission="command.particle",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
