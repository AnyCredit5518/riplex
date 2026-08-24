# Potential Feature: Production-Code OCR

**Status:** Researched, not implemented.

## Summary

Some television productions burn an episode's production code into the end
copyright slate. Optical-disc titles with ambiguous runtimes could therefore
be sampled near the end, passed through OCR, and compared with production
codes from episode metadata.

This can be useful as an optional, post-rip identity check for compatible
shows. It is not a universal episode-identification system:

- Many shows and home-video masters do not display a production code.
- A production code identifies an episode only within its production or
  series. Studios choose their own formats, so a short code is not globally
  unique.
- Alternate edits of the same episode normally share an identity and may
  share the same production code. OCR cannot distinguish a standard cut from
  a director's cut.
- TMDb and TheTVDB store production codes on episode records, but neither
  exposes a reliable global production-code search.

The safe model is therefore: fetch the known episodes for the selected show
and season first, then treat OCR as corroborating evidence only when it
uniquely matches one of those candidates.

## Why We Investigated It

An investigated television disc contained two episode-length titles that
runtime and sequence alone could not identify safely. Direct frame inspection
showed that both were alternate edits of the same episode rather than two
consecutive episodes. The longer title was an extended-cut candidate.

The selected metadata provider recorded short numeric production codes for the
season. If the same candidate code had appeared in both title endings, it could
have corroborated their shared episode identity. It still would not have
identified which title was the extended cut.

To keep this public investigation release-agnostic, it intentionally omits the
show name, episode titles and numbers, provider identifiers, disc labels, and
production-code values from the source media.

## Investigation Results

### Production codes are real but show-local

Production codes are alphanumeric episode designations assigned by a studio
or production. Their formats vary by studio, and some formats are burned into
the end copyright slate. They can also reveal production order when it differs
from broadcast order.

They are not universal identifiers. A short numeric value can be reused by
unrelated productions. A code without the selected series context is
insufficient evidence for an episode assignment.

### Metadata providers expose values, not a global resolver

- TMDb episode details include `production_code`.
- TheTVDB episode records include `productionCode`.
- TheTVDB search covers series, movies, people, and companies; its remote-id
  search is for identifiers such as IMDb or EIDR, not production codes.
- Wikidata defines production-code property `P2364`, but coverage is optional
  and should not be treated as authoritative or complete.

The useful lookup operation is local: enumerate the chosen season's episodes
from a provider and build a mapping from production code to candidate episode.

### The investigated disc did not provide usable end-slate codes

The final minute and final seconds of the two ambiguous titles were sampled,
along with several known episodes from the same season. Native-resolution
frames showed credits, copyright/legal text, union marks, and
production-company logos, but no visible episode production code.

Production-code OCR would therefore not resolve the disc layout that prompted
this investigation. This is a useful negative fixture for any future
prototype: a no-code ending must return "no evidence," not force the closest
numeric OCR result.

### The first version must run after a title is ripped

`makemkvcon` supports saving a complete title as MKV or backing up a disc. It
does not offer a simple start/end range for ripping only the final seconds of a
title. Direct FFmpeg access to encrypted optical media also cannot be assumed.

An initial implementation should operate on already-ripped MKV files. Sampling
an end slate directly from an encrypted disc would be a separate MakeMKV
streaming/decryption investigation.

### OCR should remain optional

riplex does not currently depend on an OCR engine. Tesseract-based tooling is
smaller but requires an external executable; ML OCR packages add substantial
runtime and dependency weight. OCR should therefore be an optional adapter,
not a required install or part of the default classification path.

## Proposed MVP

### Inputs

- An already-ripped MKV file.
- The selected show and season.
- Candidate episodes with production codes fetched from TMDb, TheTVDB, or a
  future metadata source.
- FFmpeg plus an optional configured OCR backend.

### Processing

1. Use ffprobe to determine the title duration.
2. Sample the last 30 to 90 seconds. Start sparsely, then sample promising
   static text slates at 3 to 4 frames per second.
3. Crop, upscale, grayscale, and threshold likely text regions before OCR.
4. Run OCR on multiple adjacent frames and retain the text and frame timestamp
   as evidence.
5. Normalize only harmless formatting differences such as case, whitespace,
   and punctuation.
6. Compare OCR tokens with the already-fetched candidate production codes.
7. Return a match only when one candidate is supported uniquely across
   multiple frames. Ambiguous character substitutions such as `O`/`0` or
   `I`/`1` should require review, especially for short codes.

Short numeric codes make broad fuzzy matching unsafe. A one-character OCR
error in a four-character code can point at a different episode, so fuzzy
similarity alone must never create an automatic assignment.

### Shared result

The business logic should live under `src/riplex/` and return a dataclass that
both the CLI and GUI can render. A result should include:

- matched production code and candidate episode, if any;
- confidence and decision reason;
- OCR text from each supporting frame;
- frame timestamps or saved evidence-frame paths;
- explicit outcomes for no code, conflicting codes, and ambiguous matches.

The first integration should be a diagnostic or organize-time review tool.
Only after it is proven against several releases should classification consume
a unique exact match as a second signal alongside runtime, disc position, and
dvdcompare metadata.

## Safety Rules

- Never search or assign by production code without a known series context.
- Never infer a match when the candidate season has duplicate or missing
  production codes.
- Never turn "no readable code" into a low-confidence assignment.
- Preserve evidence so a user can inspect what OCR actually read.
- Surface disagreement with stronger disc metadata for review rather than
  silently overriding it.
- Do not use a production-code match to choose between alternate cuts of the
  same episode.

## Validation Needed Before Integration

A future prototype should be tested with committed, rights-safe image fixtures
covering:

- a clearly displayed alphanumeric code that uniquely matches an episode;
- a numeric code with common OCR confusions;
- an ending that contains no production code;
- a season with duplicate or missing metadata codes;
- an end slate removed or changed on the home-video master;
- two alternate cuts sharing the same episode code;
- conflicting OCR results across adjacent frames.

The feature should remain opt-in until its false-positive rate is measured on
multiple studios, formats, and home-video releases.

## Revisit When

- Ambiguous episode layouts recur for shows known to display production codes.
- TMDb or TheTVDB production-code coverage proves consistent for those shows.
- A lightweight OCR backend can be supported without burdening the default
  installation.
- We have several legal test fixtures from different studios and enough
  examples to set conservative confidence thresholds.
- MakeMKV exposes a supported way to sample a title without first saving the
  complete MKV, or post-rip identification becomes a regular workflow need.

## References

- [Feature request discussion #14](https://github.com/AnyCredit5518/riplex/discussions/14)
- [Production code number background](https://en.wikipedia.org/wiki/Production_code_number)
- [Wikidata production-code property P2364](https://www.wikidata.org/wiki/Property:P2364)
- [TMDb TV episode details API](https://developer.themoviedb.org/reference/tv-episode-details)
- [TheTVDB API documentation](https://thetvdb.github.io/v4-api/)
