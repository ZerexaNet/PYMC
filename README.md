# PyMC

PyMC 是一个用 Python 实现的 Minecraft Java 版 1.21.1 服务端原型，协议版本 767。

项目目标不是基于 Bukkit/Paper/Forge 扩展现有服务端，而是直接实现 Minecraft Java 协议、登录流程、配置注册表、区块发送、玩家同步、基础命令和世界存储。

## 当前能力

- 离线模式登录
- Minecraft Java 1.21.1 协议握手、状态查询、登录、配置和 Play 阶段
- 数据包压缩、KeepAlive、玩家移动同步
- 类原版 384 高度主世界区块
- 优先使用 `native/terrain_gen.exe` 原生地形生成器，失败时回退到 Python 生成器
- Linear V2 `.linear` 区域文件读写，并支持从 Anvil `.mca` 自动转换
- 玩家位置、生命值、饱食度、经验、游戏模式等 JSON 存档
- 基础聊天、方块挖掘/放置、掉落物、经验球和简单生物实体
- 原版 Goal 思路的轻量生物 AI：随机游走、看向玩家、敌对追击、近战冷却
- 基础 `gamerule`：控制昼夜流动、自然刷怪和自然回血
- 控制台和游戏内基础命令
- Web 管理台、权限组、OP、封禁和白名单

## 目录

- `main.py`：服务端入口
- `config.py`：`server.properties` 配置读写
- `network/`：TCP 监听、连接状态、tick 循环
- `handlers/`：各协议阶段的数据包处理
- `protocol/`：VarInt、NBT、Packet 编解码
- `world/`：方块、区块编码、地形生成、存档、实体和世界编辑
- `admin/`：权限系统和 Web 管理后台
- `native/`：C++ 原生地形生成器
- `pumpkin-ref/`：本地参考源码，不属于 PyMC 运行时

## 运行

需要 Python 3.10 或更新版本。

```bash
pip install -r requirements.txt
python main.py
```

默认监听:

- Minecraft 服务端: `0.0.0.0:25565`
- Web 管理台: `0.0.0.0:25568`

使用 Minecraft Java 1.21.1 客户端连接 `localhost:25565`。

## 配置

主要配置在 `server.properties`：

- `server-port`：Minecraft 服务端端口
- `online-mode`：是否正版验证，目前默认 `false`
- `view-distance`：区块视距
- `level-seed`：世界种子
- `gamemode`：默认游戏模式
- `web-admin-enabled`：是否启用 Web 管理台
- `permissions-file`：权限文件路径
- `join-immediate-radius`：玩家入服时优先同步的近距离区块半径

权限、封禁和白名单在 `permissions.json`。

## 常用命令

已实现或部分实现的命令包括：

```text
help, list, say, me, msg, tp, gamemode, gamerule, seed, time, weather,
setworldspawn, spawnpoint, setblock, fill, clone, summon, kill,
kick, ban, pardon, ban-ip, pardon-ip, banlist, op, deop,
whitelist, reload, save-all, save-on, save-off, group, perm, stop
```

未实现完整游戏系统的原版命令会被识别并返回提示。

## 构建

Windows 下可以运行：

```bat
build.bat
```

脚本会编译 `native/terrain_gen.exe`，然后使用 Nuitka 打包为独立可执行文件。

Linux/macOS 可参考 `build.sh` 和 `CMakeLists.txt`。

## 运行数据

以下内容是运行产物，默认不提交到仓库：

- `pymc.log`
- `world/region/`
- `world/playerdata/`
- `__pycache__/`
- `dist/`
- `build/`
