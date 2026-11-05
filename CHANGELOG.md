# Changelog

## 0.1.0 — Unreleased development version

- Explicit EPSG:4326/EPSG:3857 north-up target grids and bounded local uint16 sources.
- Independent nearest-neighbor value and validity reprojection, including valid zero.
- Highest-priority valid selection, explicit source IDs and all-contributor coverage.
- Internal output masks and a JSON report with source digests and native/tool versions.
- Owned staging, exclusive writer locks and Linux atomic no-replace bundle publication.
- Bounded independent system-gdalinfo metadata checks.
- Original synthetic CLI fixtures, asserting offline demo, 32 fixed loop-oracle cases and adversarial regression tests.
- English and Brazilian Portuguese usage/API documentation and explicit unsupported boundaries.

This entry describes the development source contract, not a published release or a production-readiness claim.
