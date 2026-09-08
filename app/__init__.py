"""RideWithUBT: an offline-first virtual world for indoor cycling training."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("ridewithubt")
except PackageNotFoundError:  # pragma: no cover - only when running from a bare tree
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
