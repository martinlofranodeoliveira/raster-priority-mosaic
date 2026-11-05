"""Independent, bounded system-gdalinfo metadata checks."""
import json
import math
import os
import selectors
import shutil
import subprocess
import time

from pyproj import CRS

from .model import MosaicError

OUTPUTS = {"data.tif": "UInt16", "source_id.tif": "UInt16", "coverage.tif": "Byte"}


def bounded_command(args, *, timeout=5.0, limit=131072):
    """Bound combined pipe bytes and elapsed monotonic time; reap the owned child."""
    env = os.environ.copy()
    env.update({
        "PROJ_NETWORK": "OFF", "GDAL_PAM_ENABLED": "NO",
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR", "GDAL_NUM_THREADS": "1",
        "GDAL_SKIP": "VRT", "CPL_DEBUG": "OFF", "LC_ALL": "C",
    })
    deadline = time.monotonic() + timeout
    buffers = {"out": bytearray(), "err": bytearray()}
    try:
        process = subprocess.Popen(
            args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, env=env, shell=False,
        )
    except OSError as exc:
        raise MosaicError("cannot start the independent metadata tool") from exc
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "out")
            selector.register(process.stderr, selectors.EVENT_READ, "err")
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise MosaicError("metadata subprocess exceeded its monotonic deadline")
                for key, _ in selector.select(remaining):
                    block = os.read(key.fileobj.fileno(), 8192)
                    if not block:
                        selector.unregister(key.fileobj)
                        continue
                    if len(buffers["out"]) + len(buffers["err"]) + len(block) > limit:
                        raise MosaicError("metadata subprocess exceeded its output limit")
                    buffers[key.data].extend(block)
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise MosaicError("metadata subprocess exceeded its monotonic deadline")
            try:
                result = process.wait(timeout=remaining)
            except subprocess.TimeoutExpired as exc:
                raise MosaicError("metadata subprocess exceeded its monotonic deadline") from exc
        if result != 0:
            raise MosaicError(f"metadata subprocess failed with exit status {result}")
        try:
            return bytes(buffers["out"]).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise MosaicError("metadata subprocess returned non-UTF-8 output") from exc
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()
        process.stderr.close()


def executable():
    tool = shutil.which("gdalinfo")
    if tool is None:
        raise MosaicError("system gdalinfo is required; install gdal-bin")
    return tool


def system_gdal_version():
    text = bounded_command([executable(), "--version"], limit=4096).strip()
    if not text.startswith("GDAL "):
        raise MosaicError("unexpected gdalinfo version response")
    return text


def inspect_bundle(directory, grid):
    tool = executable()
    summaries = {}
    expected_transform = [grid.transform[i] for i in (2, 0, 1, 5, 3, 4)]
    for name, band_type in OUTPUTS.items():
        text = bounded_command([
            tool, "-json", "-nomd", "-norat", "-noct", "-nogcp", "-nofl",
            str(directory / name),
        ])
        try:
            result = json.loads(text)
            if result["size"] != [grid.width, grid.height]:
                raise ValueError("dimensions")
            actual_crs = CRS.from_wkt(result["coordinateSystem"]["wkt"])
            if not actual_crs.equals(CRS.from_user_input(grid.crs), ignore_axis_order=True):
                raise ValueError("CRS")
            actual_transform = result["geoTransform"]
            if len(actual_transform) != 6 or any(
                not math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-9)
                for a, b in zip(actual_transform, expected_transform)
            ):
                raise ValueError("transform")
            bands = result["bands"]
            if len(bands) != 1 or bands[0]["type"] != band_type or "noDataValue" in bands[0]:
                raise ValueError("band declaration")
            flags = bands[0]["mask"]["flags"]
            if flags != ["PER_DATASET"]:
                raise ValueError("explicit dataset mask")
        except (KeyError, TypeError, ValueError, pyproj_error()) as exc:
            raise MosaicError(f"independent gdalinfo check failed for {name}") from exc
        summaries[name] = {
            "size": result["size"], "crs": grid.crs,
            "band_type": band_type, "mask_flags": flags,
        }
    if {p.name for p in directory.iterdir()} != set(OUTPUTS):
        raise MosaicError("unexpected sidecar or file in staged raster bundle")
    return {"version": system_gdal_version(), "outputs": summaries}


def pyproj_error():
    # Kept local so malformed native CRS metadata is translated into the public error.
    from pyproj.exceptions import CRSError
    return CRSError
