# PyMC

PyMC 是一个用 Python 实现的 Minecraft Java 版 1.21.1 服务端原型，协议版本 767。

项目目标不是基于 Bukkit/Fabric/Forge 扩展现有服务端，而是直接实现 Minecraft Java 协议、登录流程、配置注册表、区块发送、玩家同步、基础命令和世界存储。

## 开发清单

### 已实现

- [x] Minecraft Java 1.21.1 协议版本 767 的握手、状态查询、登录、配置和 Play 阶段。
- [x] 离线模式登录、数据包压缩、KeepAlive、玩家移动同步和区块发送。
- [x] `server.properties` 配置读写，支持原版风格 `level-seed` 解析：数字种子按 64 位整数，字符串种子按 Java `String.hashCode()`。
- [x] 384 高度主世界区块数据结构，支持从 `-64` 到 `319` 的世界高度。
- [x] **原版地形引擎** `native/terrain_gen` (C++17, 多线程)：移植原版 1.21.1 的随机数 (Xoroshiro128++ / `PositionalRandomFactory`)、Perlin/Normal/Blended 噪声、完整的密度函数图 (noise router, 含 4x8x4 插值单元与 flat/2D 缓存)、样条、含水层 (aquifer)、矿脉 (ore vein)、多噪声生物群系查找和 surface rule。数据直接取自原版 worldgen JSON (`world/data/worldgen_overworld.json`)，因此同一种子的地形形状、洞穴、海洋、河流、山地和生物群系分布与原版一致。
- [x] 原版出生点选择：`Climate.findSpawnPosition` (按气候参数寻找陆地出生点) + 原版 11x11 区块螺旋搜索安全地表。
- [x] 地物装饰（近似原版）：按生物群系配置的树木（橡树/大橡树/白桦/云杉/松树/巨型云杉/丛林/金合欢/深色橡树/沼泽/樱花/红树）、草/花/蕨、仙人掌、甘蔗、海草/海带、巨型蘑菇、冰刺、苔石堆、矿石团簇和黏土/沙子/砂砾圆盘，可跨区块生成。
- [x] 启动时自动编译原生生成器 (g++/clang++/MSVC)，版本不符的旧二进制会被忽略；编译不可用时回退 Python 生成器。
- [x] 安全出生/重生：新玩家在世界出生点周围 `spawnRadius` 范围内随机挑选安全地面 (原版 `fudgeSpawnLocation`)，不会落在水里、岩浆、树顶或方块里；老玩家回到上次下线位置 (被埋住时才会挪到附近安全处)；重生优先个人出生点。
- [x] **原版 Anvil 存档** (`region/r.X.Z.mca`)：原版客户端/工具 (MCA Selector、prismarine 等) 可以直接读取；旧 PyMC 的 `.linear` 区域会在启动时自动转换 (原文件保留为 `.linear.bak`)。旧版存档中错误的方块状态顺序会自动识别并迁移。
- [x] **原版玩家存档** `playerdata/<uuid>.dat` (gzip NBT)：位置、朝向、生命、饥饿、经验、游戏模式、物品栏 (原版槽位编号)、末影箱、能力和个人出生点；旧 `.json` 存档自动迁移；正常关服和定时自动保存都会落盘。
- [x] 基础聊天、方块挖掘/放置、掉落物、经验球和简单生物实体。
- [x] C++ 原生轻量生物 AI `native/mob_ai`，支持随机游走、看向玩家、敌对追击、近战冷却等行为。
- [x] 基础 `gamerule`：昼夜流动、天气循环 (doWeatherCycle)、自然刷怪、自然回血、死亡后自动重生回出生点。
- [x] **天气客户端同步**：通过 Game Event 数据包同步下雨/雷暴的开始、结束与强度；入服时同步当前天气，`/weather` 持续时间参数生效并立即广播。
- [x] **玩家互相可见**：Spawn Entity / Set Entity Data / Entity Teleport / Rotate Head 转发，玩家皮肤层元数据同步，移动更新按 `network-movement-rate-hz` 限频（原生 1.21.1 路径）。
- [x] **战斗系统**：攻击生物（武器伤害表）、生物死亡掉落与经验球、骷髅等远程生物标记。
- [x] **物品耐久与基础附魔**：工具/武器耐久消耗、耐久 (Unbreaking) 减免、锋利 (Sharpness) 增伤。
- [x] **雷暴闪电**：雷暴期间在随机玩家附近落雷，对附近实体造成伤害。
- [x] **原版服务端外壳**：控制台日志格式 (`[时间] [Server thread/INFO]: ...`)、`logs/latest.log` 自动归档为 `日期-N.log.gz`、启动顺序与 `Done (N s)! For help, type "help"`、`stop`/Ctrl+C/SIGTERM 优雅关闭、`Can't keep up!` 过载警告、控制台命令带不带 `/` 均可。
- [x] **原版文件布局**：`server.properties`（原版键名与格式，自动补全缺失项）、`ops.json`、`whitelist.json`、`banned-players.json`、`banned-ips.json`、`usercache.json`、`<世界>/level.dat`（出生点、时间、天气、游戏规则、种子、难度）和 `session.lock`；旧版 `permissions.json` 中的 OP/封禁/白名单自动迁移。
- [x] **RCON**（`enable-rcon`/`rcon.port`/`rcon.password`）与 **正版验证**（`online-mode=true`：RSA + AES/CFB8 加密、Mojang 会话服务器验证、真实 UUID 与皮肤）。
- [x] **完整的 1.21.1 数据同步**：配置阶段发送全部 11 个原版注册表与标签（游泳、攀爬、工具挖掘速度依赖标签）、Feature Flags；主世界高度 -64..320；全量 1333 个物品 ID 表与堆叠/耐久数据；命令树 (`Commands` 包) 带原版语法提示与 Tab 补全。
- [x] **原版消息**：所有聊天类消息使用文本组件（1.20.3+ 为 NBT），加入/离开/死亡/聊天/命令反馈使用原版翻译键，客户端按自身语言显示；OP 能看到灰色斜体的 `[某人: 操作]` 通知。
- [x] **原版核心命令**：help、list、say、me、msg/tell/w、kick、ban/ban-ip/pardon/pardon-ip/banlist、op/deop、whitelist、stop、save-all/on/off、seed、time、weather、difficulty、gamerule、gamemode/defaultgamemode、tp/teleport、give、clear、kill、xp、setworldspawn、spawnpoint、summon；未知命令/无权限显示原版 `<--[HERE]` 错误。
- [x] **登录检查**：用户名合法性、协议版本（过旧/过新客户端提示）、封禁、白名单、服务器已满、同名重复登录踢出旧连接、`player-idle-timeout`。
- [x] **玩法细节**：死亡界面与原版死亡消息、掉落物品与经验、重生流程、`keepInventory`/`doImmediateRespawn`/`showDeathMessages` 等规则、受伤动画与击退、PvP（`pvp`）、潜行/疾跑/挥手/手持物品同步、生存/创造模式挖掘与放置确认、`spawn-protection`、天空光与方块光计算。
- [x] 控制台和游戏内基础命令。
- [x] 权限组、OP、封禁和白名单。
- [x] 单元测试覆盖原生地形、原版存档读写与迁移、玩家存档、原生 AI、种子解析和安全出生点。
- [x] **红石系统**：tick 引擎、电源/导线/火把/中继器/比较器/观察者/活塞、门与灯控制、TNT 起爆、音符盒、发射器/投掷器；红石时序为原版近似。
- [x] **合成**：背包 2×2 与工作台 3×3，原版 1.21.1 全部有序/无序配方（标签展开、镜像、合成剩余物），Shift 批量合成。
- [x] **物品栏系统**：`ItemStack`、玩家物品栏、协议序列化、左右键/Shift/数字键/拖拽/丢弃，以及方块容器交互与持久化；附魔台和铁砧已实现（附魔、先前工作惩罚、费用上限可由 `anvil-too-expensive-limit` 关闭）；药水外观已实现，药效尚未实现。
- [x] **PYMC 原生扩展 API**：支持 Python Mod/Plugin 的发现、依赖排序、生命周期、事件和命令注册。Java Fabric/Forge Mod 不受支持；Bukkit/Paper `.jar` 插件通过可选 Java 桥接层提供 best-effort 兼容，详见 `MOD_COMPATIBILITY.md`。

### 部分实现（不可视为完成）

- [ ] **地物 (feature) 装饰**：树木、花草、矿石等按生物群系近似原版生成，但放置随机数和部分参数与原版不同，因此同一种子下树的具体位置与原版不一致。
- [ ] **方块行为系统**：已有多种交互框架和基础行为，但部分容器与特殊方块仍是简化实现。
- [ ] **流体系统**：已有基础水/岩浆传播与交互，但尚未达到完整原版规则。
- [ ] **多版本协议兼容**：已有 47-770 的版本映射和处理器框架；只有核心路径经过有限验证，不能宣称所有版本完整兼容。
- [ ] **命令覆盖**：`CommandManager`、权限、别名和大量命令已注册，但部分命令或子命令仍只返回“暂未实现”。
- [ ] **Watchdog**：已有 UDP 心跳、监控、重启框架和真实 UDP 端到端测试，但尚未在长期运行环境中验证。
- [ ] **网络优化**：批处理已接入实体同步广播路径、移动更新已限频，但普通发送路径尚未全面接入。
- [x] **CI/CD**：GitHub Actions 工作流，Linux/macOS/Windows 三平台构建、CMake 原生组件编译、pytest 测试和 Nuitka 打包。

### 正在推进 / 待实现

- [ ] 原版 carver (峡谷与旧式洞穴雕刻) 和精确的 feature placement。
- [ ] 结构生成：村庄、废弃矿井、地牢、沉船、沙漠神殿、林地府邸、远古城市等。
- [ ] 完整洞穴系统：大型洞穴、繁茂洞穴、溶洞、地下水体、岩浆湖、深暗之域等。
- [ ] Nether、End 和多维度传送。
- [ ] 完整光照和客户端可见的区块更新细节。
- [ ] 更完整的物品栏交互：创造模式物品栏、铁砧改名与修复、药水效果。
- [ ] 更完整的生物系统：完整 A* 寻路、繁殖、村民、Boss、刷怪规则和 mob cap。
- [ ] 更完整的选择器、NBT 参数和 datapack/function 支持。

### 当前限制

- 这是服务端原型，不是完整原版服务端替代品。
- 地形生成不会下载或运行 Mojang 原版服务端；只使用原版公开的 worldgen 数据 JSON。
- 地形形状/生物群系与原版一致，但还没有结构 (村庄等) 和 carver，树木等地物位置与原版不同。
- 用旧版本 PyMC 生成的世界，已生成区块保持不变，新生成区块使用新地形，两者交界处会出现断层。
- 不支持 Java Fabric/Forge/NeoForge/Quilt Mod；Bukkit/Paper `.jar` 插件经 Java 桥接层提供生命周期与命令兼容（best-effort），另支持 PYMC 原生 Python 扩展。

## 当前能力

- 离线模式登录
- Minecraft Java 1.21.1 协议握手、状态查询、登录、配置和 Play 阶段
- 多版本协议兼容 (1.8.9 - 1.21.4, 协议版本 47-770)
- 数据包压缩、KeepAlive、玩家移动同步
- 类原版 384 高度主世界区块
- `native/terrain_gen` 原版 1.21.1 地形引擎 (噪声路由、含水层、矿脉、生物群系、surface rule)，回退到 Python 近似生成器
- 红石系统：常用组件模拟与机械激活（含 TNT、音符盒、发射器/投掷器），每 2 游戏刻 (0.1s) 红石刻
- 流体系统：水/岩浆流动，水-岩浆交互
- 物品栏系统：ItemStack、PlayerInventory、协议序列化、点击/Shift/拖拽交互与方块容器持久化
- 方块行为：基础容器和多种交互框架，部分行为为简化实现
- 原版出生点选择与安全出生/重生 (`spawnRadius` 规则)
- 原版 Anvil `.mca` 区域存档 (可选 Linear V2)，旧 `.linear` 自动转换
- 原版 `playerdata/<uuid>.dat` 玩家存档 (位置、状态、物品栏、末影箱、出生点)
- 基础聊天、方块挖掘/放置、掉落物、经验球和简单生物实体
- 玩家互相可见：实体生成/元数据/移动转发（原生 1.21.1 路径）
- 战斗系统：攻击生物、武器伤害表、生物死亡掉落与经验、远程生物标记
- 物品耐久与基础附魔效果：耐久消耗、Unbreaking 减免、Sharpness 增伤
- 原版 Goal 思路的轻量生物 AI：随机游走、看向玩家、敌对追击、近战冷却
- 命令框架：大量命令注册、权限检查和别名；部分子命令仍未完成
- Mod/插件：仅支持 PYMC 原生 Python API
- Watchdog：UDP 心跳与自动重启框架（含真实 UDP 端到端测试）
- 网络优化：实体同步广播走批处理、移动更新限频、区块排序
- 基础 `gamerule`：控制昼夜流动、天气循环、自然刷怪、自然回血和死亡自动重生
- 天气客户端同步：Game Event 广播下雨/雷暴状态与强度，入服时同步当前天气；雷暴期间落雷并伤害附近实体
- 控制台和游戏内基础命令
- 权限组、OP、封禁和白名单

## 目录

- `main.py`：服务端入口
- `config.py`：`server.properties` 配置读写
- `network/`：TCP 监听、连接状态、tick 循环
- `handlers/`：各协议阶段的数据包处理
  - `handlers/versioned/`：版本化协议处理器 (1.8 - 1.21)
- `protocol/`：VarInt、NBT、Packet 编解码
- `world/`：方块、区块编码、地形生成、存档、实体和世界编辑
  - `world/redstone.py`：红石引擎
  - `world/vanilla_terrain.py`：原版风格近似地形生成器
  - `world/inventory.py`：物品栏系统
  - `world/block_behavior.py`：方块行为系统
  - `world/fluids.py`：流体系统
- `commands/`：命令框架和原版命令
- `admin/`：权限系统
- `watchdog/`：双进程保护系统
  - `watchdog/process_manager.py`：Watchdog 管理器
  - `watchdog/network_optimizer.py`：网络优化器
  - `watchdog/health_check.py`：健康检查
  - `watchdog/restart_handler.py`：自动重启处理
- `mods/`：PYMC 原生 Python Mod API
- `plugins/`：PYMC 原生 Python Plugin API + Java Bukkit/Paper 桥接层（`plugins/java_plugin.py`）
- `native/`：C++ 原生地形生成器、轻量生物 AI、红石引擎、光照引擎、物理引擎及 PYMC 原生扩展接口

## 运行

需要 Python 3.10 或更新版本。

```bash
pip install -r requirements.txt
python main.py --nogui
```

与原版服务端一样，在一个单独的目录中运行即可，首次启动会生成 `server.properties`、`ops.json` 等文件；
也支持 `--port`、`--world`、`--universe`、`--config` 参数。`online-mode=true` 需要 `cryptography` 包。

默认监听:

- Minecraft 服务端: `0.0.0.0:25565`
- Watchdog UDP 健康检查: `127.0.0.1:25569` (启用时)

使用 Minecraft Java 1.21.1 客户端连接 `localhost:25565`。

也支持旧版客户端 (1.8.9 - 1.20.4) 连接，协议版本 47-766。

## 配置

主要配置在 `server.properties`：

- `server-port`：Minecraft 服务端端口
- `online-mode`：是否正版验证（默认 `false`，开启需安装 `cryptography`）
- `motd` / `max-players` / `difficulty` / `pvp` / `hardcore` / `white-list` / `enforce-whitelist` / `spawn-protection` / `player-idle-timeout` / `enable-status` / `hide-online-players` / `simulation-distance` / `spawn-animals` / `spawn-monsters` / `force-gamemode`：与原版含义相同
- `enable-rcon` / `rcon.port` / `rcon.password`：RCON 远程控制台
- 放置 64x64 的 `server-icon.png` 即可在服务器列表显示图标
- `view-distance`：区块视距
- `level-seed`：世界种子
- `gamemode`：默认游戏模式
- `anvil-too-expensive-limit`：铁砧合并费用达到 40 级时是否禁止取出（原版为 `true`；设为 `false` 后不限制费用，等级足够即可取出）
- `permissions-file`：权限文件路径
- `join-immediate-radius`：玩家入服时优先同步的近距离区块半径
- `min-protocol-version` / `max-protocol-version`：允许的协议版本范围 (默认 47-770)
- `vanilla-terrain`：没有原生生成器时使用 Python 原版风格近似地形 (默认 `true`)
- `region-file-format`：区域文件格式，`anvil` (原版 `.mca`，默认) 或 `linear` (Linear V2，需 `zstandard`)
- `redstone-enabled`：启用红石模拟 (默认 `true`)
- `fluid-flow-enabled`：启用流体流动 (默认 `true`)
- `mods-directory`：Mod 扫描目录 (默认 `mods`)
- `plugins-directory`：插件扫描目录 (默认 `plugins`)
- `watchdog-enabled`：启用 Watchdog 双进程保护 (默认 `false`)
- `watchdog-health-port`：Watchdog UDP 健康检查端口 (默认 25569)
- `watchdog-partner-pid`：伙伴进程 PID (0 = 自动检测)
- `watchdog-max-missed-heartbeats`：最大丢失心跳数 (默认 5)
- `network-packet-batching`：启用数据包批量发送 (默认 `true`)
- `network-movement-rate-hz`：移动更新频率 (默认 20Hz)

权限、封禁和白名单在 `permissions.json`。

## 常用命令

已实现或部分实现的命令包括：

```text
help, list, say, me, msg, tp, gamemode, gamerule, seed, time, weather,
setworldspawn, spawnpoint, setblock, fill, clone, summon, kill,
kick, ban, pardon, ban-ip, pardon-ip, banlist, op, deop,
whitelist, reload, save-all, save-on, save-off, group, perm, stop,
give, clear, xp, enchant, effect, difficulty, title, tellraw,
bossbar, scoreboard, team, tag, attribute, particle, playsound,
ride, item, recipe, schedule, execute, datapack, function,
worldborder, forceload, place, damage, spreadplayers, locate,
advancement, trigger, defaultgamemode
```

未实现完整游戏系统的原版命令会被识别并返回提示。

## 构建

Windows 下可以运行：

```bat
build.bat
```

脚本会编译 `native/terrain_gen.exe`，然后使用 Nuitka 打包为独立可执行文件。

Linux/macOS 可参考 `build.sh` 和 `CMakeLists.txt`。直接 `python main.py` 运行时，如果找不到当前版本的地形生成器，服务端会自动用本机的 g++/clang++ 编译到 `build/native/`。手动编译：

```bash
g++ -O2 -std=c++17 -ffp-contract=off -pthread -o native/terrain_gen native/terrain_gen.cpp
```

`-ffp-contract=off` 不能省略：它保证浮点运算与 Java 逐位一致，否则地形会与原版有细微差异。

`world/data/worldgen_overworld.json` 由 `tools/gen_worldgen_data.py` 从原版 1.21.1 的 worldgen 数据生成 (需要联网下载原版数据 JSON)，仓库中已附带生成结果，一般无需重新生成：

```bash
python3 tools/gen_worldgen_data.py
```

合成配方 `world/data/recipes.json` 同样由 `tools/gen_recipe_data.py` 从原版 1.21.1 数据生成（已附带）：

```bash
python3 tools/gen_recipe_data.py
```

生物群系参数查找树取自 [cubiomes](https://github.com/Cubitect/cubiomes) (MIT 许可) 的 `btree20` 表；worldgen JSON 来自 [misode/mcmeta](https://github.com/misode/mcmeta) 的 `1.21.1-data-json`。

### CI/CD

项目使用 GitHub Actions 自动构建，参见 `.github/workflows/build.yml`。

支持平台：
- Linux (ubuntu-latest)：CMake 原生编译 + pytest + Nuitka 打包
- macOS (macos-latest)：CMake 原生编译 + Nuitka 打包
- Windows (windows-latest)：MinGW/CMake 原生编译 + Nuitka 打包

## 运行数据

以下内容是运行产物，默认不提交到仓库：

- `logs/`、`ops.json`、`whitelist.json`、`banned-*.json`、`usercache.json`
- `world/level.dat`、`world/session.lock`
- `world/region/`
- `world/playerdata/`
- `__pycache__/`
- `dist/`
- `build/`
