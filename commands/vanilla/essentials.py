# ============================================================
# PyMC - 原版核心命令
# ============================================================

"""
Vanilla-faithful implementations of the commands operators and players use
every day. Registered last, so they replace the earlier simplified versions.

Feedback uses the vanilla translation keys (``commands.*``), so every client
sees it in its own language, operators get the gray ``[Source: ...]``
notification, and the console/RCON print the en_us text.

  help list say me msg/tell/w
  kick ban ban-ip pardon pardon-ip banlist op deop whitelist
  stop save-all save-on save-off seed
  time weather difficulty gamerule defaultgamemode setworldspawn spawnpoint
  gamemode tp/teleport give clear kill xp/experience
"""

from __future__ import annotations

import ipaddress
import math

from commands.framework import Command, CommandContext, SUCCESS, FAILURE
from protocol.text import translate, player_name, text as _text

GAMEMODES = ("survival", "creative", "adventure", "spectator")
DIFFICULTIES = ("peaceful", "easy", "normal", "hard")


# ------------------------------------------------------------------
# helpers
# ------------------------------------------------------------------

def _is_player(obj) -> bool:
    from network.connection import Connection
    return isinstance(obj, Connection)


def _entity_name(obj) -> dict:
    if _is_player(obj):
        return player_name(obj)
    mob_type = getattr(obj, "metadata", {}).get("mob_type") or getattr(obj, "kind", "entity")
    return {"translate": f"entity.minecraft.{mob_type}", "fallback": str(mob_type)}


def _resolve(ctx: CommandContext, spec: str) -> list:
    from commands.selector import resolve_selector
    try:
        return [t for t in resolve_selector(ctx.server, ctx.sender, spec) if t is not None]
    except Exception:
        return []


async def _players(ctx: CommandContext, spec: str) -> list | None:
    """Resolve a player argument; sends the vanilla error and returns None if empty."""
    found = [t for t in _resolve(ctx, spec) if _is_player(t)]
    if not found:
        await ctx.fail(translate("argument.entity.notfound.player"))
        return None
    return found


async def _entities(ctx: CommandContext, spec: str) -> list | None:
    found = _resolve(ctx, spec)
    if not found:
        await ctx.fail(translate("argument.entity.notfound.entity"))
        return None
    return found


async def _incomplete(ctx: CommandContext) -> int:
    await ctx.fail(translate("command.unknown.argument"))
    return FAILURE


def _profile_name(ctx: CommandContext, name: str) -> str:
    """Correct capitalisation for an (offline) player name."""
    online = ctx.server.find_player(name)
    if online is not None:
        return online.username
    cache = getattr(ctx.server, "usercache", None)
    return cache.name_for(name) if cache is not None else name


def _gamemode_component(mode: str) -> dict:
    return {"translate": f"gameMode.{mode}"}


def _difficulty_component(difficulty: str) -> dict:
    return {"translate": f"options.difficulty.{difficulty}"}


def _item_component(item_id: str) -> dict:
    """``[Item Name]`` like vanilla's ItemStack.getDisplayName()."""
    short = item_id.split(":", 1)[-1]
    pretty = short.replace("_", " ").title()
    key = f"item.minecraft.{short}"
    try:
        from world.chunk_io import BLOCK_NAME_TO_DEFAULT_STATE
        if short in BLOCK_NAME_TO_DEFAULT_STATE or item_id in BLOCK_NAME_TO_DEFAULT_STATE:
            key = f"block.minecraft.{short}"
    except Exception:
        pass
    return {"translate": "chat.square_brackets",
            "with": [{"translate": key, "fallback": pretty}]}


def _fmt(value: float) -> str:
    return f"{value:.6f}"


def _command(manager, name, func, permission, usage="", aliases=None,
             description="", category="vanilla"):
    cmd = Command(name=name, description=description or name, usage=usage or name,
                  aliases=aliases or [], permission=permission, category=category)
    cmd._execute_func = func
    manager.register(cmd)
    return cmd


async def teleport(server, target, x: float, y: float, z: float,
                   yaw: float | None = None, pitch: float | None = None) -> None:
    """Move a player or entity and synchronise everyone who can see it."""
    target.x, target.y, target.z = float(x), float(y), float(z)
    if yaw is not None:
        target.yaw = float(yaw)
    if pitch is not None:
        target.pitch = float(pitch)
    if not _is_player(target):
        return
    target.fall_start_y = target.y
    from handlers.play.join import _send_synchronize_position
    from handlers.play.chunks import _schedule_chunk_stream_update
    from handlers.play.players import relay_player_movement
    await _send_synchronize_position(target)
    _schedule_chunk_stream_update(target, server)
    try:
        await relay_player_movement(server, target, force=True)
    except TypeError:
        await relay_player_movement(server, target)


async def refresh_permissions(server, player) -> None:
    """Resend the op level and command tree after /op or /deop."""
    if getattr(player, "protocol_version", 0) != 767:
        return
    from handlers.play.state import send_op_level
    from commands.brigadier import send_commands
    await send_op_level(player, server)
    await send_commands(player, server)


# ------------------------------------------------------------------
# registration
# ------------------------------------------------------------------

def register(manager):
    server_of = lambda ctx: ctx.server  # noqa: E731

    # ---------------- help ----------------
    async def _help(ctx: CommandContext) -> int:
        args = ctx.args
        available = sorted(manager.get_commands_for_sender(ctx.sender), key=lambda c: c.name)
        if args:
            cmd = manager.get_command(args[0].lstrip("/"))
            if cmd is None or cmd not in available:
                return await ctx.fail(translate("commands.help.failed"))
            await ctx.reply(f"/{cmd.usage or cmd.name}")
            return SUCCESS
        for cmd in available:
            await ctx.reply(f"/{cmd.usage or cmd.name}")
        return SUCCESS

    _command(manager, "help", _help, "command.help", "help [<command>]", aliases=["?"])

    # ---------------- list ----------------
    async def _list(ctx: CommandContext) -> int:
        players = ctx.server.get_online_players()
        with_uuid = bool(ctx.args) and ctx.args[0].lower() == "uuids"
        names = ", ".join(
            f"{p.username} ({p.uuid})" if with_uuid else p.username for p in players)
        await ctx.reply(translate("commands.list.players", len(players),
                                  ctx.server.max_players, names))
        return SUCCESS

    _command(manager, "list", _list, "command.list", "list [uuids]")

    # ---------------- say / me / msg ----------------
    async def _say(ctx: CommandContext) -> int:
        message = ctx.remaining_input.strip()
        if not message:
            return await _incomplete(ctx)
        ctx.server.broadcast_system_message(
            translate("chat.type.announcement", ctx.source_component, _text(message)), log=True)
        return SUCCESS

    _command(manager, "say", _say, "command.say", "say <message>")

    async def _me(ctx: CommandContext) -> int:
        action = ctx.remaining_input.strip()
        if not action:
            return await _incomplete(ctx)
        ctx.server.broadcast_system_message(
            translate("chat.type.emote", ctx.source_component, _text(action)), log=True)
        return SUCCESS

    _command(manager, "me", _me, "command.me", "me <action>")

    async def _msg(ctx: CommandContext) -> int:
        from handlers.play.chat import send_system_message
        args = ctx.args
        if len(args) < 2:
            return await _incomplete(ctx)
        targets = await _players(ctx, args[0])
        if targets is None:
            return FAILURE
        message = ctx.remaining_input.split(None, 1)[1]
        for target in targets:
            await ctx.reply(translate("commands.message.display.outgoing",
                                      player_name(target), _text(message),
                                      color="gray", italic=True))
            await send_system_message(target, translate(
                "commands.message.display.incoming", ctx.source_component, _text(message),
                color="gray", italic=True))
        return SUCCESS

    _command(manager, "msg", _msg, "command.msg", "msg <targets> <message>",
             aliases=["tell", "w"])

    # ---------------- kick ----------------
    async def _kick(ctx: CommandContext) -> int:
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        targets = await _players(ctx, args[0])
        if targets is None:
            return FAILURE
        reason = (ctx.remaining_input.split(None, 1)[1].strip()
                  if len(args) > 1 else "")
        reason_component = _text(reason) if reason else translate("multiplayer.disconnect.kicked")
        for target in targets:
            from plugins.bridge import hook_player_kick
            try:
                hook_player_kick(ctx.server, target, reason)
            except Exception:
                pass
            await target.disconnect(reason_component)
            await ctx.success(translate("commands.kick.success",
                                        player_name(target), reason_component))
        return SUCCESS

    _command(manager, "kick", _kick, "command.kick", "kick <targets> [<reason>]")

    # ---------------- ban / pardon / banlist ----------------
    def _reason_from(ctx: CommandContext) -> str:
        parts = ctx.remaining_input.split(None, 1)
        return parts[1].strip() if len(parts) > 1 else ""

    async def _ban(ctx: CommandContext) -> int:
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        permissions = ctx.server.permissions
        reason = _reason_from(ctx) or "Banned by an operator."
        names = [p.username for p in _resolve(ctx, args[0]) if _is_player(p)] \
            or ([] if args[0].startswith("@") else [_profile_name(ctx, args[0])])
        if not names:
            return await ctx.fail(translate("argument.player.unknown"))
        banned = 0
        for name in names:
            if not permissions.ban_player(name, reason, source=ctx.source_name or "Server"):
                continue
            banned += 1
            await ctx.success(translate("commands.ban.success", _text(name), _text(reason)))
            online = ctx.server.find_player(name)
            if online is not None:
                await online.disconnect(translate("multiplayer.disconnect.banned"))
        if banned == 0:
            return await ctx.fail(translate("commands.ban.failed"))
        return SUCCESS

    _command(manager, "ban", _ban, "command.ban", "ban <targets> [<reason>]")

    async def _pardon(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        permissions = ctx.server.permissions
        record = permissions.data["bans"]["players"].get(ctx.args[0].lower())
        name = (record or {}).get("name", ctx.args[0])
        if not permissions.pardon_player(ctx.args[0]):
            return await ctx.fail(translate("commands.pardon.failed"))
        await ctx.success(translate("commands.pardon.success", _text(name)))
        return SUCCESS

    _command(manager, "pardon", _pardon, "command.pardon", "pardon <targets>")

    def _valid_ip(value: str) -> bool:
        try:
            ipaddress.ip_address(value)
            return True
        except ValueError:
            return False

    async def _ban_ip(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        target = ctx.args[0]
        if not _valid_ip(target):
            player = ctx.server.find_player(target)
            if player is None:
                return await ctx.fail(translate("commands.banip.invalid"))
            target = player.address.rsplit(":", 1)[0]
        reason = _reason_from(ctx) or "Banned by an operator."
        if not ctx.server.permissions.ban_ip(target, reason, source=ctx.source_name or "Server"):
            return await ctx.fail(translate("commands.banip.failed"))
        await ctx.success(translate("commands.banip.success", _text(target), _text(reason)))
        affected = [p for p in ctx.server.get_online_players()
                    if p.address.rsplit(":", 1)[0] == target]
        if affected:
            await ctx.success(translate("commands.banip.info", len(affected),
                                        ", ".join(p.username for p in affected)))
            for player in affected:
                await player.disconnect(translate("multiplayer.disconnect.ip_banned"))
        return SUCCESS

    _command(manager, "ban-ip", _ban_ip, "command.ban-ip", "ban-ip <target> [<reason>]")

    async def _pardon_ip(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        if not _valid_ip(ctx.args[0]):
            return await ctx.fail(translate("commands.pardonip.invalid"))
        if not ctx.server.permissions.pardon_ip(ctx.args[0]):
            return await ctx.fail(translate("commands.pardonip.failed"))
        await ctx.success(translate("commands.pardonip.success", _text(ctx.args[0])))
        return SUCCESS

    _command(manager, "pardon-ip", _pardon_ip, "command.pardon-ip", "pardon-ip <target>")

    async def _banlist(ctx: CommandContext) -> int:
        bans = ctx.server.permissions.get_banlist()
        which = ctx.args[0].lower() if ctx.args else ""
        entries = []
        if which in ("", "players"):
            entries += [(r.get("name", k), r) for k, r in bans["players"].items()]
        if which in ("", "ips"):
            entries += [(ip, r) for ip, r in bans["ips"].items()]
        if not entries:
            await ctx.reply(translate("commands.banlist.none"))
            return SUCCESS
        await ctx.reply(translate("commands.banlist.list", len(entries)))
        for name, record in entries:
            await ctx.reply(translate(
                "commands.banlist.entry", _text(name), _text(record.get("source") or "Server"),
                _text(record.get("reason") or "Banned by an operator.")))
        return SUCCESS

    _command(manager, "banlist", _banlist, "command.banlist", "banlist [ips|players]")

    # ---------------- op / deop ----------------
    async def _op(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        names = [p.username for p in _resolve(ctx, ctx.args[0]) if _is_player(p)] \
            or ([] if ctx.args[0].startswith("@") else [_profile_name(ctx, ctx.args[0])])
        changed = 0
        for name in names:
            if ctx.server.permissions.op(name):
                changed += 1
                await ctx.success(translate("commands.op.success", _text(name)))
                online = ctx.server.find_player(name)
                if online is not None:
                    await refresh_permissions(ctx.server, online)
        if not changed:
            return await ctx.fail(translate("commands.op.failed"))
        return SUCCESS

    _command(manager, "op", _op, "command.op", "op <targets>")

    async def _deop(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        names = [p.username for p in _resolve(ctx, ctx.args[0]) if _is_player(p)] \
            or ([] if ctx.args[0].startswith("@") else [_profile_name(ctx, ctx.args[0])])
        changed = 0
        for name in names:
            if ctx.server.permissions.deop(name):
                changed += 1
                await ctx.success(translate("commands.deop.success", _text(name)))
                online = ctx.server.find_player(name)
                if online is not None:
                    await refresh_permissions(ctx.server, online)
        if not changed:
            return await ctx.fail(translate("commands.deop.failed"))
        return SUCCESS

    _command(manager, "deop", _deop, "command.deop", "deop <targets>")

    # ---------------- whitelist ----------------
    async def _enforce_whitelist(ctx: CommandContext):
        if not ctx.server.config.get("enforce-whitelist", False):
            return
        permissions = ctx.server.permissions
        if not permissions.data["whitelist"]["enabled"]:
            return
        for player in ctx.server.get_online_players():
            if not permissions.is_whitelisted(player.username) \
                    and not permissions.is_op(player.username):
                await player.disconnect(translate("multiplayer.disconnect.not_whitelisted"))

    async def _whitelist(ctx: CommandContext) -> int:
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        permissions = ctx.server.permissions
        action = args[0].lower()
        enabled = bool(permissions.data["whitelist"]["enabled"])
        if action == "on":
            if enabled:
                return await ctx.fail(translate("commands.whitelist.alreadyOn"))
            permissions.set_whitelist_enabled(True)
            await ctx.success(translate("commands.whitelist.enabled"))
            await _enforce_whitelist(ctx)
        elif action == "off":
            if not enabled:
                return await ctx.fail(translate("commands.whitelist.alreadyOff"))
            permissions.set_whitelist_enabled(False)
            await ctx.success(translate("commands.whitelist.disabled"))
        elif action == "list":
            names = permissions.data["whitelist"]["players"]
            if not names:
                await ctx.reply(translate("commands.whitelist.none"))
            else:
                await ctx.reply(translate("commands.whitelist.list", len(names), ", ".join(names)))
        elif action in ("add", "remove") and len(args) >= 2:
            name = _profile_name(ctx, args[1])
            if action == "add":
                if not permissions.add_whitelist(name):
                    return await ctx.fail(translate("commands.whitelist.add.failed"))
                await ctx.success(translate("commands.whitelist.add.success", _text(name)))
            else:
                if not permissions.remove_whitelist(name):
                    return await ctx.fail(translate("commands.whitelist.remove.failed"))
                await ctx.success(translate("commands.whitelist.remove.success", _text(name)))
                await _enforce_whitelist(ctx)
        elif action == "reload":
            permissions.load()
            permissions.data["whitelist"]["enabled"] = enabled
            await ctx.success(translate("commands.whitelist.reloaded"))
            await _enforce_whitelist(ctx)
        else:
            return await _incomplete(ctx)
        return SUCCESS

    _command(manager, "whitelist", _whitelist, "command.whitelist",
             "whitelist (on|off|list|add|remove|reload)")

    # ---------------- stop / save ----------------
    async def _stop(ctx: CommandContext) -> int:
        await ctx.success(translate("commands.stop.stopping"))
        ctx.server.request_stop()
        return SUCCESS

    _command(manager, "stop", _stop, "command.stop", "stop")

    async def _save_all(ctx: CommandContext) -> int:
        server = ctx.server
        await ctx.success(translate("commands.save.saving"), broadcast_to_ops=False)
        try:
            server.save_all_player_states()
            server.world_storage.flush()
            from world.block_behavior import container_manager
            container_manager.save(str(server.world_storage.world_dir))
            server.save_level_data()
        except Exception:
            return await ctx.fail(translate("commands.save.failed"))
        await ctx.success(translate("commands.save.success"))
        return SUCCESS

    _command(manager, "save-all", _save_all, "command.save-all", "save-all [flush]")

    async def _save_on(ctx: CommandContext) -> int:
        if ctx.server.autosave_enabled:
            return await ctx.fail(translate("commands.save.alreadyOn"))
        ctx.server.autosave_enabled = True
        await ctx.success(translate("commands.save.enabled"))
        return SUCCESS

    async def _save_off(ctx: CommandContext) -> int:
        if not ctx.server.autosave_enabled:
            return await ctx.fail(translate("commands.save.alreadyOff"))
        ctx.server.autosave_enabled = False
        await ctx.success(translate("commands.save.disabled"))
        return SUCCESS

    _command(manager, "save-on", _save_on, "command.save-on", "save-on")
    _command(manager, "save-off", _save_off, "command.save-off", "save-off")

    # ---------------- seed ----------------
    async def _seed(ctx: CommandContext) -> int:
        seed = str(int(getattr(ctx.server, "seed", 0)))
        seed_component = {
            "translate": "chat.square_brackets",
            "with": [{"text": seed, "color": "green",
                      "clickEvent": {"action": "copy_to_clipboard", "value": seed},
                      "hoverEvent": {"action": "show_text",
                                     "contents": {"translate": "chat.copy.click"}},
                      "insertion": seed}],
        }
        await ctx.reply(translate("commands.seed.success", seed_component))
        return SUCCESS

    _command(manager, "seed", _seed, "command.seed", "seed")

    # ---------------- time ----------------
    async def _sync_time(server):
        from handlers.play.join import _send_time_update
        for player in server.get_online_players():
            await _send_time_update(player, server)

    def _parse_time(raw: str) -> int | None:
        raw = raw.lower()
        scale = 1
        if raw and raw[-1] in "dst":
            scale = {"d": 24000, "s": 20, "t": 1}[raw[-1]]
            raw = raw[:-1]
        try:
            value = float(raw)
        except ValueError:
            return None
        return int(round(value * scale)) if value >= 0 else None

    async def _time(ctx: CommandContext) -> int:
        args = ctx.args
        if len(args) < 2:
            return await _incomplete(ctx)
        manager_ = ctx.server._time_manager
        action = args[0].lower()
        if action == "set":
            presets = {"day": 1000, "noon": 6000, "night": 13000, "midnight": 18000}
            value = presets.get(args[1].lower())
            if value is None:
                value = _parse_time(args[1])
            if value is None:
                return await ctx.fail(translate("argument.time.invalid_unit"))
            manager_.day_time_total = value
            await _sync_time(ctx.server)
            await ctx.success(translate("commands.time.set", value))
        elif action == "add":
            value = _parse_time(args[1])
            if value is None:
                return await ctx.fail(translate("argument.time.invalid_unit"))
            manager_.add_time(value)
            await _sync_time(ctx.server)
            await ctx.success(translate("commands.time.set", manager_.time))
        elif action == "query":
            what = args[1].lower()
            values = {"daytime": manager_.time, "gametime": manager_.age % 2147483647,
                      "day": manager_.get_day_count() % 2147483647}
            if what not in values:
                return await _incomplete(ctx)
            await ctx.reply(translate("commands.time.query", values[what]))
        else:
            return await _incomplete(ctx)
        return SUCCESS

    _command(manager, "time", _time, "command.time", "time (add|query|set)")

    # ---------------- weather ----------------
    async def _weather(ctx: CommandContext) -> int:
        args = ctx.args
        if not args or args[0].lower() not in ("clear", "rain", "thunder"):
            return await _incomplete(ctx)
        kind = args[0].lower()
        duration = 0
        if len(args) >= 2:
            parsed = _parse_time(args[1])
            if parsed is None:
                return await ctx.fail(translate("argument.time.invalid_unit"))
            duration = parsed
        else:
            import random
            ranges = {"clear": (12000, 180000), "rain": (12000, 24000), "thunder": (3600, 15600)}
            duration = random.randint(*ranges[kind])
        await ctx.server.set_weather(kind, duration)
        await ctx.success(translate(f"commands.weather.set.{kind}"))
        return SUCCESS

    _command(manager, "weather", _weather, "command.weather", "weather (clear|rain|thunder)")

    # ---------------- difficulty ----------------
    async def _difficulty(ctx: CommandContext) -> int:
        server = ctx.server
        current = str(server.config.get("difficulty", "easy")).lower()
        if not ctx.args:
            await ctx.reply(translate("commands.difficulty.query", _difficulty_component(current)))
            return SUCCESS
        wanted = ctx.args[0].lower()
        wanted = {"0": "peaceful", "1": "easy", "2": "normal", "3": "hard",
                  "p": "peaceful", "e": "easy", "n": "normal", "h": "hard"}.get(wanted, wanted)
        if wanted not in DIFFICULTIES:
            return await _incomplete(ctx)
        if wanted == current:
            return await ctx.fail(translate("commands.difficulty.failure",
                                            _difficulty_component(current)))
        server.config["difficulty"] = wanted
        server.save_runtime_config()
        from handlers.play.state import send_difficulty
        for player in server.get_online_players():
            await send_difficulty(player, server)
        await ctx.success(translate("commands.difficulty.success", _difficulty_component(wanted)))
        return SUCCESS

    _command(manager, "difficulty", _difficulty, "command.difficulty",
             "difficulty [peaceful|easy|normal|hard]")

    # ---------------- gamerule ----------------
    async def _gamerule(ctx: CommandContext) -> int:
        args = ctx.args
        rules = ctx.server.gamerules
        if not args:
            return await _incomplete(ctx)
        known = {name.lower(): name for name in rules.known_rules()} \
            if hasattr(rules, "known_rules") else {}
        name = known.get(args[0].lower())
        if name is None:
            return await _incomplete(ctx)
        if len(args) == 1:
            value = rules.get(name)
            shown = str(value).lower() if isinstance(value, bool) else str(value)
            await ctx.reply(translate("commands.gamerule.query", _text(name), _text(shown)))
            return SUCCESS
        raw = args[1]
        old = rules.get(name)
        if isinstance(old, bool):
            if raw.lower() not in ("true", "false"):
                return await ctx.fail(translate("parsing.bool.invalid", raw))
        else:
            try:
                int(raw)
            except ValueError:
                return await ctx.fail(translate("parsing.int.invalid", raw))
        rules.set(name, raw)
        value = rules.get(name)
        shown = str(value).lower() if isinstance(value, bool) else str(value)
        try:
            from plugins.bridge import hook_gamerule_change
            hook_gamerule_change(ctx.server, name, old, value)
        except Exception:
            pass
        if name == "doDaylightCycle":
            await _sync_time(ctx.server)
        elif name == "doImmediateRespawn":
            from handlers.play.state import send_game_event
            for player in ctx.server.get_online_players():
                await send_game_event(player, 11, 1.0 if value else 0.0)
        ctx.server.save_level_data()
        await ctx.success(translate("commands.gamerule.set", _text(name), _text(shown)))
        return SUCCESS

    _command(manager, "gamerule", _gamerule, "command.gamerule", "gamerule <rule> [<value>]")

    # ---------------- gamemode / defaultgamemode ----------------
    def _parse_mode(raw: str) -> str | None:
        from handlers.play.state import normalize_gamemode
        mode = normalize_gamemode(raw, "")
        return mode if mode in GAMEMODES else None

    async def _gamemode(ctx: CommandContext) -> int:
        from handlers.play.chat import send_system_message
        from handlers.play.state import set_player_gamemode
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        mode = _parse_mode(args[0])
        if mode is None:
            return await ctx.fail(translate("argument.gamemode.invalid", args[0]))
        if len(args) >= 2:
            targets = await _players(ctx, args[1])
            if targets is None:
                return FAILURE
        elif ctx.sender is not None:
            targets = [ctx.sender]
        else:
            return await ctx.fail(translate("permissions.requires.player"))
        changed = 0
        for target in targets:
            old = target.gamemode
            if old == mode:
                continue
            await set_player_gamemode(ctx.server, target, mode)
            changed += 1
            try:
                from plugins.bridge import hook_player_gamemode_change
                hook_player_gamemode_change(ctx.server, target, GAMEMODES.index(old),
                                            GAMEMODES.index(mode))
            except Exception:
                pass
            if target is ctx.sender:
                await ctx.success(translate("commands.gamemode.success.self",
                                            _gamemode_component(mode)))
            else:
                if ctx.server.gamerules.get("sendCommandFeedback", True):
                    await send_system_message(
                        target, translate("gameMode.changed", _gamemode_component(mode)))
                await ctx.success(translate("commands.gamemode.success.other",
                                            player_name(target), _gamemode_component(mode)))
        return SUCCESS if changed else FAILURE

    _command(manager, "gamemode", _gamemode, "command.gamemode",
             "gamemode <gamemode> [<target>]")

    async def _defaultgamemode(ctx: CommandContext) -> int:
        if not ctx.args:
            return await _incomplete(ctx)
        mode = _parse_mode(ctx.args[0])
        if mode is None:
            return await ctx.fail(translate("argument.gamemode.invalid", ctx.args[0]))
        ctx.server.config["gamemode"] = mode
        ctx.server.save_runtime_config()
        if ctx.server.config.get("force-gamemode", False):
            from handlers.play.state import set_player_gamemode
            for player in ctx.server.get_online_players():
                if player.gamemode != mode:
                    await set_player_gamemode(ctx.server, player, mode)
        await ctx.success(translate("commands.defaultgamemode.success",
                                    _gamemode_component(mode)))
        return SUCCESS

    _command(manager, "defaultgamemode", _defaultgamemode, "command.defaultgamemode",
             "defaultgamemode <gamemode>")

    # ---------------- teleport ----------------
    def _looks_like_coord(token: str) -> bool:
        if token.startswith(("~", "^")):
            return True
        try:
            float(token)
            return True
        except ValueError:
            return False

    def _coords(ctx: CommandContext, tokens: list[str], base) -> tuple | None:
        from commands.arguments import parse_coordinate, resolve_coordinate
        try:
            out = []
            for index, token in enumerate(tokens[:3]):
                parsed = parse_coordinate(token)
                value = resolve_coordinate(parsed, base[index])
                # vanilla: integer x/z without a decimal point are block-centred
                if index != 1 and token.lstrip("-").isdigit():
                    value += 0.5
                out.append(value)
            return tuple(out)
        except (ValueError, IndexError):
            return None

    async def _tp(ctx: CommandContext) -> int:
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        server = ctx.server
        sender = ctx.sender

        if _looks_like_coord(args[0]):
            # /tp <x> <y> <z>
            if sender is None:
                return await ctx.fail(translate("permissions.requires.entity"))
            if len(args) < 3:
                return await _incomplete(ctx)
            targets, coord_tokens, rest = [sender], args[0:3], args[3:]
        elif len(args) == 1:
            # /tp <destination>
            if sender is None:
                return await ctx.fail(translate("permissions.requires.entity"))
            dest = await _entities(ctx, args[0])
            if dest is None:
                return FAILURE
            if len(dest) > 1:
                return await ctx.fail(translate("argument.entity.toomany"))
            await teleport(server, sender, dest[0].x, dest[0].y, dest[0].z,
                           dest[0].yaw, dest[0].pitch)
            await ctx.success(translate("commands.teleport.success.entity.single",
                                        _entity_name(sender), _entity_name(dest[0])))
            return SUCCESS
        elif len(args) == 2:
            # /tp <targets> <destination>
            targets = await _entities(ctx, args[0])
            if targets is None:
                return FAILURE
            dest = await _entities(ctx, args[1])
            if dest is None:
                return FAILURE
            if len(dest) > 1:
                return await ctx.fail(translate("argument.entity.toomany"))
            for target in targets:
                await teleport(server, target, dest[0].x, dest[0].y, dest[0].z,
                               dest[0].yaw, dest[0].pitch)
            if len(targets) == 1:
                await ctx.success(translate("commands.teleport.success.entity.single",
                                            _entity_name(targets[0]), _entity_name(dest[0])))
            else:
                await ctx.success(translate("commands.teleport.success.entity.multiple",
                                            len(targets), _entity_name(dest[0])))
            return SUCCESS
        else:
            # /tp <targets> <x> <y> <z> [<yaw> <pitch>]
            targets = await _entities(ctx, args[0])
            if targets is None:
                return FAILURE
            if len(args) < 4:
                return await _incomplete(ctx)
            coord_tokens, rest = args[1:4], args[4:]

        base = ctx.get_sender_position()
        position = _coords(ctx, coord_tokens, base)
        if position is None:
            return await ctx.fail(translate("argument.pos3d.incomplete"))
        x, y, z = position
        if abs(x) > 3.0e7 or abs(z) > 3.0e7 or not -2.0e7 <= y <= 2.0e7:
            return await ctx.fail(translate("commands.teleport.invalidPosition"))
        yaw = pitch = None
        if len(rest) >= 2:
            try:
                yaw, pitch = float(rest[0].lstrip("~") or 0), float(rest[1].lstrip("~") or 0)
            except ValueError:
                yaw = pitch = None
        for target in targets:
            await teleport(server, target, x, y, z, yaw, pitch)
        if len(targets) == 1:
            await ctx.success(translate("commands.teleport.success.location.single",
                                        _entity_name(targets[0]), _fmt(x), _fmt(y), _fmt(z)))
        else:
            await ctx.success(translate("commands.teleport.success.location.multiple",
                                        len(targets), _fmt(x), _fmt(y), _fmt(z)))
        return SUCCESS

    _command(manager, "tp", _tp, "command.tp",
             "tp (<destination>|<location>|<targets> ...)", aliases=["teleport"])

    # ---------------- give ----------------
    async def _give(ctx: CommandContext) -> int:
        from world.inventory import ItemStack, is_known_item, send_inventory_sync
        args = ctx.args
        if len(args) < 2:
            return await _incomplete(ctx)
        targets = await _players(ctx, args[0])
        if targets is None:
            return FAILURE
        item_id = args[1].split("[", 1)[0].split("{", 1)[0].lower()
        if ":" not in item_id:
            item_id = f"minecraft:{item_id}"
        if not is_known_item(item_id) or item_id == "minecraft:air":
            return await ctx.fail(translate("argument.item.id.invalid", item_id))
        count = 1
        if len(args) >= 3:
            try:
                count = int(args[2])
            except ValueError:
                return await ctx.fail(translate("parsing.int.invalid", args[2]))
            if count < 1:
                return await ctx.fail(translate("argument.integer.low", 1, count))
        stack_size = ItemStack(item_id, 1).max_stack_size
        if count > stack_size * 100:
            return await ctx.fail(translate("commands.give.failed.toomanyitems",
                                            stack_size * 100, _item_component(item_id)))
        for target in targets:
            inventory = getattr(target, "inventory_obj", None)
            if inventory is None:
                continue
            leftover = inventory.add_item(ItemStack(item_id, count))
            target.inventory_state_id += 1
            await send_inventory_sync(target)
            if leftover > 0:
                # 物品栏放不下: 掉落在玩家脚下 (原版行为)
                remaining = leftover
                while remaining > 0:
                    drop = min(stack_size, remaining)
                    entity = ctx.server.entity_manager.create_item(
                        target.x, target.y + 0.5, target.z, item_id, drop)
                    entity.pickup_delay = 0
                    remaining -= drop
            from handlers.play.players import broadcast_player_equipment
            await broadcast_player_equipment(ctx.server, target)
        if len(targets) == 1:
            await ctx.success(translate("commands.give.success.single", count,
                                        _item_component(item_id), player_name(targets[0])))
        else:
            await ctx.success(translate("commands.give.success.multiple", count,
                                        _item_component(item_id), len(targets)))
        return SUCCESS

    _command(manager, "give", _give, "command.give", "give <targets> <item> [<count>]")

    # ---------------- clear ----------------
    async def _clear(ctx: CommandContext) -> int:
        from world.inventory import send_inventory_sync
        args = ctx.args
        if args:
            targets = await _players(ctx, args[0])
            if targets is None:
                return FAILURE
        elif ctx.sender is not None:
            targets = [ctx.sender]
        else:
            return await ctx.fail(translate("permissions.requires.player"))
        item_filter = None
        if len(args) >= 2:
            item_filter = args[1].lower()
            if ":" not in item_filter:
                item_filter = f"minecraft:{item_filter}"
        max_count = -1
        if len(args) >= 3:
            try:
                max_count = max(0, int(args[2]))
            except ValueError:
                return await ctx.fail(translate("parsing.int.invalid", args[2]))
        total = 0
        for target in targets:
            inventory = getattr(target, "inventory_obj", None)
            if inventory is None:
                continue
            if max_count == 0:
                total += inventory.count_item(item_filter) if item_filter else sum(
                    s.count for s in inventory.slots if s is not None)
                continue
            removed = inventory.clear_items(item_filter, max_count)
            if item_filter is None and getattr(inventory, "carried_item", None) is not None:
                removed += inventory.carried_item.count
                inventory.carried_item = None
            total += removed
            target.inventory_state_id += 1
            await send_inventory_sync(target)
            from handlers.play.players import broadcast_player_equipment
            await broadcast_player_equipment(ctx.server, target)
        if total == 0:
            if len(targets) == 1:
                return await ctx.fail(translate("clear.failed.single", player_name(targets[0])))
            return await ctx.fail(translate("clear.failed.multiple", len(targets)))
        prefix = "commands.clear.test" if max_count == 0 else "commands.clear.success"
        if len(targets) == 1:
            await ctx.success(translate(f"{prefix}.single", total, player_name(targets[0])))
        else:
            await ctx.success(translate(f"{prefix}.multiple", total, len(targets)))
        return SUCCESS

    _command(manager, "clear", _clear, "command.clear", "clear [<targets>] [<item>] [<maxCount>]")

    # ---------------- kill ----------------
    async def _kill(ctx: CommandContext) -> int:
        from handlers.play.join import _kill_player
        if ctx.args:
            targets = await _entities(ctx, ctx.args[0])
            if targets is None:
                return FAILURE
        elif ctx.sender is not None:
            targets = [ctx.sender]
        else:
            return await ctx.fail(translate("permissions.requires.entity"))
        for target in targets:
            if _is_player(target):
                if not getattr(target, "_dead", False):
                    await _kill_player(target, ctx.server, translate(
                        "death.attack.genericKill", player_name(target)))
                    from handlers.play.join import _send_update_health
                    await _send_update_health(target)
            elif getattr(target, "kind", "") == "mob":
                from handlers.play.combat import damage_mob
                damage_mob(ctx.server, target, float("inf"))
            else:
                ctx.server.entity_manager.remove_entity(target.entity_id)
        if len(targets) == 1:
            await ctx.success(translate("commands.kill.success.single", _entity_name(targets[0])))
        else:
            await ctx.success(translate("commands.kill.success.multiple", len(targets)))
        return SUCCESS

    _command(manager, "kill", _kill, "command.kill", "kill [<targets>]")

    # ---------------- experience ----------------
    def _points_for_level(level: int) -> int:
        if level >= 30:
            return 112 + (level - 30) * 9
        if level >= 15:
            return 37 + (level - 15) * 5
        return 7 + level * 2

    def _total_for_level(level: int) -> int:
        return sum(_points_for_level(i) for i in range(max(0, level)))

    async def _xp(ctx: CommandContext) -> int:
        from handlers.play.join import _add_player_experience, _send_set_experience
        args = ctx.args
        if len(args) < 2:
            return await _incomplete(ctx)
        action = args[0].lower()
        targets = await _players(ctx, args[1])
        if targets is None:
            return FAILURE
        if action == "query":
            if len(args) < 3 or args[2].lower() not in ("points", "levels") or len(targets) > 1:
                return await _incomplete(ctx)
            target = targets[0]
            if args[2].lower() == "levels":
                await ctx.reply(translate("commands.experience.query.levels",
                                          player_name(target), target.experience_level))
            else:
                points = int(round(target.experience_progress
                                   * _points_for_level(target.experience_level)))
                await ctx.reply(translate("commands.experience.query.points",
                                          player_name(target), points))
            return SUCCESS
        if action not in ("add", "set") or len(args) < 3:
            return await _incomplete(ctx)
        try:
            amount = int(args[2])
        except ValueError:
            return await ctx.fail(translate("parsing.int.invalid", args[2]))
        unit = args[3].lower() if len(args) >= 4 else "points"
        if unit not in ("points", "levels"):
            return await _incomplete(ctx)
        if action == "set" and amount < 0:
            return await ctx.fail(translate("argument.integer.low", 0, amount))
        for target in targets:
            if unit == "levels":
                level = amount if action == "set" else target.experience_level + amount
                target.experience_level = max(0, level)
                if target.experience_level == 0 and level < 0:
                    target.experience_progress = 0.0
            elif action == "set":
                needed = _points_for_level(target.experience_level)
                if amount >= needed:
                    return await ctx.fail(translate("commands.experience.set.points.invalid"))
                target.experience_progress = amount / needed
            elif amount >= 0:
                await _add_player_experience(target, amount)
                continue
            else:
                points = (_total_for_level(target.experience_level)
                          + int(round(target.experience_progress
                                      * _points_for_level(target.experience_level))) + amount)
                points = max(0, points)
                level = 0
                while points >= _points_for_level(level):
                    points -= _points_for_level(level)
                    level += 1
                target.experience_level = level
                target.experience_progress = points / _points_for_level(level)
            target.experience_total = _total_for_level(target.experience_level) + int(round(
                target.experience_progress * _points_for_level(target.experience_level)))
            await _send_set_experience(target)
        key = f"commands.experience.{action}.{unit}.success"
        if len(targets) == 1:
            await ctx.success(translate(f"{key}.single", amount, player_name(targets[0])))
        else:
            await ctx.success(translate(f"{key}.multiple", amount, len(targets)))
        return SUCCESS

    _command(manager, "xp", _xp, "command.xp", "xp (add|set|query) <target> ...",
             aliases=["experience"])

    # ---------------- setworldspawn / spawnpoint ----------------
    def _block_pos(ctx: CommandContext, tokens: list[str]) -> tuple[int, int, int] | None:
        if len(tokens) < 3:
            if ctx.sender is None:
                return None
            return (math.floor(ctx.sender.x), math.floor(ctx.sender.y), math.floor(ctx.sender.z))
        return ctx.parse_int_coordinates(tokens, 0)

    async def _setworldspawn(ctx: CommandContext) -> int:
        position = _block_pos(ctx, ctx.args)
        if position is None:
            return await _incomplete(ctx)
        server = ctx.server
        server.spawn_position = position
        server._spawn_resolved = True
        server.save_level_data()
        from handlers.play.join import _send_spawn_position
        for player in server.get_online_players():
            await _send_spawn_position(player, *position)
        await ctx.success(translate("commands.setworldspawn.success", *position, _fmt(0.0)))
        return SUCCESS

    _command(manager, "setworldspawn", _setworldspawn, "command.setworldspawn",
             "setworldspawn [<pos>]")

    async def _spawnpoint(ctx: CommandContext) -> int:
        args = ctx.args
        if args:
            targets = await _players(ctx, args[0])
            if targets is None:
                return FAILURE
        elif ctx.sender is not None:
            targets = [ctx.sender]
        else:
            return await ctx.fail(translate("permissions.requires.player"))
        position = _block_pos(ctx, args[1:])
        if position is None:
            return await _incomplete(ctx)
        for target in targets:
            target.personal_spawn = position
            server_of(ctx).save_player_state(target)
        if len(targets) == 1:
            await ctx.success(translate("commands.spawnpoint.success.single", *position,
                                        _fmt(0.0), "minecraft:overworld", player_name(targets[0])))
        else:
            await ctx.success(translate("commands.spawnpoint.success.multiple", *position,
                                        _fmt(0.0), "minecraft:overworld", len(targets)))
        return SUCCESS

    _command(manager, "spawnpoint", _spawnpoint, "command.spawnpoint",
             "spawnpoint [<targets>] [<pos>]")

    # ---------------- summon ----------------
    async def _summon(ctx: CommandContext) -> int:
        from world.entities import MOB_PROFILES
        from handlers.play.entities import broadcast_entity_spawn
        args = ctx.args
        if not args:
            return await _incomplete(ctx)
        entity_type = args[0].lower().split(":", 1)[-1]
        base = ctx.get_sender_position()
        position = base
        if len(args) >= 4:
            position = ctx.parse_coordinates(args, 1)
            if position is None:
                return await ctx.fail(translate("argument.pos3d.incomplete"))
        x, y, z = position
        manager_ = ctx.server.entity_manager
        if entity_type == "lightning_bolt":
            entity = manager_.create_lightning(x, y, z)
        elif entity_type in MOB_PROFILES:
            entity = manager_.create_mob(x, y, z, mob_type=entity_type)
        else:
            from protocol.gamedata import entity_type_ids
            if f"minecraft:{entity_type}" not in entity_type_ids():
                return await ctx.fail(translate("argument.resource.invalid_type",
                                                f"minecraft:{entity_type}",
                                                "minecraft:entity_type", "minecraft:entity_type"))
            return await ctx.fail(translate("commands.summon.failed"))
        await broadcast_entity_spawn(ctx.server, entity)
        try:
            from plugins.bridge import hook_entity_spawn
            hook_entity_spawn(ctx.server, entity.entity_id, entity_type, x, y, z)
        except Exception:
            pass
        await ctx.success(translate(
            "commands.summon.success",
            {"translate": f"entity.minecraft.{entity_type}", "fallback": entity_type}))
        return SUCCESS

    _command(manager, "summon", _summon, "command.summon", "summon <entity> [<pos>]")
