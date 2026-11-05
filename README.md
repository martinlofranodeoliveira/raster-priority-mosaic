# Raster Priority Mosaic

Development version **0.1.0**, original MIT-licensed software by [Lofrano Tecnologia](https://lofranotecnologia.com.br). [Português brasileiro](README.pt-BR.md).

A headless application for small, local, single-band uint16 GeoTIFF mosaics. You choose the target grid and explicit priorities. It produces values, per-pixel source IDs, contributor counts and explicit validity masks. A masked high-priority pixel cannot erase a lower-priority valid value. A valid zero is data, not absence.

This is a deliberately narrow numerical tool, not a general raster ingestion service or a navigation, surveying or legal-boundary tool. There are no hosted services, accounts, telemetry or model/API dependencies.

## Install

Supported execution environment: **Linux, CPython 3.13**, a filesystem supporting `renameat2(RENAME_NOREPLACE)`, offline EPSG definitions, and system `gdalinfo`. Python wheels and system GDAL can contain different native library versions; both are reported. Native parsers are not sandboxed.

On a Debian Bookworm environment with package-install permissions:

```sh
apt-get update
apt-get install -y --no-install-recommends gdal-bin python3-venv
python -m venv .venv
. .venv/bin/activate
python -m pip install --only-binary=:all: -r requirements.txt
python -m pip install --no-build-isolation --no-deps -e .
python -m pip check
python tools/check_environment.py
```

Use a Python 3.13 interpreter for `python`; the Debian system Python itself need not be 3.13. The `python:3.13-bookworm` image supplies that interpreter. Dependency installation may access package repositories; application execution, tests and demo do not download anything. See [dependency details](docs/dependencies.md), including the distinction between version pins and artifact hashes. The requirements file pins distribution versions; it is not an artifact hash lock.

## Test and offline demo

```sh
python -m pytest -q
python -m raster_priority_mosaic demo --assert
python -m raster_priority_mosaic demo --assert --json
```

Run tests serially, without xdist, with `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1` and `GDAL_NUM_THREADS=1`. CI limits the container to 1 GiB and two CPUs. These limits do not make GDAL a parser sandbox.

The demo creates only original synthetic arrays in owned temporary storage, runs real Rasterio/GDAL/PROJ and system `gdalinfo`, checks the results and explicitly removes its temporary workspace. The default human-readable portion is:

```text
Raster Priority Mosaic 0.1.0 (development)
data: [[10, 200, 0], [300, 40, 0]]
source_id: [[1, 2, 2], [2, 1, 0]]
coverage: [[1, 2, 2], [2, 1, 0]]
mask: [[255, 255, 255], [255, 255, 0]]
cross_crs_data: [[11, 12], [21, 0]]
assertions: passed
```

A final JSON line contains those arrays and the assertion status. `--json` emits only that JSON object. This is specified example output, not a claim of an executed test run. The third pixel of the first row is a valid, winning zero; the last pixel is invalid and has no owner.

## CLI usage with persistent output

```sh
python -m raster_priority_mosaic fixtures synthetic-example
python -m raster_priority_mosaic mosaic synthetic-example/request.json mosaic-example --window-rows 1
```

Expected summary: `Published 5 valid pixels to mosaic-example`.

`fixtures` creates two synthetic TIFFs and a complete request. Both destination directories must be new; their parents must already exist. Add `--json` to `mosaic` to print the complete report. Completed mosaics persist until the caller explicitly removes them. Neither command overwrites an existing destination.

A request has exactly these fields; source paths are relative to the request file, not the working directory:

```json
{
  "sources": [
    {"path": "a.tif", "source_id": 1, "priority": 10},
    {"path": "b.tif", "source_id": 2, "priority": 20}
  ],
  "targetGrid": {
    "width": 3,
    "height": 2,
    "transform": [1, 0, 0, 0, -1, 2],
    "crs": "EPSG:4326"
  }
}
```

Malformed requests and processing failures exit 2 and print `error:` on stderr. Successful commands exit 0. Argument-parser usage failures also exit 2. `--version` prints the development version. Unknown JSON fields and duplicate keys are rejected.

## Python API

After creating `synthetic-example` above:

```python
from raster_priority_mosaic import Grid, Source, mosaic

sources = [
    Source("synthetic-example/a.tif", source_id=1, priority=10),
    Source("synthetic-example/b.tif", source_id=2, priority=20),
]
grid = Grid(3, 2, (1, 0, 0, 0, -1, 2), "EPSG:4326")
report = mosaic(sources, grid, "api-example", window_rows=1)
print(report["valid_pixels"])  # 5
```

`mosaic(sources, targetGrid, destination, *, window_rows=64)` returns the JSON-compatible report also written to `report.json`. It raises `MosaicError` for rejected inputs, native failures, failed independent checks or publication errors. The target argument is named `targetGrid` to match the public contract.

The affine tuple is **`(a,b,c,d,e,f)`**, mapping pixel corners as `x=a*column+b*row+c`, `y=d*column+e*row+f`; it is not GDAL's six-element serialization order. Values and masks are reprojected independently with nearest-neighbor sampling. `read_masks` uses nonzero=valid, the opposite of NumPy masked-array mask polarity.

## Output bundle

| File | Storage | Meaning |
| --- | --- | --- |
| `data.tif` | uint16 | Highest-priority valid contributor; zero stored when uncovered |
| `source_id.tif` | uint16 | Winning explicit source ID; zero means no contributor |
| `coverage.tif` | uint8 | Count of every valid contributor after reprojection, 0..8 |
| `report.json` | UTF-8 JSON | Geometry, source digests, coverage histogram and actual native/tool versions |

All TIFFs have an internal dataset mask: 255 where coverage is positive, otherwise 0. None declares a nodata value. All use exactly the requested grid. Data and IDs must be interpreted with the validity mask; an unmasked zero can be meaningful data. A separate fixed, bounded `gdalinfo -json` subprocess checks each output's metadata before publication.

## Why this design?

Explicit geometry avoids silently choosing resolution or a supposedly best CRS. Separate mask warps avoid nodata-zero ambiguity. IDs and coverage make overlap decisions inspectable without visual output. Canonical one-row warp units make results invariant to output-buffer grouping; `window_rows` changes write batching, not the sampling lattice. One staged directory and Linux no-replace rename publish the complete bundle, not three independently visible TIFFs.

See [the precise contract](docs/contract.md) and [design and threat boundaries](docs/design.md).

## Limits

- 1..8 sources; each source and target is at most 1024 by 1024 and 1,048,576 pixels. Source file size is at most 64 MiB. Metadata is parsed natively **before** decoded-dimension checks.
- Regular local, self-contained GTiff files only; one uint16 band, no URL/VSI/VRT, symlink paths or external mask/overview/PAM sidecars. No arbitrary raster or coordinate parsers are implemented here.
- Only canonical EPSG:4326 and EPSG:3857, north-up grids, longitude within ±180° and latitude within ±80° for the entire corner extent. No antimeridian wrapping, polar grids, rotation or inferred geometry.
- Unique positive IDs 1..65535; unique exact integer priorities, with larger values winning. Booleans are not integers for this API.
- Inputs, parent directories and native configuration must remain stable. Calls within one process are serialized; one writer per destination, readers only after publication. A crash may leave an owned stage or writer lock for manual inspection.
- GDAL caches and warp-memory options are tuning controls, not hard RSS limits. Use OS isolation and limits for untrusted inputs; this application is not a hostile-TIFF sandbox.
- Nearest-neighbor only. Results near source pixel boundaries follow the installed GDAL/PROJ sampling behavior. Tests avoid ambiguous cross-CRS edge ties. Array correctness, not TIFF byte identity, is the contract.
- Publication is atomic visibility on a supporting local filesystem, not a power-loss durability guarantee. No distributed locking or remote filesystems are qualified.

General contact: [official homepage](https://lofranotecnologia.com.br). Security reports: [GitHub private vulnerability reporting](https://github.com/martinlofranodeoliveira/raster-priority-mosaic/security/advisories/new).
