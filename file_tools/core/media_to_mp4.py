"""使用 ffmpeg 将真实内容为视频的文件无损封装为 MP4。"""

import argparse
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .common import normalize_suffixes


def run_hidden(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    """执行外部命令且在 Windows 上不弹出控制台窗口（ffmpeg 等已内置，无需外部终端）。"""
    if sys.platform == "win32":
        kwargs.setdefault("creationflags", subprocess.CREATE_NO_WINDOW)
    return subprocess.run(command, **kwargs)


def find_ffmpeg() -> str | None:
    """查找可用 ffmpeg，保证打包成 exe 后功能不出域。

    顺序：环境变量 FILE_TOOLS_FFMPEG → exe 同目录 → 内置 imageio-ffmpeg
    （随 exe 打包）→ 系统 PATH。
    """
    override = os.environ.get("FILE_TOOLS_FFMPEG", "").strip()
    if override and Path(override).is_file():
        return override
    if getattr(sys, "frozen", False):
        candidate = Path(sys.executable).parent / "ffmpeg.exe"
        if candidate.is_file():
            return str(candidate)
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001 - 未安装 imageio-ffmpeg 时回退后续查找
        pass
    return shutil.which("ffmpeg")


@dataclass
class ConversionSummary:
    converted: int = 0
    skipped: int = 0
    failed: int = 0


def find_input_files(
    source: Path,
    suffixes: set[str],
    recursive: bool = False,
) -> list[Path]:
    if source.is_file():
        return [source]
    if not source.is_dir():
        raise FileNotFoundError(f"输入路径不存在: {source}")
    if not suffixes:
        raise ValueError("目录模式必须使用 --suffix 指定待处理后缀")

    entries = source.rglob("*") if recursive else source.iterdir()
    return sorted(
        path for path in entries
        if path.is_file() and path.suffix.lower() in suffixes
    )


def output_path_for(source: Path, output_dir: Path | None) -> Path:
    target_dir = output_dir if output_dir is not None else source.parent
    return target_dir / f"{source.stem}.mp4"


def convert_file(
    source: Path,
    output: Path,
    overwrite: bool = False,
    dry_run: bool = False,
    ffmpeg: str = "ffmpeg",
) -> str:
    if source.resolve() == output.resolve():
        print(f"跳过，输入已经是目标文件: {source}")
        return "skipped"
    if output.exists() and not overwrite:
        print(f"跳过，目标已存在: {output}")
        return "skipped"

    print(f"{'[预览] ' if dry_run else ''}{source} -> {output}")
    if dry_run:
        return "converted"

    output.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        "-c",
        "copy",
        "-y" if overwrite else "-n",
        str(output),
    ]
    result = run_hidden(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        output.unlink(missing_ok=True)
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"ffmpeg 退出码 {result.returncode}"
        print(f"转换失败: {source} ({message})", file=sys.stderr)
        return "failed"

    print(f"转换成功: {output}")
    return "converted"


def convert_media(
    source: str | Path,
    suffixes: set[str] | None = None,
    recursive: bool = False,
    output_dir: str | Path | None = None,
    overwrite: bool = False,
    dry_run: bool = False,
) -> ConversionSummary:
    source = Path(source).expanduser()
    target_dir = Path(output_dir).expanduser() if output_dir else None
    files = find_input_files(source, suffixes or set(), recursive)
    summary = ConversionSummary()

    if not files:
        print("没有找到符合条件的文件。")
        return summary
    ffmpeg = find_ffmpeg()
    if not dry_run and ffmpeg is None:
        raise RuntimeError(
            "未找到 ffmpeg：请安装依赖 pip install imageio-ffmpeg，"
            "或设置环境变量 FILE_TOOLS_FFMPEG 指向 ffmpeg 可执行文件"
        )

    for path in files:
        result = convert_file(
            path,
            output_path_for(path, target_dir),
            overwrite=overwrite,
            dry_run=dry_run,
            ffmpeg=ffmpeg or "ffmpeg",
        )
        setattr(summary, result, getattr(summary, result) + 1)

    print(
        f"\n完成: 成功 {summary.converted}，跳过 {summary.skipped}，"
        f"失败 {summary.failed}"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="将真实内容为视频的文件无损封装为 MP4，输入扩展名可以任意。"
    )
    parser.add_argument("source", type=Path, help="输入文件或目录")
    parser.add_argument(
        "--suffix",
        nargs="+",
        metavar="EXT",
        help="目录模式筛选后缀，例如: --suffix jpeg woff2 ts",
    )
    parser.add_argument("--recursive", action="store_true", help="递归搜索子目录")
    parser.add_argument("--output-dir", type=Path, help="统一输出目录")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有 MP4")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不调用 ffmpeg")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = convert_media(
            args.source,
            normalize_suffixes(args.suffix),
            recursive=args.recursive,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
