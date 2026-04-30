# Configuration

riplex reads settings from three sources, in priority order:

1. CLI flags (highest priority)
2. Environment variables
3. Config file (lowest priority)

## Config file

Create a config file at one of these locations:

| Platform | Path |
|---|---|
| Windows | `%APPDATA%\riplex\config.toml` |
| Linux/macOS | `~/.config/riplex/config.toml` |
| Any (local) | `riplex.toml` in the current working directory |

Example:

```toml
tmdb_api_key = "your_api_key_here"
output_root = "/path/to/media"
rip_output = "/path/to/media/Rips"
archive_root = "/path/to/media/Rips/_archive"
```

## Settings

| Setting | CLI flag | Env var | Config key | Description |
|---|---|---|---|---|
| TMDb API key | `--api-key` | `TMDB_API_KEY` | `tmdb_api_key` | Required for all commands |
| Output root | `--output` | `PLEX_ROOT` | `output_root` | Root directory for organized output. Plex subfolders like `Movies/` and `TV Shows/` are created under this. |
| Rip output | `--output` | - | `rip_output` | Directory for MakeMKV rip output. Default: `{output_root}/Rips`. Used by `rip` and `orchestrate`. |
| Archive root | - | - | `archive_root` | Directory to move rip folders after successful organize. Optional; if not set, rip folders are left in place. |
