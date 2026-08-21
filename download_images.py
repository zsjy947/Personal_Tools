"""从 url.csv 读取图片链接并批量下载。"""

import argparse
import csv
import sys
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests


def download_images(
    csv_path: str | Path,
    output_dir: str | Path = "downloaded_images",
    timeout: float = 30,
    delay: float = 0.5,
) -> tuple[int, int, int]:
    """读取 CSV 中的 URL 列表，下载图片到指定文件夹。

    Args:
        csv_path: CSV 文件路径，每行一个 URL
        output_dir: 输出文件夹路径
    """
    csv_path = Path(csv_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        urls = [row[0].strip() for row in reader if row]

    if not urls:
        print("CSV 文件中没有找到 URL。")
        return 0, 0, 0

    print(f"共 {len(urls)} 个图片待下载。\n")

    headers = {
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    downloaded = 0
    skipped = 0
    failed = 0

    for i, url in enumerate(urls, 1):
        filename = Path(unquote(urlsplit(url).path)).name
        if not filename or filename in {".", ".."}:
            print(f"[{i}/{len(urls)}] 下载失败: URL 中没有有效文件名 — {url}")
            failed += 1
            continue
        filepath = output_dir / filename

        if filepath.exists():
            print(f"[{i}/{len(urls)}] 跳过（已存在）: {filename}")
            skipped += 1
            continue

        try:
            with requests.get(url, headers=headers, timeout=timeout, stream=True) as resp:
                resp.raise_for_status()
                with filepath.open("wb") as out:
                    for chunk in resp.iter_content(chunk_size=64 * 1024):
                        if chunk:
                            out.write(chunk)
            print(f"[{i}/{len(urls)}] 已下载: {filename}")
            downloaded += 1
        except (OSError, requests.RequestException) as e:
            filepath.unlink(missing_ok=True)
            print(f"[{i}/{len(urls)}] 下载失败: {filename} — {e}")
            failed += 1

        if delay > 0:
            time.sleep(delay)

    print(
        f"\n完成: 新增 {downloaded}，跳过 {skipped}，失败 {failed}；"
        f"保存至 '{output_dir}'。"
    )
    return downloaded, skipped, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 CSV 文件读取图片 URL 并批量下载。")
    parser.add_argument(
        "-i", "--input",
        required=True,
        type=Path,
        help="CSV 文件路径，每行第一列为一个 URL",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=Path("downloaded_images"),
        help="下载目标文件夹（默认: downloaded_images）",
    )
    parser.add_argument("--timeout", type=float, default=30, help="请求超时秒数（默认: 30）")
    parser.add_argument("--delay", type=float, default=0.5, help="每次请求后的间隔秒数（默认: 0.5）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.input.is_file():
        print(f"错误：CSV 文件不存在 — '{args.input}'", file=sys.stderr)
        return 1
    if args.timeout <= 0:
        print("错误：--timeout 必须大于 0", file=sys.stderr)
        return 1
    if args.delay < 0:
        print("错误：--delay 不能小于 0", file=sys.stderr)
        return 1

    try:
        _, _, failed = download_images(
            args.input,
            args.output,
            timeout=args.timeout,
            delay=args.delay,
        )
    except (OSError, csv.Error) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
