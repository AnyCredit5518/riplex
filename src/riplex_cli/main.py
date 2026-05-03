"""CLI entry point for riplex.

This module contains the argument parser, command dispatch, and the
``main()`` entry point.  All command implementations live in the
``riplex_cli.commands`` sub-package.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from riplex import __version__
from riplex.config import load_config
from riplex.ui import set_auto_mode

from riplex_cli.commands.lookup import run_lookup
from riplex_cli.commands.orchestrate import run_orchestrate
from riplex_cli.commands.organize import run_organize
from riplex_cli.commands.rip import run_rip
from riplex_cli.commands.setup import run_setup


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="riplex",
        description=(
            "Rip physical discs and organize MKV files into "
            "Plex-compatible folder structures."
        ),
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}",
    )
    subs = parser.add_subparsers(dest="command")

    # --- organize ---
    org_parser = subs.add_parser(
        "organize",
        help="Scan a MakeMKV rip folder and organize into Plex structure.",
    )
    org_parser.add_argument("folder", help="Path to a MakeMKV rip folder.")
    org_parser.add_argument("--title", help="Override title (default: folder name).")
    org_parser.add_argument("--year", type=int, help="Release year.")
    org_parser.add_argument(
        "--type",
        dest="media_type",
        choices=["movie", "tv", "auto"],
        default="auto",
        help="Force media type. Default: auto-detect.",
    )
    org_parser.add_argument(
        "--format",
        dest="disc_format",
        default=None,
        help="Disc format filter for dvdcompare (e.g. 'Blu-ray 4K').",
    )
    org_parser.add_argument(
        "--release",
        default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    org_parser.add_argument(
        "--output",
        default=None,
        help="Output root directory (or set PLEX_ROOT env var, or output_root in config).",
    )
    org_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually move files (default: dry-run preview only).",
    )
    org_parser.add_argument("--json", action="store_true", default=False)
    org_parser.add_argument("--api-key", default=None)
    org_parser.add_argument(
        "--unmatched",
        choices=["ignore", "move", "delete", "extras"],
        default="ignore",
        help="Policy for files that can't be matched: ignore (default), move to _Unmatched folder, delete, or extras (route to Other/ folder).",
    )
    org_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print debug logging to stderr in addition to the log file.",
    )
    org_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass the local cache and fetch fresh data from APIs.",
    )
    org_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Re-organize files even if they are already tagged as organized.",
    )
    org_parser.add_argument(
        "--snapshot",
        default=None,
        help="Load a snapshot JSON file instead of scanning a real folder. Forces dry-run mode.",
    )
    org_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )

    # --- lookup ---
    guide_parser = subs.add_parser(
        "lookup",
        help="Look up disc contents and metadata for a title from TMDb and dvdcompare.",
    )
    guide_parser.add_argument("title", help="Movie or TV show title.")
    guide_parser.add_argument("--year", type=int, help="Release year.")
    guide_parser.add_argument(
        "--type",
        dest="media_type",
        choices=["movie", "tv", "auto"],
        default="auto",
        help="Force media type. Default: auto-detect.",
    )
    guide_parser.add_argument(
        "--format",
        dest="disc_format",
        default=None,
        help="Disc format filter for dvdcompare (e.g. 'Blu-ray 4K').",
    )
    guide_parser.add_argument(
        "--release",
        default="america",
        help="Regional release: 1-based index or name keyword (default: america).",
    )
    guide_parser.add_argument(
        "--output",
        default=None,
        help="Output root for --create-folders (or set PLEX_ROOT env var, or config).",
    )
    guide_parser.add_argument(
        "--create-folders",
        action="store_true",
        default=False,
        help="Pre-create the recommended MakeMKV rip folder structure.",
    )
    guide_parser.add_argument("--json", action="store_true", default=False)
    guide_parser.add_argument("--api-key", default=None)
    guide_parser.add_argument(
        "--drive",
        default=None,
        help="Read live disc info from a drive via makemkvcon. "
             "Pass a drive index (e.g. 0), device name (e.g. D:), or 'auto' "
             "to use the first drive with a disc inserted.",
    )
    guide_parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print debug logging to stderr in addition to the log file.",
    )
    guide_parser.add_argument(
        "--no-cache",
        action="store_true",
        default=False,
        help="Bypass the local cache and fetch fresh data from APIs.",
    )
    guide_parser.add_argument(
        "--no-specials",
        action="store_true",
        default=False,
        help="Exclude specials (Season 00) for TV shows.",
    )
    guide_parser.add_argument(
        "--no-extras",
        action="store_true",
        default=False,
        help="Omit recommended extras folder skeleton.",
    )

    # --- rip ---
    rip_parser = subs.add_parser(
        "rip",
        help="Read a disc, recommend titles, and rip via makemkvcon.",
    )
    rip_parser.add_argument(
        "title", nargs="?", default=None,
        help="Movie or TV show title (auto-detected from volume label if omitted).",
    )
    rip_parser.add_argument(
        "--drive",
        default="auto",
        help="Drive index (e.g. 0), device name (e.g. D:), or 'auto' (default: auto).",
    )
    rip_parser.add_argument("--year", type=int, help="Release year.")
    rip_parser.add_argument(
        "--type", dest="media_type", choices=["movie", "tv", "auto"],
        default="auto",
    )
    rip_parser.add_argument(
        "--format", dest="disc_format", default=None,
        help="Disc format filter for dvdcompare (auto-detected from disc resolution if omitted).",
    )
    rip_parser.add_argument(
        "--release", default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    rip_parser.add_argument(
        "--output", default=None,
        help="Output root directory (or set PLEX_ROOT env var, or config).",
    )
    rip_parser.add_argument(
        "--titles", default=None,
        help="Comma-separated title indices to rip (overrides auto-recommendation).",
    )
    rip_parser.add_argument(
        "--all", dest="rip_all", action="store_true", default=False,
        help="Rip all titles (skip recommendation filter).",
    )
    rip_parser.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip confirmation prompt.",
    )
    rip_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually rip (default: dry-run preview only).",
    )
    rip_parser.add_argument(
        "--dry-run", "-n", action="store_true", default=False,
        help=argparse.SUPPRESS,  # kept for backwards compat; dry-run is now default
    )
    rip_parser.add_argument(
        "--organize", dest="auto_organize", action="store_true", default=False,
        help="Automatically run organize after ripping.",
    )
    rip_parser.add_argument("--json", action="store_true", default=False)
    rip_parser.add_argument("--api-key", default=None)
    rip_parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
    )
    rip_parser.add_argument(
        "--no-cache", action="store_true", default=False,
    )
    rip_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )

    # --- orchestrate ---
    orch_parser = subs.add_parser(
        "orchestrate",
        help="Multi-disc rip and organize pipeline.",
    )
    orch_parser.add_argument(
        "--title", default=None,
        help="Movie or TV show title (auto-detected from volume label if omitted).",
    )
    orch_parser.add_argument(
        "--drive",
        default="auto",
        help="Drive index (e.g. 0), device name (e.g. D:), or 'auto' (default: auto).",
    )
    orch_parser.add_argument("--year", type=int, help="Release year.")
    orch_parser.add_argument(
        "--type", dest="media_type", choices=["movie", "tv", "auto"],
        default="auto",
    )
    orch_parser.add_argument(
        "--format", dest="disc_format", default=None,
        help="Disc format filter for dvdcompare (auto-detected from disc resolution if omitted).",
    )
    orch_parser.add_argument(
        "--release", default=None,
        help="Regional release: 1-based index or name keyword (default: auto-detect).",
    )
    orch_parser.add_argument(
        "--output", default=None,
        help="Output root directory (or set PLEX_ROOT env var, or config).",
    )
    orch_parser.add_argument(
        "--yes", "-y", action="store_true", default=False,
        help="Skip confirmation prompts.",
    )
    orch_parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually rip and organize (default: dry-run preview only).",
    )
    orch_parser.add_argument(
        "--unmatched",
        choices=["ignore", "move", "delete", "extras"],
        default="extras",
        help="Policy for unmatched files during organize (default: extras).",
    )
    orch_parser.add_argument("--json", action="store_true", default=False)
    orch_parser.add_argument("--api-key", default=None)
    orch_parser.add_argument(
        "--verbose", "-v", action="store_true", default=False,
    )
    orch_parser.add_argument(
        "--no-cache", action="store_true", default=False,
    )
    orch_parser.add_argument(
        "--auto",
        action="store_true",
        default=False,
        help="Skip interactive prompts, use best-guess defaults.",
    )
    orch_parser.add_argument(
        "--discs", default=None,
        help="Comma-separated disc numbers to rip (e.g. '1,3'). Skips others.",
    )
    orch_parser.add_argument(
        "--snapshot",
        action="store_true",
        default=False,
        help="Scan disc and write manifest without ripping. Useful to regenerate manifests for already-ripped files.",
    )

    # --- setup ---
    setup_parser = subs.add_parser(
        "setup",
        help="Interactive setup wizard to create or update the config file.",
    )
    setup_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Delete existing config and start fresh.",
    )

    return parser


async def _run(args: argparse.Namespace) -> int:
    if args.command == "organize":
        return await run_organize(args)
    if args.command == "lookup":
        return await run_lookup(args)
    if args.command == "rip":
        return await run_rip(args)
    if args.command == "orchestrate":
        return await run_orchestrate(args)
    if args.command == "setup":
        return run_setup(force=getattr(args, "force", False))
    return 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(1)

    # Auto-run setup if no config exists and user isn't already running setup
    if args.command != "setup" and not load_config():
        print("No config file found. Running first-time setup...\n")
        result = run_setup()
        if result != 0:
            sys.exit(result)
        print()

    set_auto_mode(getattr(args, "auto", False))
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
