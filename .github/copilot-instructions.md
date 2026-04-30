# Copilot Instructions for riplex

## Documentation changelog

When any file under `docs/` is added, modified, or removed, update `docs/changelog.md` with a dated entry describing the change. Follow the [Keep a Changelog](https://keepachangelog.com/) format with sections like Added, Changed, Removed, or Fixed under a date heading.

## CLI executable

Always use `py` to run Python on this project (not `python` or `python3`). The installed `riplex.exe` in PATH may point to the wrong Python version. Prefer `py -m riplex` to ensure the correct interpreter.

## Dry-run default

The `organize` subcommand is dry-run by default. There is no `--dry-run` flag. Use `--execute` to actually move files.

## Testing

Run tests with `pytest` from the project root. All tests must pass before committing.
