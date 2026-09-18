"""批量图片下载：从 CSV/TXT 链接列表读取 URL 并并发下载。

由根目录独立脚本改造并入 file_tools：
- 输入支持 CSV（取每行第一列）或纯文本（每行一个 URL），允许 # 注释与空行。
- 并发下载（默认 4）、单文件失败重试、失败不中断。
- 文件名取自 URL；无扩展名时按 Content-Type 补全；同名自动追加序号。
"""

import argparse
import concurrent.futures
import csv
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/avif": ".avif",
    "image/x-icon": ".ico",
    "image/tiff": ".tiff",
}

_SANITIZE_RE = re.compile(r'[\\/:*?"<>|]+')


@dataclass
class DownloadSummary:
    total: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0


def read_urls(list_path: str | Path) -> list[str]:
    """读取链接列表：CSV 取第一列，纯文本每行一个 URL。"""
    list_path = Path(list_path)
    if not list_path.is_file():
        raise FileNotFoundError(f"链接列表不存在: {list_path}")
    urls: list[str] = []
    with list_path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if not row:
                continue
            first = row[0].strip()
            if first and not first.startswith("#"):
                urls.append(first)
    return urls


def _filename_for(url: str, content_type: str | None, used: set[str], lock: threading.Lock) -> Path:
    """从 URL 生成安全文件名；无扩展名按 Content-Type 补全；同名追加序号。"""
    name = _SANITIZE_RE.sub("_", unquote(urlsplit(url).path).rsplit("/", 1)[-1]).strip()
    if not name or name in {".", ".."}:
        name = "image"
    path = Path(name)
    if not path.suffix:
        suffix = CONTENT_TYPE_EXT.get((content_type or "").split(";")[0].strip().lower(), ".jpg")
        name = f"{name}{suffix}"
    candidate = name
    sequence = 1
    with lock:
        while candidate in used:
            stem, suffix = Path(name).stem, Path(name).suffix
            candidate = f"{stem} ({sequence}){suffix}"
            sequence += 1
        used.add(candidate)
    return Path(candidate)


def download_images(
    list_path: str | Path,
    output_dir: str | Path = "downloaded_images",
    *,
    concurrency: int = 4,
    timeout: float = 30,
    delay: float = 0.2,
    retries: int = 2,
    overwrite: bool = False,
) -> DownloadSummary:
    """读取链接列表并发下载图片到指定目录。"""
    urls = read_urls(list_path)
    summary = DownloadSummary(total=len(urls))
    if not urls:
        print("链接列表中没有可用 URL。")
        return summary
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"共 {len(urls)} 个链接，并发 {concurrency}，保存至 {output_dir}\n")

    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_UA,
        "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
    })
    used_names: set[str] = {p.name for p in output_dir.iterdir() if p.is_file()}
    name_lock = threading.Lock()
    counter_lock = threading.Lock()
    done = [0]

    def fetch(index_url: tuple[int, str]) -> None:
        index, url = index_url
        destination: Path | None = None
        try:
            last_error: Exception | None = None
            response = None
            for _attempt in range(retries + 1):
                try:
                    response = session.get(url, timeout=timeout, stream=True)
                    response.raise_for_status()
                    break
                except requests.RequestException as exc:
                    last_error = exc
                    response = None
            if response is None:
                raise RuntimeError(f"重试 {retries} 次后仍失败（{last_error}）")

            filename = _filename_for(
                url, response.headers.get("Content-Type"), used_names, name_lock
            )
            destination = output_dir / filename
            if destination.exists() and not overwrite:
                with counter_lock:
                    done[0] += 1
                    summary.skipped += 1
                    print(f"[{done[0]}/{len(urls)}] 跳过（已存在）: {filename}")
                return
            temporary = destination.with_suffix(destination.suffix + ".part")
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        handle.write(chunk)
            temporary.replace(destination)
            with counter_lock:
                done[0] += 1
                summary.downloaded += 1
                print(f"[{done[0]}/{len(urls)}] 已下载: {filename}")
        except (OSError, RuntimeError, requests.RequestException) as exc:
            if destination is not None:
                destination.with_suffix(destination.suffix + ".part").unlink(missing_ok=True)
            with counter_lock:
                done[0] += 1
                summary.failed += 1
                print(f"[{done[0]}/{len(urls)}] 下载失败: {url} — {exc}")
        if delay > 0:
            time.sleep(delay)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        list(pool.map(fetch, enumerate(urls, 1)))

    print(
        f"\n完成: 新增 {summary.downloaded}，跳过 {summary.skipped}，"
        f"失败 {summary.failed}；保存至 '{output_dir}'。"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="从 CSV/TXT 读取图片 URL 并批量下载。")
    parser.add_argument(
        "-i", "--input", required=True, type=Path,
        help="链接列表路径（CSV 取第一列或每行一个 URL 的文本）",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=Path("downloaded_images"),
        help="下载目标文件夹（默认: downloaded_images）",
    )
    parser.add_argument("--concurrency", type=int, default=4, help="并发下载数（默认 4）")
    parser.add_argument("--timeout", type=float, default=30, help="请求超时秒数（默认 30）")
    parser.add_argument("--delay", type=float, default=0.2, help="每个请求后的间隔秒数（默认 0.2）")
    parser.add_argument("--retries", type=int, default=2, help="单文件重试次数（默认 2）")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已存在的同名文件")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.concurrency <= 0 or args.timeout <= 0 or args.delay < 0 or args.retries < 0:
        print("错误：并发/超时必须大于 0，延迟与重试不能为负。", file=sys.stderr)
        return 1
    try:
        summary = download_images(
            args.input,
            args.output,
            concurrency=args.concurrency,
            timeout=args.timeout,
            delay=args.delay,
            overwrite=args.overwrite,
        )
    except (OSError, csv.Error) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
