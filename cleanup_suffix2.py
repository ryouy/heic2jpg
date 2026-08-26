#!/usr/bin/env python3

import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Find or delete files containing __2 in the filename.")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--delete", action="store_true", help="actually delete matches; default is dry-run")
    args = parser.parse_args()

    root = Path(args.root).expanduser().resolve()
    matches = sorted(p for p in root.rglob("*") if p.is_file() and "__2" in p.name)

    if not matches:
        print("No matching files.")
        return

    for path in matches:
        if args.delete:
            path.unlink()
            print(f"deleted: {path}")
        else:
            print(path)

    print(f"matches: {len(matches)}")
    if not args.delete:
        print("Dry-run only. Add --delete to remove them.")


if __name__ == "__main__":
    main()
