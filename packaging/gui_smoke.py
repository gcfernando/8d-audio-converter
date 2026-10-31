"""Check the extracted Windows GUI, real warm-up and constructor-close races."""

from __future__ import annotations

import argparse
import importlib.util
import json
import stat
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The Windows frozen GUI smoke check needs a Windows runner")
    root = Path(__file__).resolve().parents[1]
    evidence = root / "artifacts" / "gui-smoke" / uuid.uuid4().hex
    payload = evidence / "package with spaces"
    payload.mkdir(parents=True)
    with zipfile.ZipFile(args.archive) as archive:
        names = set()
        for entry in archive.infolist():
            path = Path(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or ":" in entry.filename
                or "\\" in entry.filename
                or entry.filename.casefold() in names
                or stat.S_ISLNK(entry.external_attr >> 16)
            ):
                raise ValueError("Unsafe Windows package member")
            names.add(entry.filename.casefold())
        if archive.testzip() is not None:
            raise ValueError("GUI package CRC check failed")
        archive.extractall(payload)
    executable = payload / "Audio8D" / "Audio8D.exe"
    if not executable.is_file():
        raise ValueError("The ZIP does not contain Audio8D/Audio8D.exe")
    spec = importlib.util.spec_from_file_location(
        "audio8d_smoke_builder", root / "packaging/build_release.py"
    )
    assert spec is not None and spec.loader is not None
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    results = []
    for case in ("warm", "close-style", "close-customize"):
        home = evidence / case
        home.mkdir()
        report = home / "result.json"
        env = builder.user_environment(home)
        env.update(AUDIO8D_GUI_SMOKE_REPORT=str(report), AUDIO8D_GUI_SMOKE_CASE=case)
        completed = subprocess.run(
            [str(executable)], cwd=payload, env=env, timeout=75, capture_output=True
        )
        if completed.returncode or not report.is_file():
            raise RuntimeError(f"Frozen GUI {case} failed; inspect {home}")
        data = json.loads(report.read_text(encoding="utf-8"))
        if not data["success"]:
            raise RuntimeError(f"Frozen GUI {case} regression: {data}")
        results.append(data)
    (evidence / "summary.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    print(
        "PASS: frozen GUI warm-up and both constructor-close cases; "
        f"evidence: {evidence}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
