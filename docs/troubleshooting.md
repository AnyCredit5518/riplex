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

## GUI: disc not being detected

**Symptom:** `riplex-ui` shows "No disc found" or sits on the disc detection screen even though a disc is inserted.

**What the GUI does:**

* On the **Disc Detection** screen, riplex now lists every optical drive your system reports, with a per-drive status badge (`Empty`, `Tray open`, `Disc loaded`, etc.).
* The list refreshes automatically every few seconds — inserting or ejecting a disc updates the screen without manual refresh. Click the circular ↻ button at the top right to force an immediate rescan.
* If exactly one drive has a loaded disc, riplex starts reading it automatically. With multiple drives or zero loaded drives, click `Read disc` next to the drive you want to use.

**If your drive is missing entirely:**

1. Confirm MakeMKV sees the drive. Open the MakeMKV GUI or run `makemkvcon -r info list` and look for a `DRV:` line with your device path.
2. If MakeMKV does not list it, the issue is at the OS/driver level — riplex only displays what MakeMKV reports.
3. Check the `makemkvcon: …` line at the top of the screen. If it shows `unavailable`, click the bundled "Download MakeMKV" link or follow the [installation guide](getting-started/installation.md).
4. Use the `Open bug report` button on the error panel — it pre-fills the GitHub issue with the captured MakeMKV diagnostics (executable path, version, last error) and points you at the log directory to attach.

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

---

## macOS: "Browse" button does nothing (tkinter not installed)

**Symptom:** In the GUI, clicking the folder browse button does nothing or shows a hint to type the path manually.

**Cause:** The browse dialog requires `tkinter`, which Homebrew Python does not include by default.

**Solution:** Install the tkinter package for your Python version:

```
brew install python-tk@3.12
```

Then relaunch `riplex-ui`.

---

## macOS: SSL error when launching the GUI for the first time

**Symptom:** The app crashes or shows an SSL certificate error on first launch. This typically happens with Homebrew-installed Python.

**Cause:** Flet downloads its desktop runtime on first launch. Homebrew Python doesn't include system SSL certificates, so the download fails.

**Solution:** Set the SSL certificate path in your venv activate script (one-time fix):

```
CERT=$(python3.12 -c "import certifi; print(certifi.where())")
echo "export SSL_CERT_FILE=\"$CERT\"" >> .venv/bin/activate
echo "export REQUESTS_CA_BUNDLE=\"$CERT\"" >> .venv/bin/activate
source .venv/bin/activate
```

Then relaunch `riplex-ui`.

---

## macOS: "app is damaged" / Gatekeeper blocks the app

**Symptom:** macOS says the app "is damaged and can't be opened" or "cannot be opened because the developer cannot be verified."

**Cause:** macOS quarantines apps downloaded from the internet that aren't signed with an Apple Developer certificate.

**Solution:** Right-click (or Control-click) on `riplex-ui.app`, choose **Open**, then click **Open** in the dialog. macOS remembers this choice and won't ask again.

If that doesn't work, remove the quarantine flag manually:

```
xattr -dr com.apple.quarantine /Applications/riplex-ui.app
```

---

## macOS: tools not found despite being installed

**Symptom:** `riplex setup` reports that `ffprobe`, `mkvmerge`, or `makemkvcon` are missing, even though MakeMKV or MKVToolNix is installed.

**Cause:** macOS `.app` bundles install their binaries inside the app package, not on your PATH. Homebrew installs to `/opt/homebrew/bin/` (Apple Silicon) or `/usr/local/bin/` (Intel), which may not be on your PATH in all contexts.

**Solution:** riplex automatically checks these locations, so this should resolve itself as of v0.4.0. If tools are still not found, verify they exist:

```
# MakeMKV
ls /Applications/MakeMKV.app/Contents/MacOS/makemkvcon

# MKVToolNix
ls /Applications/MKVToolNix.app/Contents/MacOS/mkvmerge

# ffprobe (Homebrew)
ls /opt/homebrew/bin/ffprobe    # Apple Silicon
ls /usr/local/bin/ffprobe       # Intel
ls ~/.riplex/bin/ffprobe        # auto-downloaded
```

If the tool exists but riplex can't find it, you can add it to your PATH manually in your shell profile (`~/.zshrc`).
