# Planning

The `plan` command looks up a title on TMDb and outputs the Plex-canonical folder structure and filenames. It does not touch any files on disk.

## Basic lookup

```bash
plex-planner plan "Oppenheimer" --year 2023
```

Output:

```
type: movie
canonical_title: Oppenheimer
year: 2023
runtime: 3h 1m

relative_paths:
  \Movies\Oppenheimer (2023)\
  \Movies\Oppenheimer (2023)\Featurettes\
  \Movies\Oppenheimer (2023)\Interviews\
  \Movies\Oppenheimer (2023)\Behind The Scenes\
  \Movies\Oppenheimer (2023)\Deleted Scenes\
  \Movies\Oppenheimer (2023)\Trailers\
  \Movies\Oppenheimer (2023)\Other\

main_file:
  Oppenheimer (2023).mkv
```

## TV show

```bash
plex-planner plan "A Perfect Planet" --year 2021
```

Output:

```
type: tv
canonical_title: A Perfect Planet
year: 2021

relative_paths:
  \TV Shows\A Perfect Planet (2021)\Season 00\
  \TV Shows\A Perfect Planet (2021)\Season 01\

items:
  s00e01 - Making a Perfect Planet - 44m
    file: A Perfect Planet (2021) - s00e01 - Making a Perfect Planet.mkv
  s01e01 - Volcano - 48m
    file: A Perfect Planet (2021) - s01e01 - Volcano.mkv
  ...
```

## JSON output

```bash
plex-planner plan "Top Gun Maverick" --year 2022 --json
```

## Force media type

```bash
plex-planner plan "Planet Earth III" --year 2023 --type tv
```

## Exclude specials or extras

```bash
plex-planner plan "X-Men The Animated Series" --year 1992 --no-specials
plex-planner plan "Oppenheimer" --year 2023 --no-extras
```

## Match ripped files by runtime

```bash
plex-planner plan "A Perfect Planet" --year 2021 \
  --match title_t00.mkv:48m12s title_t01.mkv:47m58s title_t02.mkv:44m03s
```

This produces a match report comparing each ripped file's duration against the planned episode runtimes, with confidence levels (high/medium/low).

## Options

| Option | Description |
|---|---|
| `title` | Movie or TV show title (required) |
| `--year` | Release year (strongly recommended) |
| `--type` | Force `movie`, `tv`, or `auto` (default: `auto`) |
| `--json` | Output as JSON |
| `--no-specials` | Exclude Season 00 specials |
| `--no-extras` | Omit extras folder skeleton |
| `--match` | Match ripped files by duration (format: `file:duration`) |
| `--api-key` | TMDb API key |
