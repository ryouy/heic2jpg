#!/usr/bin/env python3

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from timezonefinder import TimezoneFinder
except ImportError:
    print("timezonefinder is not installed.")
    print("Install it with: python3 -m pip install timezonefinder")
    sys.exit(1)

OUTPUT_NAME = "all_media"
HEIC_EXTENSIONS = {".heic", ".heif"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".bmp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".webm"}
TF = TimezoneFinder()


def run(cmd, quiet=True):
    kwargs = {"check": True}
    if quiet:
        kwargs["stdout"] = subprocess.DEVNULL
        kwargs["stderr"] = subprocess.DEVNULL
    subprocess.run(cmd, **kwargs)


def file_hash(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def safe_label(text: str):
    text = re.sub(r"[^A-Za-z0-9_-]+", "_", text).strip("_")
    return text[:40] or "unknown"


def exif_json(path: Path):
    try:
        result = subprocess.run(
            [
                "exiftool", "-j",
                "-DateTimeOriginal", "-CreateDate", "-ModifyDate",
                "-ContentCreateDate", "-MediaCreateDate", "-TrackCreateDate",
                "-OffsetTimeOriginal", "-OffsetTimeDigitized",
                "-GPSLatitude", "-GPSLongitude",
                "-ImageDescription", "-Title", "-XMP:Description",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        data = json.loads(result.stdout)
        return data[0] if data else {}
    except Exception:
        return {}


def find_sidecars(media: Path):
    candidates = [
        media.with_name(media.name + ".supplemental-metadata.json"),
        media.with_name(media.name + ".json"),
        media.with_name(media.stem + ".supplemental-metadata.json"),
        media.with_name(media.stem + ".json"),
    ]
    found = []
    for p in candidates:
        if p.exists() and p not in found:
            found.append(p)
    return found


def load_sidecars(*media_files):
    merged = {}
    paths = []
    for media in media_files:
        if media is None:
            continue
        for sidecar in find_sidecars(media):
            if sidecar in paths:
                continue
            paths.append(sidecar)
            try:
                with sidecar.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                for key, value in data.items():
                    if key not in merged or not merged[key]:
                        merged[key] = value
            except Exception as e:
                print(f"  [WARN] Cannot read JSON {sidecar.name}: {e}")
    return merged, paths


def get_json_geo(metadata):
    geo = metadata.get("geoDataExif") or metadata.get("geoData") or {}
    try:
        lat = float(geo.get("latitude", 0) or 0)
        lon = float(geo.get("longitude", 0) or 0)
        alt = float(geo.get("altitude", 0) or 0)
    except (ValueError, TypeError):
        return None, None, None
    if lat == 0 and lon == 0:
        return None, None, alt
    return lat, lon, alt


def json_local_datetime(metadata):
    taken = metadata.get("photoTakenTime") or {}
    timestamp = taken.get("timestamp")
    if not timestamp:
        return None

    lat, lon, _ = get_json_geo(metadata)
    if lat is None or lon is None:
        return None

    try:
        tz_name = TF.timezone_at(lat=lat, lng=lon)
        if not tz_name:
            return None
        utc_dt = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
        local_dt = utc_dt.astimezone(ZoneInfo(tz_name))
        exif_time = local_dt.strftime("%Y:%m:%d %H:%M:%S")
        raw_offset = local_dt.strftime("%z")
        offset = raw_offset[:3] + ":" + raw_offset[3:]
        return {"datetime": exif_time, "offset": offset, "timezone": tz_name}
    except Exception:
        return None


def apply_sidecar_metadata(destination: Path, metadata: dict):
    if not metadata:
        return

    current = exif_json(destination)
    cmd = ["exiftool", "-overwrite_original"]
    changed = False

    has_time = bool(
        current.get("DateTimeOriginal")
        or current.get("ContentCreateDate")
        or current.get("CreateDate")
        or current.get("MediaCreateDate")
        or current.get("TrackCreateDate")
    )

    if not has_time:
        converted = json_local_datetime(metadata)
        if converted:
            dt = converted["datetime"]
            offset = converted["offset"]
            cmd += [
                f"-DateTimeOriginal={dt}",
                f"-CreateDate={dt}",
                f"-ModifyDate={dt}",
                f"-OffsetTimeOriginal={offset}",
                f"-OffsetTimeDigitized={offset}",
            ]
            changed = True
            print(f"       capture time filled: {dt} {offset} ({converted['timezone']})")
        elif (metadata.get("photoTakenTime") or {}).get("timestamp"):
            print("       [WARN] JSON has UTC timestamp but no GPS; capture time not overwritten")

    has_gps = "GPSLatitude" in current and "GPSLongitude" in current
    if not has_gps:
        lat, lon, alt = get_json_geo(metadata)
        if lat is not None and lon is not None:
            cmd += [
                f"-GPSLatitude={abs(lat)}",
                f"-GPSLatitudeRef={'N' if lat >= 0 else 'S'}",
                f"-GPSLongitude={abs(lon)}",
                f"-GPSLongitudeRef={'E' if lon >= 0 else 'W'}",
            ]
            if alt is not None and alt != 0:
                cmd += [
                    f"-GPSAltitude={abs(alt)}",
                    f"-GPSAltitudeRef={0 if alt >= 0 else 1}",
                ]
            changed = True

    description = metadata.get("description") or ""
    existing_description = current.get("ImageDescription") or current.get("Description")
    if description and not existing_description:
        cmd += [f"-ImageDescription={description}", f"-XMP-dc:Description={description}"]
        changed = True

    if changed:
        cmd.append(str(destination))
        try:
            run(cmd)
        except subprocess.CalledProcessError:
            print(f"  [WARN] Could not write sidecar metadata: {destination.name}")


def copy_all_metadata(source: Path, destination: Path):
    try:
        run(["exiftool", "-overwrite_original", "-TagsFromFile", str(source), "-all:all", str(destination)])
    except subprocess.CalledProcessError:
        print("       [WARN] Could not copy metadata from source")


def find_matching_jpg(heic: Path):
    stem = heic.stem.lower()
    for item in heic.parent.iterdir():
        if item.is_file() and item.stem.lower() == stem and item.suffix.lower() in {".jpg", ".jpeg"}:
            return item
    return None


def capture_label(path: Path):
    data = exif_json(path)
    value = (
        data.get("DateTimeOriginal")
        or data.get("ContentCreateDate")
        or data.get("CreateDate")
        or data.get("MediaCreateDate")
        or data.get("TrackCreateDate")
    )
    if not value:
        return None
    m = re.search(r"(\d{4}):(\d{2}):(\d{2})[ T](\d{2}):(\d{2}):(\d{2})", str(value))
    return "".join(m.groups()) if m else None


def make_temp(output_dir: Path, suffix: str):
    return output_dir / f".tmp_{uuid.uuid4().hex}{suffix}"


def place_temp(temp: Path, desired_name: str, source_parent: Path, output_dir: Path):
    destination = output_dir / desired_name
    if not destination.exists():
        temp.replace(destination)
        return destination, False

    try:
        if file_hash(temp) == file_hash(destination):
            temp.unlink()
            return destination, True
    except Exception:
        pass

    original = Path(desired_name)
    suffix_label = capture_label(temp) or safe_label(source_parent.name)
    candidate = output_dir / f"{original.stem}__{suffix_label}{original.suffix.lower()}"

    if candidate.exists():
        try:
            if file_hash(temp) == file_hash(candidate):
                temp.unlink()
                return candidate, True
        except Exception:
            pass

        n = 2
        while True:
            candidate = output_dir / f"{original.stem}__{suffix_label}_{n}{original.suffix.lower()}"
            if not candidate.exists():
                break
            try:
                if file_hash(temp) == file_hash(candidate):
                    temp.unlink()
                    return candidate, True
            except Exception:
                pass
            n += 1

    temp.replace(candidate)
    return candidate, False


def process_heic(heic: Path, output_dir: Path, consumed: set, delete_heic: bool):
    matching_jpg = find_matching_jpg(heic)

    if matching_jpg:
        print(f"[PAIR] {heic}")
        print(f"       existing JPEG preferred: {matching_jpg.name}")
        consumed.add(matching_jpg.resolve())

        temp = make_temp(output_dir, matching_jpg.suffix.lower())
        try:
            shutil.copy2(matching_jpg, temp)
        except Exception as e:
            print(f"       [ERROR] JPEG copy failed: {e}")
            return False

        metadata, _ = load_sidecars(matching_jpg, heic)
        apply_sidecar_metadata(temp, metadata)
        final, _ = place_temp(temp, matching_jpg.name, matching_jpg.parent, output_dir)
        print(f"       -> {final.name}")

        if delete_heic:
            try:
                heic.unlink()
                print("       source HEIC deleted")
            except Exception as e:
                print(f"       [WARN] HEIC deletion failed: {e}")
        return True

    print(f"[HEIC] {heic}")
    temp = make_temp(output_dir, ".jpg")

    try:
        run(["sips", "-s", "format", "jpeg", "-s", "formatOptions", "100", str(heic), "--out", str(temp)])
    except subprocess.CalledProcessError:
        print("       [ERROR] HEIC -> JPEG failed")
        if temp.exists():
            temp.unlink()
        return False

    copy_all_metadata(heic, temp)
    metadata, _ = load_sidecars(heic)
    apply_sidecar_metadata(temp, metadata)

    if not temp.exists() or temp.stat().st_size == 0:
        print("       [ERROR] output JPEG is invalid")
        return False

    final, _ = place_temp(temp, heic.stem + ".jpg", heic.parent, output_dir)
    print(f"       -> {final.name}")

    if delete_heic:
        try:
            heic.unlink()
            print("       source HEIC deleted")
        except Exception as e:
            print(f"       [WARN] HEIC deletion failed: {e}")

    return True


def process_normal_media(source: Path, output_dir: Path):
    print(f"[COPY] {source}")
    temp = make_temp(output_dir, source.suffix)
    try:
        shutil.copy2(source, temp)
    except Exception as e:
        print(f"       [ERROR] copy failed: {e}")
        return False

    if source.suffix.lower() in IMAGE_EXTENSIONS:
        metadata, _ = load_sidecars(source)
        apply_sidecar_metadata(temp, metadata)

    final, duplicate = place_temp(temp, source.name, source.parent, output_dir)
    if duplicate:
        print(f"       duplicate skipped -> {final.name}")
    else:
        print(f"       -> {final.name}")
    return True


def check_dependencies():
    missing = []
    if not shutil.which("exiftool"):
        missing.append("exiftool (brew install exiftool)")
    if not shutil.which("sips"):
        missing.append("sips (macOS built-in)")
    if missing:
        print("Missing dependencies:")
        for item in missing:
            print("  " + item)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Merge Google Photos/Takeout media into one folder while preserving metadata.")
    parser.add_argument("root", nargs="?", default=".", help="root directory to scan")
    parser.add_argument("--clean", action="store_true", help="delete existing all_media before processing")
    parser.add_argument("--delete-heic", action="store_true", help="delete source HEIC/HEIF after successful output")
    args = parser.parse_args()

    check_dependencies()
    root = Path(args.root).expanduser().resolve()
    output_dir = root / OUTPUT_NAME

    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    source_files = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            path.relative_to(output_dir)
            continue
        except ValueError:
            pass
        source_files.append(path)

    heics = sorted(x for x in source_files if x.suffix.lower() in HEIC_EXTENSIONS)
    normal_media = sorted(
        x for x in source_files
        if x.suffix.lower() in IMAGE_EXTENSIONS or x.suffix.lower() in VIDEO_EXTENSIONS
    )

    print(f"root: {root}")
    print(f"output: {output_dir}")
    print(f"HEIC/HEIF: {len(heics)}")
    print(f"other media: {len(normal_media)}")

    consumed = set()
    success = failed = 0

    for i, heic in enumerate(heics, 1):
        print(f"\n--- HEIC {i}/{len(heics)} ---")
        if process_heic(heic, output_dir, consumed, args.delete_heic):
            success += 1
        else:
            failed += 1

    remaining = [x for x in normal_media if x.resolve() not in consumed]
    for i, media in enumerate(remaining, 1):
        print(f"\n--- MEDIA {i}/{len(remaining)} ---")
        if process_normal_media(media, output_dir):
            success += 1
        else:
            failed += 1

    for temp in output_dir.glob(".tmp_*"):
        try:
            temp.unlink()
        except Exception:
            pass

    final_files = [x for x in output_dir.iterdir() if x.is_file()]
    print("\nDone")
    print(f"success: {success}")
    print(f"failed: {failed}")
    print(f"final media count: {len(final_files)}")
    print(f"output: {output_dir}")


if __name__ == "__main__":
    main()
