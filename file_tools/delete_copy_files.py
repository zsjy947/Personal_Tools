"""递归查找并删除文件名以“副本”结尾的文件。"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class DeleteSummary:
    matched: int = 0
    deleted: int = 0
    failed: int = 0


def delete_copy_files(root_dir: str | Path, execute: bool = False) -> DeleteSummary:
    directory = Path(root_dir).expanduser()
    if not directory.is_dir():
        raise NotADirectoryError(f"不是有效目录: {directory}")

    summary = DeleteSummary()
    for path in sorted(item for item in directory.rglob("*") if item.is_file()):
        if not path.stem.endswith("副本"):
            continue
        summary.matched += 1
        print(f"{'删除' if execute else '[预览] 删除'}: {path}")
        if not execute:
            continue
        try:
            path.unlink()
            summary.deleted += 1
        except OSError as exc:
            print(f"删除失败: {path} ({exc})", file=sys.stderr)
            summary.failed += 1

    if execute:
        print(
            f"\n完成: 匹配 {summary.matched}，删除 {summary.deleted}，"
            f"失败 {summary.failed}"
        )
    else:
        print(f"\n预览完成: 匹配 {summary.matched}；使用 --execute 执行删除")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="递归删除文件名（不含扩展名）以“副本”结尾的文件。"
    )
    parser.add_argument("path", type=Path, help="目标目录")
    parser.add_argument("--execute", action="store_true", help="实际执行删除；默认仅预览")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = delete_copy_files(args.path, execute=args.execute)
    except (NotADirectoryError, OSError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
