from pathlib import Path

import pytest

from raster_priority_mosaic import Grid
from raster_priority_mosaic.model import offline_env
from raster_priority_mosaic.synthetic import write_tiff
import rasterio


@pytest.fixture
def make_tiff(tmp_path):
    def create(name, values, validity, *, grid=None, nodata=None):
        if grid is None:
            grid = Grid(len(values[0]), len(values), (1, 0, 0, 0, -1, 2), "EPSG:4326")
        return write_tiff(tmp_path / name, values, validity, grid, nodata=nodata)
    return create


@pytest.fixture
def read_bundle():
    def read(directory):
        result = {}
        with offline_env():
            for name in ("data", "source_id", "coverage"):
                with rasterio.open(Path(directory) / (name + ".tif"), driver="GTiff") as dataset:
                    result[name] = dataset.read(1)
                    result[name + "_mask"] = dataset.read_masks(1)
                    if dataset.nodata is not None:
                        pytest.fail("output nodata must be absent")
        return result
    return read
