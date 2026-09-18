"""文件名标记/后缀管理：添加、移除标记，或删除带标记的文件。

合并原“添加/移除 .1 后缀”与“删除副本文件”两个工具：
标记可以是 `.1` 这类点后缀，也可以是 `副本` 这类文字标记，由用户自定义。

- add：`.1` 这类以点开头的标记追加到完整文件名末尾（`a.txt` → `a.txt.1`），
  其他标记加到主文件名末尾、扩展名之前（`a.txt` → `a副本.txt`）。
- remove：从文件名末尾或主文件名末尾剥掉一层标记（与 add 互逆，单层）。
- delete：删除文件名或主文件名以标记结尾的全部文件。
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

INVALID_MARKER_CHARS = set('\\/:*?"<>|')


@dataclass
class SuffixSummary:
    matched: int = 0
    renamed: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0


def validate_marker(marker: str) -> str:
    marker = marker.strip()
    if not marker or marker in {".", ".."}:
        raise ValueError("标记不能为空")
    if INVALID_MARKER_CHARS & set(marker):
        raise ValueError(f"标记不能包含文件名非法字符（{''.join(sorted(INVALID_MARKER_CHARS))}）")
    return marker


def _add_name(path: Path, marker: str) -> str:
    if marker.startswith("."):
        return path.name + marker
    return f"{path.stem}{marker}{path.suffix}"


def _strip_marker(path: Path, marker: str) -> str | None:
    if path.name.endswith(marker) and len(path.name) > len(marker):
        return path.name[: -len(marker)]
    if path.stem.endswith(marker) and len(path.stem) > len(marker):
        return f"{path.stem[: -len(marker)]}{path.suffix}"
    return None


def _matches(path: Path, marker: str) -> bool:
    return _strip_marker(path, marker) is not None


def iter_files(directory: Path, recursive: bool):
    entries = directory.rglob("*") if recursive else directory.iterdir()
    yield from sorted(path for path in entries if path.is_file())


def manage_suffix(
    root_dir: str | Path,
    marker: str,
    operation: str,
    *,
    recursive: bool = False,
    dry_run: bool = False,
) -> SuffixSummary:
    """按自定义标记批量添加/移除文件名标记，或删除匹配文件。"""
    marker = validate_marker(marker)
    directory = Path(root_dir).expanduser()
    if not directory.is_dir():
        raise NotADirectoryError(f"不是有效目录: {directory}")
    if operation not in {"add", "remove", "delete"}:
        raise ValueError(f"不支持的操作: {operation}")

    summary = SuffixSummary()
    for path in iter_files(directory, recursive):
        if operation == "add":
            if _matches(path, marker):
                summary.skipped += 1
                continue
            new_name = _add_name(path, marker)
        elif operation == "remove":
            new_name = _strip_marker(path, marker)
            if new_name is None:
                continue
        else:  # delete
            if not _matches(path, marker):
                continue
            summary.matched += 1
            print(f"{'[预览] 删除' if dry_run else '删除'}: {path}")
            if dry_run:
                continue
            try:
                path.unlink()
                summary.deleted += 1
            except OSError as exc:
                print(f"删除失败: {path} ({exc})", file=sys.stderr)
                summary.failed += 1
            continue

        summary.matched += 1
        new_path = path.with_name(new_name)
        if new_path.exists():
            print(f"跳过，目标已存在: {new_path}", file=sys.stderr)
            summary.skipped += 1
            continue
        print(f"{'[预览] ' if dry_run else ''}{path} -> {new_path}")
        if dry_run:
            summary.renamed += 1
            continue
        try:
            path.rename(new_path)
            summary.renamed += 1
        except OSError as exc:
            print(f"重命名失败: {path} ({exc})", file=sys.stderr)
            summary.failed += 1

    if operation == "delete":
        tail = (
            f"预览完成: 匹配 {summary.matched}；确认无误后取消“仅预览”执行删除"
            if dry_run else
            f"完成: 匹配 {summary.matched}，删除 {summary.deleted}，失败 {summary.failed}"
        )
    else:
        verb = "计划重命名" if dry_run else "已重命名"
        tail = (
            f"完成: {verb} {summary.renamed}，跳过 {summary.skipped}，失败 {summary.failed}"
        )
    print(f"\n{tail}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="按自定义标记批量添加/移除文件名标记，或删除带标记的文件。"
    )
    parser.add_argument(
        "operation", choices=("add", "remove", "delete"),
        help="add 添加标记 / remove 移除标记 / delete 删除匹配文件",
    )
    parser.add_argument("path", type=Path, help="目标目录")
    parser.add_argument(
        "--marker", required=True,
        help='文件名标记，如 ".1" 或 "副本"',
    )
    parser.add_argument("--recursive", action="store_true", help="递归处理子目录")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不实际执行")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = manage_suffix(
            args.path,
            args.marker,
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
