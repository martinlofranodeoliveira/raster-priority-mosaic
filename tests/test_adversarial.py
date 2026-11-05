from dataclasses import replace
from pathlib import Path
import sys

import pytest
import rasterio
from rasterio.transform import Affine

from raster_priority_mosaic import Grid, MosaicError, Source, mosaic
from raster_priority_mosaic import core
from raster_priority_mosaic.inspection import bounded_command
from raster_priority_mosaic.model import digest, offline_env
from raster_priority_mosaic.publication import staged_directory

GRID = Grid(1, 1, (1, 0, 0, 0, -1, 2), "EPSG:4326")


def no_owned_debris(parent):
    assert not list(parent.glob(".rpm-stage-*"))
    assert not list(parent.glob(".*.rpm-lock"))


@pytest.mark.parametrize("change", [
    {"width": 1025}, {"height": True}, {"width": 0},
    {"transform": (1, 0, 0, 0, -1, float("nan"))},
    {"transform": (1, 0.1, 0, 0, -1, 2)},
    {"transform": (1, 0, 0, 0, 1, 2)},
    {"transform": (1, 0, 0, 0, -1, 81)},
    {"transform": (1, 0, 180, 0, -1, 2)},
    {"crs": "EPSG:3395"},
])
def test_rejected_grids_do_not_allocate_or_publish(change, make_tiff, tmp_path, monkeypatch):
    path = make_tiff("a.tif", [[1]], [[1]])
    before = digest(path)
    def forbidden(*args):
        pytest.fail("source ndarray allocation happened before request validation")
    monkeypatch.setattr(core, "_decode", forbidden)
    with pytest.raises(MosaicError):
        mosaic([Source(path, 1, 1)], replace(GRID, **change), tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert digest(path) == before
    no_owned_debris(tmp_path)


@pytest.mark.parametrize("bad_sources", [
    [(1, 7), (2, 7)], [(1, 7), (1, 8)], [(0, 1)], [(65536, 1)],
    [(True, 1)], [(1, True)], [(1, 1.0)],
])
def test_strict_ids_priorities(bad_sources, make_tiff, tmp_path):
    path = make_tiff("a.tif", [[1]], [[1]])
    sources = [Source(path, sid, priority) for sid, priority in bad_sources]
    before = digest(path)
    with pytest.raises(MosaicError):
        mosaic(sources, GRID, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert digest(path) == before
    no_owned_debris(tmp_path)


def test_ninth_source_is_rejected(make_tiff, tmp_path):
    path = make_tiff("a.tif", [[1]], [[1]])
    with pytest.raises(MosaicError):
        mosaic([Source(path, i + 1, i) for i in range(9)], GRID, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_corrupt_second_source_before_decode(make_tiff, tmp_path, monkeypatch):
    good = make_tiff("a.tif", [[1]], [[1]])
    corrupt = tmp_path / "bad.tif"
    corrupt.write_bytes(b"synthetic invalid TIFF, intentionally not a TIFF")
    before = [digest(good), digest(corrupt)]
    def forbidden(*args):
        pytest.fail("decoded first source before validating second source metadata")
    monkeypatch.setattr(core, "_decode", forbidden)
    with pytest.raises(MosaicError):
        mosaic([Source(good, 1, 1), Source(corrupt, 2, 2)], GRID, tmp_path / "out")
    assert [digest(good), digest(corrupt)] == before
    assert not (tmp_path / "out").exists()
    no_owned_debris(tmp_path)


def test_oversized_source_metadata_before_array(tmp_path, monkeypatch):
    path = tmp_path / "large.tif"
    with offline_env():
        with rasterio.open(
            path, "w", driver="GTiff", width=1025, height=1, count=1,
            dtype="uint16", crs="EPSG:4326", transform=Affine(0.001, 0, 0, 0, -1, 2),
        ):
            pass
    def forbidden(*args):
        pytest.fail("oversized decoded source was allocated")
    monkeypatch.setattr(core, "_decode", forbidden)
    with pytest.raises(MosaicError, match="dimension"):
        mosaic([Source(path, 1, 1)], GRID, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("dtype,count", [("uint8", 1), ("uint16", 2)])
def test_unsupported_raster_shapes(tmp_path, dtype, count):
    path = tmp_path / "wrong.tif"
    with offline_env():
        with rasterio.open(
            path, "w", driver="GTiff", width=1, height=1, count=count,
            dtype=dtype, crs="EPSG:4326", transform=Affine(*GRID.transform),
        ):
            pass
    with pytest.raises(MosaicError, match="single-band"):
        mosaic([Source(path, 1, 1)], GRID, tmp_path / "out")


@pytest.mark.parametrize("bad_path", ["https://invalid.example/a.tif", "/vsimem/a.tif", "../a.tif"])
def test_nonlocal_paths_rejected(bad_path, tmp_path):
    with pytest.raises(MosaicError):
        mosaic([Source(bad_path, 1, 1)], GRID, tmp_path / "out")
    no_owned_debris(tmp_path)


def test_symlink_and_external_mask_rejected(make_tiff, tmp_path):
    path = make_tiff("a.tif", [[1]], [[1]])
    link = tmp_path / "link.tif"
    link.symlink_to(path)
    with pytest.raises(MosaicError, match="symlink"):
        mosaic([Source(link, 1, 1)], GRID, tmp_path / "out")
    Path(str(path) + ".msk").write_bytes(b"synthetic sidecar")
    with pytest.raises(MosaicError, match="sidecar"):
        mosaic([Source(path, 1, 1)], GRID, tmp_path / "out")


def test_existing_destination_unchanged_for_bad_and_good_requests(make_tiff, tmp_path):
    path = make_tiff("a.tif", [[1]], [[1]])
    corrupt = tmp_path / "bad.tif"
    corrupt.write_bytes(b"synthetic corruption")
    dest = tmp_path / "out"
    dest.mkdir()
    marker = dest / "keep.txt"
    marker.write_text("owned by caller", encoding="utf-8")
    before = [digest(path), digest(corrupt)]
    attempts = [
        ([Source(path, 1, 5), Source(path, 2, 5)], GRID),
        ([Source(path, 1, 1)], replace(GRID, width=1025)),
        ([Source(path, 1, 1), Source(corrupt, 2, 2)], GRID),
        ([Source(path, 1, 1)], GRID),
    ]
    for sources, grid in attempts:
        with pytest.raises(MosaicError):
            mosaic(sources, grid, dest)
        assert marker.read_text() == "owned by caller"
        assert list(dest.iterdir()) == [marker]
        assert [digest(path), digest(corrupt)] == before
        no_owned_debris(tmp_path)


def test_failure_after_writing_is_not_published(make_tiff, tmp_path, monkeypatch):
    path = make_tiff("a.tif", [[1]], [[1]])
    before = digest(path)
    def fail(*args):
        raise MosaicError("synthetic independent checker failure")
    monkeypatch.setattr(core, "inspect_bundle", fail)
    with pytest.raises(MosaicError, match="checker failure"):
        mosaic([Source(path, 1, 1)], GRID, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert digest(path) == before
    no_owned_debris(tmp_path)


def test_input_mutation_detected_before_publication(make_tiff, tmp_path, monkeypatch):
    path = make_tiff("a.tif", [[1]], [[1]])
    original = core.inspect_bundle
    def mutate(stage, grid):
        result = original(stage, grid)
        with path.open("ab") as stream:
            stream.write(b"synthetic test mutation")
        return result
    monkeypatch.setattr(core, "inspect_bundle", mutate)
    with pytest.raises(MosaicError, match="input changed"):
        mosaic([Source(path, 1, 1)], GRID, tmp_path / "out")
    assert not (tmp_path / "out").exists()
    no_owned_debris(tmp_path)


def test_no_replace_even_if_empty_destination_appears(tmp_path):
    dest = tmp_path / "out"
    with pytest.raises(MosaicError, match="already exists"):
        with staged_directory(dest) as stage:
            (stage / "owned.txt").write_text("synthetic")
            dest.mkdir()
    assert dest.is_dir()
    assert list(dest.iterdir()) == []
    no_owned_debris(tmp_path)


def test_one_writer_lock_and_unrelated_staging_preserved(tmp_path):
    unrelated = tmp_path / ".rpm-stage-not-ours"
    unrelated.mkdir()
    with staged_directory(tmp_path / "out") as stage:
        with pytest.raises(MosaicError, match="writer lock"):
            with staged_directory(tmp_path / "out"):
                pytest.fail("second writer acquired lock")
        (stage / "value.txt").write_text("synthetic")
    assert (tmp_path / "out" / "value.txt").read_text() == "synthetic"
    assert unrelated.is_dir()
    assert not list(tmp_path.glob(".*.rpm-lock"))


def test_subprocess_deadline_and_output_limit():
    with pytest.raises(MosaicError, match="deadline"):
        bounded_command([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.1)
    with pytest.raises(MosaicError, match="output limit"):
        bounded_command(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 100000)"], limit=1024
        )
