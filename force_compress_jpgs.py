#!/usr/bin/env python3

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

QUALITIES = [95, 90, 85, 80, 75, 70, 65, 60]
EMERGENCY_QUALITIES = [55, 50, 45, 40, 35, 30, 25, 20]


def mb(size):
    return size / 1024 / 1024


def check_dependencies():
    if not shutil.which("sips"):
        print("sips が見つかりません。このスクリプトは macOS 向けです。")
        sys.exit(1)
    if not shutil.which("exiftool"):
        print("exiftool が見つかりません: brew install exiftool")
        sys.exit(1)


def get_dimensions(path: Path):
    result = subprocess.run(
        ["exiftool", "-j", "-ImageWidth", "-ImageHeight", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(result.stdout)[0]
    return int(data["ImageWidth"]), int(data["ImageHeight"])


def copy_metadata(original: Path, destination: Path):
    subprocess.run(
        [
            "exiftool", "-overwrite_original",
            "-TagsFromFile", str(original),
            "-all:all",
            "-PreviewImage=", "-ThumbnailImage=", "-JpgFromRaw=",
            str(destination),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def make_candidate(original: Path, destination: Path, quality: int, max_dimension=None):
    cmd = ["sips", "-s", "format", "jpeg", "-s", "formatOptions", str(quality)]
    if max_dimension is not None:
        cmd += ["-Z", str(max_dimension)]
    cmd += [str(original), "--out", str(destination)]

    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    copy_metadata(original, destination)


def candidate(path: Path, quality: int, dimension):
    fd, temp_name = tempfile.mkstemp(prefix=".forcecompress_", suffix=".jpg", dir=path.parent)
    os.close(fd)
    temp = Path(temp_name)
    try:
        make_candidate(path, temp, quality, dimension)
        return temp, temp.stat().st_size
    except Exception:
        if temp.exists():
            temp.unlink()
        return None, None


def process_file(path: Path, target_bytes: int):
    original_size = path.stat().st_size
    if original_size <= target_bytes:
        print(f"[SKIP] {path.name}: {mb(original_size):.2f} MB")
        return original_size, original_size, False

    try:
        width, height = get_dimensions(path)
    except Exception as e:
        print(f"[ERROR] {path.name}: 画像サイズ取得失敗 ({e})")
        return original_size, original_size, False

    original_max = max(width, height)
    original_stat = path.stat()
    print(f"[TARGET] {path.name}: {width}x{height} / {mb(original_size):.2f} MB")

    # まず原寸。収まらなければ最大辺を85%ずつ縮小。
    dimensions = [original_max]
    current = original_max
    while current > 640:
        current = max(640, int(current * 0.85))
        if current not in dimensions:
            dimensions.append(current)
        if current == 640:
            break

    for dimension in dimensions:
        scale = dimension / original_max * 100
        for quality in QUALITIES:
            temp, size = candidate(path, quality, dimension)
            if temp is None:
                continue
            print(f"       {scale:5.1f}% Q{quality:02d}: {mb(size):.2f} MB")
            if size <= target_bytes:
                os.replace(temp, path)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
                reduction = (1 - size / original_size) * 100
                print(f"[OK]   {path.name}: {mb(original_size):.2f} -> {mb(size):.2f} MB / Q{quality} / 最大辺{dimension}px / {reduction:.1f}%削減")
                return original_size, size, True
            temp.unlink()

    # 念のための強制モード。ここまで来れば通常の写真なら確実に収まる。
    for dimension in [600, 500, 400, 320, 240]:
        for quality in EMERGENCY_QUALITIES:
            temp, size = candidate(path, quality, dimension)
            if temp is None:
                continue
            print(f"       FORCE {dimension}px Q{quality:02d}: {mb(size):.2f} MB")
            if size <= target_bytes:
                os.replace(temp, path)
                os.utime(path, (original_stat.st_atime, original_stat.st_mtime))
                print(f"[OK]   {path.name}: {mb(original_size):.2f} -> {mb(size):.2f} MB / FORCE")
                return original_size, size, True
            temp.unlink()

    print(f"[ERROR] {path.name}: {mb(target_bytes):.2f} MB 以下にできませんでした。元ファイルは維持します")
    return original_size, original_size, False


def main():
    parser = argparse.ArgumentParser(description="JPEGをメタデータを維持しながら強制的に指定サイズ以下へ圧縮")
    parser.add_argument("directory", nargs="?", default="all_media")
    parser.add_argument("--max-mb", type=float, default=2.0)
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
    print(f"JPEG: {len(files)}枚 / 強制上限: {args.max_mb:.2f} MB")
    print("上限を超える場合はJPEG品質を下げ、それでも収まらなければ解像度も縮小します。")

    total_before = total_after = 0
    changed = 0
    for i, path in enumerate(files, 1):
        print(f"\n[{i}/{len(files)}]")
        before, after, did_change = process_file(path, target_bytes)
        total_before += before
        total_after += after
        changed += int(did_change)

    print("\n完了")
    print(f"圧縮: {changed}枚")
    print(f"合計: {mb(total_before):.1f} MB -> {mb(total_after):.1f} MB")


if __name__ == "__main__":
    main()
