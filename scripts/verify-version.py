"""Verify that every shipped component uses the release version."""

import argparse
import json
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]


def app_version():
    source = (ROOT / "oneclickdl" / "_version.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
    if not match:
        raise RuntimeError("could not read __version__ from oneclickdl/_version.py")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", help="Release tag to validate, for example v0.2.0")
    args = parser.parse_args()

    version = app_version()
    manifest = json.loads(
        (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    )
    errors = []
    if manifest.get("version") != version:
        errors.append(
            f"extension version {manifest.get('version')!r} does not match app {version!r}"
        )
    if args.tag and args.tag != f"v{version}":
        errors.append(f"tag {args.tag!r} must be v{version}")

    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    print(f"version {version} is consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
