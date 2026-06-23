# ============================================================
# Example PYMC Plugin — demonstrates the full Plugin API
# ============================================================

from plugins import PyMCPlugin, PluginEvents, EventPriority


class ExamplePlugin(PyMCPlugin):
    """
    Example plugin that showcases all features of the PYMC Plugin API:
    - Event handling with priorities
    - Command registration
    - Per-plugin configuration
    - Scheduled tasks
    - Inter-plugin communication
    """

    def on_load(self):
        """Called when the plugin is first loaded."""
        self.get_logger().info("ExamplePlugin is loading...")

        # Load config with defaults
        from plugins.config import PluginConfig
        self._config = PluginConfig("example_plugin")
        self._config.set_defaults({
            "welcome_message": "Welcome to the server, {player}!",
            "broadcast_join": True,
            "max_messages_per_minute": 30,
        })
        self._config.load()

    def on_enable(self):
        """Called when the plugin is enabled. Register commands and events."""
        self.get_logger().info("ExamplePlugin is enabling...")

        # Register commands
        self.register_command("hello", self.cmd_hello)
        self.register_command("motd", self.cmd_motd)
        self.register_command("pinfo", self.cmd_plugin_info)

        # Register event handlers with different priorities
        self.register_event_handler(
            PluginEvents.PLAYER_JOIN,
            self.on_player_join,
            priority=EventPriority.NORMAL,
        )
        self.register_event_handler(
            PluginEvents.PLAYER_CHAT,
            self.on_player_chat,
            priority=EventPriority.HIGH,
        )
        self.register_event_handler(
            PluginEvents.BLOCK_BREAK,
            self.on_block_break,
            priority=EventPriority.LOW,
        )
        self.register_event_handler(
            PluginEvents.SERVER_TICK,
            self.on_tick,
            priority=EventPriority.MONITOR,
        )

        # Schedule a repeating task (every 600 ticks = 30 seconds)
        server = self.get_server()
        if hasattr(server, '_plugin_scheduler') and server._plugin_scheduler is not None:
            self._task_id = server._plugin_scheduler.run_every(
                600, self.scheduled_announcement, "example_plugin"
            )
            self.get_logger().info(f"Scheduled repeating task: {self._task_id}")

        self._tick_counter = 0
        self.get_logger().info("ExamplePlugin enabled!")

    def on_disable(self):
        """Called when the plugin is disabled. Clean up resources."""
        self.get_logger().info("ExamplePlugin is disabling...")

        # Cancel scheduled tasks
        server = self.get_server()
        if hasattr(server, '_plugin_scheduler') and server._plugin_scheduler is not None:
            server._plugin_scheduler.cancel_all_for_plugin("example_plugin")

        # Save config
        if hasattr(self, '_config'):
            self._config.save()

        self.get_logger().info("ExamplePlugin disabled!")

    # --- Command handlers ---

    def cmd_hello(self, args):
        """Handle /hello command."""
        server = self.get_server()
        server.broadcast("aHello from ExamplePlugin!")

    def cmd_motd(self, args):
        """Handle /motd command."""
        server = self.get_server()
        motd = server.get_motd()
        server.broadcast(f"9MOTD: {motd}")

    def cmd_plugin_info(self, args):
        """Handle /pinfo command."""
        server = self.get_server()
        players = server.get_online_players()
        tps = server.get_tps()
        version = server.get_version()
        self.get_logger().info(
            f"Server: v{version}, TPS: {tps:.1f}, "
            f"Online: {len(players)} players"
        )

    # --- Event handlers ---

    def on_player_join(self, event):
        """Handle player join — send welcome message."""
        player_name = event.get("player_name", "unknown")
        if self._config.get_bool("broadcast_join", True):
            msg = self._config.get("welcome_message", "Welcome!")
            msg = msg.replace("{player}", player_name)
            self.get_server().broadcast(f"e{msg}")

    def on_player_chat(self, event):
        """Handle player chat — log and optionally filter."""
        player_name = event.get("player_name", "")
        message = event.get("message", "")
        self.get_logger().info(f"[Chat] <{player_name}> {message}")

        # Example: could cancel event to block certain messages
        # if "bad_word" in message.lower():
        #     event.cancel()

    def on_block_break(self, event):
        """Handle block break — log for monitoring."""
        x = event.get("x", 0)
        y = event.get("y", 0)
        z = event.get("z", 0)
        block_state = event.get("block_state", 0)
        self.get_logger().debug(
            f"Block break at ({x}, {y}, {z}), state={block_state}"
        )

    def on_tick(self, event):
        """Handle server tick — count ticks."""
        self._tick_counter += 1

    def scheduled_announcement(self):
        """Called every 30 seconds by the scheduler."""
        server = self.get_server()
        if server.is_running():
            online = server.get_online_player_count()
            self.get_logger().info(
                f"[Scheduled] Server running, {online} players online"
            )
