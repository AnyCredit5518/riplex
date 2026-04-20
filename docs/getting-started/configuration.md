# Configuration

plex-planner reads settings from three sources, in priority order:

1. CLI flags (highest priority)
2. Environment variables
3. Config file (lowest priority)

## Config file

Create a config file at one of these locations:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\plex-planner\config.toml` |
| Linux/macOS | `~/.config/plex-planner/config.toml` |
| Any (local) | `plex-planner.toml` in the current working directory |

Example:

```toml
tmdb_api_key = "your_api_key_here"
output_root = "/path/to/media"
```

## Settings

| Setting | CLI flag | Env var | Config key | Description |
|---|---|---|---|---|
| TMDb API key | `--api-key` | `TMDB_API_KEY` | `tmdb_api_key` | Required for all commands |
| Output root | `--output` | `PLEX_ROOT` | `output_root` | Root directory for organized output. Plex subfolders like `Movies/` and `TV Shows/` are created under this. |
