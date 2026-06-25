# ============================================================
# Example PYMC Mod — demonstrates the full Mod API
# ============================================================

from mods import PyMCMod, ModEvents


class ExampleMod(PyMCMod):
    """
    Example mod that showcases the PYMC Native Mod API:
    - Custom block/item/biome registration
    - Event handling
    - Tick-based logic
    """

    def on_load(self):
        """Called when the mod is loaded. Register custom content."""
        self.logger.info("ExampleMod is loading...")

        # Register custom blocks
        self.register_block("example_mod:glow_ore", {
            "material": "stone",
            "hardness": 3.0,
            "resistance": 5.0,
            "light_level": 15,
            "is_opaque": False,
        })

        self.register_block("example_mod:reinforced_glass", {
            "material": "glass",
            "hardness": 5.0,
            "resistance": 50.0,
            "is_opaque": False,
        })

        # Register custom items
        self.register_item("example_mod:wrench", {
            "max_count": 1,
            "max_damage": 250,
            "rarity": "rare",
        })

        self.register_item("example_mod:guide_book", {
            "max_count": 1,
            "is_food": False,
        })

        # Register custom biome
        self.register_biome("example_mod:crystal_plains", {
            "temperature": 0.3,
            "downfall": 0.1,
            "grass_color": 0x88CCFF,
            "water_color": 0x4488FF,
        })

        self._tick_count = 0
        self.logger.info("ExampleMod loaded: registered 2 blocks, 2 items, 1 biome")

    def on_enable(self):
        """Called when the mod is enabled. Register event handlers."""
        self.logger.info("ExampleMod enabling...")

        self.register_event_handler(ModEvents.TICK, self.on_tick)
        self.register_event_handler(ModEvents.BLOCK_BREAK, self.on_block_break)
        self.register_event_handler(ModEvents.PLAYER_JOIN, self.on_player_join)
        self.register_event_handler(ModEvents.CHUNK_LOAD, self.on_chunk_load)

        self.logger.info("ExampleMod enabled!")

    def on_disable(self):
        """Called when the mod is disabled. Clean up."""
        self.logger.info(f"ExampleMod disabled after {self._tick_count} ticks")

    # --- Event handlers ---

    def on_tick(self, event):
        """Handle server tick."""
        self._tick_count += 1

    def on_block_break(self, event):
        """Handle block break — check for custom blocks."""
        block_state = event.data.get("block_state", 0)
        player = event.data.get("player", "")
        self.logger.debug(f"Block break: state={block_state} by {player}")

    def on_player_join(self, event):
        """Handle player join — log for mod tracking."""
        player = event.data.get("player", "unknown")
        self.logger.info(f"Player joined: {player}")

    def on_chunk_load(self, event):
        """Handle chunk load — could inject custom worldgen."""
        cx = event.data.get("chunk_x", 0)
        cz = event.data.get("chunk_z", 0)
        # Could modify chunk data here for custom worldgen
        self.logger.debug(f"Chunk loaded: ({cx}, {cz})")
