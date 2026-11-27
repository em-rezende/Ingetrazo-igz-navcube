"""Build the distributable ZIP for the igz_navcube IngeTrazo extension.

The community catalog expects a ZIP holding ONE folder with an
``__init__.py`` inside (the package IngeTrazo imports), so the archive is
written as ``igz_navcube/<files>`` straight from the source tree — no staging
copy, no caches, no development files.

    python build_zip.py

Prints the archive path and the SHA-256 to paste into the catalog entry
(``extensions/igz_navcube.toml``).
"""
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "igz_navcube"
DIST = ROOT / "dist"
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIXES = {".pyc", ".pyo"}


def version():
    """The version announced in README.md (``- **Version:** 1.0.1``)."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"\*\*Version:\*\*\s*([0-9][0-9A-Za-z.+_-]*)", text)
    if not match:
        raise SystemExit("README.md has no '- **Version:** x.y.z' line")
    return match.group(1).rstrip(".-_")


def members():
    """``(path, archive name)`` of everything that ships, in stable order."""
    for path in sorted(PACKAGE.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix in SKIP_SUFFIXES or SKIP_DIRS & set(path.parts):
            continue
        yield path, path.relative_to(ROOT).as_posix()


def main():
    entry = PACKAGE / "__init__.py"
    if not entry.is_file():
        raise SystemExit(f"missing entry point: {entry}")
    DIST.mkdir(exist_ok=True)
    target = DIST / f"igz_navcube-v{version()}.zip"
    files = list(members())
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, name in files:
            archive.write(path, name)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    print(f"{target}  ({target.stat().st_size} bytes, {len(files)} files)")
    print(f"sha256 = {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
