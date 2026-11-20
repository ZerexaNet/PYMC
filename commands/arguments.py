# ============================================================
# PyMC - Argument Types
# Specialized argument types for Minecraft commands
# BlockPos, BlockState, ItemStack, Time, Color, Component,
# Identifier, Angle, Rotation, ScoreHolder, etc.
# ============================================================

from __future__ import annotations

import json
import logging
import math
import re

logger = logging.getLogger("PyMC.参数")


# --- Time argument ---

TIME_PRESETS = {
    "day": 1000,
    "noon": 6000,
    "night": 13000,
    "midnight": 18000,
    "sunrise": 23000,
    "sunset": 12000,
}


def parse_time_value(raw: str) -> int:
    """Parse a time value: tick count, preset name, or time string (1d, 5s, etc.).
    
    Supported formats:
      - Integer ticks: "100"
      - Preset names: "day", "noon", "night", "midnight", "sunrise", "sunset"
      - Time units: "10s" (seconds), "5m" (minutes), "1d" (days), "0t" (ticks)
    """
    raw = raw.strip().lower()

    # Check presets
    if raw in TIME_PRESETS:
        return TIME_PRESETS[raw]

    # Check for time suffixes (1d = 24000 ticks, 1s = 20 ticks, 1t = 1 tick, 1m = 1200 ticks)
    match = re.match(r'^(-?\d+(?:\.\d+)?)\s*([dstm])$', raw)
    if match:
        value = float(match.group(1))
        suffix = match.group(2)
        if suffix == 'd':
            return int(value * 24000)
        elif suffix == 's':
            return int(value * 20)
        elif suffix == 'm':
            return int(value * 1200)
        elif suffix == 't':
            return int(value)

    # Raw tick count
    try:
        return int(raw)
    except ValueError:
        raise ValueError(f"Invalid time value: {raw}")


# --- GameMode argument ---

GAMEMODE_MAP = {
    "survival": 0, "s": 0, "0": 0,
    "creative": 1, "c": 1, "1": 1,
    "adventure": 2, "a": 2, "2": 2,
    "spectator": 3, "sp": 3, "3": 3,
}

GAMEMODE_NAMES = {0: "survival", 1: "creative", 2: "adventure", 3: "spectator"}


# --- Difficulty argument ---

DIFFICULTY_MAP = {
    "peaceful": 0, "p": 0, "0": 0,
    "easy": 1, "e": 1, "1": 1,
    "normal": 2, "n": 2, "2": 2,
    "hard": 3, "h": 3, "3": 3,
}


# --- Block state string parsing ---

# --- Coordinate parsing with relative support ---

def parse_coordinate(raw: str) -> tuple[float, bool]:
    """
    Parse a coordinate value, supporting relative (~) and caret (^) notation.

    Returns:
        (value, is_relative) where is_relative means the value is an offset from the entity's position
    """
    raw = raw.strip()
    if raw.startswith("^"):
        # Local coordinates (relative to entity rotation) - treat as relative for now
        offset = float(raw[1:]) if len(raw) > 1 else 0.0
        return (offset, True)
    if raw.startswith("~"):
        offset = float(raw[1:]) if len(raw) > 1 else 0.0
        return (offset, True)
    return (float(raw), False)


def resolve_coordinate(parsed: tuple[float, bool], base: float) -> float:
    """Resolve a parsed coordinate to an absolute value."""
    value, is_relative = parsed
    if is_relative:
        return base + value
    return value


def parse_three_coordinates(tokens: list[str], start: int, base_x: float = 0.0, base_y: float = 100.0, base_z: float = 0.0) -> tuple[float, float, float] | None:
    """
    Parse three coordinate values from tokens starting at the given index.

    Returns:
        (x, y, z) absolute coordinates, or None on parse failure
    """
    if start + 2 >= len(tokens):
        return None
    try:
        px = parse_coordinate(tokens[start])
        py = parse_coordinate(tokens[start + 1])
        pz = parse_coordinate(tokens[start + 2])
        x = resolve_coordinate(px, base_x)
        y = resolve_coordinate(py, base_y)
        z = resolve_coordinate(pz, base_z)
        return (x, y, z)
    except (ValueError, IndexError):
        return None


def parse_int_coordinates(tokens: list[str], start: int, base_x: float = 0.0, base_y: float = 100.0, base_z: float = 0.0) -> tuple[int, int, int] | None:
    """Like parse_three_coordinates but floors to int."""
    result = parse_three_coordinates(tokens, start, base_x, base_y, base_z)
    if result is None:
        return None
    return (int(math.floor(result[0])), int(math.floor(result[1])), int(math.floor(result[2])))


# --- Item stack parsing ---

# --- Effect parsing ---

EFFECT_NAMES = {
    "speed": 1, "haste": 3, "strength": 5, "jump_boost": 8,
    "regeneration": 10, "resistance": 11, "fire_resistance": 12,
    "water_breathing": 13, "invisibility": 14, "slow_falling": 28,
    "luck": 27, "night_vision": 16, "weakness": 18, "poison": 19,
    "wither": 20, "slowness": 2, "mining_fatigue": 4,
    "nausea": 9, "blindness": 15, "hunger": 17, "levitation": 25,
    "glowing": 24, "absorption": 22, "saturation": 23,
    "conduit_power": 26, "dolphins_grace": 30, "bad_omen": 31,
    "hero_of_the_village": 32, "darkness": 33,
    "wind_charged": 34, "weaving": 35, "oozing": 36,
    "infested": 37, "raid_omen": 38, "trial_omen": 39,
}


def parse_effect_name(raw: str) -> str:
    """Parse and normalize an effect name."""
    raw = raw.strip().lower().replace(" ", "_")
    if raw not in EFFECT_NAMES:
        if ":" in raw:
            return raw
        raise ValueError(f"Unknown effect: {raw}")
    return f"minecraft:{raw}"


# --- Enchantment parsing ---

ENCHANTMENT_NAMES = {
    "protection": 1, "fire_protection": 2, "feather_falling": 3,
    "blast_protection": 4, "projectile_protection": 5, "respiration": 6,
    "aqua_affinity": 7, "thorns": 8, "depth_strider": 9,
    "frost_walker": 10, "binding_curse": 11, "sharpness": 12,
    "smite": 13, "bane_of_arthropods": 14, "knockback": 15,
    "fire_aspect": 16, "looting": 17, "sweeping": 18,
    "efficiency": 19, "silk_touch": 20, "unbreaking": 21,
    "fortune": 22, "power": 23, "punch": 24, "flame": 25,
    "infinity": 26, "luck_of_the_sea": 27, "lure": 28,
    "loyalty": 29, "impaling": 30, "riptide": 31,
    "channeling": 32, "mending": 33, "vanishing_curse": 34,
    "soul_speed": 35, "swift_sneak": 36,
    "breach": 37, "density": 38, "wind_burst": 39,
}


def parse_enchantment_name(raw: str) -> str:
    """Parse and normalize an enchantment name."""
    raw = raw.strip().lower().replace(" ", "_")
    if raw not in ENCHANTMENT_NAMES:
        if ":" in raw:
            return raw
        raise ValueError(f"Unknown enchantment: {raw}")
    return f"minecraft:{raw}"


# --- Weather parsing ---

WEATHER_TYPES = {"clear", "rain", "thunder"}


# --- Text component parsing ---

def parse_text_component(raw: str) -> dict:
    """Parse a text component from JSON or plain text.
    
    Supports:
      - JSON text component: '{"text":"Hello","color":"red"}'
      - Plain text: 'Hello World'
      - Selector substitution: '@a' etc (stored as-is)
    """
    raw = raw.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"text": raw}


# --- Damage type parsing ---

DAMAGE_TYPES = {
    "arrow", "trident", "mob_attack", "player_attack",
    "fire", "fire_tick", "lava", "hot_floor", "burn",
    "cactus", "fall", "fly_into_wall", "out_of_world",
    "drown", "starve", "poison", "wither", "thorns",
    "explosion", "explosion.player", "falling_block",
    "magic", "indirect_magic", "lightning_bolt", "freeze",
    "stalagmite", "sonic_boom", "generic", "kill",
    "wither_skull", "dragon_breath", "campfire",
    "cramming", "dry_out", "freeze", "generic_kill",
    "outside_border", "sweet_berry_bush", "thrown_projectile",
    "wind_charge", "mace_smash",
}


def parse_damage_type(raw: str) -> str:
    """Parse a damage type."""
    raw = raw.strip().lower().replace(" ", "_")
    if raw not in DAMAGE_TYPES:
        # Allow custom namespaced types
        if ":" in raw:
            return raw
        raise ValueError(f"Unknown damage type: {raw}")
    return f"minecraft:{raw}"


# --- Particle parsing ---

PARTICLE_NAMES = {
    "ambient_entity_effect", "angry_villager", "block", "block_marker",
    "bubble", "cloud", "crit", "damage_indicator", "dragon_breath",
    "dripping_lava", "falling_lava", "landing_lava", "dripping_water",
    "falling_water", "dust", "dust_color_transition", "effect",
    "elder_guardian", "enchanted_hit", "enchant", "end_rod",
    "entity_effect", "explosion_emitter", "explosion", "gust",
    "small_gust", "gust_emitter", "sonic_boom", "falling_dust",
    "firework", "fishing", "flame", "cherry_leaves", "scrape",
    "sculk_soul", "sculk_charge", "sculk_charge_pop", "soul_fire_flame",
    "soul", "spit", "squid_ink", "sweep_attack", "totem_of_undying",
    "underwater", "splash", "witch", "bubble_pop", "current_down",
    "bubble_column_up", "nautilus", "dolphin", "campfire_cosy_smoke",
    "campfire_signal_smoke", "crying_obsidian", "falling_honey",
    "falling_nectar", "falling_spore_blossom", "spore_blossom_air",
    "dripping_honey", "honey_block", "dripping_obsidian_tear",
    "falling_obsidian_tear", "landing_obsidian_tear", "flash",
    "item", "snowflake", "vault_connection",
    "trial_spawner_detection", "trial_spawner_detection_ominous",
    "ominous_spawning", "raid_omen", "trial_omen",
    "tinted_leaves", "pale_oak_leaves", "dust_plume",
}


def parse_particle_name(raw: str) -> str:
    """Parse a particle type name."""
    raw = raw.strip().lower().replace(" ", "_")
    if raw not in PARTICLE_NAMES:
        if ":" in raw:
            return raw
        raise ValueError(f"Unknown particle: {raw}")
    return f"minecraft:{raw}"


# --- Sound parsing ---

def parse_sound_name(raw: str) -> str:
    """Parse a sound name."""
    raw = raw.strip().lower().replace(" ", "_")
    if ":" not in raw:
        return f"minecraft:{raw}"
    return raw


SOUND_SOURCES = {"master", "music", "record", "weather", "block", "hostile",
                 "neutral", "player", "ambient", "voice"}


def parse_sound_source(raw: str) -> str:
    """Parse a sound source category."""
    raw = raw.strip().lower()
    if raw not in SOUND_SOURCES:
        raise ValueError(f"Invalid sound source: {raw}. Expected: {', '.join(SOUND_SOURCES)}")
    return raw


# --- Scoreboard related ---

DISPLAY_SLOTS = {"below_name", "sidebar", "list", "sidebar.team.black",
                 "sidebar.team.dark_blue", "sidebar.team.dark_green",
                 "sidebar.team.dark_aqua", "sidebar.team.dark_red",
                 "sidebar.team.dark_purple", "sidebar.team.gold",
                 "sidebar.team.gray", "sidebar.team.dark_gray",
                 "sidebar.team.blue", "sidebar.team.green",
                 "sidebar.team.aqua", "sidebar.team.red",
                 "sidebar.team.light_purple", "sidebar.team.yellow",
                 "sidebar.team.white"}


def parse_display_slot(raw: str) -> str:
    """Parse a scoreboard display slot."""
    raw = raw.strip().lower()
    if raw not in DISPLAY_SLOTS:
        raise ValueError(f"Invalid display slot: {raw}")
    return raw


CRITERIA_NAMES = {
    "dummy", "trigger", "death_count", "player_kill_count",
    "total_kill_count", "health", "food", "air", "armor",
    "xp", "level", "killed_by_team.", "teamkill.",
}


def parse_criteria(raw: str) -> str:
    """Parse a scoreboard criteria name."""
    raw = raw.strip().lower()
    # Allow namespaced criteria and prefix-based ones
    if raw in CRITERIA_NAMES:
        return raw
    if any(raw.startswith(prefix) for prefix in ("minecraft.", "killed_by_team.", "teamkill.")):
        return raw
    return raw


# --- Structure/Biome locate ---

STRUCTURE_TYPES = {
    "village", "pillager_outpost", "fortress", "bastion_remnant",
    "end_city", "mineshaft", "mansion", "stronghold",
    "monument", "ancient_city", "shipwreck", "ocean_ruin",
    "buried_treasure", "desert_pyramid", "igloo", "jungle_pyramid",
    "swamp_hut", "trial_chambers",
}

BIOME_NAMES = {
    "plains", "desert", "mountains", "forest", "taiga", "swamp",
    "river", "frozen_ocean", "frozen_river", "snowy_plains",
    "mushroom_fields", "beach", "jungle", "sparse_jungle",
    "deep_ocean", "stony_shore", "snowy_beach", "birch_forest",
    "dark_forest", "flower_forest", "ice_spikes", "ocean",
    "cold_ocean", "lukewarm_ocean", "warm_ocean", "deep_lukewarm_ocean",
    "deep_cold_ocean", "deep_frozen_ocean", "cherry_grove",
    "grove", "snowy_slopes", "jagged_peaks", "frozen_peaks",
    "stony_peaks", "meadow", "mangrove_swamp",
    "badlands", "eroded_badlands", "wooded_badlands",
    "pale_garden",
}


def parse_locate_target(raw: str) -> tuple[str, str]:
    """Parse a locate target. Returns (type, name) where type is 'structure' or 'biome'."""
    raw = raw.strip().lower()
    if ":" in raw:
        raw = raw.split(":", 1)[1]
    if raw in STRUCTURE_TYPES:
        return ("structure", raw)
    if raw in BIOME_NAMES:
        return ("biome", raw)
    # Default to structure for unknown names
    return ("structure", raw)


# --- Clone/Fill mask mode ---

MASK_MODES = {"replace", "masked", "filtered"}
CLONE_MODES = {"normal", "force", "move"}
FILL_MODES = {"replace", "destroy", "keep", "hollow", "outline"}


def parse_clone_mode(raw: str) -> str:
    raw = raw.strip().lower()
    if raw not in CLONE_MODES:
        raise ValueError(f"Invalid clone mode: {raw}")
    return raw


def parse_fill_mode(raw: str) -> str:
    raw = raw.strip().lower()
    if raw not in FILL_MODES:
        raise ValueError(f"Invalid fill mode: {raw}")
    return raw


# --- Color parsing ---

VALID_COLORS = {
    "black", "dark_blue", "dark_green", "dark_aqua", "dark_red",
    "dark_purple", "gold", "gray", "dark_gray", "blue", "green",
    "aqua", "red", "light_purple", "yellow", "white",
}


# --- Identifier parsing ---

# --- Angle parsing ---

# --- Rotation parsing ---

# --- Score holder parsing ---

# --- Entity type parsing ---

MOB_TYPES = {
    "pig", "cow", "sheep", "chicken", "wolf", "cat", "horse",
    "zombie", "skeleton", "creeper", "spider", "enderman",
    "witch", "slime", "phantom", "blaze", "ghast",
    "silverfish", "endermite", "guardian", "shulker",
    "evoker", "vindicator", "pillager", "ravager",
    "wither_skeleton", "stray", "husk", "zombie_villager",
    "villager", "iron_golem", "snow_golem", "bat",
    "bee", "fox", "panda", "dolphin", "squid",
    "glow_squid", "axolotl", "goat", "frog", "tadpole",
    "allay", "warden", "camel", "sniffer", "armadillo",
    "bogged", "breeze", "wind_charger",
}


# --- Attribute parsing ---

ATTRIBUTE_NAMES = {
    "max_health", "knockback_resistance", "movement_speed",
    "attack_damage", "armor", "armor_toughness",
    "luck", "attack_speed", "follow_range",
    "flying_speed", "horse_jump_strength",
    "zombie_spawn_reinforcements_chance",
    "generic.max_health", "generic.knockback_resistance",
    "generic.movement_speed", "generic.attack_damage",
    "generic.armor", "generic.armor_toughness",
    "generic.luck", "generic.attack_speed",
    "generic.follow_range", "generic.flying_speed",
    "generic.max_absorption",
}


# --- Bossbar parsing ---

BOSSBAR_COLORS = {"pink", "blue", "red", "green", "yellow", "purple", "white"}
BOSSBAR_STYLES = {
    "progress", "notched_6", "notched_10", "notched_12", "notched_20"
}


# --- Datapack parsing ---

DATAPACK_ACTIONS = {"enable", "disable", "list"}


# --- Forceload parsing ---

FORCELOAD_ACTIONS = {"add", "remove", "query"}


# --- Trigger parsing ---

TRIGGER_ACTIONS = {"enable", "set", "add"}


# --- Ride parsing ---

RIDE_ACTIONS = {"mount", "dismount"}


# --- Item command actions ---

ITEM_ACTIONS = {"replace", "modify"}


# --- Recipe parsing ---

RECIPE_ACTIONS = {"give", "take"}


# --- Advancement parsing ---

ADVANCEMENT_ACTIONS = {"grant", "revoke"}


# --- Schedule parsing ---

SCHEDULE_ACTIONS = {"function", "clear"}


# --- Place parsing ---

PLACE_TYPES = {"structure", "jigsaw", "template"}


# --- Worldborder parsing ---

WORLDBORDER_ACTIONS = {"add", "set", "center", "damage", "get", "set", "warning", "shrink"}


# --- Data command parsing ---

DATA_TARGETS = {"block", "entity", "storage"}
DATA_ACTIONS = {"get", "merge", "modify", "remove"}


# --- Title command parsing ---

TITLE_ACTIONS = {"title", "subtitle", "actionbar", "times", "clear", "reset"}


# --- Tag command parsing ---

TAG_ACTIONS = {"add", "remove", "list"}


# --- Team command parsing ---

TEAM_ACTIONS = {"add", "remove", "join", "leave", "list", "modify", "empty"}


# --- Gamerule parsing ---

GAMERULE_NAMES = {
    "announceadvancements", "commandblockoutput", "disableraids",
    "dodaylightcycle", "doentitydrops", "dofiretick",
    "dogameloggervisual", "doimmediaterespawn",
    "doinfinityfireworksliding", "domobloot", "domobspawning",
    "dotiledrops", "doweathercycle", "drowningdamage",
    "falldamage", "firedamage", "forgivedeadplayers",
    "keepinventory", "logadmincommands", "mobgriefing",
    "naturalregeneration", "playerssleepingpercentage",
    "randomtickspeed", "reduceddebuginfo", "sendcommandfeedback",
    "showdeatmessages", "spawnradius", "spectatorsgeneratechunks",
    "villagertradingrebalance",
}

BOOLEAN_GAMERULES = {
    "announceadvancements", "commandblockoutput", "disableraids",
    "dodaylightcycle", "doentitydrops", "dofiretick",
    "doimmediaterespawn", "domobloot", "domobspawning",
    "dotiledrops", "doweathercycle", "drowningdamage",
    "falldamage", "firedamage", "forgivedeadplayers",
    "keepinventory", "logadmincommands", "mobgriefing",
    "naturalregeneration", "reduceddebuginfo", "sendcommandfeedback",
    "spectatorsgeneratechunks",
}

INTEGER_GAMERULES = {
    "playerssleepingpercentage", "randomtickspeed", "spawnradius",
}


