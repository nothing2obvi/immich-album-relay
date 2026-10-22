#!/usr/bin/env python3
"""Copy only publishable application paths. Never delete or copy back private data."""

import hashlib
import json
import os
import shutil
import sys
from pathlib import Path

FILES = (
    "Dockerfile",
    ".dockerignore",
    ".gitignore",
    "pyproject.toml",
    "requirements.lock",
    "README.md",
    "LICENSE",
    "uv.lock",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "compose.yml",
    "compose.test.yml",
    "config.example.yml",
    ".env.example",
    "Makefile",
)
TREES = {
    "src": {".py"},
    "scripts": {".py", ".sh"},
    "tests": {".py"},
    "docs": {".md"},
    ".github": {".yml", ".yaml"},
}
MANIFEST = ".relay-managed.json"


def allowed(relative):
    path = Path(relative)
    return (
        not path.is_absolute()
        and ".." not in path.parts
        and (
            relative in FILES
            or (
                len(path.parts) > 1
                and path.parts[0] in TREES
                and path.suffix in TREES[path.parts[0]]
                and "__pycache__" not in path.parts
            )
        )
    )


def safe_target(destination, relative):
    target = destination / relative
    if (
        not allowed(relative)
        or target.is_symlink()
        or any(p.is_symlink() for p in target.parents if p != destination.parent)
    ):
        raise ValueError("Symlink or invalid managed deployment path")
    return target


def synchronize(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or source in destination.parents or destination in source.parents:
        raise ValueError("Source and private deployment must be separate, non-nested directories")
    destination.mkdir(parents=True, exist_ok=True)
    entries = [source / path for path in FILES]
    for tree in TREES:
        entries.extend(
            p for p in (source / tree).rglob("*") if p.is_file() and allowed(str(p.relative_to(source)))
        )
    manifest = destination / MANIFEST
    if manifest.is_symlink():
        raise ValueError("Symlink in deployment manifest")
    previous = json.loads(manifest.read_text()) if manifest.exists() else {}
    if not isinstance(previous, dict):
        raise ValueError("Invalid deployment manifest")
    current = {str(path.relative_to(source)) for path in entries}
    retired = []
    for relative, digest in previous.items():
        target = safe_target(destination, relative)
        if relative not in current and target.exists():
            if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError("Retired application file has private edits; preserve it before redeploying")
            retired.append(target)
    count = 0
    hashes = {}
    for path in entries:
        if not path.is_file():
            raise ValueError(f"Missing allowlisted application file: {path.name}")
        if path.is_symlink():
            raise ValueError("Symlink in application allowlist")
        target = safe_target(destination, str(path.relative_to(source)))
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".relay-sync-tmp")
        if temporary.exists() or temporary.is_symlink():
            raise ValueError("Reserved sync temporary path already exists")
        shutil.copy2(path, temporary)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(temporary.read_bytes()).digest():
            temporary.unlink()
            raise ValueError("Synchronized file hash mismatch")
        os.replace(temporary, target)
        hashes[str(path.relative_to(source))] = hashlib.sha256(target.read_bytes()).hexdigest()
        count += 1
    for target in retired:
        target.unlink()  # Only unchanged, previously managed application files; never private files.
    with manifest.open("w") as handle:
        json.dump(hashes, handle, sort_keys=True, indent=2)
    print(f"Synchronized and hash-verified {count} application files; private files preserved")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    synchronize(root, sys.argv[1] if len(sys.argv) > 1 else root.with_name("immich-album-relay_test"))
