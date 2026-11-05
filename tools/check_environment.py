"""Report installed distribution metadata and native versions without network access.

METADATA hashes identify installed metadata, not downloaded wheel archives.
"""
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import platform
import sys

from raster_priority_mosaic.inspection import system_gdal_version
from raster_priority_mosaic.model import offline_env, runtime_versions


def main():
    if sys.version_info[:2] != (3, 13):
        raise RuntimeError("the documented environment is CPython 3.13")
    requirements = Path(__file__).parent.parent / "requirements.txt"
    installed = {}
    for line in requirements.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, expected = line.split("==")
        item = distribution(name)
        if item.version != expected:
            raise RuntimeError(f"{name}: expected {expected}, installed {item.version}")
        metadata = item.read_text("METADATA")
        if metadata is None:
            raise RuntimeError(f"{name}: installed METADATA is missing")
        installed[name] = {
            "version": item.version,
            "requires_python": item.metadata.get("Requires-Python"),
            "metadata_sha256": hashlib.sha256(metadata.encode("utf-8")).hexdigest(),
        }
    with offline_env():
        native = runtime_versions()
        native["system_gdalinfo"] = system_gdal_version()
    print(json.dumps({
        "python": platform.python_version(), "distributions": installed, "native": native,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
