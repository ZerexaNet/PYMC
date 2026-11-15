#!/usr/bin/env python3
"""Build world/data/worldgen_overworld.json for the native terrain generator.

Inputs (downloaded on demand into a cache directory, not vendored):

  * misode/mcmeta, branch ``1.21.1-data-json``: the vanilla 1.21.1 worldgen
    data (noise settings, density functions, noise parameters, biomes).
  * cubiomes ``tables/btree20.h`` (MIT, Copyright (c) 2020 Cubitect): the
    overworld multi-noise biome parameter tree. Vanilla builds this table in
    code (OverworldBiomeBuilder) and does not ship it as data; cubiomes'
    encoding reproduces vanilla's R-tree including its tie-breaking order.

The output resolves everything the C++ side would otherwise need to know:
block states become numeric state ids, biomes become PyMC registry ids and
density-function/noise references are kept by name (shared sub-graphs).

Usage:
    python tools/gen_worldgen_data.py [cache_dir]
"""

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

MCMETA = "https://raw.githubusercontent.com/misode/mcmeta/1.21.1-data-json/data/minecraft/worldgen/"
CUBIOMES = "https://raw.githubusercontent.com/Cubitect/cubiomes/master/"
OUT = ROOT / "world" / "data" / "worldgen_overworld.json"


class Fetcher:
    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)

    def get(self, url: str) -> bytes:
        name = re.sub(r"[^A-Za-z0-9_.-]", "_", url.split("://", 1)[1])
        path = self.cache / name
        if not path.exists():
            with urllib.request.urlopen(url, timeout=60) as response:
                path.write_bytes(response.read())
        return path.read_bytes()

    def worldgen(self, kind: str, key: str):
        key = key.split(":", 1)[-1]
        return json.loads(self.get(f"{MCMETA}{kind}/{key}.json"))


def ns(name: str) -> str:
    return name if ":" in name else "minecraft:" + name


# ----------------------------------------------------------------------
# Density functions and noises
# ----------------------------------------------------------------------

class GraphCollector:
    def __init__(self, fetch: Fetcher):
        self.fetch = fetch
        self.functions: dict[str, object] = {}
        self.noises: dict[str, dict] = {}

    def noise(self, key: str) -> str:
        key = ns(key)
        if key not in self.noises:
            data = self.fetch.worldgen("noise", key)
            self.noises[key] = {"firstOctave": data["firstOctave"],
                                "amplitudes": data["amplitudes"]}
        return key

    def walk(self, node):
        """Normalise a density function node; references are collected by name."""
        if isinstance(node, (int, float)):
            return {"type": "constant", "argument": float(node)}
        if isinstance(node, str):
            key = ns(node)
            if key not in self.functions:
                self.functions[key] = None  # break cycles
                self.functions[key] = self.walk(self.fetch.worldgen("density_function", key))
            return {"type": "ref", "name": key}
        node = dict(node)
        kind = node["type"].split(":", 1)[-1]
        node["type"] = kind
        if kind in ("shift_a", "shift_b", "shift"):
            node["argument"] = self.noise(node["argument"])
            return node
        for field in ("argument", "argument1", "argument2", "input", "when_in_range",
                      "when_out_of_range", "shift_x", "shift_y", "shift_z"):
            if field in node and not (kind == "constant" and field == "argument"):
                node[field] = self.walk(node[field])
        if "noise" in node and isinstance(node["noise"], str):
            node["noise"] = self.noise(node["noise"])
        if kind == "spline":
            node["spline"] = self.spline(node["spline"])
        return node

    def spline(self, spline):
        if isinstance(spline, (int, float)):
            return float(spline)
        return {
            "coordinate": self.walk(spline["coordinate"]),
            "points": [
                {"location": p["location"], "derivative": p["derivative"],
                 "value": self.spline(p["value"])}
                for p in spline["points"]
            ],
        }


# ----------------------------------------------------------------------
# Surface rule: resolve block states and biome names
# ----------------------------------------------------------------------

def block_state_id(state: dict) -> int:
    from world.chunk_io import BLOCK_KEY_TO_STATE_ID, BLOCK_NAME_TO_DEFAULT_STATE
    name = ns(state["Name"])
    props = state.get("Properties") or {}
    if not props:
        return BLOCK_NAME_TO_DEFAULT_STATE[name]
    key = (name, tuple(sorted(props.items())))
    if key in BLOCK_KEY_TO_STATE_ID:
        return BLOCK_KEY_TO_STATE_ID[key]
    # Fall back to the default state when the property combination is unknown.
    return BLOCK_NAME_TO_DEFAULT_STATE[name]


def biome_id(name: str) -> int:
    from world.biomes import BIOME_NAME_TO_ID
    return BIOME_NAME_TO_ID[ns(name)]


def convert_surface(node, collector: GraphCollector):
    if isinstance(node, list):
        return [convert_surface(n, collector) for n in node]
    if not isinstance(node, dict):
        return node
    out = {}
    for key, value in node.items():
        if key == "type":
            out[key] = value.split(":", 1)[-1]
        elif key in ("result_state", "default_block", "default_fluid"):
            out[key] = block_state_id(value)
        elif key == "biome_is":
            out[key] = [biome_id(b) for b in value]
        elif key == "noise" and isinstance(value, str):
            out[key] = collector.noise(value)
        else:
            out[key] = convert_surface(value, collector)
    return out


# ----------------------------------------------------------------------
# Biome parameter tree (cubiomes btree20)
# ----------------------------------------------------------------------

def parse_cubiomes_tree(fetch: Fetcher):
    header = fetch.get(CUBIOMES + "tables/btree20.h").decode()
    biomes_h = fetch.get(CUBIOMES + "biomes.h").decode()

    order = int(re.search(r"btree20_order\s*=\s*(\d+)", header).group(1))
    steps = [int(v) for v in re.search(r"btree20_steps\[\]\s*=\s*\{([^}]*)\}", header).group(1).split(",") if v.strip()]
    params_src = re.search(r"btree20_param\[\]\[2\]\s*=\s*\{(.*?)\};", header, re.S).group(1)
    params = [[int(a), int(b)] for a, b in re.findall(r"\{\s*(-?\d+)\s*,\s*(-?\d+)\s*\}", params_src)]
    nodes_src = re.search(r"btree20_nodes\[\]\s*=\s*\{(.*?)\};", header, re.S).group(1)
    nodes_src = re.sub(r"//[^\n]*", "", nodes_src)
    nodes = [int(v, 16) for v in re.findall(r"0x([0-9A-Fa-f]+)", nodes_src)]

    # cubiomes biome enum -> vanilla name
    enum_src = re.search(r"enum BiomeID\s*\{(.*?)\};", biomes_h, re.S).group(1)
    enum_src = re.sub(r"//[^\n]*", "", enum_src)
    values: dict[str, int] = {}
    current = -1
    for entry in enum_src.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" in entry:
            name, expr = (p.strip() for p in entry.split("=", 1))
            expr = expr.replace(" ", "")
            if re.fullmatch(r"-?\d+", expr):
                current = int(expr)
            elif "+" in expr:
                base, add = expr.split("+")
                current = values[base] + int(add)
            else:
                current = values[expr]
        else:
            name = entry
            current += 1
        values[name] = current

    from world.biomes import BIOME_NAME_TO_ID
    id_to_name: dict[int, str] = {}
    for name, value in values.items():
        key = "minecraft:" + name
        if key in BIOME_NAME_TO_ID and value not in id_to_name:
            id_to_name[value] = key
    # cubiomes aliases whose first enum name is a pre-1.18 name
    for name, value in values.items():
        key = "minecraft:" + name
        if key in BIOME_NAME_TO_ID:
            id_to_name[value] = key if value not in id_to_name else id_to_name[value]

    remapped = []
    used = set()
    for node in nodes:
        if (node >> 56) & 0xFF == 0xFF:
            cub_id = (node >> 48) & 0xFF
            name = id_to_name.get(cub_id)
            if name is None:
                raise SystemExit(f"unknown cubiomes biome id {cub_id}")
            used.add(name)
            node = (node & ~(0xFF << 48)) | (BIOME_NAME_TO_ID[name] << 48)
        remapped.append(node)
    return {"order": order, "steps": steps, "params": params,
            "nodes": [str(n) for n in remapped], "biomes": sorted(used)}


# Block states used by the feature stage (trees, plants, ores, snow).
WOODS = ["oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "cherry", "mangrove"]
FLOWERS = ["dandelion", "poppy", "blue_orchid", "allium", "azure_bluet", "red_tulip", "orange_tulip",
           "white_tulip", "pink_tulip", "oxeye_daisy", "cornflower", "lily_of_the_valley"]
ORES = ["coal", "iron", "copper", "gold", "redstone", "lapis", "diamond", "emerald"]


def feature_states() -> dict:
    states = {}

    def add(name, **props):
        key = "minecraft:" + name
        if props:
            key += "[" + ",".join(f"{k}={v}" for k, v in sorted(props.items())) + "]"
        states[key] = block_state_id({"Name": "minecraft:" + name,
                                      "Properties": {k: str(v) for k, v in props.items()}})

    for wood in WOODS:
        for axis in "xyz":
            add(f"{wood}_log", axis=axis)
        for distance in range(1, 8):
            add(f"{wood}_leaves", distance=distance, persistent="false", waterlogged="false")
    for name in ["short_grass", "fern", "dead_bush", "brown_mushroom", "red_mushroom", "pumpkin", "melon",
                 "lily_pad", "seagrass", "kelp_plant", "mossy_cobblestone", "packed_ice", "ice", "blue_ice",
                 "stone", "deepslate", "granite", "diorite", "andesite", "tuff", "dirt", "gravel", "clay",
                 "sand", "grass_block", "podzol", "mycelium", "coarse_dirt", "rooted_dirt", "moss_block", "mud",
                 "mangrove_roots", "muddy_mangrove_roots", "red_sand", "snow_block", "water", "air",
                 "moss_carpet", "cobblestone", "terracotta", "bedrock", "sandstone", "calcite", "powder_snow",
                 "smooth_basalt", "dripstone_block", "glow_lichen"] + FLOWERS:
        add(name)
    for half in ("lower", "upper"):
        for plant in ("tall_grass", "large_fern", "sunflower", "lilac", "rose_bush", "peony", "tall_seagrass"):
            add(plant, half=half)
    add("cactus", age=0)
    add("sugar_cane", age=0)
    add("kelp", age=20)
    add("sweet_berry_bush", age=3)
    add("snow", layers=1)
    for block in ("grass_block", "podzol", "mycelium"):
        add(block, snowy="true")
    for amount in range(1, 5):
        for facing in ("north", "east", "south", "west"):
            add("pink_petals", facing=facing, flower_amount=amount)
    for leaves in ("none", "small", "large"):
        add("bamboo", age=0, leaves=leaves, stage=0)
    add("bamboo_sapling")
    for block in ("brown_mushroom_block", "red_mushroom_block", "mushroom_stem"):
        add(block, down="true", east="true", north="true", south="true", up="true", west="true")
        add(block, down="false", east="true", north="true", south="true", up="true", west="true")
    for face in ("north", "east", "south", "west"):
        props = {f: "false" for f in ("north", "east", "south", "west", "up")}
        props[face] = "true"
        add("vine", **props)
    for ore in ORES:
        add(f"{ore}_ore") if ore != "redstone" else add("redstone_ore", lit="false")
        add(f"deepslate_{ore}_ore") if ore != "redstone" else add("deepslate_redstone_ore", lit="false")
    add("sea_pickle", pickles=1, waterlogged="true")
    add("sea_pickle", pickles=3, waterlogged="true")
    return states


def main():
    cache = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "build" / "worldgen-cache"
    fetch = Fetcher(cache)
    collector = GraphCollector(fetch)

    settings = fetch.worldgen("noise_settings", "overworld")
    router = {name: collector.walk(fn) for name, fn in settings["noise_router"].items()}
    surface_rule = convert_surface(settings["surface_rule"], collector)
    # Noises used directly by the surface system / aquifer / ore veins
    for key in ("surface", "surface_secondary", "clay_bands_offset", "badlands_pillar",
                "badlands_pillar_roof", "badlands_surface", "iceberg_pillar",
                "iceberg_pillar_roof", "iceberg_surface", "surface_swamp", "calcite",
                "gravel", "powder_snow", "packed_ice", "ice"):
        collector.noise(key)

    biome_temperatures = {}
    from world.biomes import BIOME_NAME_TO_ID
    for name, biome in BIOME_NAME_TO_ID.items():
        data = fetch.worldgen("biome", name)
        biome_temperatures[biome] = {
            "temperature": data["temperature"],
            "frozen": data.get("temperature_modifier", "none") == "frozen",
            "precipitation": bool(data.get("has_precipitation", True)),
        }

    out = {
        "version": "1.21.1",
        "sea_level": settings["sea_level"],
        "noise": settings["noise"],
        "default_block": block_state_id(settings["default_block"]),
        "default_fluid": block_state_id(settings["default_fluid"]),
        "aquifers_enabled": settings["aquifers_enabled"],
        "ore_veins_enabled": settings["ore_veins_enabled"],
        "spawn_target": settings["spawn_target"],
        "router": router,
        "density_functions": collector.functions,
        "noises": collector.noises,
        "surface_rule": surface_rule,
        "biome_tree": parse_cubiomes_tree(fetch),
        "biomes": {str(k): v for k, v in biome_temperatures.items()},
        "biome_ids": dict(BIOME_NAME_TO_ID),
        "states": feature_states(),
        "blocks": {name: block_state_id({"Name": name}) for name in (
            "minecraft:air", "minecraft:water", "minecraft:lava", "minecraft:stone",
            "minecraft:bedrock", "minecraft:deepslate", "minecraft:granite", "minecraft:tuff",
            "minecraft:copper_ore", "minecraft:deepslate_iron_ore", "minecraft:raw_copper_block",
            "minecraft:raw_iron_block", "minecraft:terracotta", "minecraft:orange_terracotta",
            "minecraft:yellow_terracotta", "minecraft:brown_terracotta", "minecraft:red_terracotta",
            "minecraft:white_terracotta", "minecraft:light_gray_terracotta", "minecraft:ice",
            "minecraft:packed_ice", "minecraft:snow_block", "minecraft:snow",
        )},
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size // 1024} KiB): "
          f"{len(collector.functions)} density functions, {len(collector.noises)} noises, "
          f"{len(out['biome_tree']['nodes'])} biome tree nodes")


if __name__ == "__main__":
    main()
