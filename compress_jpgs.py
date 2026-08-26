#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QUALITIES = [95, 92, 90, 88, 86, 84, 82, 80, 78, 76, 74, 72, 70, 68, 65, 62, 60, 57, 55, 52, 50]


def mb(size):
    return size / 1024 / 1024


def check_dependencies():
    if not shutil.which("sips"):
        print("sips が見つかりません。このスクリプトは macOS 向けです。")
        sys.exit(1)
    if not shutil.which("exiftool"):
        print("exiftool が見つかりません: brew install exiftool")
        sys.exit(1)


def copy_metadata(original: Path, compressed: Path):
    subprocess.run(
        [
            "exiftool", "-overwrite_original",
            "-TagsFromFile", str(original),
            "-all:all",
            str(compressed),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def compress_at_quality(original: Path, output: Path, quality: int):
    subprocess.run(
        [
            "sips",
            "-s", "format", "jpeg",
            "-s", "formatOptions", str(quality),
            str(original),
            "--out", str(output),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    copy_metadata(original, output)


def process_file(path: Path, target_bytes: int, dry_run=False):
    original_size = path.stat().st_size

    if original_size <= target_bytes:
        print(f"[SKIP] {path.name}: {mb(original_size):.2f} MB")
        return "skip", original_size, original_size

    if dry_run:
        print(f"[TARGET] {path.name}: {mb(original_size):.2f} MB -> <= {mb(target_bytes):.2f} MB")
        return "dry", original_size, original_size

    original_stat = path.stat()

    for quality in QUALITIES:
        fd, temp_name = tempfile.mkstemp(prefix=".compress_", suffix=".jpg", dir=path.parent)
        os.close(fd)
        temp = Path(temp_name)

        try:
            compress_at_quality(path, temp, quality)
            size = temp.stat().st_size
            print(f"       Q{quality:02d}: {mb(size):.2f} MB")

            if size <= target_bytes:
                os.replace(temp, path)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
                reduction = (1 - size / original_size) * 100
                print(f"[OK]   {path.name}: {mb(original_size):.2f} -> {mb(size):.2f} MB / Q{quality} / {reduction:.1f}%削減")
                return "ok", original_size, size
        except Exception as e:
            print(f"       Q{quality}: 失敗 ({e})")
        finally:
            if temp.exists():
                try:
                    temp.unlink()
                except Exception:
                    pass

    print(f"[OVER] {path.name}: 品質50でも {mb(target_bytes):.2f} MB 以下にならないため変更しません")
    return "over", original_size, original_size


def main():
    parser = argparse.ArgumentParser(description="JPEGを解像度を変えずに指定サイズ以下へ圧縮")
    parser.add_argument("directory", nargs="?", default="all_media")
    parser.add_argument("--max-mb", type=float, default=2.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--recursive", action="store_true")
    args = parser.parse_args()

    check_dependencies()
    root = Path(args.directory).expanduser().resolve()
    if not root.exists():
        print(f"ERROR: {root} が存在しません")
        sys.exit(1)

    target_bytes = int(args.max_mb * 1024 * 1024)
    iterator = root.rglob("*") if args.recursive else root.iterdir()
    files = sorted(p for p in iterator if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg"})

    print(f"対象: {root}")
    print(f"JPEG: {len(files)}枚 / 上限: {args.max_mb:.2f} MB / 解像度維持")
    if args.dry_run:
        print("DRY RUN: ファイルは変更しません")

    total_before = total_after = 0
    changed = 0

    for i, path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}] {path.name}")
        result, before, after = process_file(path, target_bytes, args.dry_run)
        total_before += before
        total_after += after
        if result == "ok":
            changed += 1

    print("\n完了")
    print(f"圧縮: {changed}枚")
    if not args.dry_run:
        print(f"合計: {mb(total_before):.1f} MB -> {mb(total_after):.1f} MB")


if __name__ == "__main__":
    main()
