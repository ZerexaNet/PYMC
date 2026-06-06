# PyMC

PyMC 是一个用 Python 实现的 Minecraft Java 版 1.21.1 服务端原型，协议版本 767。

项目目标不是基于 Bukkit/Paper/Forge 扩展现有服务端，而是直接实现 Minecraft Java 协议、登录流程、配置注册表、区块发送、玩家同步、基础命令和世界存储。

## 开发清单

### 已实现

- [x] Minecraft Java 1.21.1 协议版本 767 的握手、状态查询、登录、配置和 Play 阶段。
- [x] 离线模式登录、数据包压缩、KeepAlive、玩家移动同步和区块发送。
- [x] `server.properties` 配置读写，支持原版风格 `level-seed` 解析：数字种子按 64 位整数，字符串种子按 Java `String.hashCode()`。
- [x] 384 高度主世界区块数据结构，支持从 `-64` 到 `319` 的世界高度。
- [x] C++ 原生地形生成器 `native/terrain_gen`，优先使用原生生成，失败时回退到 Python 生成器。
- [x] C++ 地形生成批量接口和 biome metadata 返回，降低入服时批量区块生成开销。
- [x] 类原版主世界地形：气候/生物群系采样、海洋/河流/山地/沙漠/雪地/恶地等基础地貌。
- [x] 地表规则和装饰：草地、泥土、沙子、红沙、沙石、红沙石、陶瓦、积雪、细雪、方解石、灰化土、砂砾等。
- [x] 植被和自然特征：多树种树木、草、蕨、枯灌木、甘蔗、南瓜、西瓜、海草、海带等。
- [x] 安全出生点解析：首次进入和重生时会生成/读取附近区块，避免出生在地下、水里、岩浆或危险方块上。
- [x] Linear V2 `.linear` 区域文件读写，并支持从 Anvil `.mca` 自动转换。
- [x] 玩家 JSON 存档：位置、生命值、饱食度、经验、游戏模式和个人出生点。
- [x] 基础聊天、方块挖掘/放置、掉落物、经验球和简单生物实体。
- [x] C++ 原生轻量生物 AI `native/mob_ai`，支持随机游走、看向玩家、敌对追击、近战冷却等行为。
- [x] 基础 `gamerule`：昼夜流动、自然刷怪、自然回血、死亡后重生屏幕等。
- [x] 控制台和游戏内基础命令。
- [x] Web 管理台、权限组、OP、封禁和白名单。
- [x] 单元测试覆盖原生地形、原生 AI、种子解析和安全出生点。

### 正在推进 / 待实现

- [ ] 完全原版同种子同地形复刻：目标是输入原版 Java 版种子后生成同位置同地形。当前是 clean-room C++ 近似实现，还没有达到逐区块完全一致。
- [ ] 补齐原版 1.21.1 噪声参数、密度函数、surface rule、carver、aquifer、ore vein 和 feature placement 的精确行为。
- [ ] 结构生成：村庄、废弃矿井、地牢、沉船、沙漠神殿、林地府邸、远古城市等。
- [ ] 完整洞穴系统：大型洞穴、繁茂洞穴、溶洞、地下水体、岩浆湖、深暗之域等。
- [ ] Nether、End 和多维度传送。
- [ ] 完整光照、天气效果、昼夜同步和客户端可见的区块更新细节。
- [ ] 背包、物品栏、合成、熔炉、容器、掉落拾取和耐久系统。
- [ ] 更完整的方块行为：门、床、作物、流体流动、红石、活塞、重力方块等。
- [ ] 更完整的生物系统：寻路、繁殖、掉落、远程攻击、村民、Boss、刷怪规则和 mob cap。
- [ ] 正版登录验证、加密链路和更完整的权限模型。
- [ ] 更完整的命令系统、选择器、NBT 参数和 datapack/function 支持。

### 当前限制

- 这是服务端原型，不是完整原版服务端替代品。
- 当前地形生成不会下载或运行 Mojang 原版服务端；地形和 AI 走本项目 C++/Python clean-room 实现。
- 目标是逐步逼近原版，但现在还不能保证任意原版种子生成完全相同地形。

## 当前能力

- 离线模式登录
- Minecraft Java 1.21.1 协议握手、状态查询、登录、配置和 Play 阶段
- 数据包压缩、KeepAlive、玩家移动同步
- 类原版 384 高度主世界区块
- 优先使用 `native/terrain_gen.exe` 原生地形生成器，失败时回退到 Python 生成器
- 安全出生点解析，避免首次进入或重生时卡在地下、水里或危险方块上
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
