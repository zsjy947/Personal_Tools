"""图片批量重命名：把选中的图片剪切到「输出目录/统一名称」下连续编号。

编号对所有后缀统一分配（不会同时出现 名称-1.jpg 与 名称-1.png），后缀原样保留。
目标文件夹已有 名称-N 时自动从最大编号之后续接，因此三种场景同为一条路径：

- 选一个文件夹或若干图片：批量重命名（从 名称-1 开始）；
- 选多个文件夹：按给定顺序依次连续编号（合并）；
- 目标文件夹已有编号：接着已有顺序继续编号（追加）。
"""

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
INVALID_NAME_CHARS = set('\\/:*?"<>|')


@dataclass
class RenameSummary:
    found: int = 0
    moved: int = 0
    skipped: int = 0
    failed: int = 0


def validate_name(name: str) -> str:
    name = name.strip().rstrip(" .")
    if not name:
        raise ValueError("统一名称不能为空")
    if INVALID_NAME_CHARS & set(name):
        raise ValueError(f"名称不能包含文件名非法字符（{''.join(sorted(INVALID_NAME_CHARS))}）")
    return name


def _natural_key(path: Path):
    """自然排序：img-2 排在 img-10 之前。"""
    return [
        int(part) if part.isdigit() else part
        for part in re.split(r"(\d+)", str(path).lower())
    ]


def collect_images(
    sources, *, suffixes: set[str], recursive: bool = False
) -> tuple[list[Path], int]:
    """按源顺序收集图片：目录展开为其下图片，文件直接保留；返回 (文件列表, 跳过数)。"""
    files: list[Path] = []
    seen: set[Path] = set()
    skipped = 0

    def add(path: Path) -> None:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            files.append(path)

    for raw in sources:
        source = Path(raw).expanduser()
        if not source.exists():
            raise FileNotFoundError(f"路径不存在: {source}")
        if source.is_dir():
            entries = source.rglob("*") if recursive else source.iterdir()
            images = [path for path in entries if path.is_file() and path.suffix.lower() in suffixes]
            images.sort(key=_natural_key)
            for path in images:
                add(path)
        elif source.suffix.lower() in suffixes:
            add(source)
        else:
            print(f"跳过，非图片文件: {source}", file=sys.stderr)
            skipped += 1
    return files, skipped


def next_index(target_dir: Path, name: str) -> int:
    """目标文件夹中 名称-N 的最大编号 + 1（无则 1）。"""
    prefix = f"{name.lower()}-"
    largest = 0
    if target_dir.is_dir():
        for path in target_dir.iterdir():
            if not path.is_file():
                continue
            stem = path.stem.lower()
            if stem.startswith(prefix) and stem[len(prefix):].isdigit():
                largest = max(largest, int(stem[len(prefix):]))
    return largest + 1


def rename_images(
    sources,
    output_dir,
    name: str,
    *,
    recursive: bool = False,
    dry_run: bool = False,
    suffixes: set[str] | None = None,
) -> RenameSummary:
    """把收集到的图片剪切到 输出目录/统一名称 下，按 名称-1、名称-2… 连续编号。"""
    name = validate_name(name)
    suffixes = {item.lower() for item in (suffixes or DEFAULT_IMAGE_SUFFIXES)}
    target = Path(output_dir).expanduser() / name

    files, skipped = collect_images(sources, suffixes=suffixes, recursive=recursive)
    summary = RenameSummary(skipped=skipped)

    # 已在目标文件夹内的文件跳过，避免和自己已有的编号互相冲撞
    if target.is_dir():
        target_resolved = target.resolve()
        kept: list[Path] = []
        for path in files:
            if path.resolve().parent == target_resolved:
                print(f"跳过，已在目标文件夹内: {path}", file=sys.stderr)
                summary.skipped += 1
            else:
                kept.append(path)
        files = kept
    summary.found = len(files)
    if not files:
        print("没有找到可处理的图片。")
        return summary
    if not dry_run:
        target.mkdir(parents=True, exist_ok=True)

    index = next_index(target, name)
    for path in files:
        dest = target / f"{name}-{index}{path.suffix}"
        while dest.exists():
            index += 1
            dest = target / f"{name}-{index}{path.suffix}"
        print(f"{'[预览] ' if dry_run else ''}{path} -> {dest}")
        if dry_run:
            summary.moved += 1
            index += 1
            continue
        try:
            shutil.move(str(path), str(dest))
            summary.moved += 1
        except OSError as exc:
            print(f"移动失败: {path} ({exc})", file=sys.stderr)
            summary.failed += 1
        index += 1

    verb = "计划移动" if dry_run else "已移动"
    print(f"\n完成: {verb} {summary.moved}，跳过 {summary.skipped}，失败 {summary.failed}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="把选中的图片剪切到「输出目录/统一名称」下，按 名称-1、名称-2… 连续编号。",
    )
    parser.add_argument(
        "sources", nargs="+", type=Path,
        help="源文件/目录（可多个；目录收其下图片，按给定顺序编号）",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, required=True,
        help="输出目录（在其下创建以统一名称命名的子文件夹）",
    )
    parser.add_argument("-n", "--name", required=True, help="统一名称（编号为 名称-1、名称-2…）")
    parser.add_argument("--recursive", action="store_true", help="目录源递归收集子目录图片")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不实际移动")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = rename_images(
            args.sources,
            args.output_dir,
            args.name,
            recursive=args.recursive,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
