import json

import numpy as np
import pytest

from raster_priority_mosaic import Grid, Source, mosaic
from raster_priority_mosaic.model import digest


def test_aligned_acceptance(make_tiff, tmp_path, read_bundle):
    a = make_tiff("a.tif", [[10, 20], [30, 40]], [[1, 1], [1, 1]])
    b = make_tiff("b.tif", [[99, 200], [300, 88]], [[0, 1], [1, 0]])
    before = [digest(a), digest(b)]
    grid = Grid(2, 2, (1, 0, 0, 0, -1, 2), "EPSG:4326")
    destination = tmp_path / "result"
    report = mosaic([Source(b, 2, 200), Source(a, 1, -10)], grid, destination)
    actual = read_bundle(destination)
    np.testing.assert_array_equal(actual["data"], [[10, 200], [300, 40]])
    np.testing.assert_array_equal(actual["source_id"], [[1, 2], [2, 1]])
    np.testing.assert_array_equal(actual["coverage"], [[1, 2], [2, 1]])
    for name in ("data", "source_id", "coverage"):
        np.testing.assert_array_equal(actual[name + "_mask"], [[255, 255], [255, 255]])
    assert actual["data"].dtype == np.uint16
    assert actual["source_id"].dtype == np.uint16
    assert actual["coverage"].dtype == np.uint8
    assert [digest(a), digest(b)] == before
    assert set(p.name for p in destination.iterdir()) == {
        "data.tif", "source_id.tif", "coverage.tif", "report.json"
    }
    assert json.loads((destination / "report.json").read_text()) == report
    assert report["coverage_histogram"] == [0, 2, 2]
    # This summary was produced by actual system gdalinfo, not Rasterio alone.
    assert report["independent_gdalinfo"]["version"].startswith("GDAL ")
    for info in report["independent_gdalinfo"]["outputs"].values():
        assert info["size"] == [2, 2]
        assert info["crs"] == "EPSG:4326"
        assert info["mask_flags"] == ["PER_DATASET"]


def test_valid_zero_and_no_contributor(make_tiff, tmp_path, read_bundle):
    a = make_tiff("a.tif", [[9, 8, 7]], [[1, 1, 0]])
    # The internal explicit mask takes precedence over this nodata declaration.
    b = make_tiff("b.tif", [[0, 0, 123]], [[1, 0, 0]], nodata=0)
    grid = Grid(3, 1, (1, 0, 0, 0, -1, 2), "EPSG:4326")
    mosaic([Source(a, 1, 1), Source(b, 65535, 2)], grid, tmp_path / "out")
    result = read_bundle(tmp_path / "out")
    np.testing.assert_array_equal(result["data"], [[0, 8, 0]])
    np.testing.assert_array_equal(result["source_id"], [[65535, 1, 0]])
    np.testing.assert_array_equal(result["coverage"], [[2, 1, 0]])
    for name in ("data", "source_id", "coverage"):
        np.testing.assert_array_equal(result[name + "_mask"], [[255, 255, 0]])


def loop_oracle(values, masks, ids, priorities):
    """Independent per-pixel candidate collection; no reprojection or vector overwrite."""
    height, width = len(values[0]), len(values[0][0])
    data = [[0 for _ in range(width)] for _ in range(height)]
    owners = [[0 for _ in range(width)] for _ in range(height)]
    coverage = [[0 for _ in range(width)] for _ in range(height)]
    for row in range(height):
        for col in range(width):
            candidates = []
            for index in range(len(values)):
                if masks[index][row][col] != 0:
                    candidates.append(index)
            coverage[row][col] = len(candidates)
            if candidates:
                winner = max(candidates, key=lambda i: priorities[i])
                data[row][col] = values[winner][row][col]
                owners[row][col] = ids[winner]
    return data, owners, coverage


@pytest.mark.parametrize("case", range(32))
def test_32_fixed_priority_oracles(case, make_tiff, tmp_path, read_bundle):
    count = 1 + case % 4
    priorities = [40, -5, 9, 100][:count]
    ids = [10 * (case + 1) + i + 1 for i in range(count)]
    values, masks, sources = [], [], []
    for index in range(count):
        # Arithmetic fixtures are fully fixed, not sampled at runtime.
        value = [[(case * 71 + index * 103 + row * 17 + col * 11) % 65536
                  for col in range(3)] for row in range(2)]
        value[case % 2][(case + index) % 3] = 0
        mask = [[0 if ((case + 1) * (index + 2) + row * 3 + col * 7) % 5 == 0
                 else 1 for col in range(3)] for row in range(2)]
        values.append(value)
        masks.append(mask)
        path = make_tiff(f"s{index}.tif", value, mask)
        sources.append(Source(path, ids[index], priorities[index]))
    expected = loop_oracle(values, masks, ids, priorities)
    grid = Grid(3, 2, (1, 0, 0, 0, -1, 2), "EPSG:4326")
    mosaic(list(reversed(sources)), grid, tmp_path / "out", window_rows=1 + case % 2)
    actual = read_bundle(tmp_path / "out")
    for name, array in zip(("data", "source_id", "coverage"), expected):
        np.testing.assert_array_equal(actual[name], array)
        np.testing.assert_array_equal(
            actual[name + "_mask"], [[255 if v else 0 for v in row] for row in expected[2]]
        )


def test_all_eight_contributors_count(make_tiff, tmp_path, read_bundle):
    sources = [Source(make_tiff(f"s{i}.tif", [[i]], [[1]]), i + 1, -i) for i in range(8)]
    grid = Grid(1, 1, (1, 0, 0, 0, -1, 2), "EPSG:4326")
    mosaic(sources, grid, tmp_path / "out")
    result = read_bundle(tmp_path / "out")
    assert result["data"].tolist() == [[0]]
    assert result["source_id"].tolist() == [[1]]
    assert result["coverage"].tolist() == [[8]]
    assert result["data_mask"].tolist() == [[255]]


def test_outside_source_is_invalid(make_tiff, tmp_path, read_bundle):
    source = make_tiff("tiny.tif", [[42]], [[1]])
    grid = Grid(3, 2, (1, 0, -1, 0, -1, 3), "EPSG:4326")
    mosaic([Source(source, 4, 9)], grid, tmp_path / "out")
    result = read_bundle(tmp_path / "out")
    np.testing.assert_array_equal(result["data"], [[0, 0, 0], [0, 42, 0]])
    np.testing.assert_array_equal(result["coverage"], [[0, 0, 0], [0, 1, 0]])
