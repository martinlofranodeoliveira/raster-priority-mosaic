import math

import numpy as np
from pyproj import Transformer

from raster_priority_mosaic import Grid, Source, mosaic
from raster_priority_mosaic.model import offline_env

R = 6378137.0


def test_spherical_webmerc_references():
    with offline_env():
        project = Transformer.from_crs(4326, 3857, always_xy=True, allow_ballpark=False)
        x, y = project.transform(1, 0, errcheck=True)
        _, y45 = project.transform(0, 45, errcheck=True)
    assert abs(x - 111319.49079327357) <= 0.000001
    assert abs(x - R * math.pi / 180) <= 0.000001
    assert abs(y) <= 0.00000001
    assert abs(y45 - 5621521.486192066) <= 0.000001
    assert abs(y45 - R * math.log(math.tan(math.pi / 4 + math.pi / 8))) <= 0.000001


def test_cross_crs_inverse_formula_oracle_and_batching(make_tiff, tmp_path, read_bundle):
    original = [[11, 12, 13], [21, 22, 23], [31, 32, 33]]
    mask = [[1, 1, 1], [1, 0, 1], [1, 1, 1]]
    source_grid = Grid(3, 3, (1, 0, 0, 0, -1, 3), "EPSG:4326")
    path = make_tiff("geo.tif", original, mask, grid=source_grid)
    unit = R * math.pi / 180
    target = Grid(2, 2, (unit, 0, 0, 0, -unit, 3 * unit), "EPSG:3857")
    data, owner, coverage = [], [], []
    for row in range(2):
        data.append([])
        owner.append([])
        coverage.append([])
        for col in range(2):
            x, y = (col + 0.5) * unit, (2.5 - row) * unit
            longitude = math.degrees(x / R)
            latitude = math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)
            sx, sy = longitude, 3 - latitude
            # These centers are deliberately well away from nearest-neighbor ties.
            assert min(sx % 1, 1 - sx % 1, sy % 1, 1 - sy % 1) > 0.410
            column, line = math.floor(sx), math.floor(sy)
            valid = mask[line][column] != 0
            data[row].append(original[line][column] if valid else 0)
            owner[row].append(7 if valid else 0)
            coverage[row].append(1 if valid else 0)
    source = [Source(path, 7, -3)]
    for rows, name in ((2, "full"), (1, "strips")):
        report = mosaic(source, target, tmp_path / name, window_rows=rows)
        assert report["independent_gdalinfo"]["outputs"]["data.tif"]["crs"] == "EPSG:3857"
        result = read_bundle(tmp_path / name)
        for key, expected in (("data", data), ("source_id", owner), ("coverage", coverage)):
            np.testing.assert_array_equal(result[key], expected)
            np.testing.assert_array_equal(result[key + "_mask"], [[255, 255], [255, 0]])
    full, strips = read_bundle(tmp_path / "full"), read_bundle(tmp_path / "strips")
    for key in full:
        np.testing.assert_array_equal(full[key], strips[key])


def test_global_row_transforms_on_non_equatorial_grid(make_tiff, tmp_path, read_bundle):
    source_grid = Grid(4, 5, (0.2, 0, -1.2, 0, -0.2, 46), "EPSG:4326")
    values = [[100 * row + col for col in range(4)] for row in range(5)]
    masks = [[int((row + col) % 3 != 0) for col in range(4)] for row in range(5)]
    path = make_tiff("latitude.tif", values, masks, grid=source_grid)
    with offline_env():
        project = Transformer.from_crs(4326, 3857, always_xy=True)
        left, top = project.transform(-1.2, 46)
    target = Grid(5, 7, (17500, 0, left, 0, -20000, top), "EPSG:3857")
    for rows, name in ((7, "full"), (1, "row"), (3, "batch")):
        mosaic([Source(path, 12, 3)], target, tmp_path / name, window_rows=rows)
    baseline = read_bundle(tmp_path / "full")
    for name in ("row", "batch"):
        actual = read_bundle(tmp_path / name)
        for key in baseline:
            np.testing.assert_array_equal(baseline[key], actual[key])
