# Testing

riplex uses `pytest`. Run the whole suite from the project root with the venv
active:

```
pytest
```

The suite has two layers:

- **Unit tests** (`tests/test_*.py`) — one file per source module, covering
  parsing, planning, matching, and per-screen handler logic in isolation.
- **GUI integration tests** (`tests/integration/`) — headless end-to-end flows
  that drive the Flet wizard through mocked scenarios to catch regressions in
  how screens hand off to each other.

To run only the integration flows (or skip them):

```
pytest -m integration
pytest -m "not integration"
```

## GUI integration tests

The integration suite builds a real `RiplexApp` on a fake page and clicks
through the wizard the way a user would — but with every external system
(makemkv, TMDb, dvdcompare, config, network) replaced by fakes. This means a
whole flow (welcome → disc detection → metadata → release → disc overview →
rip → done) runs in milliseconds with no disc, no network, and no crash dialog.

The goal is to catch the most common regression class: a screen that throws
while rendering because an upstream change altered the shape of the state it
reads.

### Harness (`tests/support/`)

| Module | Responsibility |
| ------ | -------------- |
| `fake_page.py` | `FakePage`, a stand-in for `ft.Page` implementing only the surface the screens touch, plus control-tree walking helpers. |
| `sync_runtime.py` | Makes background threads and `page.run_task` run synchronously so flows are deterministic (no sleeps, no polling loops). |
| `fixtures.py` | Loads a scenario JSON and reconstructs the **real** riplex dataclasses (`DiscInfo`, `MetadataSearchResult`, `PlannedDisc`, …). |
| `provider_mocks.py` | Installs scenario-driven fakes for makemkv, TMDb, dvdcompare, config, and network in one call. |
| `driver.py` | `WizardDriver` — `click(label)`, `has_text(...)`, `current`, `state`, `crashed()`. |

The `gui` pytest fixture (in `tests/conftest.py`) wires it all together:

```python
def test_movie_flow(gui):
    d = gui("the-matrix-1999")        # load a scenario, mock everything
    d.click("Rip Disc")               # welcome -> disc detection -> metadata
    d.click("Next")                   # accept the TMDb match
    assert d.current == "disc_overview"
    assert not d.crashed()
```

Failure injection to prove the net works: adding a `raise` to any screen's
`build()` fails both the relevant flow test and the screen-build smoke matrix.

### What is covered

- **Screen-build smoke matrix** (`test_screen_build_smoke.py`) — builds *every*
  screen with a fully-populated state for one representative scenario per media
  type (plus a no-dvdcompare edge case).
- **Media-type flow tests** (`test_flow_media_types.py`) — drive *every* fixture
  of a given media type through the core orchestrate path, so the whole fixture
  corpus is exercised through the real screens.
- **Named flow tests** — movie orchestrate, TV multi-disc, organize,
  resume/prefill fast paths, and error paths (makemkv unavailable, TMDb
  empty/raises, dvdcompare failure, rip failure).
- **Fixture integrity** — every committed scenario reconstructs into real
  dataclasses and carries a valid media-type category.

### Targeting media types

Each scenario is classified into one media-type **category** so a test can run
against exactly the fixtures it applies to — and automatically pick up new
fixtures of that type as they're generated:

| Category | Meaning |
| -------- | ------- |
| `movie` | A theatrical / feature film release. |
| `tv_miniseries` | A limited, self-contained series (e.g. Chernobyl). |
| `tv_series` | An ongoing multi-season show — a single-season rip *or* a complete-series set. |

A single season of an ongoing show (e.g. a `Season 01` folder) is **series
content**, so it classifies as `tv_series` and flows through the series tests.
"Seasonal series" isn't a separate category; use `season_scenarios()` to target
just the single-season rips.

The category is inferred from the archive folder name, dvdcompare release name,
and TMDb season structure; a scenario can also pin it with a top-level
`"category"` key. `tests/support/fixtures.py` exposes filter helpers that return
the matching scenario names for parametrization:

```python
from tests.support.fixtures import movie_scenarios, series_scenarios, season_scenarios

@pytest.mark.parametrize("name", series_scenarios())   # every TV series fixture
def test_series_flow(gui, name):
    d = gui(name)
    ...

@pytest.mark.parametrize("name", season_scenarios())   # just single-season rips
def test_seasonal_flow(gui, name):
    ...
```

Adding a new fixture of a category makes it flow through that category's tests
on the next run — no test edits required.

## Test fixtures from archived rips

Integration scenarios live as committed JSON under
`tests/fixtures/gui/scenarios/`. They share one schema between hand-authored
edge cases and scenarios generated from real archived rips. The loader reads
only the committed JSON, so the test suite never needs the archive and CI stays
hermetic.

### Generating scenarios

Archived rips carry everything a scenario needs — the disc titles makemkv
reported, the confirmed TMDb match, and the dvdcompare release breakdown — in
their debug artifacts:

- `<Title (Year)>/_riplex/riplex-rip.snapshot.json` — disc titles, TMDb match,
  dvdcompare disc breakdown.
- `<Title (Year)>/Disc N/_rip_manifest.json` — richer per-title stream info plus
  the exact dvdcompare release name, disc format, and volume label (when
  present).

`scripts/gen_gui_fixtures.py` walks an archive root, normalizes each title
folder into a scenario JSON, and writes it under `tests/fixtures/gui/scenarios/`:

```
# List archived folders (a * marks ones with a usable snapshot)
python scripts/gen_gui_fixtures.py --list

# Generate all scenarios
python scripts/gen_gui_fixtures.py

# Generate just one, from a custom archive path
python scripts/gen_gui_fixtures.py --only "Chernobyl (2019)" \
    --archive "/path/to/_archive"
```

Missing pieces (a TMDb id, per-episode lists on older snapshots, TMDb season
structure) are synthesized deterministically and listed under a `synthesized`
key in the output so consumers know which blocks are inferred rather than
observed. Each generated scenario also carries a `category` (see
[Targeting media types](#targeting-media-types)), which you can override by
hand-editing the field.

Re-run the generator and commit the resulting JSON whenever you want to refresh
or add real-world scenarios. The archive itself is never required to run the
tests.
