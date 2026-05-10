"""riplex: automates MakeMKV disc ripping and Plex-compatible file organization."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("riplex")
except PackageNotFoundError:
    __version__ = "dev"
