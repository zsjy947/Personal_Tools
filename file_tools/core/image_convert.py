"""图片格式转换：Pillow 批量重编码（webp/jpg/png/bmp 互转）。

与 media_to_mp4 的区别：那里是 ffmpeg 无损封装（只换容器不重编码），
本模块是真正的解码重编码。要点：

- 透明通道转 jpg/bmp 自动垫白底；CMYK 转 PNG 自动转 RGB；动图（gif/webp）只取首帧。
- `--quality` 仅 jpg/webp 生效；输出默认在原图同目录，`--output-dir` 时平铺存放。
- 与目标同后缀的文件跳过；目标重名跳过不覆盖；坏图计失败不中断。
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps

# 目录模式的默认筛选集合，对齐 image_decrypt 的常见图片后缀
SOURCE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}

FORMATS = {
    "jpg": ("JPEG", ".jpg"),
    "png": ("PNG", ".png"),
    "webp": ("WEBP", ".webp"),
    "bmp": ("BMP", ".bmp"),
}


@dataclass
class ConvertSummary:
    converted: int = 0
    skipped: int = 0
    failed: int = 0


def _prepare(image: Image.Image, fmt: str) -> Image.Image:
    """纠正 EXIF 方向，并为不支持透明通道的目标格式垫白底、收敛颜色模式。"""
    image = ImageOps.exif_transpose(image)
    if fmt in ("JPEG", "BMP") and (
        image.mode in ("RGBA", "LA", "PA")
        or (image.mode == "P" and "transparency" in image.info)
    ):
        rgba = image.convert("RGBA")
        background = Image.new("RGB", rgba.size, (255, 255, 255))
        background.paste(rgba, mask=rgba.getchannel("A"))
        image = background
    if fmt == "JPEG" and image.mode not in ("RGB", "L", "CMYK"):
        image = image.convert("RGB")
    if fmt == "BMP" and image.mode not in ("RGB", "L", "P", "1"):
        image = image.convert("RGB")
    if fmt == "PNG" and image.mode == "CMYK":
        image = image.convert("RGB")
    return image


def convert_images(
    source,
    target_format: str,
    *,
    output_dir=None,
    quality: int | None = None,
    delete_original: bool = False,
    suffixes: set[str] | None = None,
    recursive: bool = False,
    dry_run: bool = False,
) -> ConvertSummary:
    """批量把图片转换为 target_format；source 可以是单个图片文件或目录。"""
    if target_format not in FORMATS:
        raise ValueError(f"不支持的目标格式: {target_format}（可选：{'/'.join(FORMATS)}）")
    fmt, target_ext = FORMATS[target_format]
    if quality is not None and not 1 <= quality <= 100:
        raise ValueError("质量必须在 1 到 100 之间")
    source = Path(source).expanduser()
    if not source.exists():
        raise FileNotFoundError(f"路径不存在: {source}")
    allowed = {item.lower() for item in (suffixes or SOURCE_SUFFIXES)}

    if source.is_dir():
        entries = source.rglob("*") if recursive else source.iterdir()
        files = sorted(
            path for path in entries if path.is_file() and path.suffix.lower() in allowed
        )
    else:
        files = [source]
    output = Path(output_dir).expanduser() if output_dir else None
    if output is not None and files and not dry_run:
        output.mkdir(parents=True, exist_ok=True)

    summary = ConvertSummary()
    save_kwargs = {"quality": quality} if quality is not None and fmt in ("JPEG", "WEBP") else {}
    for path in files:
        if path.suffix.lower() == target_ext:
            print(f"跳过，已是 {target_format}: {path}")
            summary.skipped += 1
            continue
        dest = (output or path.parent) / f"{path.stem}{target_ext}"
        if dest.exists():
            print(f"跳过，目标已存在: {dest}", file=sys.stderr)
            summary.skipped += 1
            continue
        print(f"{'[预览] ' if dry_run else ''}{path} -> {dest}")
        if dry_run:
            summary.converted += 1
            continue
        try:
            with Image.open(path) as handle:
                prepared = _prepare(handle, fmt)
                prepared.load()  # 数据读入内存后即可关闭源文件（Windows 删除原图需要释放句柄）
            prepared.save(dest, format=fmt, **save_kwargs)
            summary.converted += 1
        except Exception as exc:  # noqa: BLE001 - 单张坏图不应中断整批
            print(f"转换失败: {path} ({exc})", file=sys.stderr)
            summary.failed += 1
            continue
        if delete_original:
            try:
                path.unlink()
            except OSError as exc:
                print(f"删除原图失败: {path} ({exc})", file=sys.stderr)
                summary.failed += 1

    verb = "计划转换" if dry_run else "已转换"
    print(f"\n完成: {verb} {summary.converted}，跳过 {summary.skipped}，失败 {summary.failed}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="用 Pillow 批量转换图片格式（webp/jpg/png/bmp 互转，透明转 jpg/bmp 垫白底）。",
    )
    parser.add_argument("source", type=Path, help="源图片或目录")
    parser.add_argument(
        "-t", "--to", required=True, choices=tuple(sorted(FORMATS)), help="目标格式"
    )
    parser.add_argument("-o", "--output-dir", type=Path, help="输出目录（留空保存在原图同目录）")
    parser.add_argument("--quality", type=int, help="质量 1-100（仅 jpg/webp 生效）")
    parser.add_argument("--delete-original", action="store_true", help="转换成功后删除原图")
    parser.add_argument(
        "--ext", help="目录模式的筛选后缀（空格/逗号分隔，留空用内置常见图片集合）"
    )
    parser.add_argument("--recursive", action="store_true", help="目录递归收集子目录图片")
    parser.add_argument("--dry-run", action="store_true", help="只显示计划，不实际转换")
    return parser


def main(argv: list[str] | None = None) -> int:
    from .common import normalize_suffixes

    args = build_parser().parse_args(argv)
    try:
        summary = convert_images(
            args.source,
            args.to,
            output_dir=args.output_dir,
            quality=args.quality,
            delete_original=args.delete_original,
            suffixes=normalize_suffixes([args.ext]) if args.ext else None,
            recursive=args.recursive,
            dry_run=args.dry_run,
        )
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
