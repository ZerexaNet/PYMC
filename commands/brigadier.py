# ============================================================
# PyMC - Declare Commands (Brigadier 命令树)
# ============================================================

"""
Builds the ``Commands`` packet (clientbound ``declare_commands``).

The vanilla client uses this tree for tab completion, syntax highlighting and
the usage hints above the chat box. Without it every ``/command`` is rendered
red as "unknown". The tree is assembled from:

  * the vanilla 1.21.1 command graph (``protocol/data/commands_767.json``),
    restricted to commands that are actually registered in the
    ``CommandManager`` and that the player may use;
  * a generic ``<name> [args...]`` node for every other registered command
    (PyMC extensions and plugin commands), with server-side suggestions.
"""

from __future__ import annotations

import logging
import struct

from protocol.data_types import write_string, write_varint

logger = logging.getLogger("PyMC.命令")

FLAG_LITERAL = 0x01
FLAG_ARGUMENT = 0x02
FLAG_EXECUTABLE = 0x04
FLAG_REDIRECT = 0x08
FLAG_SUGGESTIONS = 0x10

_PARSER_ALIASES = {"minecraft:nbt_compound_tag": "minecraft:nbt"}
_STRING_TYPES = {"word": 0, "phrase": 1, "greedy": 2}


def _min_max(props: dict, fmt: str) -> bytes:
    props = props or {}
    flags = (0x01 if "min" in props else 0) | (0x02 if "max" in props else 0)
    out = bytearray([flags])
    if "min" in props:
        out += struct.pack(fmt, props["min"])
    if "max" in props:
        out += struct.pack(fmt, props["max"])
    return bytes(out)


def _parser_properties(parser: str, props: dict | None) -> bytes:
    props = props or {}
    if parser == "brigadier:float":
        return _min_max(props, ">f")
    if parser == "brigadier:double":
        return _min_max(props, ">d")
    if parser == "brigadier:integer":
        return _min_max(props, ">i")
    if parser == "brigadier:long":
        return _min_max(props, ">q")
    if parser == "brigadier:string":
        return write_varint(_STRING_TYPES.get(props.get("type", "word"), 0))
    if parser == "minecraft:entity":
        flags = (0x01 if props.get("amount") == "single" else 0)
        flags |= (0x02 if props.get("type") == "players" else 0)
        return bytes([flags])
    if parser == "minecraft:score_holder":
        return bytes([0x01 if props.get("amount") == "multiple" else 0])
    if parser == "minecraft:time":
        return struct.pack(">i", int(props.get("min", 0)))
    if parser in ("minecraft:resource", "minecraft:resource_key",
                  "minecraft:resource_or_tag", "minecraft:resource_or_tag_key"):
        return write_string(props.get("registry", "minecraft:item"))
    return b""


class _TreeBuilder:
    def __init__(self, parsers: dict[str, int], vanilla_root: dict):
        self.parsers = parsers
        self.vanilla_root = vanilla_root
        self.nodes: list[dict] = []
        self._by_identity: dict[int, int] = {}
        self._pending_redirects: list[tuple[int, list[str]]] = []
        self.root = self._new_node({"flags": 0, "name": None})
        self._top_level: dict[str, int] = {}

    def _new_node(self, node: dict) -> int:
        node.setdefault("children", [])
        self.nodes.append(node)
        return len(self.nodes) - 1

    def _add_vanilla(self, name: str, source: dict, path: list[str]) -> int:
        key = id(source)
        if key in self._by_identity:
            return self._by_identity[key]
        if source.get("type") == "argument":
            parser = _PARSER_ALIASES.get(source["parser"], source["parser"])
            if parser not in self.parsers:
                # Unknown parser: degrade to a greedy string so the node stays usable.
                parser, properties = "brigadier:string", {"type": "greedy"}
            else:
                properties = source.get("properties")
            node = {"flags": FLAG_ARGUMENT, "name": name, "parser": parser,
                    "properties": properties}
        else:
            node = {"flags": FLAG_LITERAL, "name": name}
        if source.get("executable"):
            node["flags"] |= FLAG_EXECUTABLE
        index = self._new_node(node)
        self._by_identity[key] = index

        if "redirect" in source:
            self._pending_redirects.append((index, list(source["redirect"])))
        elif path == ["execute", "run"]:
            self._pending_redirects.append((index, []))
        for child_name, child in source.get("children", {}).items():
            node["children"].append(self._add_vanilla(child_name, child, path + [child_name]))
        return index

    def add_vanilla_command(self, name: str) -> bool:
        source = self.vanilla_root.get("children", {}).get(name)
        if source is None or name in self._top_level:
            return source is not None
        index = self._add_vanilla(name, source, [name])
        self._top_level[name] = index
        self.nodes[self.root]["children"].append(index)
        return True

    def add_generic_command(self, name: str) -> None:
        if name in self._top_level:
            return
        args = self._new_node({
            "flags": FLAG_ARGUMENT | FLAG_EXECUTABLE | FLAG_SUGGESTIONS,
            "name": "args", "parser": "brigadier:string",
            "properties": {"type": "greedy"}, "suggestions": "minecraft:ask_server",
        })
        index = self._new_node({"flags": FLAG_LITERAL | FLAG_EXECUTABLE, "name": name,
                                "children": [args]})
        self._top_level[name] = index
        self.nodes[self.root]["children"].append(index)

    def _resolve_path(self, path: list[str]) -> int | None:
        if not path:
            return self.root
        index = self._top_level.get(path[0])
        for part in path[1:]:
            if index is None:
                return None
            index = next((c for c in self.nodes[index]["children"]
                          if self.nodes[c]["name"] == part), None)
        return index

    def encode(self) -> bytes:
        for index, path in self._pending_redirects:
            target = self._resolve_path(path)
            if target is not None:
                self.nodes[index]["redirect"] = target
                self.nodes[index]["flags"] |= FLAG_REDIRECT

        out = bytearray(write_varint(len(self.nodes)))
        for node in self.nodes:
            out.append(node["flags"])
            out += write_varint(len(node["children"]))
            for child in node["children"]:
                out += write_varint(child)
            if node["flags"] & FLAG_REDIRECT:
                out += write_varint(node["redirect"])
            if node["name"] is not None:
                out += write_string(node["name"])
            if node["flags"] & 0x03 == FLAG_ARGUMENT:
                out += write_varint(self.parsers[node["parser"]])
                out += _parser_properties(node["parser"], node.get("properties"))
                if node["flags"] & FLAG_SUGGESTIONS:
                    out += write_string(node["suggestions"])
        out += write_varint(self.root)
        return bytes(out)


_CACHE: dict[frozenset, bytes] = {}


def available_command_names(server, conn) -> list[str]:
    """Every name (including aliases) the player can type."""
    manager = getattr(server, "command_manager", None)
    if manager is None:
        return []
    from commands import GLOBAL_ALIASES
    names: set[str] = set()
    for command in manager.get_commands_for_sender(conn):
        names.add(command.name)
        names.update(command.aliases)
    for alias, target in GLOBAL_ALIASES.items():
        if target in names:
            names.add(alias)
    return sorted(n for n in names if n and " " not in n)


def build_commands_payload(names: list[str]) -> bytes:
    """Encode the command tree for the given set of usable command names."""
    key = frozenset(names)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached

    from protocol.gamedata import load_data
    data = load_data("commands_767.json")
    builder = _TreeBuilder(data["parsers"], data["tree"])
    vanilla_children = data["tree"].get("children", {})

    # Redirect targets (e.g. tp -> teleport) must exist before aliases resolve.
    for name in names:
        source = vanilla_children.get(name)
        if source is not None and "redirect" in source:
            target = source["redirect"][0]
            builder.add_vanilla_command(target)
    for name in names:
        if not builder.add_vanilla_command(name):
            builder.add_generic_command(name)

    payload = builder.encode()
    if len(_CACHE) > 64:
        _CACHE.clear()
    _CACHE[key] = payload
    return payload


async def send_commands(conn, server) -> None:
    """Send (or refresh) the command tree for one player."""
    from protocol.packet_map import get_clientbound_packet
    pid = get_clientbound_packet(conn.protocol_version, "declare_commands")
    if pid is None or conn.protocol_version != 767:
        return
    try:
        payload = build_commands_payload(available_command_names(server, conn))
    except Exception as e:  # never let a tree bug block a login
        logger.warning(f"构建命令树失败: {e}")
        return
    await conn.send_packet(pid, payload)
