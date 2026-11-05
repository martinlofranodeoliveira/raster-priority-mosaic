import json
import os
import subprocess
import sys

from raster_priority_mosaic.cli import main
from raster_priority_mosaic.synthetic import create_fixtures


def test_asserting_demo_machine_output():
    result = subprocess.run(
        [sys.executable, "-m", "raster_priority_mosaic", "demo", "--assert", "--json"],
        capture_output=True, text=True, timeout=90, env=os.environ.copy(), check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "version": "0.1.0", "assertions": "passed",
        "data": [[10, 200, 0], [300, 40, 0]],
        "source_id": [[1, 2, 2], [2, 1, 0]],
        "coverage": [[1, 2, 2], [2, 1, 0]],
        "mask": [[255, 255, 255], [255, 255, 0]],
        "cross_crs_data": [[11, 12], [21, 0]],
    }


def test_fixture_manifest_cli(tmp_path, capsys):
    workspace = tmp_path / "fixtures"
    assert main(["fixtures", str(workspace)]) == 0
    capsys.readouterr()
    assert main(["mosaic", str(workspace / "request.json"), str(tmp_path / "out"), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["valid_pixels"] == 5
    assert report["coverage_histogram"] == [1, 2, 3]
    assert main(["mosaic", str(workspace / "request.json"), str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "already exists" in captured.err
    assert "Traceback" not in captured.err


def test_manifest_duplicate_keys_unknown_fields_and_size(tmp_path, capsys):
    path = tmp_path / "request.json"
    for text in (
        '{"sources": [], "sources": [], "targetGrid": {}}',
        '{"sources": [], "targetGrid": {}, "extra": 1}',
        '{"sources": [], "targetGrid": {"width": NaN}}',
        " " * 65537,
    ):
        path.write_text(text, encoding="utf-8")
        assert main(["mosaic", str(path), str(tmp_path / "out")]) == 2
        assert not (tmp_path / "out").exists()
        assert "error:" in capsys.readouterr().err


def test_manifest_relative_source_paths_use_manifest_directory(tmp_path, monkeypatch, capsys):
    workspace = tmp_path / "fixture"
    create_fixtures(workspace)
    another = tmp_path / "elsewhere"
    another.mkdir()
    monkeypatch.chdir(another)
    assert main(["mosaic", str(workspace / "request.json"), str(another / "out")]) == 0
    assert "Published 5 valid pixels" in capsys.readouterr().out


def test_manifest_requires_utf8_and_handles_deep_json_without_raw_diagnostics(tmp_path, capsys):
    path = tmp_path / "private-customer-marker.json"
    for raw in (
        b"[" * 1200 + b"0" + b"]" * 1200,
        '{"sources": [], "targetGrid": {}}'.encode("utf-16"),
        b'{"private-customer-marker":1,"private-customer-marker":2}',
    ):
        path.write_bytes(raw)
        assert main(["mosaic", str(path), str(tmp_path / "out")]) == 2
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "Traceback" not in captured.err
        assert "private-customer-marker" not in captured.err
        assert not (tmp_path / "out").exists()


def test_invalid_arguments_do_not_echo_values(capsys):
    assert main(["mosaic", "request.json", "out", "--window-rows", "private-customer-marker"]) == 2
    assert "private-customer-marker" not in capsys.readouterr().err


def test_corrupt_native_input_diagnostic_does_not_echo_path(tmp_path, capsys):
    create_fixtures(tmp_path / "fixtures")
    path = tmp_path / "fixtures" / "request.json"
    request = json.loads(path.read_text())
    corrupt = tmp_path / "fixtures" / "private-customer-marker.tif"
    corrupt.write_bytes(b"not a TIFF")
    request["sources"][0]["path"] = corrupt.name
    path.write_text(json.dumps(request))
    assert main(["mosaic", str(path), str(tmp_path / "out")]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "private-customer-marker" not in captured.err
    assert "Traceback" not in captured.err
    assert not (tmp_path / "out").exists()


def test_successful_output_flush_failure_is_failure(monkeypatch):
    import io
    import raster_priority_mosaic.cli as cli
    class BrokenOutput(io.StringIO):
        def flush(self):
            raise OSError("private-customer-marker")
    diagnostic = io.StringIO()
    monkeypatch.setattr(cli.sys, "stdout", BrokenOutput())
    monkeypatch.setattr(cli.sys, "stderr", diagnostic)
    monkeypatch.setattr(cli, "demonstration", lambda check: {"ok": True})
    assert main(["demo", "--json"]) == 2
    assert diagnostic.getvalue() == "error: local I/O operation failed\n"


def test_real_cli_preserves_exit2_when_standard_sink_is_full():
    with open("/dev/full", "wb") as full:
        output = subprocess.run(
            [sys.executable, "-m", "raster_priority_mosaic", "demo", "--assert", "--json"],
            stdout=full, stderr=subprocess.PIPE, timeout=90, check=False,
        )
        diagnostic = subprocess.run(
            [sys.executable, "-m", "raster_priority_mosaic", "invalid-owner-option"],
            stdout=subprocess.PIPE, stderr=full, timeout=90, check=False,
        )
    assert output.returncode == 2
    assert output.stderr == b"error: local I/O operation failed\n"
    assert diagnostic.returncode == 2
    assert diagnostic.stdout == b""
