# Contributing

Contributions should preserve the narrow, inspectable development 0.1.0 contract. Use original code and synthetic fixtures only. Do not submit client imagery, private code, secrets or real personal data. Contributions are under the project's MIT license.

## Local checks

Use Linux and CPython 3.13. Install system `gdalinfo` and the pinned Python requirements as documented in README.md, then run:

```sh
python -m pip check
python tools/check_environment.py
python -m pytest -q
python -m raster_priority_mosaic demo --assert
```

Tests run serially with one native thread, within the intended 1 GiB/two-CPU envelope. Do not substitute mocks for the numerical Rasterio/GDAL/PROJ checks or for the required independent gdalinfo checks. Targeted failure-injection tests may mock a failure boundary explicitly.

## Review expectations

- Explain any contract change in docs/contract.md and both READMEs.
- Keep all dimensions/counts checked before ndarray allocation, while acknowledging earlier native metadata parsing.
- Test effective masks, valid zero, uncovered pixels, provenance and coverage independently of the implementation's overwrite loop.
- Use spherical Web Mercator equations only in independent expected-fixture calculations; production coordinates belong to GDAL/PROJ.
- Test one output buffer and strip groupings. Compare decoded arrays/masks, not TIFF bytes.
- Preserve no-overwrite publication, existing destinations and input bytes. Cleanup must be limited to owned artifacts.
- Do not add telemetry, runtime network access, arbitrary driver support or hidden CRS/resolution heuristics.
- Do not add release, package-publishing or remote-deployment workflows.
- Record actual dependency metadata when evaluating a platform; never invent wheel hashes or successful test results.

Use repository issues for non-sensitive reproducible bugs, including a tiny synthetic fixture and the environment tool output. Inspect reports before sharing them, especially local environment details. Report vulnerabilities privately through the link in SECURITY.md. General contact is through the [official homepage](https://lofranotecnologia.com.br).
