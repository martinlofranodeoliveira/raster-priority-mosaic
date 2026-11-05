# Public contract — development 0.1.0

This document defines the supported subset. Unsupported cases fail explicitly rather than triggering inference or format conversion.

## API

```python
Source(path, source_id, priority)
Grid(width, height, transform, crs)
mosaic(sources, targetGrid, destination, *, window_rows=64) -> dict
```

`Source` and `Grid` are frozen dataclasses. Construction does not perform I/O; `mosaic` validates them. `sources` is a list or tuple of 1..8 sources. The public `targetGrid` argument is a `Grid`, not an unvalidated dictionary. `destination` is a local string or `Path` naming a new directory in an existing parent. The return value equals the parsed contents of `report.json`. Expected rejections and processing/publication failures raise `MosaicError`.

IDs are unique exact Python integers in 1..65535. Zero is reserved. Priorities are unique exact Python integers, with larger values winning. Both reject bool, floats and NumPy integer scalars; priorities have no application-defined numeric range. No time or source-list position breaks ties, because ties are rejected.

`window_rows` is an exact Python integer in 1..1024. It bounds the output-buffer height and does not change canonical one-row reprojection units. Width and height are exact integers in 1..1024; each source and target is limited to 1,048,576 decoded pixels. Limits are checked before raster ndarray reads/allocations; native source metadata parsing necessarily precedes source-dimension validation.

## Geometry

A target explicitly provides all six affine coefficients `(a,b,c,d,e,f)`, dimensions and CRS. Coefficients must be finite Python int/float values, not bool. Coordinates at pixel corners are:

- `x = a * column + b * row + c`
- `y = d * column + e * row + f`

Only `a > 0`, `e < 0`, `b = d = 0` are accepted. The derived right and bottom edges must be finite, representably distinct, and inside the allowed domain. Pixel sampling uses nearest-neighbor GDAL conventions on the specified global target grid. Pixel centers are at half-integer indices.

The target CRS is exactly `EPSG:4326` or `EPSG:3857`. Source CRS metadata must equal one of these canonical Rasterio CRS definitions. Sources must also have north-up finite geometry and satisfy the same domain. Coordinates use x/y order: longitude/latitude in EPSG:4326; easting/northing in EPSG:3857.

The entire corner extent must fit longitude [-180,180] and latitude [-80,80]. For EPSG:3857 the corresponding projected rectangular limits are computed by PROJ. No longitude wrapping, polar singularities, rotated/south-up grids, arbitrary CRS definitions, GCP/RPC-driven geometry or inferred resolution are supported. The six-element affine is authoritative; there is no best-CRS heuristic.

EPSG:3857 is spherical Web Mercator with R=6378137, not ellipsoidal Mercator. The independent reference values are x=111319.49079327357 metres at longitude 1°, latitude 0°, y=0 there, and y=5621521.486192066 metres at latitude 45°.

## Input files and environment

Inputs are regular, self-contained, local GTiff files of at most 64 MiB each, containing exactly one uint16 band and internal georeferencing. The application opens them read-only with the GTiff reader. There is no image/TIFF/CRS parser in application code.

URL, colon, `/vsi` and parent-traversal syntax, symlink path components, VRT and external `.msk`, `.aux.xml` or `.ovr` sidecars are unsupported. Paths can otherwise be absolute or relative local paths. Directory scanning is disabled. TIFF metadata and data remain native-parser input, not sandboxed content. No arbitrary auxiliary-file format detection is promised.

`PROJ_NETWORK=OFF`, `GDAL_PAM_ENABLED=NO` and single-thread native settings are applied. pyproj networking is explicitly disabled. Offline EPSG definitions must be available in both installed native stacks; there are no grid-download or online fallbacks. Runtime distributions are checked against the exact NumPy/Rasterio/pyproj pins. System `gdalinfo` must be available in PATH and support the documented flags. Host environment/library paths must be trusted.

Inputs and their namespace must remain immutable for the entire operation. SHA-256 is recorded before source decoding and checked again before publication; this detects ordinary mutation, not adversarial races or changes deliberately reverted between checks. The API does not lock input owners. Caller-controlled parents must remain stable and must not be attacked by another local process.

## Pixel rule

For each source, raw values and the effective GDAL `read_masks(1)` result are separately warped with nearest-neighbor sampling under identical geometry. `read_masks` nonzero means valid. It is not NumPy masked-array polarity. Outside-source warped masks are zero. No numeric nodata is passed to either warp, so a valid zero from an explicit source mask survives even when the source also declares nodata=0. Without an explicit source mask, GDAL's nodata-derived or all-valid mask remains the effective validity definition.

For each target pixel, collect every source whose warped mask is nonzero:

1. Coverage is the size of this collection, including lower-priority contributors.
2. If nonempty, choose its source with greatest priority; copy that value and explicit ID.
3. If empty, store data=0, ID=0, coverage=0 and mask=0.
4. If nonempty, mask=255 even when the winning numeric data is zero.

All output-buffer groupings yield identical decoded arrays because canonical row warp calls and their global-grid transforms are unchanged. Cross-CRS decisions exactly at source pixel edges remain GDAL/PROJ behavior; no alternate tie-breaking rule is imposed.

## Bundle and report

Publication contains exactly:

- `data.tif`: uint16, one band.
- `source_id.tif`: uint16, one band.
- `coverage.tif`: uint8, one band, values 0..8.
- `report.json`: UTF-8, schema_version 1.

All TIFFs have the target transform, CRS and dimensions, no nodata declaration, and an explicit internal PER_DATASET mask equal to `255 * (coverage > 0)`. There are no required external sidecars. All three masks share contributor validity, including the ID and coverage outputs. Read raw ID/coverage bands to inspect stored zero in uncovered pixels.

The report contains application/version/status, the explicit grid, sources in increasing priority order with ID/priority/SHA-256, a coverage histogram with indices 0..source_count, `valid_pixels`, actual Python-native library versions, system gdalinfo version and checked output metadata summaries. It contains no timestamps, source absolute paths or execution-duration claims. Native versions can differ by installation; encoded TIFF bytes and source TIFF hashes can differ across native encoders even when decoded arrays agree.

The metadata oracle uses actual `gdalinfo -json -nomd -norat -noct -nogcp -nofl` in fixed serial subprocesses. It checks size, CRS, transform, one band, dtype, absent nodata and dataset-mask flags. It requests no statistics, checksums or histograms. Each process has a five-second monotonic deadline and 128 KiB combined stdout/stderr limit; the version query is limited to 4 KiB. Failure prevents publication.

## Publication and lifecycle

Only Linux with libc/kernel/filesystem support for `renameat2(RENAME_NOREPLACE)` is supported. The stage is created in the destination parent, guaranteeing the same filesystem for rename. An exclusive-create lock allows one cooperating writer per destination. There is no waiting, lease or time-dependent priority. A destination that already exists, even empty, is never replaced. The final kernel rename still enforces this if a destination appears late.

Normal failures publish no partial destination. Cleanup removes only the recorded owned stage and owned writer lock. Existing destinations and source files are not modified. Abrupt process termination may leave a stage or lock; inspection/removal is explicit and manual. Completed bundles persist until explicitly removed by their owner. Readers access only the completed destination after publication. Atomic visibility does not imply crash durability or distributed locking. Remote filesystem semantics are outside this contract.

Native environment configuration is process-global. Overlapping `mosaic` calls in one process are rejected. Independent destination operations can run in separate processes, subject to their resource budgets. The application starts no background workers or network requests. Cache/warp options are not hard RSS guarantees.

## CLI

- `python -m raster_priority_mosaic fixtures DIRECTORY`: publish synthetic a.tif, b.tif and request.json into a new directory.
- `python -m raster_priority_mosaic mosaic REQUEST DESTINATION [--window-rows N] [--json]`: publish a bundle; print a summary or the full report.
- `python -m raster_priority_mosaic demo [--assert] [--json]`: temporary offline fixtures and two mosaics; optional explicit checks that remain active under Python `-O`.
- `python -m raster_priority_mosaic --version`: development version.

A request is UTF-8 JSON, at most 65536 bytes, with exactly `sources` and `targetGrid`. A source object has exactly `path`, `source_id`, `priority`. A grid has exactly `width`, `height`, `transform`, `crs`. Duplicate keys and extra fields are rejected. Relative source paths resolve against the request's parent. The destination is supplied separately, never from the manifest. CLI errors exit 2; successful execution exits 0. Handled CLI failures use bounded application messages without raw native errors, path values or argument values; no traceback is printed. UTF-16/32 input is rejected, and JSON recursion failures are handled as invalid UTF-8 JSON. Output is explicitly flushed before a successful return.

## Resumo do contrato em português

A API exige fontes locais uint16 de uma banda, IDs e prioridades inteiros estritos únicos, grade explícita orientada ao norte e CRS EPSG:4326 ou EPSG:3857. A extensão inteira fica dentro de longitude ±180° e latitude ±80°. A máscara GDAL usa não zero como válido. O maior valor de prioridade vence apenas entre contribuições válidas; cobertura conta todas elas. Zero válido não significa ausência. As três saídas usam máscara interna, sem nodata. O pacote inteiro é publicado por renomeação Linux sem substituição. Entradas e pais devem permanecer imutáveis; leituras ocorrem apenas após publicação. Limites de matrizes não isolam os analisadores nativos. Veja README.pt-BR.md para comandos e exemplos completos.
