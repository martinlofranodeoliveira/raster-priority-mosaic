# Security

Raster Priority Mosaic 0.1.0 is a development version. No production-readiness, response-time or certification claim is made.

Report suspected vulnerabilities privately using [GitHub private vulnerability reporting](https://github.com/martinlofranodeoliveira/raster-priority-mosaic/security/advisories/new). Do not put exploit inputs, secrets or private imagery in public issues. General contact is available through the [official Lofrano Tecnologia homepage](https://lofranotecnologia.com.br).

## Boundaries

- Rasterio/GDAL and PROJ parse native metadata before the application can check decoded raster dimensions. This is not a parser sandbox. Malicious TIFFs can still exploit native library defects or consume native resources.
- Source count, decoded geometry, file bytes, output buffers and tool pipe output are bounded. Cache and warp-memory settings do not guarantee hard process RSS. Apply independent OS/container limits and isolation for untrusted files.
- Only regular self-contained local GTiff inputs are supported. URL/VSI/VRT, parent traversal, symlink paths and known external raster sidecars are rejected. PAM writes, directory scanning and PROJ networking are disabled. No source modification is requested.
- Input files, parent namespaces and host native-library configuration must stay stable and trusted. Hash rechecks detect ordinary mutation, not a hostile local filesystem race. Do not use a parent writable by an adversary.
- Atomic publication requires a supporting Linux filesystem. Locks coordinate cooperating writers, not distributed or malicious processes. Readers must wait for final publication. No automatic abandoned-stage cleanup is performed.
- The independent metadata tool is invoked without a shell, with fixed flags, bounded output and a monotonic deadline. Only its owned child is killed and reaped on failure.
- Version pins are not artifact-hash verification. See docs/dependencies.md before preparing a reproducible installation.

A useful private report includes the affected code/version, minimal original synthetic reproduction, expected and actual behavior, platform/native versions and impact. Share only material you are authorized to disclose. There is no need to include real imagery or personal information.
