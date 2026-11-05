"""Explicit, offline, mask-aware mosaics for small local GeoTIFFs."""
import os

# Set before importing either native coordinate stack.
os.environ["PROJ_NETWORK"] = "OFF"
os.environ["GDAL_PAM_ENABLED"] = "NO"

from .model import Grid, MosaicError, Source
from .core import mosaic

__version__ = "0.1.0"
__all__ = ["Grid", "Source", "MosaicError", "mosaic"]
