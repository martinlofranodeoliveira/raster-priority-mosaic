"""Original synthetic fixtures. No external imagery or downloaded data."""
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import Affine

from .model import Grid, MosaicError, Source, offline_env
from .publication import staged_directory

DEMO_GRID = Grid(3, 2, (1, 0, 0, 0, -1, 2), "EPSG:4326")


def write_tiff(path, values, validity, grid, *, nodata=None):
    path = Path(path)
    if path.exists():
        raise MosaicError("fixture output already exists")
    values = np.asarray(values, dtype=np.uint16)
    validity = np.asarray(validity, dtype=np.uint8)
    if values.shape != (grid.height, grid.width) or validity.shape != values.shape:
        raise MosaicError("fixture array shape does not match its grid")
    with offline_env():
        with rasterio.open(
            path, "w", driver="GTiff", width=grid.width, height=grid.height,
            count=1, dtype="uint16", crs=grid.crs,
            transform=Affine(*grid.transform), nodata=nodata,
        ) as dataset:
            dataset.write(values, 1)
            dataset.write_mask(np.where(validity != 0, 255, 0).astype(np.uint8))
    return path


def populate(directory):
    """Write into an owned empty directory and return explicit API arguments."""
    a = write_tiff(
        directory / "a.tif", [[10, 20, 0], [30, 40, 7]],
        [[1, 1, 1], [1, 1, 0]], DEMO_GRID,
    )
    b = write_tiff(
        directory / "b.tif", [[99, 200, 0], [300, 88, 12]],
        [[0, 1, 1], [1, 0, 0]], DEMO_GRID, nodata=0,
    )
    request = {
        "sources": [
            {"path": "a.tif", "source_id": 1, "priority": 10},
            {"path": "b.tif", "source_id": 2, "priority": 20},
        ],
        "targetGrid": {
            "width": 3, "height": 2, "transform": list(DEMO_GRID.transform),
            "crs": DEMO_GRID.crs,
        },
    }
    (directory / "request.json").write_text(
        json.dumps(request, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return [Source(a, 1, 10), Source(b, 2, 20)], DEMO_GRID


def create_fixtures(destination):
    with staged_directory(destination) as stage:
        populate(stage)
