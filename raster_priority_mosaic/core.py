"""Nearest-neighbor reprojection with independent validity and provenance."""
from contextlib import ExitStack
from dataclasses import dataclass
import json
import threading

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import RasterioError
from rasterio.warp import Resampling, reproject
from rasterio.windows import Window, transform as window_transform

from .inspection import inspect_bundle
from .model import (
    MosaicError, check_geometry, check_request, digest, offline_env,
    require_runtime, runtime_versions,
)
from .publication import staged_directory

_BUSY = threading.Lock()


@dataclass
class _Decoded:
    source: object
    path: object
    transform: object
    crs: object
    values: np.ndarray
    validity: np.ndarray
    sha256: str


def _decode(dataset):
    # Both are raw ndarrays. No inherited nodata value is passed to reproject.
    return dataset.read(1, masked=False), dataset.read_masks(1)


def _load_sources(sources, paths):
    with ExitStack() as stack:
        metadata = []
        for source, path in zip(sources, paths):
            dataset = stack.enter_context(rasterio.open(path, "r", driver="GTiff", sharing=False))
            if dataset.driver != "GTiff" or dataset.count != 1 or dataset.dtypes != ("uint16",):
                raise MosaicError("sources must be single-band uint16 GTiff files")
            epsg = dataset.crs.to_epsg() if dataset.crs is not None else None
            if epsg not in (4326, 3857) or dataset.crs != CRS.from_epsg(epsg):
                raise MosaicError("source CRS must be EPSG:4326 or EPSG:3857")
            check_geometry(
                dataset.width, dataset.height, tuple(dataset.transform)[:6], f"EPSG:{epsg}"
            )
            metadata.append((source, path, dataset))
        # Validate ALL decoded dimensions before requesting ANY raster ndarray.
        decoded = []
        for source, path, dataset in metadata:
            before = digest(path)
            values, validity = _decode(dataset)
            decoded.append(_Decoded(
                source, path, dataset.transform, dataset.crs, values, validity, before
            ))
        return sorted(decoded, key=lambda item: item.source.priority)


def _render(outputs, decoded, grid, transform, window_rows):
    histogram = np.zeros(len(decoded) + 1, dtype=np.int64)
    for start in range(0, grid.height, window_rows):
        height = min(window_rows, grid.height - start)
        values = np.zeros((height, grid.width), dtype=np.uint16)
        owners = np.zeros((height, grid.width), dtype=np.uint16)
        coverage = np.zeros((height, grid.width), dtype=np.uint8)
        for local_row in range(height):
            # Canonical one-row warp units make batching independent of GDAL's
            # approximate-transform subdivisions. All transforms use the global grid.
            row_window = Window(0, start + local_row, grid.width, 1)
            row_transform = window_transform(row_window, transform)
            for item in decoded:
                warped_values = np.zeros((1, grid.width), dtype=np.uint16)
                warped_mask = np.zeros((1, grid.width), dtype=np.uint8)
                geometry = dict(
                    src_transform=item.transform, src_crs=item.crs,
                    dst_transform=row_transform, dst_crs=grid.crs,
                    src_nodata=None, dst_nodata=None,
                    resampling=Resampling.nearest, init_dest_nodata=False,
                    num_threads=1, warp_mem_limit=16,
                )
                reproject(item.values, warped_values, **geometry)
                reproject(item.validity, warped_mask, **geometry)
                valid = warped_mask[0] != 0
                coverage[local_row, valid] += 1
                values[local_row, valid] = warped_values[0, valid]
                owners[local_row, valid] = item.source.source_id
        window = Window(0, start, grid.width, height)
        mask = np.where(coverage != 0, 255, 0).astype(np.uint8)
        for dataset, array in zip(outputs, (values, owners, coverage)):
            dataset.write(array, 1, window=window)
            dataset.write_mask(mask, window=window)
        histogram += np.bincount(coverage.ravel(), minlength=len(decoded) + 1)
    return [int(v) for v in histogram]


def mosaic(sources, targetGrid, destination, *, window_rows=64):
    """Publish a four-file bundle; return the same JSON-compatible report it contains.

    Source IDs and priorities are unique exact integers. Larger priority wins among
    contributors with nonzero read_masks validity. Inputs and parents stay immutable.
    Linux renameat2, offline CRS definitions and system gdalinfo are required.
    """
    if not _BUSY.acquire(blocking=False):
        raise MosaicError("native operations must be serialized within this process")
    try:
        require_runtime()
        with offline_env():
            transform, paths = check_request(sources, targetGrid, window_rows)
            decoded = _load_sources(sources, paths)
            with staged_directory(destination) as stage:
                profile = dict(
                    driver="GTiff", width=targetGrid.width, height=targetGrid.height,
                    count=1, crs=targetGrid.crs, transform=transform,
                    compress="deflate", predictor=2,
                )
                with ExitStack() as stack:
                    outputs = [
                        stack.enter_context(rasterio.open(stage / name, "w", dtype=dtype, **profile))
                        for name, dtype in (
                            ("data.tif", "uint16"), ("source_id.tif", "uint16"),
                            ("coverage.tif", "uint8"),
                        )
                    ]
                    histogram = _render(outputs, decoded, targetGrid, transform, window_rows)
                independent = inspect_bundle(stage, targetGrid)
                for item in decoded:
                    if digest(item.path) != item.sha256:
                        raise MosaicError("input changed during the operation")
                report = {
                    "schema_version": 1,
                    "application": "Raster Priority Mosaic",
                    "version": "0.1.0",
                    "status": "development",
                    "grid": {
                        "width": targetGrid.width, "height": targetGrid.height,
                        "transform": list(targetGrid.transform), "crs": targetGrid.crs,
                    },
                    "sources": [
                        {"source_id": item.source.source_id, "priority": item.source.priority,
                         "sha256": item.sha256}
                        for item in decoded
                    ],
                    "coverage_histogram": histogram,
                    "valid_pixels": targetGrid.width * targetGrid.height - histogram[0],
                    "native_versions": runtime_versions(),
                    "independent_gdalinfo": independent,
                }
                with (stage / "report.json").open("x", encoding="utf-8") as stream:
                    json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
                    stream.write("\n")
            return report
    except MosaicError:
        raise
    except (OSError, RasterioError, ValueError, OverflowError) as exc:
        raise MosaicError("native mosaic operation failed") from exc
    finally:
        _BUSY.release()
