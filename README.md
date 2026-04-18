# PyMC

Python Minecraft 1.21.1 server prototype.

## Features

- Offline-mode login and basic world join flow
- Native or Python terrain generation
- Startup spawn-area pregeneration with Linear V2 region storage
- Generated chunks are stored as vanilla chunk NBT inside `.linear` region files
- Near-spawn chunks are sent first so players enter the world faster
- Console commands
- Group-based permissions, banlist and whitelist
- Web admin panel at `0.0.0.0:25568`
- Limited file editing for `server.properties`, `permissions.json` and `README.md`
- Configurable chunk generation threading and join preload radius

## Commands

Implemented management commands include `help`, `list`, `say`, `msg`, `me`, `tp`, `gamemode`, `kick`, `ban`, `ban-ip`, `pardon`, `pardon-ip`, `banlist`, `op`, `deop`, `whitelist`, `reload`, `save-all`, `save-on`, `save-off`, `difficulty`, `defaultgamemode`, `time`, `weather`, `setworldspawn`, `seed`, `group`, `perm`, `stop`.

Changes made through `difficulty`, `defaultgamemode` and `setworldspawn` are persisted back to `server.properties`.

Many other vanilla command names are recognized, but advanced gameplay-heavy commands are currently reported as unsupported because the underlying entity, scoreboard, command-function and data systems are not implemented yet.

## Web Admin

Open `http://0.0.0.0:25568` after startup to:

- inspect server status
- run console commands
- assign users to permission groups
- edit allowed files

## Useful Config

- `chunk-generation-multithreading=false`
- `chunk-generation-workers=0`
  `0` means auto-pick based on CPU cores.
- `join-immediate-radius=2`
  Controls how many near-spawn chunks are sent before the player is fully placed into the world.
- `level-spawn-x`, `level-spawn-y`, `level-spawn-z`
  Persistent world spawn position used by startup and `setworldspawn`.
