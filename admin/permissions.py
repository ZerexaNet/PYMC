# ============================================================
# PyMC - 权限、封禁与白名单管理
# ============================================================

"""
权限数据的磁盘布局与原版服务端一致:

  ops.json             管理员 (uuid / name / level / bypassesPlayerLimit)
  whitelist.json       白名单 (uuid / name)
  banned-players.json  封禁玩家 (uuid / name / created / source / expires / reason)
  banned-ips.json      封禁 IP  (ip / created / source / expires / reason)
  usercache.json       玩家名 <-> UUID 缓存

权限组 / 用户权限节点是 PyMC 的扩展, 保存在 permissions.json。
旧版本把 OP、封禁和白名单也写在 permissions.json 里, 首次加载时会自动迁移。
"""

import hashlib
import json
import logging
import time
import uuid as _uuid
from copy import deepcopy
from pathlib import Path

logger = logging.getLogger("PyMC.权限")


DEFAULT_DATA = {
    "meta": {
        "schema": 1,
    },
    "groups": {
        "default": {
            "inherits": [],
            "permissions": [
                "command.help",
                "command.list",
                "command.me",
                "command.msg",
                "command.tell",
                "command.w",
            ],
        },
        "moderator": {
            "inherits": ["default"],
            "permissions": [
                "command.say",
                "command.tp",
                "command.teleport",
                "command.gamemode",
                "command.kick",
                "command.kill",
                "command.time",
                "command.weather",
            ],
        },
        "admin": {
            "inherits": ["moderator"],
            "permissions": [
                "command.*",
                "web.access",
                "file.read.*",
                "file.write.server.properties",
                "file.write.permissions.json",
            ],
        },
    },
    "users": {},
    "ops": [],
    "bans": {
        "players": {},
        "ips": {},
    },
    "whitelist": {
        "enabled": False,
        "players": [],
    },
}


def offline_uuid(username: str) -> _uuid.UUID:
    """与 Java 版一致的离线 UUID: UUID.nameUUIDFromBytes("OfflinePlayer:" + name)。"""
    digest = bytearray(hashlib.md5(f"OfflinePlayer:{username}".encode("utf-8")).digest())
    digest[6] = (digest[6] & 0x0F) | 0x30
    digest[8] = (digest[8] & 0x3F) | 0x80
    return _uuid.UUID(bytes=bytes(digest))


def _timestamp(epoch: float | None = None) -> str:
    """原版 JSON 列表使用的时间格式: 2024-01-31 12:00:00 +0000。"""
    return time.strftime("%Y-%m-%d %H:%M:%S +0000", time.gmtime(epoch))


def _read_json_list(path: Path) -> list | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        logger.error(f"Failed to load {path.name}: {e}")
        return []


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


class UserCache:
    """usercache.json: 记录见过的玩家名与 UUID (原版格式, 30 天过期)。"""

    EXPIRY_SECONDS = 30 * 24 * 3600

    def __init__(self, filepath: str | Path = "usercache.json"):
        self.filepath = Path(filepath)
        self.entries: dict[str, dict] = {}
        for entry in _read_json_list(self.filepath) or []:
            if isinstance(entry, dict) and entry.get("name") and entry.get("uuid"):
                self.entries[entry["name"].lower()] = entry

    def record(self, name: str, player_uuid) -> None:
        self.entries[name.lower()] = {
            "name": name,
            "uuid": str(player_uuid),
            "expiresOn": _timestamp(time.time() + self.EXPIRY_SECONDS),
        }
        self.save()

    def lookup(self, name: str) -> str | None:
        entry = self.entries.get(name.lower())
        return entry["uuid"] if entry else None

    def name_for(self, name: str) -> str:
        """返回缓存中的正确大小写, 未知时原样返回。"""
        entry = self.entries.get(name.lower())
        return entry["name"] if entry else name

    def save(self) -> None:
        try:
            _write_json(self.filepath, list(self.entries.values()))
        except OSError as e:
            logger.warning(f"Failed to save {self.filepath.name}: {e}")


class PermissionManager:
    """管理权限组、用户权限、OP、封禁和白名单。"""

    def __init__(self, filepath: str = "permissions.json", default_op_level: int = 4,
                 usercache: UserCache | None = None):
        self.filepath = Path(filepath)
        base = self.filepath.parent
        self.ops_path = base / "ops.json"
        self.whitelist_path = base / "whitelist.json"
        self.banned_players_path = base / "banned-players.json"
        self.banned_ips_path = base / "banned-ips.json"
        self.default_op_level = max(1, min(4, int(default_op_level)))
        self.usercache = usercache
        self.on_whitelist_toggle = None   # callback(enabled) -> 写回 server.properties
        self.op_levels: dict[str, int] = {}
        self.data = deepcopy(DEFAULT_DATA)
        self.load()

    # ------------------------------------------------------------------
    # 磁盘读写
    # ------------------------------------------------------------------

    def _uuid_for(self, username: str) -> str:
        if self.usercache is not None:
            cached = self.usercache.lookup(username)
            if cached:
                return cached
        return str(offline_uuid(username))

    def load(self):
        """从磁盘加载权限文件，不存在则创建默认文件。"""
        previous = deepcopy(self.data)
        legacy: dict = {}
        if self.filepath.exists():
            try:
                with self.filepath.open("r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.data = deepcopy(DEFAULT_DATA)
                legacy = {k: loaded.pop(k) for k in ("ops", "bans", "whitelist") if k in loaded}
                self._merge_dict(self.data, loaded)
            except Exception as e:
                logger.error(f"读取权限文件失败: {e}，将保留当前内存配置")
                self.data = previous
                return
        self._load_vanilla_lists(legacy)
        if not self.filepath.exists() or legacy:
            self.save()

    def _load_vanilla_lists(self, legacy: dict):
        """读取 ops.json 等原版文件; 文件不存在时迁移旧版 permissions.json 数据。"""
        # --- ops.json ---
        ops = _read_json_list(self.ops_path)
        self.op_levels = {}
        if ops is None:
            names = [str(n) for n in legacy.get("ops", [])]
        else:
            names = []
            for entry in ops:
                if isinstance(entry, dict) and entry.get("name"):
                    names.append(entry["name"])
                    self.op_levels[entry["name"].lower()] = int(
                        entry.get("level", self.default_op_level))
        self.data["ops"] = names

        # --- whitelist.json ---
        enabled = bool(self.data.get("whitelist", {}).get("enabled", False))
        whitelist = _read_json_list(self.whitelist_path)
        if whitelist is None:
            legacy_wl = legacy.get("whitelist", {}) or {}
            players = [str(n) for n in legacy_wl.get("players", [])]
            enabled = bool(legacy_wl.get("enabled", enabled))
        else:
            players = [e["name"] for e in whitelist if isinstance(e, dict) and e.get("name")]
        self.data["whitelist"] = {"enabled": enabled, "players": players}

        # --- banned-players.json / banned-ips.json ---
        bans = {"players": {}, "ips": {}}
        banned_players = _read_json_list(self.banned_players_path)
        if banned_players is None:
            for key, record in (legacy.get("bans", {}) or {}).get("players", {}).items():
                bans["players"][key.lower()] = {
                    "name": record.get("name", key), "reason": record.get("reason", "")}
        else:
            for entry in banned_players:
                if isinstance(entry, dict) and entry.get("name"):
                    bans["players"][entry["name"].lower()] = dict(entry)
        banned_ips = _read_json_list(self.banned_ips_path)
        if banned_ips is None:
            for ip, record in (legacy.get("bans", {}) or {}).get("ips", {}).items():
                bans["ips"][ip] = {"reason": record.get("reason", "")}
        else:
            for entry in banned_ips:
                if isinstance(entry, dict) and entry.get("ip"):
                    bans["ips"][entry["ip"]] = dict(entry)
        self.data["bans"] = bans

    def save(self):
        """保存 permissions.json (权限组/用户) 以及原版格式的各个列表文件。"""
        extension_data = {k: v for k, v in self.data.items()
                          if k not in ("ops", "bans", "whitelist")}
        _write_json(self.filepath, extension_data)

        _write_json(self.ops_path, [
            {
                "uuid": self._uuid_for(name),
                "name": name,
                "level": self.op_levels.get(name.lower(), self.default_op_level),
                "bypassesPlayerLimit": False,
            }
            for name in self.data["ops"]
        ])
        _write_json(self.whitelist_path, [
            {"uuid": self._uuid_for(name), "name": name}
            for name in self.data["whitelist"]["players"]
        ])
        _write_json(self.banned_players_path, [
            {
                "uuid": record.get("uuid") or self._uuid_for(record.get("name", key)),
                "name": record.get("name", key),
                "created": record.get("created") or _timestamp(),
                "source": record.get("source") or "Server",
                "expires": record.get("expires") or "forever",
                "reason": record.get("reason") or "Banned by an operator.",
            }
            for key, record in self.data["bans"]["players"].items()
        ])
        _write_json(self.banned_ips_path, [
            {
                "ip": ip,
                "created": record.get("created") or _timestamp(),
                "source": record.get("source") or "Server",
                "expires": record.get("expires") or "forever",
                "reason": record.get("reason") or "Banned by an operator.",
            }
            for ip, record in self.data["bans"]["ips"].items()
        ])

    def snapshot(self) -> dict:
        """返回当前数据快照。"""
        return deepcopy(self.data)

    def list_groups(self) -> dict:
        return deepcopy(self.data["groups"])

    def get_user_record(self, username: str) -> dict:
        key = username.lower()
        users = self.data["users"]
        if key not in users:
            users[key] = {
                "name": username,
                "group": "default",
                "permissions": [],
                "denied": [],
            }
        return users[key]

    def set_user_group(self, username: str, group: str):
        if group not in self.data["groups"]:
            raise ValueError(f"权限组不存在: {group}")
        record = self.get_user_record(username)
        record["name"] = username
        record["group"] = group
        self.save()

    # ------------------------------------------------------------------
    # 权限判定
    # ------------------------------------------------------------------

    def is_op(self, username: str) -> bool:
        key = username.lower()
        return any(name.lower() == key for name in self.data.get("ops", []))

    def get_op_level(self, username: str) -> int:
        """原版权限等级 (0-4): OP 取 ops.json 中的 level, 其余为 0。"""
        if self.is_op(username):
            return self.op_levels.get(username.lower(), self.default_op_level)
        return 0

    def has_permission(self, username: str, permission: str) -> bool:
        if self.is_op(username):
            return True

        key = username.lower()
        record = self.data["users"].get(key) or {
            "group": "default", "permissions": [], "denied": []}
        denied = set(record.get("denied", []))
        if self._matches_any(permission, denied):
            return False

        allowed = set(record.get("permissions", []))
        group_name = record.get("group", "default")
        allowed.update(self._collect_group_permissions(group_name))
        return self._matches_any(permission, allowed)

    def get_permission_level(self, username: str) -> str:
        if self.is_op(username):
            return "admin"
        return self.data["users"].get(username.lower(), {}).get("group", "default")

    # ------------------------------------------------------------------
    # OP / 封禁 / 白名单
    # ------------------------------------------------------------------

    def op(self, username: str, level: int | None = None) -> bool:
        """设为管理员。返回是否发生变化。"""
        if self.is_op(username):
            return False
        self.data["ops"].append(username)
        self.op_levels[username.lower()] = (
            self.default_op_level if level is None else max(1, min(4, int(level))))
        self.save()
        return True

    def deop(self, username: str) -> bool:
        if not self.is_op(username):
            return False
        self.data["ops"] = [name for name in self.data["ops"] if name.lower() != username.lower()]
        self.op_levels.pop(username.lower(), None)
        self.save()
        return True

    def is_banned(self, username: str) -> bool:
        return username.lower() in self.data["bans"]["players"]

    def ban_player(self, username: str, reason: str = "", source: str = "Server") -> bool:
        already = self.is_banned(username)
        self.data["bans"]["players"][username.lower()] = {
            "uuid": self._uuid_for(username),
            "name": username,
            "created": _timestamp(),
            "source": source,
            "expires": "forever",
            "reason": reason or "Banned by an operator.",
        }
        self.save()
        return not already

    def pardon_player(self, username: str) -> bool:
        removed = self.data["bans"]["players"].pop(username.lower(), None) is not None
        self.save()
        return removed

    def ban_ip(self, ip: str, reason: str = "", source: str = "Server") -> bool:
        already = ip in self.data["bans"]["ips"]
        self.data["bans"]["ips"][ip] = {
            "created": _timestamp(),
            "source": source,
            "expires": "forever",
            "reason": reason or "Banned by an operator.",
        }
        self.save()
        return not already

    def pardon_ip(self, ip: str) -> bool:
        removed = self.data["bans"]["ips"].pop(ip, None) is not None
        self.save()
        return removed

    def get_banlist(self) -> dict:
        return deepcopy(self.data["bans"])

    def set_whitelist_enabled(self, enabled: bool):
        self.data["whitelist"]["enabled"] = bool(enabled)
        if self.on_whitelist_toggle is not None:
            try:
                self.on_whitelist_toggle(bool(enabled))
            except Exception as e:  # pragma: no cover - defensive
                logger.warning(f"无法写回 white-list 配置: {e}")

    def is_whitelisted(self, username: str) -> bool:
        key = username.lower()
        return any(name.lower() == key for name in self.data["whitelist"]["players"])

    def add_whitelist(self, username: str) -> bool:
        if self.is_whitelisted(username):
            return False
        players = self.data["whitelist"]["players"]
        players.append(username)
        players.sort(key=str.lower)
        self.save()
        return True

    def remove_whitelist(self, username: str) -> bool:
        if not self.is_whitelisted(username):
            return False
        players = self.data["whitelist"]["players"]
        self.data["whitelist"]["players"] = [
            name for name in players if name.lower() != username.lower()
        ]
        self.save()
        return True

    def check_login(self, username: str, ip: str):
        """
        登录检查。允许时返回 None, 否则返回断开原因 (文本组件),
        与原版的断开消息一致。
        """
        from protocol.text import translate
        ban = self.data["bans"]["players"].get(username.lower())
        if ban is not None:
            reason = ban.get("reason") or "Banned by an operator."
            return translate("multiplayer.disconnect.banned.reason", reason)

        ip_ban = self.data["bans"]["ips"].get(ip)
        if ip_ban is not None:
            reason = ip_ban.get("reason") or "Banned by an operator."
            return translate("multiplayer.disconnect.banned_ip.reason", reason)

        whitelist = self.data["whitelist"]
        if whitelist.get("enabled") and not self.is_whitelisted(username) \
                and not self.is_op(username):
            return translate("multiplayer.disconnect.not_whitelisted")

        return None

    def _collect_group_permissions(self, group_name: str, seen: set[str] | None = None) -> set[str]:
        seen = seen or set()
        if group_name in seen:
            return set()
        seen.add(group_name)

        group = self.data["groups"].get(group_name, {})
        permissions = set(group.get("permissions", []))
        for parent in group.get("inherits", []):
            permissions.update(self._collect_group_permissions(parent, seen))
        return permissions

    @staticmethod
    def _matches_any(permission: str, allowed: set[str]) -> bool:
        if permission in allowed or "*" in allowed:
            return True
        parts = permission.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i]) + ".*"
            if candidate in allowed:
                return True
        return False

    @staticmethod
    def _merge_dict(base: dict, override: dict):
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                PermissionManager._merge_dict(base[key], value)
            else:
                base[key] = value
