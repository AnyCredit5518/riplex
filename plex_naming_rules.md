# Plex Naming Rules Reference

This file defines the naming/output rules our tool should follow when generating
suggested folder structures and file names.

It is a formatting reference, not the metadata source of truth.

## Top-Level Library Separation

Keep major media types separated:

- `\Movies\`
- `\TV Shows\`
- `\Music\`

Do not mix movies and TV content in the same main folder.

## Movies

Preferred structure:

\Movies\Movie Name (Year)\
\Movies\Movie Name (Year)\Movie Name (Year).ext

Examples:

\Movies\Oppenheimer (2023)\Oppenheimer (2023).mkv
\Movies\Top Gun (1986)\Top Gun (1986).mkv

### Optional Movie Extras Folders

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

\Movies\Top Gun Maverick (2022)\Featurettes\
\Movies\Top Gun Maverick (2022)\Interviews\

### Optional Movie Editions

When needed, editions may be represented as:

Movie Name (Year) {edition-Edition Name}

Example:

Blade Runner (1982) {edition-Director's Cut}.mkv

## TV Shows

Preferred structure:

\TV Shows\Show Name (Year)\Season XX\
\TV Shows\Show Name (Year)\Season XX\Show Name (Year) - sXXeYY - Episode Title.ext

Examples:

\TV Shows\A Perfect Planet (2021)\Season 01\A Perfect Planet (2021) - s01e01 - Volcano.mkv
\TV Shows\Planet Earth III (2023)\Season 01\Planet Earth III (2023) - s01e03 - Deserts and Grasslands.mkv

## TV Specials

Specials belong in:

\TV Shows\Show Name (Year)\Season 00\

Example:

\TV Shows\A Perfect Planet (2021)\Season 00\A Perfect Planet (2021) - s00e01 - Making a Perfect Planet.mkv

## TV Extras

Plex supports extras for TV shows at two levels:

### Show-level extras

Place in subdirectories of the show folder:

\TV Shows\Show Name (Year)\Featurettes\Special Effects.mkv
\TV Shows\Show Name (Year)\Trailers\Trailer 1.mkv

### Season-level extras

Place in subdirectories inside the season folder:

\TV Shows\Show Name (Year)\Season 01\Behind The Scenes\A look at season 1.mkv
\TV Shows\Show Name (Year)\Season 01\Deleted Scenes\Season 1 Deleted Scenes.mkv

### Supported extras folder names (same for movies and TV)

- `Behind The Scenes`
- `Deleted Scenes`
- `Featurettes`
- `Interviews`
- `Scenes`
- `Shorts`
- `Trailers`
- `Other`

### Extras vs specials

If a special appears in TMDb as a Season 00 episode, prefer naming it as an
episode in `Season 00/` so Plex can match it automatically. If a special does
not appear in TMDb (e.g. DVD bonus, gag reel), place it as an extra in the
appropriate subfolder.

### Chapter splitting for "play all" compilations

Some discs include a single file with multiple specials concatenated (e.g. a
"play all" featurette containing all behind-the-scenes episodes). These files
have internal MKV chapters, one per episode.

When the number of chapters in such a file matches the number of Season 00
episodes from TMDb, the tool splits the file by chapters (using mkvmerge) and
names each piece as an individual Season 00 episode:

\TV Shows\Show Name (Year)\Season 00\Show Name (Year) - s00e01 - Episode Title.mkv
\TV Shows\Show Name (Year)\Season 00\Show Name (Year) - s00e02 - Episode Title.mkv

This ensures each special appears separately in Plex with correct metadata,
rather than as a single combined file that always plays from the beginning.

Source: https://support.plex.tv/articles/local-files-for-tv-show-trailers-and-extras/

## Windows Filename Safety

Output names must be Windows-safe.

At minimum:
- remove `:`
- remove or replace other illegal Windows filename characters
- preserve readability

Examples:

- `Top Gun: Maverick` -> `Top Gun Maverick`
- `X-Men: The Animated Series` -> `X-Men The Animated Series`

## General Output Rules

- Prefer title + year canonical naming
- Prefer relative paths, not absolute drive paths
- Include runtimes in output items when available
- For TV, include specials and episode numbering
- Do not use disc packaging terms like `Disc 1` or `Volume 2` in final Plex paths unless they are only temporary/staging labels