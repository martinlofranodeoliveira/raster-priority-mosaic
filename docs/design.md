# Design — development 0.1.0

## Data flow

1. Check the pinned Python runtime distributions and enter the offline native environment.
2. Validate the target and all request-level limits before decoding raster arrays.
3. Open each source read-only, with GTiff as the permitted reader. Inspect native metadata for **all** sources before requesting any raster ndarray. Native TIFF metadata parsing has already happened at this point.
4. Read bounded raw uint16 values and `read_masks(1)` separately. Hash source bytes with bounded reads. Hold at most eight bounded source pairs.
5. Acquire the destination's exclusive writer lock and create an owned stage in its parent.
6. Render canonical target rows. Reproject raw values and byte masks separately, using identical source/target geometry, nearest sampling and zero-initialized destination arrays. No numeric source or destination nodata is passed to either warp.
7. Count every nonzero warped validity mask. Visit sources in increasing priority and update values/owner IDs only at valid pixels.
8. Write buffered output strips and explicit internal masks. Close all TIFF writers.
9. Invoke the system `gdalinfo` independently for every TIFF. Check dimensions, transform, CRS, band type, missing nodata and explicit dataset mask flags. Reject unexpected stage files, including external masks. Recheck source digests and write the report.
10. Atomically publish the complete directory with Linux `renameat2(RENAME_NOREPLACE)`. Release only the owned lock.

## Why decode bounded sources?

This scope favors clarity over streaming arbitrarily large source rasters. One source contributes at most 2 MiB of uint16 values and 1 MiB of validity bytes; eight sources contribute at most 24 MiB of these decoded arrays. Output buffering is at most 5 MiB for values, owner IDs and coverage, plus mask buffers and temporary/native work. Metadata, Python/native overhead and GDAL buffers are additional.

Source dimensions, pixel count, count of sources and file bytes are bounded independently. Source metadata checks precede `_decode`, a separately testable allocation boundary. The 16 MiB GDAL cache and 16 MiB warp setting are tuning parameters, **not** enforceable process memory ceilings. TIFF block decoding can allocate beyond a requested read window. Native drivers and coordinate libraries remain a security boundary outside this implementation.

## Canonical sampling units versus output strips

GDAL can subdivide approximate coordinate transforms differently for different destination shapes. A nearest-neighbor decision near a boundary could otherwise change when an output strip changes height. This implementation always warps one entire target row at a time, deriving its transform directly from the global affine and the global row index. `window_rows` only groups those rows for output writes. The two independent warps for a contributor have the same geometry and shape.

This is intentionally more native-call-heavy than a large adaptive warp. There is no throughput claim. The bounded, small-fixture use case values reproducible sampling decisions over maximum throughput. Tests compare one output buffer with row strips and intermediate strip heights, including a non-equatorial cross-CRS grid. A whole output buffer is not a different resampling algorithm.

## Validity and ownership

GDAL masks have nonzero=valid. Numeric zero does not encode validity. Reading raw arrays rather than passing a dataset band to `reproject` prevents a source `nodata=0` declaration from silently turning an explicitly valid zero into absence. If a TIFF has no explicit mask, GDAL's effective `read_masks` result, including any nodata-derived validity, is authoritative.

All three outputs share contributor validity, with an internal dataset mask. Uncovered storage values are deterministically zero. There is no output nodata declaration. Counts describe all valid sampled contributors, not just the selected source. Source input order has no effect because priorities are explicit and distinct.

## CRS boundary

Production uses GDAL/PROJ, never a hand-written coordinate parser or projection. Only two EPSG definitions are accepted, with always-x/y validation conventions and a nonpolar rectangular domain. Grid bounds in EPSG:3857 are obtained from PROJ's projection of the allowed longitude/latitude limits.

Independent tests use the spherical Web Mercator equations with R=6378137. They check one degree at the equator, latitude 45°, and inverse mapping of tiny target centers more than 0.410 source pixels from a boundary. These test equations are not a second production projection implementation. General ellipsoidal Mercator is not substituted for EPSG:3857.

## Publication and ownership

The destination parent must be local, trusted and stable. A hidden exclusive-create lock rejects a second cooperating writer immediately. A unique stage has mode 0700 from `mkdtemp`; no broad cleanup search is used. Cleanup checks the recorded stage inode before recursively removing that stage only. Lock cleanup similarly checks its inode.

An existence check alone is insufficient: ordinary POSIX directory rename can replace an empty directory. The final kernel no-replace rename is mandatory, even if a destination appeared after the lock was acquired. Unsupported libc, kernel or filesystem behavior fails rather than falling back to a check-then-rename race. Different destinations can be handled by separate processes. Native operations inside one process must be serialized because native/environment configuration is process-global; overlapping API calls are rejected.

Normal exceptions publish nothing. After rename, all four files are visible as one bundle and are not modified. Readers open only completed destinations. The application never deletes completed mosaics. Crash recovery is manual: inspect abandoned locks/stages in the trusted parent, ensure no writer is active, then remove only those owned artifacts explicitly. No background worker, lease timeout or age-based cleanup exists. Atomic visibility is not a promise of fsync/power-loss durability.

## Independent processes

`gdalinfo` is a required, separate executable, not a Rasterio metadata echo. Commands contain fixed flags, no shell, no statistics or histogram requests, and only owned output paths. Each invocation has a five-second monotonic deadline, a combined 128 KiB pipe-output limit and no stdin. The version invocation has a 4 KiB output limit. Both pipes are drained, failures kill and reap the owned process, and no process is deliberately left running. At most one tool child runs at a time; a mosaic uses three metadata invocations and one version invocation.

PAM writes and network coordinate access are disabled in both stacks. Directory scanning is disabled and known external input sidecars are rejected. Local GTiff validation is not a claim that arbitrary native file parsing cannot exploit the host. Configuration and library search paths supplied by the host must also be trusted.

## Regression strategy

Tests include the exact 2x2 acceptance fixture, explicit valid-zero/nodata precedence, uncovered pixels, eight contributors, 32 fixed arithmetic priority fixtures with a nested-loop candidate oracle, spherical coordinate references and inverse cross-CRS sampling. They inspect arrays, masks, IDs, counts and independent metadata, not visual appearance or encoded TIFF bytes.

Adversarial tests exercise strict integer typing, invalid grids, unsupported types, oversized decoded metadata before allocation, a corrupt second source, URLs/VSI/traversal/symlinks/sidecars, duplicate manifest keys, existing destinations, late failure cleanup, input mutation, a late-created empty destination, writer contention, preservation of unrelated stages, subprocess output limits and monotonic deadlines.

## Source references

These references justify semantics; implementation and fixture code are original:

- https://rasterio.readthedocs.io/en/stable/topics/reproject.html
- https://rasterio.readthedocs.io/en/stable/topics/masks.html
- https://rasterio.readthedocs.io/en/stable/topics/windowed-rw.html
- https://proj.org/en/stable/operations/projections/webmerc.html
- https://proj.org/en/stable/operations/projections/merc.html
- https://gdal.org/en/stable/programs/gdalinfo.html

No broad GeoTIFF or CRS standards conformance is claimed: native libraries handle file encoding and only the explicit subset in the contract is supported.
