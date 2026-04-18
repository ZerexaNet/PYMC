# PyMC

PyMC 是一个使用 Python 编写的 Minecraft Java Edition `1.21.1` 服务端项目，目前以“可启动、可进服、可持续补功能”的原型服务端为目标持续开发。

## 当前特性

- 支持 `1.21.1` 客户端离线模式登录与基础进服流程
- 支持纯 Python 地形生成
- 支持原生 `C++` 地形生成器桥接
- 启动时预生成出生点视距范围内区块
- 生成后的区块以原版 `Chunk NBT` 形式写入 `.linear` 区域文件
- 玩家进入世界时优先发送出生点附近区块
- 玩家移动跨区块后会继续动态补发新区块
- 支持基础控制台命令
- 支持权限组、白名单、封禁列表
- 支持简单 Web 管理台，默认监听 `0.0.0.0:25568`
- 支持区块生成多线程开关

## 已实现命令

当前可用的管理命令包括：

- `help`
- `list`
- `say`
- `msg`
- `me`
- `tp`
- `gamemode`
- `defaultgamemode`
- `kick`
- `ban`
- `ban-ip`
- `pardon`
- `pardon-ip`
- `banlist`
- `op`
- `deop`
- `whitelist`
- `reload`
- `save-all`
- `save-on`
- `save-off`
- `save-status`
- `difficulty`
- `time`
- `weather`
- `setworldspawn`
- `seed`
- `group`
- `perm`
- `stop`

其中 `difficulty`、`defaultgamemode`、`setworldspawn` 等命令的变更会回写到 `server.properties`。

另外，项目已经识别了大量原版命令名；但像实体系统、掉落物、AI、计分板、命令函数、NBT 数据操作等依赖完整游戏系统的高级命令，当前仍会提示“已识别但未实现”。

## Web 管理台

服务器启动后可以访问：

`http://0.0.0.0:25568`

当前支持：

- 查看服务器状态
- 执行控制台命令
- 给玩家分配权限组
- 编辑允许的文件

当前允许编辑的文件包括：

- `server.properties`
- `permissions.json`
- `README.md`

## 重要配置项

### 区块与性能

- `view-distance=10`
  控制服务器视距。

- `chunk-generation-multithreading=false`
  是否开启区块生成多线程，默认关闭。

- `chunk-generation-workers=0`
  多线程生成时的线程数。`0` 表示自动按 CPU 核心数选择。

- `join-immediate-radius=2`
  玩家正式放入世界前，优先发送出生点附近多少圈区块。

### 世界

- `level-name=world`
  世界目录名称。

- `level-seed=0`
  世界种子。

- `level-spawn-x`
- `level-spawn-y`
- `level-spawn-z`
  持久化出生点坐标。

### 网络

- `server-ip=0.0.0.0`
- `server-port=25565`
- `max-players=20`
- `network-compression-threshold=256`

## 存档说明

- 世界区块保存在 `world/region/` 目录下
- 区域文件使用 `.linear` 格式
- 区块内容写入为原版 `Chunk NBT`
- 已支持从旧区块缓存格式读取
- 已支持从 `Anvil (.mca)` 自动转换到 `.linear`

## 原生地形生成器

项目支持原生 `C++` 地形生成器：

- Windows：`native/terrain_gen.exe`
- Linux / macOS：`native/terrain_gen`

如果运行时找不到原生生成器，会自动回退到纯 Python 生成器。

## 打包

### Windows 本地打包

直接运行：

```bat
build.bat
```

### Linux / macOS 本地打包

直接运行：

```bash
./build.sh
```

### GitHub Actions

工作流会构建以下产物：

- `PyMC-windows.exe`
- `PyMC-linux`
- `PyMC-macos`

## 当前状态说明

这个项目已经具备基础进服、基础地形、基础区块存档、基础命令与管理能力，但还不是完整原版服务端。下面这些系统仍在持续完善中：

- 掉落物实体
- 生物生成
- 生物 AI
- 完整伤害系统
- 更完整的光照传播
- 更完整的原版命令系统
- 更完整的玩家状态同步

如果你打算继续开发，建议优先查看这些目录：

- `main.py`
- `network/`
- `handlers/`
- `world/`
- `admin/`

