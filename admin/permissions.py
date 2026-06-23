# ============================================================
# PyMC - 权限、封禁与白名单管理
# ============================================================

import json
import logging
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


class PermissionManager:
    """管理权限组、用户权限、封禁和白名单。"""

    def __init__(self, filepath: str = "permissions.json"):
        self.filepath = Path(filepath)
        self.data = deepcopy(DEFAULT_DATA)
        self.load()

    def load(self):
        """从磁盘加载权限文件，不存在则创建默认文件。"""
        if not self.filepath.exists():
            self.save()
            return

        previous = deepcopy(self.data)
        try:
            with self.filepath.open("r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.data = deepcopy(DEFAULT_DATA)
            self._merge_dict(self.data, loaded)
        except Exception as e:
            logger.error(f"读取权限文件失败: {e}，将保留当前内存配置")
            self.data = previous

    def save(self):
        """保存权限文件。"""
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        with self.filepath.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def snapshot(self) -> dict:
        """返回当前数据快照。"""
        return deepcopy(self.data)

    def list_groups(self) -> dict:
        return deepcopy(self.data["groups"])

    def list_users(self) -> dict:
        return deepcopy(self.data["users"])

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

    def set_group(self, name: str, permissions: list[str], inherits: list[str] | None = None):
        if name == "default" and inherits:
            logger.warning("default 组通常不建议继承其他组")
        self.data["groups"][name] = {
            "inherits": inherits or [],
            "permissions": sorted(set(permissions)),
        }
        self.save()

    def has_permission(self, username: str, permission: str) -> bool:
        key = username.lower()
        if key in {name.lower() for name in self.data.get("ops", [])}:
            return True

        record = self.get_user_record(username)
        denied = set(record.get("denied", []))
        if self._matches_any(permission, denied):
            return False

        allowed = set(record.get("permissions", []))
        group_name = record.get("group", "default")
        allowed.update(self._collect_group_permissions(group_name))
        return self._matches_any(permission, allowed)

    def get_permission_level(self, username: str) -> str:
        if username.lower() in {name.lower() for name in self.data.get("ops", [])}:
            return "admin"
        return self.get_user_record(username).get("group", "default")

    def op(self, username: str):
        if username not in self.data["ops"]:
            self.data["ops"].append(username)
            self.save()

    def deop(self, username: str):
        self.data["ops"] = [name for name in self.data["ops"] if name.lower() != username.lower()]
        self.save()

    def ban_player(self, username: str, reason: str = ""):
        self.data["bans"]["players"][username.lower()] = {
            "name": username,
            "reason": reason,
        }
        self.save()

    def pardon_player(self, username: str):
        self.data["bans"]["players"].pop(username.lower(), None)
        self.save()

    def ban_ip(self, ip: str, reason: str = ""):
        self.data["bans"]["ips"][ip] = {"reason": reason}
        self.save()

    def pardon_ip(self, ip: str):
        self.data["bans"]["ips"].pop(ip, None)
        self.save()

    def get_banlist(self) -> dict:
        return deepcopy(self.data["bans"])

    def set_whitelist_enabled(self, enabled: bool):
        self.data["whitelist"]["enabled"] = enabled
        self.save()

    def add_whitelist(self, username: str):
        players = self.data["whitelist"]["players"]
        if username not in players:
            players.append(username)
            players.sort(key=str.lower)
            self.save()

    def remove_whitelist(self, username: str):
        players = self.data["whitelist"]["players"]
        self.data["whitelist"]["players"] = [
            name for name in players if name.lower() != username.lower()
        ]
        self.save()

    def get_whitelist(self) -> dict:
        return deepcopy(self.data["whitelist"])

    def check_login_allowed(self, username: str, ip: str) -> str | None:
        if username.lower() in self.data["bans"]["players"]:
            ban = self.data["bans"]["players"][username.lower()]
            reason = ban.get("reason") or "你已被封禁"
            return f"玩家已被封禁: {reason}"

        if ip in self.data["bans"]["ips"]:
            ban = self.data["bans"]["ips"][ip]
            reason = ban.get("reason") or "你的 IP 已被封禁"
            return f"IP 已被封禁: {reason}"

        whitelist = self.data["whitelist"]
        if whitelist.get("enabled"):
            players = whitelist.get("players", [])
            if username.lower() not in {name.lower() for name in players}:
                return "服务器已启用白名单"

        return None

    def get_web_payload(self) -> dict:
        return {
            "groups": self.list_groups(),
            "users": self.list_users(),
            "ops": list(self.data["ops"]),
            "bans": self.get_banlist(),
            "whitelist": self.get_whitelist(),
        }

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
