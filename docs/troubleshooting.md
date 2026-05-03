# Troubleshooting

Common issues and solutions reported by users.

---

## "makemkvcon not on PATH"

**Symptom:** `riplex setup` warns that `makemkvcon` is not found, even though MakeMKV is installed.

**Cause:** On Linux, installing MakeMKV via Flatpak does not include `makemkvcon` (the command-line tool). The Flatpak only packages the GUI.

**Solution:** Install MakeMKV from source using the instructions on the [MakeMKV website](https://www.makemkv.com/forum/viewtopic.php?f=3&t=224). This installs both the GUI and `makemkvcon`.

---

## "Error reading disc" / drive not detected

**Symptom:** `riplex orchestrate` or `riplex rip` can't find your optical drive, or reports "no disc found in any drive."

**Possible causes:**

1. **MakeMKV itself can't see the drive.** Run `makemkvcon info disc:-1` to check. If MakeMKV doesn't list your drive, the problem is at the OS/driver level, not riplex.

2. **MakeMKV not installed correctly (Linux).** If you see an error like `libmakemkv.so.1: cannot open shared object file`, MakeMKV's libraries aren't linked properly. Reinstalling MakeMKV from source usually fixes this.

3. **External drive not recognized.** Try specifying the drive manually:
   ```
   riplex orchestrate --drive /dev/sr0    # Linux
   riplex orchestrate --drive D:          # Windows
   riplex rip --drive 1                   # by index
   ```

**Solution:** Verify MakeMKV works first (open the GUI or run `makemkvcon info disc:-1`). If it doesn't see the drive, reinstall MakeMKV. If MakeMKV works but riplex doesn't, use the `--drive` flag to specify the drive manually.

---

## Invalid config file (TOML parse error)

**Symptom:** Running any riplex command crashes with a `TOMLDecodeError` traceback mentioning your config file.

**Cause:** The config file has a syntax error, possibly from hand-editing or a corrupted write.

**Solution:** Re-run setup with the `--force` flag to delete the bad config and start fresh:

```
riplex setup --force
```

---

## Getting a TMDb API key

**Symptom:** You're not sure what to enter on the TMDb API key request form because you're not a business or app developer.

**Solution:** TMDb asks for an app name and URL when you request a key. You can enter "riplex" as the app name and `https://github.com/AnyCredit5518/riplex` as the URL. The rest of the form can be filled with basic info - it doesn't need to be a real business. The key is approved instantly.

Sign up and request a key at: https://www.themoviedb.org/settings/api

---

## "dvdcompare lookup failed" / disc not on dvdcompare

**Symptom:** `riplex orchestrate` or `riplex organize` exits with an error about dvdcompare failing to find your disc.

**Cause:** Not every disc release is listed on dvdcompare.net. Niche or region-specific releases may not have entries.

**Workaround:** Use `riplex rip` instead, which handles missing dvdcompare data gracefully by falling back to TMDb runtime matching:

```
riplex rip "Movie Title"
riplex rip "Movie Title" --execute
```

You'll still get duplicate filtering, 4K preference, play-all detection, and TMDb runtime matching. The only thing you lose is automatic title matching and naming, so you'll need to rename and move the file into your Plex library manually after ripping.

> [!NOTE]
> A fix to make `orchestrate` and `organize` handle missing dvdcompare data gracefully is planned.
