# Plex Naming Rules

This page defines the naming and output rules riplex follows when generating Plex-compatible folder structures and filenames. It is a formatting reference, not the metadata source of truth.

## Top-level library separation

Keep major media types separated:

- `\Movies\`
- `\TV Shows\`
- `\Music\`

Do not mix movies and TV content in the same main folder.

## Movies

Preferred structure:

```
\Movies\Movie Name (Year)\
\Movies\Movie Name (Year)\Movie Name (Year).ext
```

Examples:

```
\Movies\Movie Name (2024)\Movie Name (2024).mkv
\Movies\Another Movie (2023)\Another Movie (2023).mkv
```

### Optional movie extras folders

Use these when outputting extras skeletons:

- `Behind The Scenes`
- `Deleted Scenes`
- `Featurettes`
- `Interviews`
- `Scenes`
- `Shorts`
- `Trailers`
- `Other`

Example:

```
\Movies\Movie Name (2024)\Featurettes\
\Movies\Movie Name (2024)\Interviews\
```

### Optional movie editions

When needed, editions may be represented as:

```
Movie Name (Year) {edition-Edition Name}
```

Example:

```
Movie Name (2024) {edition-Director's Cut}.mkv
```

## TV shows

Preferred structure:

```
\TV Shows\Show Name (Year)\Season XX\
\TV Shows\Show Name (Year)\Season XX\Show Name (Year) - sXXeYY - Episode Title.ext
```

Examples:

```
\TV Shows\Show Name (2024)\Season 01\Show Name (2024) - s01e01 - Episode One.mkv
\TV Shows\Another Show (2023)\Season 01\Another Show (2023) - s01e03 - Episode Three.mkv
```

## TV specials

Specials belong in Season 00:

```
\TV Shows\Show Name (Year)\Season 00\
\TV Shows\Show Name (Year)\Season 00\Show Name (Year) - s00e01 - Episode Title.mkv
```

## TV extras

Plex supports extras for TV shows at two levels.

### Show-level extras

Place in subdirectories of the show folder:

```
\TV Shows\Show Name (Year)\Featurettes\Special Effects.mkv
\TV Shows\Show Name (Year)\Trailers\Trailer 1.mkv
```

### Season-level extras

Place in subdirectories inside the season folder:

```
\TV Shows\Show Name (Year)\Season 01\Behind The Scenes\A look at season 1.mkv
\TV Shows\Show Name (Year)\Season 01\Deleted Scenes\Season 1 Deleted Scenes.mkv
```

### Supported extras folder names

These apply to both movies and TV shows:

- `Behind The Scenes`
- `Deleted Scenes`
- `Featurettes`
- `Interviews`
- `Scenes`
- `Shorts`
- `Trailers`
- `Other`

### Extras vs specials

If a special appears in TMDb as a Season 00 episode, prefer naming it as an episode in `Season 00/` so Plex can match it automatically. If a special does not appear in TMDb (e.g. DVD bonus, gag reel), place it as an extra in the appropriate subfolder.

### Chapter splitting for "play all" compilations

Some discs include a single file with multiple specials concatenated (e.g. a "play all" featurette containing all behind-the-scenes episodes). These files have internal MKV chapters, one per episode.

When the number of chapters in such a file matches the number of Season 00 episodes from TMDb, the tool splits the file by chapters (using mkvmerge) and names each piece as an individual Season 00 episode:

```
\TV Shows\Show Name (Year)\Season 00\Show Name (Year) - s00e01 - Episode Title.mkv
\TV Shows\Show Name (Year)\Season 00\Show Name (Year) - s00e02 - Episode Title.mkv
```

This ensures each special appears separately in Plex with correct metadata, rather than as a single combined file that always plays from the beginning.

Source: <https://support.plex.tv/articles/local-files-for-tv-show-trailers-and-extras/>

## Windows filename safety

Output names must be Windows-safe:

- Remove `:`
- Remove or replace other illegal Windows filename characters
- Preserve readability

Examples:

- `Movie Name: Extended Cut` becomes `Movie Name Extended Cut`
- `Example Show: The Series` becomes `Example Show The Series`

## General output rules

- Prefer title + year canonical naming
- Prefer relative paths, not absolute drive paths
- Include runtimes in output items when available
- For TV, include specials and episode numbering
- Do not use disc packaging terms like `Disc 1` or `Volume 2` in final Plex paths (they are only temporary/staging labels)
