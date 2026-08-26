#!/usr/bin/env python3

import argparse
import json
import re
import subprocess
from pathlib import Path

JPEG_EXTENSIONS = {".jpg", ".jpeg"}


def get_created_time(path: Path):
    try:
        result = subprocess.run(
            [
                "exiftool", "-j",
                "-ContentCreateDate", "-DateTimeOriginal", "-CreateDate",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)[0]
    except Exception as e:
        print(f"[ERROR] metadata read failed: {path.name}: {e}")
        return None

    value = data.get("ContentCreateDate") or data.get("DateTimeOriginal") or data.get("CreateDate")
    if not value:
        return None

    m = re.search(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(value))
    if not m:
        return None

    y, mo, d, h, mi, s = m.groups()
    return f"{y}{mo}{d}_{h}{mi}{s}"


def choose_unique_name(directory: Path, base: str, suffix: str, reserved: set):
    candidate = directory / f"{base}{suffix.lower()}"
    if candidate.name not in reserved and not candidate.exists():
        reserved.add(candidate.name)
        return candidate

    n = 2
    while True:
        candidate = directory / f"{base}_{n}{suffix.lower()}"
        if candidate.name not in reserved and not candidate.exists():
            reserved.add(candidate.name)
            return candidate
        n += 1


def main():
    parser = argparse.ArgumentParser(description="Rename JPEGs using ContentCreateDate / DateTimeOriginal / CreateDate.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--recursive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    files = sorted(
        p for p in (root.rglob("*") if args.recursive else root.iterdir())
        if p.is_file() and p.suffix.lower() in JPEG_EXTENSIONS
    )

    # Build the whole rename plan first, so files being renamed do not collide with later files.
    plan = []
    reserved_by_dir = {}

    for path in files:
        created = get_created_time(path)
        if not created:
            print(f"[SKIP] no usable created time: {path.name}")
            continue

        reserved = reserved_by_dir.setdefault(path.parent, set())
        target = choose_unique_name(path.parent, created, path.suffix, reserved)
        plan.append((path, target))

    # First move everything to temporary names to avoid rename cycles/collisions.
    temp_plan = []
    for idx, (src, dst) in enumerate(plan):
        temp = src.with_name(f".__rename_tmp_{idx}_{src.name}")
        temp_plan.append((src, temp, dst))

    if args.dry_run:
        for src, _, dst in temp_plan:
            print(f"{src.name} -> {dst.name}")
        print(f"planned: {len(temp_plan)}")
        return

    for src, temp, _ in temp_plan:
        src.rename(temp)

    for _, temp, dst in temp_plan:
        temp.rename(dst)
        print(f"{temp.name} -> {dst.name}")

    print(f"renamed: {len(temp_plan)}")


if __name__ == "__main__":
    main()
