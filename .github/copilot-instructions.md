# Copilot Instructions for riplex

## Documentation changelog

When any file under `docs/` is added, modified, or removed, update `docs/changelog.md` with a dated entry describing the change. Follow the [Keep a Changelog](https://keepachangelog.com/) format with sections like Added, Changed, Removed, or Fixed under a date heading.

## Installing from source

Install in editable mode with dev extras:
```
py -m pip install -e ".[dev]"
```

For the GUI, also include the gui extra:
```
py -m pip install -e ".[dev,gui]"
```

## Running

Always use `py` to run Python on this project (not `python` or `python3`).

After installing from source, use the installed entry points:
```
riplex rip              # CLI dry-run
riplex rip --execute    # CLI actual rip
riplex-ui              # Launch the Flet GUI
```

Do NOT use `py -m riplex` (that errors — riplex is a library package, not runnable). Do NOT use `py -m riplex_cli.main` when the entry point works.

## Dry-run default

All destructive commands (`rip`, `organize`, `orchestrate`) are dry-run by default. There is no `--dry-run` flag. Use `--execute` to actually perform the operation.

## Testing

Run tests with `py -m pytest` from the project root. All tests must pass before committing.
