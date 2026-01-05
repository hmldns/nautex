"""Nautex CLI package."""

from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("nautex")
except PackageNotFoundError:
    # Package is not installed
    __version__ = "0.0.0-dev"

