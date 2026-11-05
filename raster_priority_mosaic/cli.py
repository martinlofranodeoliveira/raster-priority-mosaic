"""Strict JSON CLI and deterministic, asserting offline demonstration."""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile

import numpy as np
from pyproj import Transformer
import rasterio

from .core import mosaic
from .model import Grid, MosaicError, Source, lexical_path, local_file, offline_env
from .synthetic import create_fixtures, populate, write_tiff


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MosaicError("duplicate JSON key")
        result[key] = value
    return result


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise MosaicError("manifest fields do not match the documented schema")


def load_request(filename):
    path = local_file(filename, limit=65536)
    try:
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise MosaicError("manifest exceeds 65536 bytes")
        request = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise MosaicError("manifest must be UTF-8 JSON") from exc
    _keys(request, ("sources", "targetGrid"))
    grid = request["targetGrid"]
    _keys(grid, ("width", "height", "transform", "crs"))
    raw_sources = request["sources"]
    if not isinstance(raw_sources, list) or not 1 <= len(raw_sources) <= 8:
        raise MosaicError("manifest requires 1..8 sources")
    sources = []
    for source in raw_sources:
        _keys(source, ("path", "source_id", "priority"))
        if not isinstance(source["path"], str):
            raise MosaicError("manifest source paths must be strings")
        # Validate before joining: joining must not disguise URL or traversal syntax.
        lexical_path(source["path"])
        p = Path(source["path"])
        if not p.is_absolute():
            p = path.parent / p
        sources.append(Source(p, source["source_id"], source["priority"]))
    return sources, Grid(**grid)


def _arrays(directory):
    result = {}
    with offline_env():
        for name in ("data", "source_id", "coverage"):
            with rasterio.open(directory / (name + ".tif"), driver="GTiff") as dataset:
                result[name] = dataset.read(1).tolist()
                result[name + "_mask"] = dataset.read_masks(1).tolist()
    return result


def _require(condition, message):
    if not condition:
        raise MosaicError("demo assertion failed: " + message)


def demonstration(check):
    with tempfile.TemporaryDirectory(prefix="rpm-demo-") as temporary:
        root = Path(temporary)
        sources, grid = populate(root)
        mosaic(sources, grid, root / "aligned", window_rows=1)
        arrays = _arrays(root / "aligned")
        source_grid = Grid(3, 3, (1, 0, 0, 0, -1, 3), "EPSG:4326")
        cross_source = write_tiff(
            root / "cross.tif", [[11, 12, 13], [21, 22, 23], [31, 32, 33]],
            [[1, 1, 1], [1, 0, 1], [1, 1, 1]], source_grid,
        )
        unit = 111319.49079327357
        target = Grid(2, 2, (unit, 0, 0, 0, -unit, 3 * unit), "EPSG:3857")
        mosaic([Source(cross_source, 7, -3)], target, root / "cross", window_rows=2)
        cross = _arrays(root / "cross")
        with offline_env():
            project = Transformer.from_crs(4326, 3857, always_xy=True, allow_ballpark=False)
            x, y = project.transform(1, 0, errcheck=True)
            _, y45 = project.transform(0, 45, errcheck=True)
        if check:
            expected = {
                "data": [[10, 200, 0], [300, 40, 0]],
                "source_id": [[1, 2, 2], [2, 1, 0]],
                "coverage": [[1, 2, 2], [2, 1, 0]],
            }
            for name, value in expected.items():
                _require(arrays[name] == value, name)
                _require(arrays[name + "_mask"] == [[255, 255, 255], [255, 255, 0]], name + " mask")
            for name, value in {
                "data": [[11, 12], [21, 0]],
                "source_id": [[7, 7], [7, 0]],
                "coverage": [[1, 1], [1, 0]],
            }.items():
                _require(cross[name] == value, "cross-CRS " + name)
                _require(cross[name + "_mask"] == [[255, 255], [255, 0]], "cross-CRS mask")
            _require(abs(x - 111319.49079327357) <= 0.000001, "one-degree x")
            _require(abs(y) <= 0.00000001, "equatorial y")
            _require(abs(y45 - 5621521.486192066) <= 0.000001, "45-degree y")
        return {
            "version": "0.1.0", "assertions": "passed" if check else "not requested",
            "data": arrays["data"], "source_id": arrays["source_id"],
            "coverage": arrays["coverage"], "mask": arrays["data_mask"],
            "cross_crs_data": cross["data"],
        }


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # ArgumentParser's usual diagnostic embeds untrusted argument values.
        raise MosaicError("invalid command arguments; use --help")


def parser():
    result = _Parser(prog="raster-priority-mosaic")
    result.add_argument("--version", action="version", version="0.1.0 (development)")
    commands = result.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="run original offline fixtures in owned temporary storage")
    demo.add_argument("--assert", dest="check", action="store_true")
    demo.add_argument("--json", action="store_true", help="emit only JSON")
    fixtures = commands.add_parser("fixtures", help="create synthetic TIFFs and request.json")
    fixtures.add_argument("directory")
    build = commands.add_parser("mosaic", help="publish a new mosaic bundle from a JSON request")
    build.add_argument("request")
    build.add_argument("destination")
    build.add_argument("--window-rows", type=int, default=64)
    build.add_argument("--json", action="store_true", help="emit the complete report")
    return result


def _discard_failed_standard_stream(stream):
    # CPython retries standard-stream flushes during shutdown and otherwise exits120.
    # Redirect only the original process sink after a terminal write/flush failure.
    if stream is not sys.__stdout__ and stream is not sys.__stderr__:
        return
    try:
        descriptor = stream.fileno()
        if descriptor not in (1, 2):
            return
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, descriptor)
        finally:
            os.close(null)
    except (OSError, ValueError):
        pass


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.command == "fixtures":
            create_fixtures(args.directory)
            print("Synthetic fixtures written: " + args.directory)
        elif args.command == "mosaic":
            sources, grid = load_request(args.request)
            report = mosaic(sources, grid, args.destination, window_rows=args.window_rows)
            if args.json:
                print(json.dumps(report, sort_keys=True, allow_nan=False))
            else:
                print(f"Published {report['valid_pixels']} valid pixels to {args.destination}")
        else:
            report = demonstration(args.check)
            if not args.json:
                print("Raster Priority Mosaic 0.1.0 (development)")
                for key in ("data", "source_id", "coverage", "mask", "cross_crs_data"):
                    print(key + ": " + json.dumps(report[key]))
                print("assertions: " + report["assertions"])
            print(json.dumps(report, sort_keys=True, allow_nan=False))
        sys.stdout.flush()
        return 0
    except (MosaicError, OSError) as exc:
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            _discard_failed_standard_stream(sys.stdout)
        message = str(exc) if isinstance(exc, MosaicError) else "local I/O operation failed"
        try:
            print("error: " + message, file=sys.stderr)
            sys.stderr.flush()
        except (OSError, ValueError):
            _discard_failed_standard_stream(sys.stderr)
        return 2
