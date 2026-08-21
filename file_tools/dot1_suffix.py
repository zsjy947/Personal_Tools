"""批量添加或移除文件名末尾的 .1 后缀。"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class RenameSummary:
    renamed: int = 0
    skipped: int = 0
    failed: int = 0


def iter_files(directory: Path, recursive: bool):
    entries = directory.rglob("*") if recursive else directory.iterdir()
    yield from sorted(path for path in entries if path.is_file())


def rename_dot1_files(
    root_dir: str | Path,
    operation: str,
    recursive: bool = False,
    dry_run: bool = False,
) -> RenameSummary:
    directory = Path(root_dir).expanduser()
    if not directory.is_dir():
        raise NotADirectoryError(f"不是有效目录: {directory}")
    if operation not in {"add", "remove"}:
        raise ValueError(f"不支持的操作: {operation}")

    summary = RenameSummary()
    for old_path in iter_files(directory, recursive):
        if operation == "add":
            if old_path.name.endswith(".1"):
                summary.skipped += 1
                continue
            new_path = old_path.with_name(f"{old_path.name}.1")
        else:
            if not old_path.name.endswith(".1"):
                continue
            new_path = old_path.with_name(old_path.name[:-2])

        if new_path.exists():
            print(f"跳过，目标已存在: {new_path}", file=sys.stderr)
            summary.skipped += 1
            continue

        print(f"{'[预览] ' if dry_run else ''}{old_path} -> {new_path}")
        if dry_run:
            summary.renamed += 1
            continue
        try:
            old_path.rename(new_path)
            summary.renamed += 1
        except OSError as exc:
            print(f"重命名失败: {old_path} ({exc})", file=sys.stderr)
            summary.failed += 1

    print(
        f"\n完成: {'计划重命名' if dry_run else '已重命名'} {summary.renamed}，"
        f"跳过 {summary.skipped}，失败 {summary.failed}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="批量添加或移除文件名末尾的 .1 后缀。"
    )
    parser.add_argument("operation", choices=("add", "remove"), help="执行添加或移除")
    parser.add_argument("path", type=Path, help="目标目录")
    parser.add_argument("--recursive", action="store_true", help="递归处理子目录")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不重命名")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = rename_dot1_files(
            args.path,
            args.operation,
            recursive=args.recursive,
            dry_run=args.dry_run,
        )
    except (NotADirectoryError, OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
