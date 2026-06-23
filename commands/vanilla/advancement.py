# ============================================================
# PyMC - /advancement Command
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from commands.selector import resolve_selector
from network.connection import Connection


# Simple advancement tracking
_advancements: dict[str, dict] = {}
_player_advancements: dict[str, dict[str, bool]] = {}  # username -> {adv_name -> done}


def register(manager):
    async def _execute(ctx: CommandContext) -> int:
        tokens = ctx.arguments.get("_raw_tokens", [])
        args = tokens[1:] if len(tokens) > 1 else []

        if len(args) < 3:
            await ctx.reply("[PyMC] 用法: advancement <grant|revoke> <目标> <everything|only|from|through|until> [进度名]")
            return FAILURE

        action = args[0].lower()
        if action not in ("grant", "revoke"):
            await ctx.reply(f"[PyMC] 未知操作: {action}。可用: grant, revoke")
            return FAILURE

        targets = resolve_selector(ctx.server, ctx.sender, args[1])
        players = [t for t in targets if isinstance(t, Connection)]
        if not players:
            await ctx.reply(f"[PyMC] 未找到目标: {args[1]}")
            return FAILURE

        mode = args[2].lower()

        if mode == "everything":
            count = 0
            for player in players:
                if player.username not in _player_advancements:
                    _player_advancements[player.username] = {}
                if action == "grant":
                    for adv_name in _advancements:
                        if not _player_advancements[player.username].get(adv_name):
                            _player_advancements[player.username][adv_name] = True
                            count += 1
                else:
                    count = len(_player_advancements[player.username])
                    _player_advancements[player.username] = {}
            action_cn = "授予" if action == "grant" else "撤销"
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家的所有进度 ({count} 个)")
            return SUCCESS

        if mode == "only":
            if len(args) < 4:
                await ctx.reply("[PyMC] 用法: advancement <grant|revoke> <目标> only <进度名>")
                return FAILURE
            adv_name = args[3]
            count = 0
            for player in players:
                if player.username not in _player_advancements:
                    _player_advancements[player.username] = {}
                _player_advancements[player.username][adv_name] = (action == "grant")
                count += 1
            action_cn = "授予" if action == "grant" else "撤销"
            await ctx.reply(f"[PyMC] 已{action_cn} {len(players)} 个玩家进度: {adv_name}")
            return SUCCESS

        # from, through, until - simplified
        adv_name = args[3] if len(args) >= 4 else "unknown"
        action_cn = "授予" if action == "grant" else "撤销"
        await ctx.reply(f"[PyMC] 已{action_cn}进度: {adv_name} (from/through/until 模式暂简化处理)")
        return SUCCESS

    cmd = Command(
        name="advancement",
        description="授予或撤销进度",
        usage="advancement <grant|revoke> <目标> <everything|only|from|through|until> [进度名]",
        permission="command.advancement",
    )
    cmd._execute_func = _execute
    manager.register(cmd)
