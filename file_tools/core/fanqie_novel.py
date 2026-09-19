"""番茄小说搜索与下载（仅供学习研究，请尊重作者版权，勿用于商业用途）。

本模块是内置 Rust 后端 TomatoNovelDownloader.exe 的薄客户端：
后端（上游 https://github.com/zhongbai2333/Tomato-Novel-Downloader v2.4.15，
MIT 许可，随本工具打包于 core/data/，许可文本见同目录）以 `--server` 模式
在 127.0.0.1 本地端口提供 Web API，走 App 官方 API 明文链路（设备注册 →
内容密钥 → 批量章节），搜索与下载均经它完成，正文无错字。

不包含任何网页抓取或字体反混淆逻辑；后端进程全局复用，随程序退出终止。
"""

import argparse
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import requests

_TOMATO_EXE = Path(__file__).resolve().parent / "data" / "TomatoNovelDownloader.exe"
_TOMATO_PORT = 38474
_TOMATO_WORKDIR = Path(tempfile.gettempdir()) / "file_tools_tomato"
_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n]+')

_tomato_proc = None  # 全局复用，避免每次调用都重启后端


@dataclass
class BookInfo:
    book_id: str
    title: str = ""
    author: str = ""
    abstract: str = ""
    word_count: int = 0


@dataclass
class NovelSummary:
    total: int = 0
    downloaded: int = 0
    failed: int = 0
    output: str = ""


def sanitize_filename(name: str) -> str:
    return _ILLEGAL_RE.sub("_", name).strip()[:80] or "未命名"


def parse_chapter_range(raw: str) -> tuple[int, int] | None:
    """把 "3-20" 之类的输入解析成 [起,止]（1 起，含端点）；空返回 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", raw)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
    else:
        start = end = int(raw)
    if start < 1 or end < start:
        raise ValueError(f"章节范围无效: {raw}")
    return start, end


def re_search_id(text: str) -> str | None:
    """从文本中提取书籍 ID（纯数字 ID 或 fanqienovel.com/page/{id} 链接）。"""
    match = re.search(r"fanqienovel\.com/page/(\d+)", text)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d{5,25}", text.strip()):
        return text.strip()
    return None


# -------- 内置后端管理 --------

def _find_tomato_exe() -> Path | None:
    """定位内置 Rust 后端：环境变量优先，其次随包 data 目录。"""
    override = os.environ.get("FILE_TOOLS_TOMATO_EXE", "").strip()
    if override and Path(override).is_file():
        return Path(override)
    if _TOMATO_EXE.is_file():
        return _TOMATO_EXE
    return None


def _shutdown_tomato() -> None:
    global _tomato_proc
    if _tomato_proc is not None and _tomato_proc.poll() is None:
        _tomato_proc.terminate()
    _tomato_proc = None


atexit.register(_shutdown_tomato)


def _tomato_server() -> str:
    """启动（或复用）内置后端的 Web 服务，返回 base URL。"""
    global _tomato_proc
    base = f"http://127.0.0.1:{_TOMATO_PORT}"
    if _tomato_proc is not None and _tomato_proc.poll() is None:
        return base
    try:
        if requests.get(base + "/api/status", timeout=2).json().get("version"):
            return base  # 已有实例（如上次运行遗留）在监听
    except Exception:  # noqa: BLE001 - 端口无人监听则启动
        pass

    exe = _find_tomato_exe()
    if exe is None:
        raise RuntimeError(
            "未找到内置番茄下载后端（TomatoNovelDownloader.exe），请重新安装本工具"
        )

    workdir = _TOMATO_WORKDIR
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / "output").mkdir(exist_ok=True)
    (workdir / "config.yml").write_text(
        "max_workers: 3\n"
        "request_timeout: 15\n"
        "max_retries: 3\n"
        f"save_path: '{(workdir / 'output').as_posix()}'\n"
        "novel_format: txt\n"
        "bulk_files: false\n"
        "auto_clear_dump: true\n"
        "auto_open_downloaded_files: false\n"
        "enable_audiobook: false\n"
        "use_official_api: true\n"
        "ask_format_after_download: false\n"
        "ask_after_download: false\n"
        "preferred_book_name_field: book_name\n",
        encoding="utf-8",
    )
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    _tomato_proc = subprocess.Popen(
        [str(exe), "--server", "--data-dir", str(workdir)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        env={**os.environ, "TOMATO_WEB_ADDR": f"127.0.0.1:{_TOMATO_PORT}"},
    )
    for _ in range(40):
        if _tomato_proc.poll() is not None:
            break
        try:
            if requests.get(base + "/api/status", timeout=2).json().get("version"):
                return base
        except Exception:  # noqa: BLE001 - 尚未就绪
            time.sleep(0.5)
    raise RuntimeError("内置番茄下载后端启动失败")


def _tomato_set_format(base: str, fmt: str) -> None:
    requests.post(
        base + "/api/config/raw", json={"yaml": f"novel_format: {fmt}\n"}, timeout=10
    ).raise_for_status()


# -------- 搜索与下载 --------

def search_books(keyword: str, *, limit: int = 12) -> list[BookInfo]:
    """按书名搜索（经内置后端官方 API）。"""
    base = _tomato_server()
    response = requests.get(base + "/api/search", params={"q": keyword}, timeout=30)
    response.raise_for_status()
    items = (response.json().get("items") or [])[:limit]
    books = []
    for item in items:
        raw = item.get("raw") or {}
        books.append(
            BookInfo(
                book_id=str(item.get("book_id") or raw.get("book_id") or ""),
                title=item.get("title") or raw.get("book_name") or "未知书名",
                author=item.get("author") or raw.get("author") or "",
                abstract=(raw.get("abstract") or raw.get("book_abstract_v2") or "").strip(),
                word_count=int(raw.get("word_number") or 0),
            )
        )
    return [b for b in books if b.book_id]


def fetch_book(book_id: str) -> BookInfo:
    """按书籍 ID 取书名/作者/简介（经内置后端预览接口）。"""
    base = _tomato_server()
    response = requests.get(base + f"/api/preview/{book_id}", timeout=30)
    response.raise_for_status()
    data = response.json()
    return BookInfo(
        book_id=str(data.get("book_id") or book_id),
        title=data.get("book_name") or data.get("title") or "未知书名",
        author=data.get("author") or "",
        abstract=(data.get("description") or data.get("abstract") or "").strip(),
    )


def download_novel(
    book_id: str,
    output_dir: str | Path = "novel_downloads",
    *,
    fmt: str = "txt",
    chapter_range: str = "",
    on_progress=None,
) -> NovelSummary:
    """下载整本（或指定范围）小说。on_progress(完成数, 总数, 标题)。

    经内置后端官方 API 明文链路下载，产物为后端生成的 TXT/EPUB。
    """
    if fmt not in {"txt", "epub"}:
        raise ValueError(f"不支持的格式: {fmt}")
    base = _tomato_server()
    _tomato_set_format(base, fmt)
    status = requests.get(base + "/api/status", timeout=10).json()
    save_dir = Path(status.get("save_dir") or (_TOMATO_WORKDIR / "output"))

    payload = {"book_id": str(book_id)}
    bounds = parse_chapter_range(chapter_range)
    if bounds:
        payload["range_start"] = bounds[0]
        payload["range_end"] = bounds[1]
    response = requests.post(base + "/api/jobs", json=payload, timeout=15)
    response.raise_for_status()
    job_id = str(response.json().get("id"))

    deadline = time.time() + 1800
    title = ""
    saved = total = 0
    while time.time() < deadline:
        time.sleep(1.5)
        items = requests.get(base + "/api/jobs", timeout=10).json().get("items") or []
        item = next((it for it in items if str(it.get("id")) == job_id), None)
        if item is None:
            continue
        title = item.get("title") or title
        progress = item.get("progress") or {}
        saved = int(progress.get("saved_chapters") or 0)
        total = int(progress.get("chapter_total") or 0)
        state = item.get("state")
        if on_progress and total:
            on_progress(min(saved, total), total, title)
        if state == "done":
            break
        if state in {"failed", "error", "cancelled"}:
            raise RuntimeError(f"后端下载失败: {item.get('message') or state}")
        if item.get("book_name_options") or item.get("format_options"):
            requests.post(f"{base}/api/jobs/{job_id}/cancel", timeout=10)
            raise RuntimeError("后端任务需要交互选择（书名/格式），请重试")
    else:
        raise RuntimeError("后端下载超时")

    suffix = ".txt" if fmt == "txt" else ".epub"
    produced = sorted(
        save_dir.glob(f"*{suffix}"), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not produced:
        raise RuntimeError("后端未生成输出文件")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    destination = output_path / f"{sanitize_filename(title or book_id)}{suffix}"
    shutil.copyfile(produced[0], destination)
    print(f"完成: 《{title or book_id}》{saved}/{total or saved} 章 → {destination}")
    return NovelSummary(total=total or saved, downloaded=saved, output=str(destination))


# -------- CLI --------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="番茄小说搜索与下载（仅供学习研究，请尊重作者版权）。"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search_parser = sub.add_parser("search", help="按书名搜索")
    search_parser.add_argument("keyword", help="搜索关键词")

    download_parser = sub.add_parser("download", help="下载书籍（书页地址或 book_id）")
    download_parser.add_argument("book", help="书籍 ID 或 fanqienovel.com 书页地址")
    download_parser.add_argument("-o", "--output", type=Path, default=Path("novel_downloads"))
    download_parser.add_argument("--format", choices=("txt", "epub"), default="txt")
    download_parser.add_argument("--range", dest="chapter_range", help="章节范围，如 1-100（默认全部）")

    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            books = search_books(args.keyword)
            if not books:
                print("没有搜索到结果。")
                return 0
            for number, book in enumerate(books, 1):
                print(f"  [{number}] {book.title} | {book.author} | id={book.book_id}")
                if book.abstract:
                    print(f"      {book.abstract[:60]}")
            return 0
        match = re_search_id(args.book)
        if not match:
            print(f"错误: 无法从输入中识别书籍 ID: {args.book}", file=sys.stderr)
            return 1
        summary = download_novel(
            match, args.output, fmt=args.format, chapter_range=args.chapter_range,
            on_progress=lambda done, total, title: print(f"[{done}/{total}] {title}"),
        )
        return 0 if summary.downloaded else 1
    except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
