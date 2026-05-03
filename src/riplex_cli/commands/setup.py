"""riplex setup command — interactive config wizard."""

from __future__ import annotations

from riplex.config import load_config, save_config, _config_write_path


def _offer_install(missing: list[str]) -> None:
    """Offer to install missing tools via the system package manager."""
    import platform
    import subprocess

    system = platform.system()
    packages: dict[str, dict[str, str]] = {
        "Windows": {"makemkvcon": "GuinpinSoft.MakeMKV", "ffprobe": "Gyan.FFmpeg", "mkvmerge": "MoritzBunkus.MKVToolNix", "mkvpropedit": "MoritzBunkus.MKVToolNix"},
        "Darwin": {"makemkvcon": "makemkv", "ffprobe": "ffmpeg", "mkvmerge": "mkvtoolnix", "mkvpropedit": "mkvtoolnix"},
        "Linux": {"makemkvcon": "", "ffprobe": "ffmpeg", "mkvmerge": "mkvtoolnix", "mkvpropedit": "mkvtoolnix"},
    }

    if system not in packages:
        return

    pkg_map = packages[system]
    to_install = sorted(set(pkg_map[t] for t in missing if pkg_map.get(t)))
    if not to_install:
        return

    if system == "Windows":
        cmd_name = "winget"
        cmds = [["winget", "install", "--accept-source-agreements", "--accept-package-agreements", pkg] for pkg in to_install]
    elif system == "Darwin":
        cmd_name = "brew"
        cmds = [["brew", "install"] + to_install]
    else:
        cmd_name = "apt"
        cmds = [["sudo", "apt", "install", "-y"] + to_install]

    print(f"\n  Install via {cmd_name}?")
    for cmd in cmds:
        print(f"    {' '.join(cmd)}")
    answer = input("\n  Proceed? [Y/n]: ").strip().lower()
    if answer and answer != "y":
        return

    for cmd in cmds:
        print(f"\n  Running: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"  Failed: {exc}")
            return

    print("\n  Installation complete. You may need to restart your terminal for PATH changes to take effect.")


def run_setup(force: bool = False) -> int:
    """Interactive setup wizard to create or update the riplex config file."""
    import shutil

    config_path = _config_write_path()

    print("riplex setup")
    print(f"Config file: {config_path}\n")

    if force and config_path.is_file():
        config_path.unlink()
        print("(Existing config deleted. Starting fresh.)\n")
        existing: dict[str, str] = {}
    else:
        existing = load_config()
        if existing:
            print("(Existing config found. Press Enter to keep current values.)\n")

    def prompt(key: str, label: str, hint: str = "", mask: bool = False) -> str:
        current = existing.get(key, "")
        display = (current[:4] + "...") if mask and current else current
        suffix = f" [{display}]" if current else ""
        prompt_hint = f" ({hint})" if hint else ""
        value = input(f"{label}{prompt_hint}{suffix}: ").strip()
        return value if value else current

    tmdb_key = prompt("tmdb_api_key", "TMDb API key", "free at themoviedb.org/settings/api", mask=True)
    output_root = prompt("output_root", "Plex library root", "e.g. E:/Media")
    rip_output = prompt("rip_output", "MakeMKV rip output folder", "e.g. E:/Media/Rips")
    archive_root = prompt("archive_root", "Archive root (optional)", "move raw rips here after organizing")

    # Verify makemkvcon, ffprobe, mkvmerge are available
    print()
    tools = {"makemkvcon": None, "ffprobe": None, "mkvmerge": None, "mkvpropedit": None}
    for tool in tools:
        path = shutil.which(tool)
        tools[tool] = path
        status = f"found: {path}" if path else "NOT FOUND"
        print(f"  {tool}: {status}")

    missing = [t for t, p in tools.items() if p is None]
    if missing:
        print(f"\n  Warning: {', '.join(missing)} not on PATH. Some commands will not work.")
        _offer_install(missing)

    # Write config
    print()
    config_path = save_config(
        tmdb_api_key=tmdb_key,
        output_root=output_root,
        rip_output=rip_output,
        archive_root=archive_root,
    )
    print(f"Config written to {config_path}")
    return 0
