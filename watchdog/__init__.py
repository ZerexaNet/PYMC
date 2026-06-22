# ============================================================
# PyMC - Watchdog Dual-Process Mutual Protection
# Two processes watch each other. If one crashes, the other restarts it.
# Also includes PlayerNetworkOptimizer for batch network packets.
# ============================================================

from watchdog.process_manager import WatchdogManager
from watchdog.network_optimizer import PlayerNetworkOptimizer

__all__ = ["WatchdogManager", "PlayerNetworkOptimizer"]
