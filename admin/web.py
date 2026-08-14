# ============================================================
# PyMC - Web 管理后台
# ============================================================

import asyncio
import ipaddress
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
      --bg: #ffffff;
      --panel: #ffffff;
      --text: #050505;
      --muted: #666666;
      --line: #000000;
      --soft-line: #d8d8d8;
      --soft: #f7f7f7;
      --danger: #9b111e;
    }
    * { box-sizing: border-box; }
    html, body { min-height: 100%; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      letter-spacing: 0;
    }
    button, input, select, textarea { font: inherit; }
    button {
      min-height: 34px;
      padding: 7px 12px;
      background: #ffffff;
      color: #000000;
      border: 1px solid var(--line);
      border-radius: 6px;
      cursor: pointer;
      white-space: nowrap;
    }
    button:hover, button.active { background: #000000; color: #ffffff; }
    button.danger { border-color: var(--danger); color: var(--danger); }
    button.danger:hover { background: var(--danger); color: #ffffff; }
    input, select, textarea {
      width: 100%;
      min-height: 34px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #ffffff;
      color: #000000;
      padding: 7px 10px;
    }
    textarea {
      min-height: 300px;
      resize: vertical;
      font-family: Consolas, "Cascadia Mono", monospace;
      line-height: 1.45;
    }
    pre {
      margin: 0;
      padding: 12px;
      border: 1px solid var(--soft-line);
      border-radius: 6px;
      background: var(--soft);
      white-space: pre-wrap;
      word-break: break-word;
      font-family: Consolas, "Cascadia Mono", monospace;
      line-height: 1.45;
    }
    table { width: 100%; border-collapse: collapse; }
    th, td { padding: 9px 8px; border-bottom: 1px solid var(--soft-line); text-align: left; vertical-align: top; }
    th { font-size: 12px; text-transform: uppercase; color: var(--muted); font-weight: 600; }
    .app { display: grid; grid-template-columns: 224px minmax(0, 1fr); min-height: 100vh; }
    .sidebar { border-right: 1px solid var(--line); padding: 18px 14px; position: sticky; top: 0; height: 100vh; background: #ffffff; }
    .brand { padding: 0 8px 18px; border-bottom: 1px solid var(--line); margin-bottom: 14px; }
    .brand h1 { margin: 0; font-size: 22px; line-height: 1.1; }
    .brand p { margin: 7px 0 0; color: var(--muted); font-size: 12px; }
    .nav { display: grid; gap: 7px; }
    .nav button { width: 100%; text-align: left; }
    .main { padding: 20px; min-width: 0; }
    .topbar { display: flex; gap: 12px; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); padding-bottom: 14px; margin-bottom: 18px; }
    .topbar h2 { margin: 0; font-size: 21px; }
    .topbar .right { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .status-dot { width: 10px; height: 10px; border: 1px solid #000000; border-radius: 999px; display: inline-block; }
    .status-dot.on { background: #000000; }
    .view { display: none; }
    .view.active { display: block; }
    .grid { display: grid; gap: 14px; grid-template-columns: repeat(12, minmax(0, 1fr)); }
    .panel { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 14px; min-width: 0; }
    .panel h3 { margin: 0 0 12px; font-size: 16px; }
    .span-3 { grid-column: span 3; }
    .span-4 { grid-column: span 4; }
    .span-5 { grid-column: span 5; }
    .span-6 { grid-column: span 6; }
    .span-7 { grid-column: span 7; }
    .span-8 { grid-column: span 8; }
    .span-12 { grid-column: span 12; }
    .metric { display: grid; gap: 6px; }
    .metric .label { color: var(--muted); font-size: 12px; }
    .metric .value { font-size: 24px; font-weight: 650; overflow-wrap: anywhere; }
    .muted { color: var(--muted); }
    .small { font-size: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .row > * { flex: 1 1 160px; }
    .row.tight > * { flex: 0 0 auto; }
    .stack { display: grid; gap: 10px; }
    .split { display: grid; gap: 12px; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); }
    .toolbar { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 12px; }
    .toolbar input, .toolbar select { width: auto; min-width: 180px; }
    .console-output { min-height: 360px; max-height: 520px; overflow: auto; }
    .list { display: grid; gap: 8px; }
    .list-item { border: 1px solid var(--soft-line); border-radius: 6px; padding: 10px; }
    .config-item { grid-column: span 4; border: 1px solid var(--soft-line); border-radius: 6px; padding: 10px; }
    .tag { display: inline-flex; align-items: center; min-height: 24px; padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; font-size: 12px; }
    .command-grid { display: grid; gap: 8px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
    .command-name { border: 1px solid var(--soft-line); border-radius: 6px; padding: 8px 10px; font-family: Consolas, "Cascadia Mono", monospace; }
    .message { min-height: 20px; color: var(--muted); }
    @media (max-width: 980px) {
      .app { grid-template-columns: 1fr; }
      .sidebar { position: static; height: auto; border-right: 0; border-bottom: 1px solid var(--line); }
      .nav { grid-template-columns: repeat(auto-fit, minmax(128px, 1fr)); }
      .span-3, .span-4, .span-5, .span-6, .span-7, .span-8, .span-12, .config-item { grid-column: 1 / -1; }
      .split { grid-template-columns: 1fr; }
      .topbar { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside class="sidebar">
      <div class="brand">
        <h1>PyMC Admin</h1>
        <p>Web Console</p>
      </div>
      <nav class="nav" id="nav"></nav>
    </aside>
    <main class="main">
      <div class="topbar">
        <div>
          <h2 id="view-title">仪表盘</h2>
          <div class="small muted" id="view-subtitle">服务器运行概览</div>
        </div>
        <div class="right">
          <span class="status-dot" id="status-dot"></span>
          <span id="status-text" class="small">未连接</span>
          <button onclick="refreshAll()">刷新</button>
        </div>
      </div>

      <section class="view active" data-view="dashboard">
        <div class="grid">
          <div class="panel span-3 metric"><div class="label">运行状态</div><div class="value" id="metric-running">-</div></div>
          <div class="panel span-3 metric"><div class="label">在线玩家</div><div class="value" id="metric-players">-</div></div>
          <div class="panel span-3 metric"><div class="label">世界时间</div><div class="value" id="metric-time">-</div></div>
          <div class="panel span-3 metric"><div class="label">非玩家实体</div><div class="value" id="metric-entities">-</div></div>
          <div class="panel span-6">
            <h3>快速控制</h3>
            <div class="toolbar">
              <button onclick="quickCommand('save-all')">保存世界</button>
              <button onclick="quickCommand('save-on')">开启自动保存</button>
              <button onclick="quickCommand('save-off')">关闭自动保存</button>
              <button onclick="quickCommand('time query')">查询时间</button>
              <button class="danger" onclick="confirmCommand('stop')">停止服务器</button>
            </div>
            <div class="message" id="quick-result"></div>
          </div>
          <div class="panel span-6">
            <h3>运行参数</h3>
            <div id="runtime-summary" class="list"></div>
          </div>
          <div class="panel span-12">
            <h3>在线玩家</h3>
            <div id="dashboard-players"></div>
          </div>
        </div>
      </section>

      <section class="view" data-view="console">
        <div class="grid">
          <div class="panel span-12">
            <h3>控制台</h3>
            <div class="toolbar">
              <input id="command" placeholder="输入命令">
              <button onclick="runCommand()">执行</button>
              <button onclick="clearConsole()">清空输出</button>
            </div>
            <pre id="command-result" class="console-output">等待命令</pre>
          </div>
          <div class="panel span-12">
            <h3>服务端日志</h3>
            <div class="toolbar">
              <button onclick="loadLogs()">刷新日志</button>
            </div>
            <pre id="logs" class="console-output">等待日志</pre>
          </div>
        </div>
      </section>

      <section class="view" data-view="players">
        <div class="grid">
          <div class="panel span-12">
            <h3>玩家管理</h3>
            <div id="players-table"></div>
          </div>
          <div class="panel span-12">
            <h3>玩家操作</h3>
            <div class="row">
              <input id="player-name" placeholder="玩家名">
              <select id="player-gamemode">
                <option value="survival">survival</option>
                <option value="creative">creative</option>
                <option value="adventure">adventure</option>
                <option value="spectator">spectator</option>
              </select>
              <button onclick="playerGamemode()">设置模式</button>
              <button onclick="playerKick()">踢出</button>
              <button onclick="quickCommand('op ' + val('player-name'))">OP</button>
              <button onclick="quickCommand('deop ' + val('player-name'))">取消 OP</button>
            </div>
            <div class="row">
              <input id="tp-player" placeholder="玩家名">
              <input id="tp-x" placeholder="x">
              <input id="tp-y" placeholder="y">
              <input id="tp-z" placeholder="z">
              <button onclick="playerTeleport()">传送</button>
            </div>
          </div>
        </div>
      </section>

      <section class="view" data-view="world">
        <div class="grid">
          <div class="panel span-6">
            <h3>世界</h3>
            <div class="row">
              <input id="time-value" placeholder="时间值，例如 day 或 1000">
              <button onclick="quickCommand('time set ' + val('time-value'))">设置时间</button>
            </div>
            <div class="row">
              <select id="weather-value">
                <option value="clear">clear</option>
                <option value="rain">rain</option>
                <option value="thunder">thunder</option>
              </select>
              <button onclick="quickCommand('weather ' + val('weather-value'))">设置天气</button>
            </div>
            <div class="row">
              <input id="spawn-x" placeholder="出生点 x">
              <input id="spawn-y" placeholder="出生点 y">
              <input id="spawn-z" placeholder="出生点 z">
              <button onclick="quickCommand('setworldspawn ' + val('spawn-x') + ' ' + val('spawn-y') + ' ' + val('spawn-z'))">设置出生点</button>
            </div>
          </div>
          <div class="panel span-6">
            <h3>游戏规则</h3>
            <div id="gamerules" class="list"></div>
          </div>
          <div class="panel span-12">
            <h3>实体</h3>
            <div class="row">
              <select id="summon-type">
                <option value="pig">pig</option>
                <option value="cow">cow</option>
                <option value="sheep">sheep</option>
                <option value="zombie">zombie</option>
                <option value="item">item</option>
                <option value="orb">orb</option>
              </select>
              <input id="summon-x" placeholder="x">
              <input id="summon-y" placeholder="y">
              <input id="summon-z" placeholder="z">
              <button onclick="summonEntity()">生成</button>
              <button class="danger" onclick="confirmCommand('kill @e')">清理实体</button>
            </div>
            <div id="entities-summary" class="list"></div>
          </div>
        </div>
      </section>

      <section class="view" data-view="permissions">
        <div class="grid">
          <div class="panel span-6">
            <h3>权限组</h3>
            <div class="row">
              <input id="perm-user" placeholder="玩家名">
              <input id="perm-group" placeholder="组名">
              <button onclick="assignGroup()">设置玩家组</button>
            </div>
            <pre id="permissions">等待权限数据</pre>
          </div>
          <div class="panel span-6">
            <h3>白名单与封禁</h3>
            <div class="row">
              <input id="wl-player" placeholder="玩家名">
              <button onclick="quickCommand('whitelist add ' + val('wl-player'))">加入白名单</button>
              <button onclick="quickCommand('whitelist remove ' + val('wl-player'))">移出白名单</button>
            </div>
            <div class="row">
              <button onclick="quickCommand('whitelist on')">开启白名单</button>
              <button onclick="quickCommand('whitelist off')">关闭白名单</button>
              <button onclick="quickCommand('whitelist list')">白名单列表</button>
            </div>
            <div class="row">
              <input id="ban-player" placeholder="玩家名或 IP">
              <button class="danger" onclick="quickCommand('ban ' + val('ban-player'))">封禁玩家</button>
              <button onclick="quickCommand('pardon ' + val('ban-player'))">解除玩家</button>
              <button class="danger" onclick="quickCommand('ban-ip ' + val('ban-player'))">封禁 IP</button>
              <button onclick="quickCommand('pardon-ip ' + val('ban-player'))">解除 IP</button>
            </div>
          </div>
        </div>
      </section>

      <section class="view" data-view="config">
        <div class="grid">
          <div class="panel span-12">
            <h3>server.properties</h3>
            <div id="properties-grid" class="grid"></div>
            <div class="toolbar">
              <button onclick="saveProperties()">保存配置</button>
              <button onclick="loadProperties()">重新加载</button>
            </div>
            <div class="message" id="properties-message"></div>
          </div>
        </div>
      </section>

      <section class="view" data-view="files">
        <div class="grid">
          <div class="panel span-12">
            <h3>文件编辑</h3>
            <div class="toolbar">
              <select id="file-name" onchange="loadFile()"></select>
              <button onclick="loadFile()">读取</button>
              <button onclick="saveFile()">保存</button>
            </div>
            <textarea id="file-content"></textarea>
            <div class="message" id="file-message"></div>
          </div>
        </div>
      </section>

      <section class="view" data-view="commands">
        <div class="grid">
          <div class="panel span-12">
            <h3>命令目录</h3>
            <div class="toolbar">
              <input id="command-search" placeholder="搜索命令" oninput="renderCommands()">
            </div>
            <div id="commands-list" class="command-grid"></div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    const views = [
      ['dashboard', '仪表盘', '服务器运行概览'],
      ['console', '控制台', '执行命令并查看日志'],
      ['players', '玩家', '在线玩家与常用操作'],
      ['world', '世界', '时间、天气、规则和实体'],
      ['permissions', '权限', '权限组、白名单和封禁'],
      ['config', '配置', 'server.properties 可视化编辑'],
      ['files', '文件', '受限文件编辑'],
      ['commands', '命令', '服务端命令目录']
    ];
    const state = { status: null, permissions: null, properties: {}, console: [] };

    function el(id) { return document.getElementById(id); }
    function val(id) { return (el(id)?.value || '').trim(); }
    function fmt(value) {
      if (value === null || value === undefined || value === '') return '-';
      if (typeof value === 'number') return Number.isInteger(value) ? String(value) : value.toFixed(2);
      return String(value);
    }
    function escapeHtml(text) {
      return String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    async function jget(url) {
      const res = await fetch(url);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    async function jpost(url, body) {
      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body || {})
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || res.statusText);
      return data;
    }
    function initNav() {
      const nav = el('nav');
      nav.innerHTML = views.map(([id, title], index) =>
        `<button class="${index === 0 ? 'active' : ''}" data-target="${id}" onclick="showView('${id}')">${title}</button>`
      ).join('');
    }
    function showView(id) {
      document.querySelectorAll('.view').forEach(node => node.classList.toggle('active', node.dataset.view === id));
      document.querySelectorAll('.nav button').forEach(node => node.classList.toggle('active', node.dataset.target === id));
      const view = views.find(item => item[0] === id);
      el('view-title').textContent = view ? view[1] : id;
      el('view-subtitle').textContent = view ? view[2] : '';
      if (id === 'console') loadLogs();
      if (id === 'config') loadProperties();
      if (id === 'files') ensureFileList();
      if (id === 'commands') renderCommands();
    }
    async function refreshAll() {
      await Promise.allSettled([refreshStatus(), refreshPermissions()]);
      renderAll();
    }
    async function refreshStatus() {
      try {
        state.status = await jget('/api/status');
        el('status-dot').classList.toggle('on', !!state.status.running);
        el('status-text').textContent = state.status.running ? '运行中' : '已停止';
      } catch (err) {
        el('status-dot').classList.remove('on');
        el('status-text').textContent = '连接失败';
        appendConsole('status', err.message);
      }
    }
    async function refreshPermissions() {
      try {
        state.permissions = await jget('/api/permissions');
      } catch (err) {
        appendConsole('permissions', err.message);
      }
    }
    function renderAll() {
      renderDashboard();
      renderPlayers();
      renderPermissions();
      renderGamerules();
      renderEntities();
      ensureFileList();
      renderCommands();
    }
    function renderDashboard() {
      const s = state.status || {};
      const players = s.players || [];
      const entities = s.entities || {};
      const entityCount = Object.values(entities).reduce((a, b) => a + Number(b || 0), 0);
      el('metric-running').textContent = s.running ? '运行中' : '已停止';
      el('metric-players').textContent = `${players.length}/${fmt(s.max_players)}`;
      el('metric-time').textContent = fmt(s.time);
      el('metric-entities').textContent = String(entityCount);
      el('runtime-summary').innerHTML = [
        ['地址', s.address],
        ['Web', s.web_admin],
        ['天气', s.weather],
        ['出生点', Array.isArray(s.spawn_position) ? s.spawn_position.join(', ') : s.spawn_position],
        ['自动保存', s.autosave_enabled ? '开启' : '关闭'],
        ['地形引擎', s.terrain_engine],
        ['视距', s.view_distance]
      ].map(([k, v]) => `<div class="list-item"><b>${k}</b><div>${escapeHtml(fmt(v))}</div></div>`).join('');
      el('dashboard-players').innerHTML = playerTable(players, false);
    }
    function playerTable(players, actions) {
      if (!players || players.length === 0) return '<div class="muted">当前没有在线玩家</div>';
      const rows = players.map(p => `
        <tr>
          <td>${escapeHtml(p.username)}</td>
          <td>${escapeHtml(p.group || '-')}</td>
          <td>${escapeHtml([p.x, p.y, p.z].map(n => Number(n || 0).toFixed(1)).join(', '))}</td>
          <td>${escapeHtml(p.gamemode || '-')}</td>
          <td>${actions ? `<button onclick="fillPlayer(decodeURIComponent('${encodeURIComponent(p.username)}'))">选择</button>` : ''}</td>
        </tr>`).join('');
      return `<table><thead><tr><th>玩家</th><th>权限</th><th>坐标</th><th>模式</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
    }
    function renderPlayers() {
      el('players-table').innerHTML = playerTable((state.status || {}).players || [], true);
    }
    function renderPermissions() {
      el('permissions').textContent = JSON.stringify(state.permissions || {}, null, 2);
    }
    function renderGamerules() {
      const rules = (state.status || {}).gamerules || {};
      el('gamerules').innerHTML = Object.keys(rules).sort().map(name => `
        <div class="list-item">
          <div class="row tight">
            <span class="tag">${escapeHtml(name)}</span>
            <button onclick="setGamerule('${escapeHtml(name)}', true)">true</button>
            <button onclick="setGamerule('${escapeHtml(name)}', false)">false</button>
            <span class="muted">${String(rules[name])}</span>
          </div>
        </div>`).join('') || '<div class="muted">暂无游戏规则数据</div>';
    }
    function renderEntities() {
      const entities = (state.status || {}).entities || {};
      const keys = Object.keys(entities).sort();
      el('entities-summary').innerHTML = keys.length
        ? keys.map(k => `<div class="list-item"><b>${escapeHtml(k)}</b><div>${escapeHtml(entities[k])}</div></div>`).join('')
        : '<div class="muted">当前没有非玩家实体</div>';
    }
    function renderCommands() {
      const commands = ((state.status || {}).commands || []);
      const query = (el('command-search')?.value || '').toLowerCase();
      const filtered = commands.filter(name => name.toLowerCase().includes(query));
      el('commands-list').innerHTML = filtered.map(name => `<div class="command-name">/${escapeHtml(name)}</div>`).join('');
    }
    function ensureFileList() {
      const select = el('file-name');
      if (!select || select.dataset.loaded || !state.status) return;
      select.innerHTML = '';
      for (const name of state.status.allowed_files || []) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = name;
        select.appendChild(opt);
      }
      select.dataset.loaded = '1';
      if (select.value) loadFile();
    }
    function appendConsole(command, result) {
      const time = new Date().toLocaleTimeString();
      const line = `[${time}] ${command}\\n${typeof result === 'string' ? result : JSON.stringify(result, null, 2)}`;
      state.console.push(line);
      state.console = state.console.slice(-80);
      el('command-result').textContent = state.console.join('\\n\\n');
    }
    function clearConsole() {
      state.console = [];
      el('command-result').textContent = '等待命令';
    }
    async function runCommand() {
      const command = val('command');
      if (!command) return;
      await quickCommand(command);
      el('command').value = '';
    }
    async function quickCommand(command) {
      if (!command || !command.trim()) return;
      try {
        const data = await jpost('/api/command', { command });
        appendConsole(command, data);
        el('quick-result').textContent = `已执行: ${command}`;
        await refreshAll();
      } catch (err) {
        appendConsole(command, err.message);
        el('quick-result').textContent = err.message;
      }
    }
    function confirmCommand(command) {
      if (confirm(`确认执行: ${command}`)) quickCommand(command);
    }
    function fillPlayer(username) {
      ['player-name', 'tp-player', 'perm-user', 'wl-player', 'ban-player'].forEach(id => { if (el(id)) el(id).value = username; });
      showView('players');
    }
    function playerGamemode() {
      quickCommand(`gamemode ${val('player-gamemode')} ${val('player-name')}`);
    }
    function playerKick() {
      quickCommand(`kick ${val('player-name')}`);
    }
    function playerTeleport() {
      quickCommand(`tp ${val('tp-player')} ${val('tp-x')} ${val('tp-y')} ${val('tp-z')}`);
    }
    function summonEntity() {
      quickCommand(`summon ${val('summon-type')} ${val('summon-x')} ${val('summon-y')} ${val('summon-z')}`);
    }
    function setGamerule(name, value) {
      quickCommand(`gamerule ${name} ${value ? 'true' : 'false'}`);
    }
    async function assignGroup() {
      try {
        const data = await jpost('/api/permissions/user', { username: val('perm-user'), group: val('perm-group') });
        state.permissions = data;
        renderPermissions();
        await refreshStatus();
      } catch (err) {
        appendConsole('permissions/user', err.message);
      }
    }
    async function loadFile() {
      const name = val('file-name');
      if (!name) return;
      try {
        const data = await jget('/api/file?name=' + encodeURIComponent(name));
        el('file-content').value = data.content || '';
        el('file-message').textContent = `已读取 ${name}`;
      } catch (err) {
        el('file-message').textContent = err.message;
      }
    }
    async function saveFile() {
      const name = val('file-name');
      if (!name) return;
      try {
        const data = await jpost('/api/file?name=' + encodeURIComponent(name), { content: el('file-content').value });
        el('file-message').textContent = data.message || `已保存 ${name}`;
        await refreshAll();
      } catch (err) {
        el('file-message').textContent = err.message;
      }
    }
    async function loadProperties() {
      try {
        const data = await jget('/api/properties');
        state.properties = data.properties || {};
        const keys = Object.keys(state.properties).sort();
        el('properties-grid').innerHTML = keys.map(key => `
          <label class="config-item">
            <div class="small muted">${escapeHtml(key)}</div>
            <input data-prop="${escapeHtml(key)}" value="${escapeHtml(state.properties[key])}">
          </label>
        `).join('');
        el('properties-message').textContent = `已加载 ${keys.length} 项配置`;
      } catch (err) {
        el('properties-message').textContent = err.message;
      }
    }
    async function saveProperties() {
      const properties = {};
      document.querySelectorAll('[data-prop]').forEach(input => properties[input.dataset.prop] = input.value);
      try {
        const data = await jpost('/api/properties', { properties });
        state.properties = data.properties || properties;
        el('properties-message').textContent = data.message || '配置已保存';
        await refreshAll();
      } catch (err) {
        el('properties-message').textContent = err.message;
      }
    }
    async function loadLogs() {
      try {
        const data = await jget('/api/logs');
        el('logs').textContent = data.content || '暂无日志';
      } catch (err) {
        el('logs').textContent = err.message;
      }
    }
    initNav();
    refreshAll();
    setInterval(refreshStatus, 5000);
  </script>
</body>
</html>
"""


class WebAdminServer:
    """轻量 Web 管理端。"""

    def __init__(self, server, host: str, port: int,
                 allow_remote: bool = False):
        self.server = server
        self.host = host
        self.port = port
        self.allow_remote = allow_remote
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        if self._httpd is not None:
            return
        if not self.allow_remote and not self._is_loopback_host(self.host):
            raise ValueError(
                "Web admin has no authentication and may only bind to loopback. "
                "Set web-admin-allow-remote=true only when protected by an "
                "authenticated reverse proxy or equivalent access control."
            )
        handler_cls = self._make_handler()
        self._httpd = ThreadingHTTPServer((self.host, self.port), handler_cls)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="PyMC-WebAdmin",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Web 管理台已启动: http://{self.host}:{self.port}")

    @staticmethod
    def _is_loopback_host(host: str) -> bool:
        normalized = host.strip().lower()
        if normalized == "localhost":
            return True
        try:
            return ipaddress.ip_address(normalized).is_loopback
        except ValueError:
            return False

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
                if parsed.path == "/api/properties":
                    self._send_json(outer.properties_payload())
                    return
                if parsed.path == "/api/logs":
                    lines = parse_qs(parsed.query).get("lines", ["240"])[0]
                    try:
                        line_count = max(20, min(2000, int(lines)))
                    except ValueError:
                        line_count = 240
                    self._send_json({"content": outer.read_log_tail(line_count)})
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

                if parsed.path == "/api/properties":
                    properties = payload.get("properties", {})
                    if not isinstance(properties, dict):
                        self._send_json({"error": "properties 必须是对象"}, HTTPStatus.BAD_REQUEST)
                        return
                    try:
                        result = outer.write_properties(properties)
                        self._send_json(result)
                    except Exception as e:
                        self._send_json({"error": str(e)}, HTTPStatus.BAD_REQUEST)
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

    def properties_payload(self) -> dict:
        return {
            "properties": {
                key: self._property_to_string(value)
                for key, value in self.server.config.items()
            }
        }

    def write_properties(self, properties: dict) -> dict:
        from config import save_config

        for key, raw_value in properties.items():
            if not isinstance(key, str):
                continue
            current = self.server.config.get(key)
            self.server.config[key] = self._coerce_property_value(raw_value, current)

        self._apply_runtime_properties()
        save_config(self.server.config, self.server.config_path)
        return {
            "message": "server.properties 已保存",
            "properties": self.properties_payload()["properties"],
        }

    def read_log_tail(self, line_count: int = 240) -> str:
        path = Path("pymc.log")
        if not path.exists():
            return ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except TypeError:
            text = path.read_text(encoding="utf-8")
        return "\n".join(text.splitlines()[-line_count:])

    @staticmethod
    def _property_to_string(value) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    @staticmethod
    def _coerce_property_value(value, current):
        text = str(value)
        if isinstance(current, bool):
            return text.lower() in {"true", "1", "yes", "on"}
        if isinstance(current, int) and not isinstance(current, bool):
            try:
                return int(text)
            except ValueError:
                return current
        return text

    def _apply_runtime_properties(self):
        config = self.server.config
        self.server.motd = config.get("motd", self.server.motd)
        self.server.max_players = int(config.get("max-players", self.server.max_players))
        self.server.online_mode = bool(config.get("online-mode", self.server.online_mode))
        self.server.compression_threshold = int(
            config.get("network-compression-threshold", self.server.compression_threshold)
        )
        self.server.view_distance = int(config.get("view-distance", self.server.view_distance))
        self.server.join_immediate_radius = max(
            0, int(config.get("join-immediate-radius", self.server.join_immediate_radius))
        )
        self.server.spawn_position = (
            int(config.get("level-spawn-x", self.server.spawn_position[0])),
            int(config.get("level-spawn-y", self.server.spawn_position[1])),
            int(config.get("level-spawn-z", self.server.spawn_position[2])),
        )

    def _status_payload(self) -> dict:
        from handlers.play import ALL_VANILLA_COMMAND_NAMES
        return {
            "running": self.server.running,
            "address": f"{self.server.host}:{self.server.port}",
            "web_admin": f"http://{self.host}:{self.port}",
            "max_players": self.server.max_players,
            "view_distance": self.server.view_distance,
            "autosave_enabled": self.server.autosave_enabled,
            "terrain_engine": "native" if getattr(self.server, "_use_native_terrain", False) else "python",
            "gamerules": dict(getattr(self.server, "gamerules", {})),
            "entities": self.server.entity_manager.count_by_kind(),
            "players": [
                {
                    "username": p.username,
                    "address": p.address,
                    "x": p.x,
                    "y": p.y,
                    "z": p.z,
                    "gamemode": p.gamemode,
                    "health": p.health,
                    "food": p.food,
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
