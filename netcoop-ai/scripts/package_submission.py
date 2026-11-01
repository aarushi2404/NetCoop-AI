"""Build a clean submission ZIP: source, config, docs, tests, data and generated reports only.

    python scripts/package_submission.py                     # -> build/netcoop-ai-submission.zip
    python scripts/package_submission.py --include-web-build # also ship web/dist (judges without Node)

Excludes the same things as .gitignore: virtual environments, node_modules, caches, build output.
"""
from __future__ import annotations

import argparse
import fnmatch
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".venv", "venv", "env", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
             ".ruff_cache", ".vite", "build", "out", "logs", ".idea", ".vscode", "htmlcov"}
SKIP_FILES = ("*.pyc", "*.pyo", "*.zip", "*.tsbuildinfo", "*.log", ".DS_Store", "Thumbs.db", ".coverage")


def wanted(rel: Path, include_web_build: bool) -> bool:
    parts = rel.parts
    if any(p in SKIP_DIRS or p.endswith(".egg-info") for p in parts[:-1]):
        return False
    if parts[:2] == ("web", "dist") and not include_web_build:
        return False
    return not any(fnmatch.fnmatch(parts[-1], pat) for pat in SKIP_FILES)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=str(ROOT / "build" / "netcoop-ai-submission.zip"))
    ap.add_argument("--include-web-build", action="store_true")
    a = ap.parse_args()
    out = Path(a.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    files = sorted(p for p in ROOT.rglob("*") if p.is_file() and p != out
                   and wanted(p.relative_to(ROOT), a.include_web_build))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, Path("netcoop-ai") / p.relative_to(ROOT))
    print(f"{len(files)} files, {out.stat().st_size / 1e6:.1f} MB -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
