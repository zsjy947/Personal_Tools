"""从 url.csv 读取图片链接并批量下载。"""

import argparse
import csv
import os
import sys
import time

import requests


def download_images(csv_path: str, output_dir: str = "downloaded_images") -> None:
    """读取 CSV 中的 URL 列表，下载图片到指定文件夹。

    Args:
        csv_path: CSV 文件路径，每行一个 URL
        output_dir: 输出文件夹路径
    """
    os.makedirs(output_dir, exist_ok=True)

    with open(csv_path, encoding="utf-8") as f:
        reader = csv.reader(f)
        urls = [row[0].strip() for row in reader if row]

    if not urls:
        print("CSV 文件中没有找到 URL。")
        return

    print(f"共 {len(urls)} 个图片待下载。\n")

    headers = {
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    }
    success = 0

    for i, url in enumerate(urls, 1):
        filename = os.path.basename(url.split("?")[0])
        filepath = os.path.join(output_dir, filename)

        if os.path.exists(filepath):
            print(f"[{i}/{len(urls)}] 跳过（已存在）: {filename}")
            success += 1
            continue

        try:
            resp = requests.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            with open(filepath, "wb") as out:
                out.write(resp.content)
            print(f"[{i}/{len(urls)}] 已下载: {filename}")
            success += 1
        except requests.RequestException as e:
            print(f"[{i}/{len(urls)}] 下载失败: {filename} — {e}")

        time.sleep(0.5)

    print(f"\n完成。成功 {success}/{len(urls)}，保存至 '{output_dir}'。")


if __name__ == "__main__":
    default_csv = os.path.join(os.path.dirname(__file__), "url.csv")

    parser = argparse.ArgumentParser(description="从 CSV 文件读取图片 URL 并批量下载。")
    parser.add_argument(
        "-i", "--input",
        default=default_csv,
        help=f"CSV 文件路径（默认: {default_csv}）",
    )
    parser.add_argument(
        "-o", "--output",
        default="downloaded_images",
        help="下载目标文件夹（默认: downloaded_images）",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f"错误：CSV 文件不存在 — '{args.input}'", file=sys.stderr)
        sys.exit(1)

    download_images(args.input, args.output)
