"""Recursively rename files ending with .1 by stripping the .1 suffix."""

import argparse
import os
import sys


def rename_dot1_files(root_dir: str, dry_run: bool = False) -> int:
    count = 0
    for dirpath, _, filenames in os.walk(root_dir):
        for name in filenames:
            if not name.endswith(".1"):
                continue
            old_path = os.path.join(dirpath, name)
            new_path = os.path.join(dirpath, name[:-2])  # strip trailing ".1"

            if os.path.exists(new_path):
                print(f"SKIP (target exists): {old_path}", file=sys.stderr)
                continue

            print(f"{'[DRY RUN] ' if dry_run else ''}{old_path} -> {new_path}")
            if not dry_run:
                os.rename(old_path, new_path)
            count += 1

    print(f"\nTotal: {count} file(s) {'would be ' if dry_run else ''}renamed")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Recursively remove .1 suffix from files in a directory."
    )
    parser.add_argument("path", nargs="?", default=".", help="Target directory (default: current dir)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, do not rename")
    args = parser.parse_args()

    if not os.path.isdir(args.path):
        print(f"Error: '{args.path}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    rename_dot1_files(os.path.abspath(args.path), dry_run=args.dry_run)


if __name__ == "__main__":
    main()
