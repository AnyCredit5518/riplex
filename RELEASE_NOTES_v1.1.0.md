# riplex v1.1.0

This release adds alternate TV disc layout detection, making multi-disc season
sets resilient when the physical discs do not divide episodes where the
metadata listing says they do.

## Alternate TV disc layout detection

riplex now recognizes when an episode physically appears on the disc before or
after the one assigned by dvdcompare metadata. Instead of shifting every later
episode or silently assigning the wrong title, it:

- borrows episode identity from the adjacent metadata disc when the physical
  title sequence and runtime evidence support it;
- carries unresolved episode identities forward to the next physical disc;
- persists that carryover in rip manifests so stopping and resuming does not
  lose the corrected sequence;
- marks affected titles as **REVIEW** and names the metadata disc they were
  expected on in both the GUI and CLI; and
- keeps the rip and organize stages aligned through the manifest's canonical
  episode identities.

![Alternate disc layout detection on the Select Titles screen](https://raw.githubusercontent.com/AnyCredit5518/riplex/main/screenshots/v1.1.0_Alternate_Layout_Detection.png)

## Episode matching reliability

- Explicitly named episode variants, including extended and director's cuts,
  are reserved for the closest matching physical title before sequential
  episode assignment.
- Next-disc overflow uses the release's own runtime evidence and no longer
  invents a match from a conflicting canonical runtime.
- Alternate-layout warnings now point in the correct direction and retain
  unmatched episode identities for the following disc.

## Other changes

- Fixed DVDCompare request throttling when lookups cross multiple asyncio event
  loops.
- Added an anonymized investigation into production-code OCR as a possible
  future episode-identification fallback.

The auto-generated section below lists every commit included since v1.0.4.
