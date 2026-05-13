# Copilot Instructions for riplex

## Documentation changelog

When any file under `docs/` is added, modified, or removed, update `docs/changelog.md` with a dated entry describing the change. Follow the [Keep a Changelog](https://keepachangelog.com/) format with sections like Added, Changed, Removed, or Fixed under a date heading.

## Installing from source

First-time setup — create a virtualenv and install in editable mode:
```
python3.12 -m venv .venv
source .venv/bin/activate   # macOS/Linux
.venv\Scripts\activate      # Windows
pip install -e ".[dev,gui]"
```

The `.vscode/settings.json` in this repo points VS Code at `.venv` automatically,
so the integrated terminal activates it on open. In any external terminal, run
`source .venv/bin/activate` first.

If you already have a venv active, just install:
```
pip install -e ".[dev]"
```

For the GUI, also include the gui extra:
```
pip install -e ".[dev,gui]"
```

### Editable-installing dvdcompare-scraper (optional)

By default `dvdcompare-scraper` is pulled from PyPI as a regular install, so
local edits to that sibling repo (typically at
`../dvdcompare-scraper/`) do not take effect until a new version is
published. To pick up scraper changes immediately without bumping the
version, editable-install it once:

```
pip install -e ../dvdcompare-scraper
```

After this, `riplex-ui` and the CLI will use the local checkout directly.

### macOS extras (Homebrew Python only)

If you installed Python via Homebrew, two additional one-time steps are needed:

**1. SSL certificates** — Flet downloads its desktop runtime on first launch and will
fail with an SSL error without this fix:
```
CERT=$(python3.12 -c "import certifi; print(certifi.where())")
echo "export SSL_CERT_FILE=\"$CERT\"" >> .venv/bin/activate
echo "export REQUESTS_CA_BUNDLE=\"$CERT\"" >> .venv/bin/activate
source .venv/bin/activate
```

**2. Folder picker (tkinter)** — the browse buttons in the GUI require tkinter,
which Homebrew ships as a separate package:
```
brew install python-tk@3.12
```
Without this, the browse buttons show a hint telling the user to type the path
manually instead of crashing silently.

## Running

After installing from source, use the installed entry points:
```
riplex rip              # CLI dry-run
riplex rip --execute    # CLI actual rip
riplex-ui              # Launch the Flet GUI
```

Do NOT use `python -m riplex` (that errors — riplex is a library package, not runnable). Do NOT use `python -m riplex_cli.main` when the entry point works.

Because `riplex` is editable-installed (`pip install -e .`), any local edit
to source files under `src/riplex/`, `src/riplex_cli/`, or `src/riplex_app/`
is live the next time you launch `riplex-ui` or run a `riplex` CLI command.
No reinstall step is needed for normal development.

## Upgrading dependencies

The only dependency that needs an explicit upgrade is `dvdcompare-scraper`,
since it's installed from PyPI (not editable). After a new version is
published (every push to its `main` branch auto-bumps the patch and
publishes), bump the pin in `pyproject.toml` and run:
```
pip install -e ".[dev,gui]" --upgrade
```

Close `riplex-ui` first if it's running — the `.exe` shim is locked while
the process is alive and pip will fail with `WinError 32`.

To verify the upgrade picked up the new version:
```
py -m pip show dvdcompare-scraper | Select-String Version
```


## Dry-run default

All destructive commands (`rip`, `organize`, `orchestrate`) are dry-run by default. There is no `--dry-run` flag. Use `--execute` to actually perform the operation.

## Testing

Run tests with `pytest` (or `python -m pytest`) from the project root with the venv active. All tests must pass before committing.
