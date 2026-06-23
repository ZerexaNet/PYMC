# PYMC Mod/Plugin 兼容性说明

## 重要声明

**PYMC 不支持 Java Fabric/Forge/NeoForge/Quilt 模组。**

**PYMC 不支持 Java Bukkit/Paper 插件。**

## 为什么不支持？

Java 模组加载器（Fabric、Forge、NeoForge、Quilt）依赖以下技术：

1. **JVM（Java 虚拟机）**：模组是 Java 字节码，必须运行在 JVM 上
2. **Mixin 字节码注入**：模组通过 Mixin 在运行时修改 Minecraft 的字节码，这是模组实现功能的核心机制
3. **Java 类加载器**：模组的 jar 包需要 Java 的 ClassLoader 体系来加载

PYMC 是一个 Python/C++ 实现的 Minecraft 服务器，**没有 JVM**，**无法执行 Mixin 字节码注入**。这不是功能缺失，而是根本性的架构差异——Mixin 需要在 JVM 字节码层面操作，Python/C++ 服务器无法提供这个环境。

同样，Bukkit/Paper 插件也是 Java 程序，依赖完整的 Bukkit API 类层次和 JVM 来运行，PYMC 无法提供这些。

## PYMC 提供什么？

PYMC 提供自己的 **Python 原生 Mod/Plugin API**，让你可以用 Python 编写模组和插件：

### PYMC Native Mod API

适用于需要注册自定义方块、物品、生物群系等游戏内容的场景。

**模组描述文件** (`pymc_mod.json`):
```json
{
    "id": "my_cool_mod",
    "name": "My Cool Mod",
    "version": "1.0.0",
    "description": "一个酷炫的模组",
    "main_class": "my_cool_mod.MainMod",
    "api_version": "1.0",
    "dependencies": [],
    "mc_version": "1.21.1"
}
```

**模组代码** (`my_cool_mod/__init__.py`):
```python
from pymc.mods import PyMCMod, ModEvents

class MainMod(PyMCMod):
    def on_load(self):
        self.logger.info("模组正在加载！")

    def on_enable(self):
        # 注册自定义方块
        self.register_block("my_cool_mod:magic_block", {
            "material": "stone",
            "hardness": 2.0,
            "resistance": 10.0,
            "light_level": 15,
        })

        # 注册自定义物品
        self.register_item("my_cool_mod:magic_wand", {
            "max_count": 1,
            "rarity": "rare",
        })

        # 注册事件处理器
        self.register_event_handler(ModEvents.PLAYER_JOIN, self.on_player_join)
        self.register_event_handler(ModEvents.BLOCK_BREAK, self.on_block_break)

    def on_player_join(self, event):
        player = event.data.get("player_name", "未知玩家")
        self.logger.info(f"玩家 {player} 加入了服务器！")

    def on_block_break(self, event):
        block = event.data.get("block_id", "")
        if block == "my_cool_mod:magic_block":
            self.logger.info("魔法方块被打破了！")

    def on_disable(self):
        self.logger.info("模组正在关闭！")
```

**目录结构**:
```
mods/
└── my_cool_mod/
    ├── pymc_mod.json
    └── __init__.py
```

### PYMC Plugin API

适用于需要处理命令、事件、聊天等服务器逻辑的场景。

**插件描述文件** (`pymc_plugin.json`):
```json
{
    "id": "welcome_plugin",
    "name": "Welcome Plugin",
    "version": "1.0.0",
    "description": "欢迎玩家加入服务器",
    "main_class": "welcome_plugin.MainPlugin",
    "api-version": "1.0",
    "depend": [],
    "softdepend": []
}
```

**插件代码** (`welcome_plugin/__init__.py`):
```python
from pymc.plugins import PyMCPlugin, PluginEvents, EventPriority

class MainPlugin(PyMCPlugin):
    def on_load(self):
        self.get_logger().info("欢迎插件正在加载！")

    def on_enable(self):
        # 注册命令
        self.register_command("welcome", self.cmd_welcome)

        # 注册事件处理器（带优先级）
        self.register_event_handler(
            PluginEvents.PLAYER_JOIN,
            self.on_player_join,
            priority=EventPriority.NORMAL
        )
        self.register_event_handler(
            PluginEvents.PLAYER_CHAT,
            self.on_player_chat,
            priority=EventPriority.LOWEST
        )

    def cmd_welcome(self, args):
        self.get_server().broadcast("欢迎使用 PYMC 服务器！")

    def on_player_join(self, event):
        player = event.get("player_name", "未知玩家")
        self.get_server().broadcast(f"欢迎 {player} 加入服务器！")

    def on_player_chat(self, event):
        msg = event.get("message", "")
        if "违规词" in msg:
            event.cancel()  # 取消事件，消息不会发送

    def on_disable(self):
        self.get_logger().info("欢迎插件正在关闭！")
```

**目录结构**:
```
plugins/
└── welcome_plugin/
    ├── pymc_plugin.json
    └── __init__.py
```

### 支持的事件

| 分类 | 事件名称 | 说明 |
|------|---------|------|
| 服务器 | `server_start` / `ServerStartEvent` | 服务器启动 |
| 服务器 | `server_stop` / `ServerStopEvent` | 服务器停止 |
| 玩家 | `player_join` / `PlayerJoinEvent` | 玩家加入 |
| 玩家 | `player_leave` / `PlayerQuitEvent` | 玩家离开 |
| 玩家 | `chat` / `AsyncPlayerChatEvent` | 聊天消息 |
| 方块 | `block_break` / `BlockBreakEvent` | 方块破坏 |
| 方块 | `block_place` / `BlockPlaceEvent` | 方块放置 |
| 实体 | `entity_damage` / `EntityDamageEvent` | 实体受伤 |
| 实体 | `entity_death` / `EntityDeathEvent` | 实体死亡 |

### 插件事件优先级

| 优先级 | 说明 |
|--------|------|
| `LOWEST` (0) | 最先执行，其他插件可以覆盖 |
| `LOW` (1) | 较早执行 |
| `NORMAL` (2) | 默认优先级 |
| `HIGH` (3) | 较晚执行 |
| `HIGHEST` (4) | 最后修改事件 |
| `MONITOR` (5) | 只读，不应修改事件 |

## 未来的可能性

理论上可以通过嵌入 JVM（使用 JNI）来实现 Java 模组/插件的支持，但这是一个极其庞大的工程：

- 需要实现完整的 Bukkit API 桩代码
- 需要支持 Mixin 框架的字节码操作
- 需要桥接 Java 对象和 PYMC 的 C++/Python 内部结构
- 性能开销巨大（JVM + Python + C++ 三层调用）
- 维护成本极高（需要跟进每个 Minecraft 版本的 API 变更）

目前 PYMC 选择提供简洁、诚实的 Python 原生 API，而不是假装支持无法真正实现的 Java 兼容层。
