# PyMC

Python Minecraft 1.21.1 server prototype.

## Features

- Offline-mode login and basic world join flow
- Native or Python terrain generation
- Console commands
- Group-based permissions, banlist and whitelist
- Web admin panel at `0.0.0.0:25568`
- Limited file editing for `server.properties`, `permissions.json` and `README.md`

## Commands

Implemented management commands include `help`, `list`, `say`, `msg`, `me`, `tp`, `gamemode`, `kick`, `ban`, `ban-ip`, `pardon`, `pardon-ip`, `banlist`, `op`, `deop`, `whitelist`, `reload`, `save-all`, `save-on`, `save-off`, `difficulty`, `defaultgamemode`, `time`, `weather`, `setworldspawn`, `seed`, `group`, `perm`, `stop`.

Many other vanilla command names are recognized, but advanced gameplay-heavy commands are currently reported as unsupported because the underlying entity, scoreboard, command-function and data systems are not implemented yet.

## Web Admin

Open `http://0.0.0.0:25568` after startup to:

- inspect server status
- run console commands
- assign users to permission groups
- edit allowed files
