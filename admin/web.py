# ============================================================
# PyMC - Web 管理后台
# ============================================================

import asyncio
import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("PyMC.Web")


HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>PyMC Admin</title>
  <style>
    :root {
      --bg: #f5efe4;
      --card: #fffaf1;
      --text: #2a241e;
      --accent: #466b4a;
      --line: #d9cdbd;
    }
    body { font-family: "Segoe UI", "PingFang SC", sans-serif; margin: 0; background: linear-gradient(135deg, #efe7da, #f8f3eb); color: var(--text); }
    .wrap { max-width: 1100px; margin: 0 auto; padding: 24px; }
    h1, h2 { margin: 0 0 12px; }
    .grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
    .card { background: var(--card); border: 1px solid var(--line); border-radius: 18px; padding: 18px; box-shadow: 0 12px 30px rgba(80, 64, 40, 0.08); }
    button { background: var(--accent); color: white; border: 0; border-radius: 10px; padding: 10px 14px; cursor: pointer; }
    input, textarea, select { width: 100%; box-sizing: border-box; margin: 8px 0 12px; padding: 10px 12px; border-radius: 10px; border: 1px solid var(--line); background: white; }
    textarea { min-height: 220px; font-family: Consolas, monospace; }
    pre { white-space: pre-wrap; word-break: break-word; background: #f3ebdf; padding: 12px; border-radius: 10px; }
    .row { display: flex; gap: 10px; align-items: center; }
    .row > * { flex: 1; }
    .muted { color: #786d60; font-size: 14px; }
  </style>
</head>
<body>
  <div class="wrap">
    <h1>PyMC 管理台</h1>
    <p class="muted">状态、命令、权限组和受限文件编辑都在这里。</p>
    <div class="grid">
      <section class="card">
        <h2>服务器状态</h2>
        <pre id="status">加载中...</pre>
        <button onclick="refreshStatus()">刷新状态</button>
      </section>
      <section class="card">
        <h2>执行命令</h2>
        <input id="command" placeholder="输入控制台命令，例如 whitelist list">
        <button onclick="runCommand()">执行</button>
        <pre id="command-result">等待命令...</pre>
      </section>
      <section class="card">
        <h2>权限组</h2>
        <pre id="permissions">加载中...</pre>
        <div class="row">
          <input id="perm-user" placeholder="玩家名">
          <input id="perm-group" placeholder="组名，如 admin">
        </div>
        <button onclick="assignGroup()">设置玩家组</button>
      </section>
      <section class="card">
        <h2>编辑文件</h2>
        <select id="file-name" onchange="loadFile()"></select>
        <textarea id="file-content"></textarea>
        <button onclick="saveFile()">保存文件</button>
      </section>
    </div>
  </div>
  <script>
    async function jget(url) {
      const res = await fetch(url);
      return await res.json();
    }
    async function jpost(url, body) {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      return await res.json();
    }
    async function refreshStatus() {
      const data = await jget('/api/status');
      document.getElementById('status').textContent = JSON.stringify(data, null, 2);
      const select = document.getElementById('file-name');
      if (!select.dataset.loaded) {
        select.innerHTML = '';
        for (const name of data.allowed_files) {
          const opt = document.createElement('option');
          opt.value = name;
          opt.textContent = name;
          select.appendChild(opt);
        }
        select.dataset.loaded = '1';
        loadFile();
      }
    }
    async function refreshPermissions() {
      const data = await jget('/api/permissions');
      document.getElementById('permissions').textContent = JSON.stringify(data, null, 2);
    }
    async function runCommand() {
      const command = document.getElementById('command').value;
      const data = await jpost('/api/command', { command });
      document.getElementById('command-result').textContent = JSON.stringify(data, null, 2);
      refreshStatus();
      refreshPermissions();
    }
    async function assignGroup() {
      const username = document.getElementById('perm-user').value;
      const group = document.getElementById('perm-group').value;
      const data = await jpost('/api/permissions/user', { username, group });
      document.getElementById('permissions').textContent = JSON.stringify(data, null, 2);
    }
    async function loadFile() {
      const name = document.getElementById('file-name').value;
      if (!name) return;
      const data = await jget('/api/file?name=' + encodeURIComponent(name));
      document.getElementById('file-content').value = data.content || '';
    }
    async function saveFile() {
      const name = document.getElementById('file-name').value;
      const content = document.getElementById('file-content').value;
      const data = await jpost('/api/file?name=' + encodeURIComponent(name), { content });
      alert(data.message || '已保存');
    }
    refreshStatus();
    refreshPermissions();
  </script>
</body>
</html>
"""


class WebAdminServer:
    """轻量 Web 管理端。"""

    def __init__(self, server, host: str, port: int):
        self.server = server
        self.host = host
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        if self._httpd is not None:
            return
        handler_cls = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="PyMC-WebAdmin",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Web 管理台已启动: http://{self.host}:{self.port}")

    def stop(self):
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        logger.info("Web 管理台已关闭")

    def _make_handler(self):
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._send_html(HTML_PAGE)
                    return
                if parsed.path == "/api/status":
                    self._send_json(outer._status_payload())
                    return
                if parsed.path == "/api/permissions":
                    self._send_json(outer.server.permissions.get_web_payload())
                    return
                if parsed.path == "/api/file":
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    try:
                        content = outer.read_allowed_file(name)
                        self._send_json({"name": name, "content": content})
                    except Exception as e:
                        self._send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
                    return
                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def do_POST(self):
                parsed = urlparse(self.path)
                try:
                    payload = self._read_json()
                except Exception as e:
                    self._send_json({"error": f"无效 JSON: {e}"}, HTTPStatus.BAD_REQUEST)
                    return

                if parsed.path == "/api/command":
                    command = payload.get("command", "").strip()
                    if not command:
                        self._send_json({"error": "命令不能为空"}, HTTPStatus.BAD_REQUEST)
                        return
                    result = outer.run_command(command)
                    self._send_json(result)
                    return

                if parsed.path == "/api/permissions/user":
                    username = payload.get("username", "").strip()
                    group = payload.get("group", "").strip()
                    if not username or not group:
                        self._send_json({"error": "username 和 group 必填"}, HTTPStatus.BAD_REQUEST)
                        return
                    try:
                        outer.server.permissions.set_user_group(username, group)
                    except Exception as e:
                        self._send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
                        return
                    self._send_json(outer.server.permissions.get_web_payload())
                    return

                if parsed.path == "/api/permissions/group":
                    name = payload.get("name", "").strip()
                    permissions = payload.get("permissions", [])
                    inherits = payload.get("inherits", [])
                    if not name:
                        self._send_json({"error": "组名不能为空"}, HTTPStatus.BAD_REQUEST)
                        return
                    outer.server.permissions.set_group(name, permissions, inherits)
                    self._send_json(outer.server.permissions.get_web_payload())
                    return

                if parsed.path == "/api/file":
                    name = parse_qs(parsed.query).get("name", [""])[0]
                    try:
                        outer.write_allowed_file(name, payload.get("content", ""))
                        self._send_json({"message": f"已保存 {name}"})
                    except Exception as e:
                        self._send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
                    return

                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)

            def log_message(self, fmt, *args):
                logger.debug(fmt, *args)

            def _read_json(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                return json.loads(raw.decode("utf-8"))

            def _send_json(self, payload: dict, status: int = HTTPStatus.OK):
                body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _send_html(self, html: str):
                body = html.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def run_command(self, command: str) -> dict:
        from handlers.play import execute_server_command
        future = asyncio.run_coroutine_threadsafe(
            execute_server_command(self.server, command),
            self.server.loop,
        )
        handled = future.result(timeout=10)
        return {
            "command": command,
            "handled": handled,
            "players": [p.username for p in self.server.get_online_players()],
        }

    def allowed_files(self) -> dict[str, Path]:
        permissions_name = Path(self.server.permissions.filepath).name
        files = {
            "server.properties": Path("server.properties"),
            permissions_name: self.server.permissions.filepath,
            "README.md": Path("README.md"),
        }
        return files

    def read_allowed_file(self, name: str) -> str:
        path = self.allowed_files().get(name)
        if path is None:
            raise ValueError("该文件不允许通过 Web 编辑")
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def write_allowed_file(self, name: str, content: str):
        path = self.allowed_files().get(name)
        if path is None:
            raise ValueError("该文件不允许通过 Web 编辑")
        path.write_text(content, encoding="utf-8")
        if path.resolve() == self.server.permissions.filepath.resolve():
            self.server.permissions.load()

    def _status_payload(self) -> dict:
        from handlers.play import ALL_VANILLA_COMMAND_NAMES
        return {
            "running": self.server.running,
            "address": f"{self.server.host}:{self.server.port}",
            "web_admin": f"http://{self.host}:{self.port}",
            "players": [
                {
                    "username": p.username,
                    "address": p.address,
                    "x": p.x,
                    "y": p.y,
                    "z": p.z,
                    "group": self.server.permissions.get_permission_level(p.username),
                }
                for p in self.server.get_online_players()
            ],
            "time": self.server.world_time,
            "weather": self.server.weather,
            "spawn_position": self.server.spawn_position,
            "allowed_files": list(self.allowed_files().keys()),
            "commands": ALL_VANILLA_COMMAND_NAMES,
        }
