"""Public types, finite geometry checks, and offline native configuration."""
from contextlib import contextmanager
from dataclasses import dataclass
from importlib.metadata import version
import hashlib
import math
import os
from pathlib import Path
import stat

import numpy as np
import pyproj
from pyproj import Transformer
import rasterio
from rasterio.transform import Affine

MAX_SIDE = 1024
MAX_PIXELS = 1024 * 1024
MAX_SOURCES = 8
MAX_FILE_BYTES = 64 * 1024 * 1024
PINS = {"numpy": "2.2.6", "rasterio": "1.4.3", "pyproj": "3.7.1"}


class MosaicError(Exception):
    """A rejected request, native processing error, or publication failure."""


@dataclass(frozen=True)
class Source:
    path: str | Path
    source_id: int
    priority: int


@dataclass(frozen=True)
class Grid:
    width: int
    height: int
    transform: tuple[float, float, float, float, float, float]
    crs: str


@contextmanager
def offline_env():
    """Process-global native settings: callers must serialize native operations."""
    os.environ["PROJ_NETWORK"] = "OFF"
    pyproj.network.set_network_enabled(False)
    with rasterio.Env(
        PROJ_NETWORK="OFF",
        GDAL_PAM_ENABLED="NO",
        GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
        GDAL_TIFF_INTERNAL_MASK=True,
        GDAL_CACHEMAX=16 * 1024 * 1024,
        GDAL_NUM_THREADS="1",
        GDAL_SKIP="VRT",
        CHECK_WITH_INVERT_PROJ="YES",
    ):
        yield


def runtime_versions():
    return {
        "numpy": np.__version__,
        "rasterio": rasterio.__version__,
        "rasterio_gdal": rasterio.__gdal_version__,
        "rasterio_proj": rasterio.__proj_version__,
        "pyproj": pyproj.__version__,
        "pyproj_proj": pyproj.proj_version_str,
    }


def require_runtime():
    for name, expected in PINS.items():
        if version(name) != expected:
            raise MosaicError(f"unsupported {name} version; install {name}=={expected}")


def lexical_path(value):
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise MosaicError("path must be a local string or Path") from exc
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise MosaicError("invalid local path")
    if ":" in raw or raw.lower().startswith("/vsi") or ".." in Path(raw).parts:
        raise MosaicError("URLs, VSI paths, colon paths and parent traversal are unsupported")
    return Path(os.path.abspath(raw))


def checked_components(path, *, missing_leaf=False):
    for part in reversed((path, *path.parents)):
        try:
            info = part.lstat()
        except FileNotFoundError:
            if missing_leaf and part == path:
                continue
            raise MosaicError("path parent does not exist") from None
        if stat.S_ISLNK(info.st_mode):
            raise MosaicError("symlink paths are unsupported")


def local_file(value, limit=MAX_FILE_BYTES):
    path = lexical_path(value)
    checked_components(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode):
        raise MosaicError("input must be a regular local file")
    if not 0 < info.st_size <= limit:
        raise MosaicError(f"file size must be between 1 and {limit} bytes")
    return path


def destination_path(value):
    path = lexical_path(value)
    if path == path.parent or len(path.name.encode("utf-8")) > 128:
        raise MosaicError("destination needs a name of at most 128 UTF-8 bytes")
    checked_components(path, missing_leaf=True)
    if not path.parent.is_dir():
        raise MosaicError("destination parent must be an existing directory")
    return path


def digest(path):
    result = hashlib.sha256()
    total = 0
    with path.open("rb") as stream:
        while block := stream.read(65536):
            total += len(block)
            if total > MAX_FILE_BYTES:
                raise MosaicError("input grew beyond the file-size limit")
            result.update(block)
    return result.hexdigest()


def check_dimensions(width, height):
    if type(width) is not int or type(height) is not int:
        raise MosaicError("dimensions must be exact integers, not booleans")
    if not (1 <= width <= MAX_SIDE and 1 <= height <= MAX_SIDE):
        raise MosaicError("each decoded dimension must be in 1..1024")
    if width * height > MAX_PIXELS:
        raise MosaicError("decoded pixel limit exceeded")


def check_geometry(width, height, transform, crs):
    check_dimensions(width, height)
    if crs not in ("EPSG:4326", "EPSG:3857"):
        raise MosaicError("only EPSG:4326 and EPSG:3857 are supported")
    if not isinstance(transform, (tuple, list)) or len(transform) != 6:
        raise MosaicError("transform must contain exactly a,b,c,d,e,f")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in transform):
        raise MosaicError("transform coefficients must be finite numbers, not booleans")
    a, b, c, d, e, f = transform
    if a <= 0 or e >= 0 or b != 0 or d != 0:
        raise MosaicError("only north-up transforms with positive x scale are supported")
    east, south = c + a * width, f + e * height
    if not all(math.isfinite(v) for v in (east, south)) or east <= c or south >= f:
        raise MosaicError("grid extent is nonfinite or not representably increasing")
    if crs == "EPSG:4326":
        xmax, ymax = 180.0, 80.0
    else:
        # Production coordinate operations belong to PROJ, not hand-written formulas.
        project = Transformer.from_crs(4326, 3857, always_xy=True, allow_ballpark=False)
        xmax, ymax = project.transform(180.0, 80.0, errcheck=True)
    if c < -xmax or east > xmax or south < -ymax or f > ymax:
        raise MosaicError("entire grid must lie within longitude +/-180 and latitude +/-80")
    return Affine(a, b, c, d, e, f)


def check_request(sources, target_grid, window_rows):
    if not isinstance(sources, (tuple, list)) or not 1 <= len(sources) <= MAX_SOURCES:
        raise MosaicError("sources must be a list or tuple containing 1..8 Source objects")
    if not isinstance(target_grid, Grid):
        raise MosaicError("targetGrid must be a Grid")
    transform = check_geometry(
        target_grid.width, target_grid.height, target_grid.transform, target_grid.crs
    )
    if type(window_rows) is not int or not 1 <= window_rows <= MAX_SIDE:
        raise MosaicError("window_rows must be an exact integer in 1..1024")
    ids, priorities = set(), set()
    paths = []
    for source in sources:
        if not isinstance(source, Source):
            raise MosaicError("each source must be a Source")
        if type(source.source_id) is not int or not 1 <= source.source_id <= 65535:
            raise MosaicError("source IDs must be exact integers in 1..65535")
        if type(source.priority) is not int:
            raise MosaicError("priorities must be exact integers, not booleans")
        if source.source_id in ids or source.priority in priorities:
            raise MosaicError("source IDs and priorities must both be unique")
        ids.add(source.source_id)
        priorities.add(source.priority)
        path = local_file(source.path)
        # Self-contained TIFFs only; known external auxiliary files are not consumed.
        for suffix in (".msk", ".aux.xml", ".ovr"):
            if Path(str(path) + suffix).exists():
                raise MosaicError("external TIFF sidecars are unsupported")
        paths.append(path)
    return transform, paths
