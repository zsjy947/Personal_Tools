"""Recursively delete files whose name (before extension) ends with '副本'."""

import argparse
import os
import sys


def delete_copy_files(root_dir: str, dry_run: bool = False) -> int:
    count = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            stem, _ = os.path.splitext(name)
            if not stem.endswith("副本"):
                continue
            full_path = os.path.join(dirpath, name)
            print(f"{'[DRY RUN] ' if dry_run else ''}DELETE: {full_path}")
            if not dry_run:
                os.remove(full_path)
            count += 1

    print(f"\nTotal: {count} file(s) {'would be ' if dry_run else ''}deleted")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively delete files whose stem ends with '副本'."
    )
    parser.add_argument("path", nargs="?", default=".", help="Target directory (default: current dir)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not delete")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"Error: '{args.path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    delete_copy_files(os.path.abspath(args.path), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
