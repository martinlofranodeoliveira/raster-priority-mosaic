# Dependencies and reproducibility boundary

## Exact distribution versions

The source declares these real distribution releases for Linux CPython 3.13:

| Role | Distribution | Version |
| --- | --- | --- |
| Arrays | NumPy | 2.2.6 |
| TIFF and GDAL warp | Rasterio | 1.4.3 |
| Offline coordinate operations/checks | pyproj | 3.7.1 |
| Serial tests | pytest | 8.3.5 |
| Build backend | setuptools | 80.9.0 |
| Wheel support | wheel | 0.45.1 |

`requirements.txt` also fixes the small transitive Python dependency set. Rasterio requires affine, attrs, certifi, click, click-plugins, cligj and NumPy. pyproj requires certifi. pytest requires iniconfig, packaging and pluggy in the documented Linux environment. No model/API package is used.

Authoritative release metadata endpoints for the principal pins:

- https://pypi.org/pypi/numpy/2.2.6/json
- https://pypi.org/pypi/rasterio/1.4.3/json
- https://pypi.org/pypi/pyproj/3.7.1/json
- https://pypi.org/pypi/pytest/8.3.5/json

These links are documentation, not runtime fetches. Install with `--only-binary=:all:` so an unavailable interpreter/platform wheel fails instead of silently compiling a different native stack. Build the local application with `--no-build-isolation --no-deps` after installing the declared build tools.

## Integrity is not implied by a version pin

This source distribution supplies exact version constraints, **not a hash-locked wheel manifest**. No artifact SHA-256 or successful resolution result is invented here. Wheel archive hashes depend on the exact interpreter, architecture and selected filename. A reproducible installation requires a separately verified wheelhouse/hash manifest for that platform and an appropriately fixed system image/package repository. Review the real release metadata and archive hashes when preparing that installation. A plain version-pinned pip install is not cryptographic supply-chain verification.

After installation:

```sh
python -m pip check
python tools/check_environment.py
python -m pytest -q
python -m raster_priority_mosaic demo --assert --json
```

The environment tool checks every requirement against installed distribution metadata, prints its real `Requires-Python` and computes SHA-256 of the installed METADATA text. **Those hashes are metadata hashes, not wheel hashes**, and cannot substitute for a verified download manifest. The tool performs no network access and claims no package-signature verification.

For a prepopulated, verified wheelhouse, installation can avoid the package index:

```sh
python -m pip install --no-index --find-links wheelhouse --only-binary=:all: -r requirements.txt
python -m pip install --no-build-isolation --no-deps -e .
```

## Native libraries and independent tools

Rasterio wheels carry/use GDAL and PROJ; pyproj wheels carry/use PROJ and local CRS databases. The system `gdalinfo` comes from Debian's `gdal-bin`, not from a fabricated Python substitute. Debian Bookworm supplies a GDAL 3.6-series tool, while wheel-native versions can differ. The source does not claim those native versions are equal or that every possible vendor build is qualified.

Actual installed versions are obtained from:

- `rasterio.__gdal_version__` and `rasterio.__proj_version__`;
- `pyproj.proj_version_str`;
- bounded `gdalinfo --version`;
- installed Python distribution metadata.

Every mosaic report records these separately. Exact native/tool versions cannot be established from distribution version strings alone. The environment report and numerical tests are required evidence for a particular installation; this source does not assert already-measured success or an unobserved native version.

The tests exercise offline availability of EPSG:4326 and EPSG:3857 in both coordinate stacks and the independent tool. No runtime operation downloads CRS grids, imagery or datasets. `PROJ_NETWORK=OFF` is set before native imports and pyproj networking is disabled explicitly. The supported transformations need no datum-shift grid download.

## Resource envelope

CI uses the `python:3.13-bookworm` base image with 1 GiB memory, two CPUs, single-thread native settings and serial pytest. That image tag and apt repository are not content-addressed locks. CI reports actual versions rather than representing them as immutable. Normal execution is designed for that small-fixture envelope; no benchmark or maximum RSS result is asserted. For hostile inputs, enforce process/container limits independently and evaluate the native parser risks.
