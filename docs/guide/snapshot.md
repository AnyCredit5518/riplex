# Snapshots

The `snapshot` command captures a metadata snapshot of a MakeMKV rip folder to a JSON file. This records every file's duration, size, streams, chapters, resolution, title tag, and perceptual hash without including any actual video data.

## Capture a snapshot

```bash
plex-planner snapshot E:\Media\_MakeMKV\Oppenheimer
```

By default, the snapshot is written to `Oppenheimer.snapshot.json` in the current directory.

## Custom output path

```bash
plex-planner snapshot E:\Media\_MakeMKV\Oppenheimer -o snapshots/oppenheimer.json
```

## Replay with organize

Snapshots can be replayed through the organize workflow for offline testing and debugging:

```bash
plex-planner organize E:\Media\_MakeMKV\Oppenheimer --snapshot Oppenheimer.snapshot.json
```

Snapshot replays are always dry-run, regardless of the `--execute` flag.

## Use cases

- **Sharing disc layouts**: Send a snapshot to someone for debugging without sharing video files
- **Offline testing**: Run the organize workflow against captured metadata without needing the original files
- **Documentation**: Record what was on a disc before organizing it
- **Regression testing**: The test suite uses snapshots to validate organize behavior deterministically

## Options

| Option | Description |
|---|---|
| `folder` | Path to a MakeMKV rip folder (required) |
| `-o`, `--output` | Output file path (default: `<folder>.snapshot.json` in current directory) |
