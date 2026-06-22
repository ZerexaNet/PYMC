# ============================================================
# PyMC - Vanilla Commands Registration
# Registers all vanilla and PyMC-specific commands
#
# Command modules are organized as consolidated files:
#   core.py        - help, list, stop, reload, save-all/on/off, save-status
#   player.py      - tp, gamemode, give, clear, kill, xp, effect, enchant, damage
#   world.py       - time, weather, difficulty, seed, setblock, fill, clone,
#                    setworldspawn, spawnpoint, fillbiome
#   entity.py      - summon, ride, spreadplayers
#   server.py      - kick, ban, ban-ip, pardon, pardon-ip, banlist, op, deop,
#                    whitelist, say, me, msg
#   execute_cmd.py - execute command with chained subcommands
#   display.py     - tellraw, title, scoreboard, bossbar, team, tag
#   world_mgmt.py  - worldborder, locate, forceload, place, function, schedule,
#                    datapack, advancement, attribute, recipe, trigger
#
# Individual command files still exist in this directory for backward
# compatibility and can be imported directly if needed.
# ============================================================

from commands.framework import Command, CommandContext, SUCCESS, FAILURE

# --- Consolidated command module imports ---
from commands.vanilla.core import register as register_core
from commands.vanilla.player import register as register_player
from commands.vanilla.world import register as register_world
from commands.vanilla.entity import register as register_entity
from commands.vanilla.server import register as register_server
from commands.vanilla.execute_cmd import register as register_execute_cmd
from commands.vanilla.display import register as register_display
from commands.vanilla.world_mgmt import register as register_world_mgmt

# --- Additional standalone command modules ---
from commands.vanilla.gamerule import register as register_gamerule
from commands.vanilla.particle import register as register_particle
from commands.vanilla.playsound import register as register_playsound
from commands.vanilla.data import register as register_data
from commands.vanilla.item import register as register_item
from commands.vanilla.default_commands import register as register_default


def register_all(manager):
    """Register all vanilla and PyMC-specific commands.
    
    Commands are organized into consolidated modules by category.
    Each consolidated module registers all commands for its category.
    Additional standalone modules register commands not covered by
    the consolidated modules.
    """

    # ===== Core commands =====
    # help, list, stop, reload, save-all, save-on, save-off, save-status
    register_core(manager)
    
    # ===== Player commands =====
    # tp, gamemode, give, clear, kill, xp, effect, enchant, damage
    register_player(manager)
    
    # ===== World commands =====
    # time, weather, difficulty, seed, setblock, fill, clone,
    # setworldspawn, spawnpoint, fillbiome
    register_world(manager)
    
    # ===== Entity commands =====
    # summon, ride, spreadplayers
    register_entity(manager)
    
    # ===== Server administration commands =====
    # kick, ban, ban-ip, pardon, pardon-ip, banlist, op, deop,
    # whitelist, say, me, msg
    register_server(manager)
    
    # ===== Execute command =====
    # execute (with chained subcommands: as, at, positioned, rotated, align,
    # anchored, facing, in, if, unless, store, on, summon, run)
    register_execute_cmd(manager)
    
    # ===== Display commands =====
    # tellraw, title, scoreboard, bossbar, team, tag
    register_display(manager)
    
    # ===== World management commands =====
    # worldborder, locate, forceload, place, function, schedule,
    # datapack, advancement, attribute, recipe, trigger
    register_world_mgmt(manager)

    # ===== Additional commands =====
    # gamerule, particle, playsound, data, item
    register_gamerule(manager)
    register_particle(manager)
    register_playsound(manager)
    register_data(manager)
    register_item(manager)
    
    # Default server commands (includes PyMC-specific commands like
    # entities, group, perm, defaultgamemode, and duplicates of some
    # commands from consolidated modules for backward compatibility)
    register_default(manager)
