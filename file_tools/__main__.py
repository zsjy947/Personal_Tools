"""文件处理工具集的统一交互入口。

各工具模块在进入对应功能时才导入，缺少第三方依赖不影响菜单本身。
"""

from pathlib import Path


class BackToMainMenu(Exception):
    """用户主动要求从当前工具返回主菜单。"""


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    hint = "[Y/n]" if default else "[y/N]"
    answer = input(f"{prompt} {hint}: ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "是"}


def ask_value(prompt: str) -> str:
    value = input(f"{prompt}: ").strip()
    if value == "0":
        raise BackToMainMenu
    return value


def run_image_decrypt() -> None:
    from .core.image_decrypt import normalize_suffixes, process_image, process_image_directory

    while True:
        operation_value = ask_value("操作：1 混淆 / 2 解混淆")
        if operation_value in {"1", "2"}:
            operation = "encrypt" if operation_value == "1" else "decrypt"
            break
        print("错误: 操作必须是 1 或 2。")

    print("\n模式: 1 方块 / 2 行像素 / 3 像素 / 4 PicEncrypt 行 / 5 PicEncrypt 行+列")
    input_path = Path(ask_value("输入图片路径").strip('"'))
    is_directory = input_path.is_dir()
    output_path = Path(
        ask_value("输出目录" if is_directory else "输出图片路径（包含扩展名）").strip('"')
    )

    while True:
        mode = ask_value("解密模式")
        if mode in {"1", "2", "3", "4", "5"}:
            break
        print("错误: 解密模式必须是 1 至 5。")

    while True:
        key = ask_value("密钥")
        if mode in {"1", "2", "3"}:
            break
        try:
            numeric_key = float(key)
        except ValueError:
            print("错误: 模式 4 和 5 的密钥必须是 0 到 1 之间的数字。")
            continue
        if 0 < numeric_key < 1:
            break
        print("错误: 模式 4 和 5 的密钥必须大于 0 且小于 1。")

    if is_directory:
        suffix_value = input("筛选后缀（留空处理常见图片格式，多个用空格或逗号分隔）: ")
        suffixes = normalize_suffixes([suffix_value.replace(" ", ",")])
        process_image_directory(
            operation,
            mode,
            input_path,
            key,
            output_path,
            suffixes=suffixes,
            recursive=ask_yes_no("递归处理子目录"),
            overwrite=ask_yes_no("覆盖已有输出文件"),
        )
    else:
        process_image(operation, mode, input_path, key, output_path)


def run_media_to_mp4() -> None:
    from .core.media_to_mp4 import convert_media, normalize_suffixes

    source = Path(ask_value("输入文件或目录").strip('"'))
    suffixes: set[str] = set()
    recursive = False
    if source.is_dir():
        suffixes = normalize_suffixes([input("筛选后缀（空格或逗号分隔）: ").replace(" ", ",")])
        recursive = ask_yes_no("递归处理子目录")
    output_value = input("统一输出目录（留空表示源文件目录）: ").strip().strip('"')
    convert_media(
        source,
        suffixes,
        recursive=recursive,
        output_dir=Path(output_value) if output_value else None,
        overwrite=ask_yes_no("覆盖已有 MP4"),
        dry_run=ask_yes_no("仅预览，不调用 ffmpeg"),
    )


def run_suffix_manager() -> None:
    from .core.suffix_manager import manage_suffix

    path = Path(ask_value("目标目录").strip('"'))
    marker = ask_value("文件名标记（如 .1 或 副本）")
    print("操作: 1 添加标记 / 2 移除标记 / 3 删除匹配文件")
    while True:
        choice = ask_value("操作")
        if choice in {"1", "2", "3"}:
            break
        print("错误: 操作必须是 1 至 3。")
    operation = {"1": "add", "2": "remove", "3": "delete"}[choice]
    manage_suffix(
        path,
        marker,
        operation,
        recursive=ask_yes_no("递归处理子目录"),
        dry_run=ask_yes_no("仅预览，不实际执行", default=True),
    )


def run_download_images() -> None:
    from .core.download_images import download_images

    list_path = Path(ask_value("链接列表路径（CSV/TXT）").strip('"'))
    output_value = input("输出目录（留空使用 downloaded_images）: ").strip().strip('"')
    download_images(list_path, output_value or "downloaded_images")


def run_media_grab() -> None:
    from .core.media_grab import grab_media

    url = ask_value("输入网页或直接的媒体/m3u8 地址").strip('"')
    output_value = input("输出目录（留空使用 media_downloads）: ").strip().strip('"')
    output = output_value or "media_downloads"
    print("嗅探模式: 1 直连（默认，站点可正常访问时用） / 2 浏览器（打开浏览器播放视频后捕获，站点被阻断/反爬时用）")
    while True:
        mode_choice = ask_value("选择模式")
        if mode_choice in {"1", "2", ""}:
            break
        print("错误: 模式必须是 1 或 2。")
    mode = "browser" if mode_choice == "2" else "direct"
    grab_media(url, output, mode=mode, list_only=True, probe=mode == "direct")
    if not ask_yes_no("是否下载部分资源（选否结束）"):
        return

    raw = input("下载第几个资源（序号，空格分隔；留空=全部）: ").strip()
    picks = [int(item) for item in raw.split()] if raw else None
    grab_media(
        url,
        output,
        mode=mode,
        picks=picks,
        grab_all=not raw,
        concurrency=8,
        to_mp4=ask_yes_no("视频流自动封装 MP4（选否保留原始流）", default=True),
        overwrite=ask_yes_no("覆盖已有输出文件"),
    )


def run_fanqie_novel() -> None:
    from .core.fanqie_novel import download_novel, search_books

    keyword = ask_value("书名关键词或书籍 ID/链接").strip('"')
    book_id = None
    import re

    match = re.search(r"fanqienovel\.com/page/(\d+)", keyword)
    if match:
        book_id = match.group(1)
    elif re.fullmatch(r"\d{5,25}", keyword):
        book_id = keyword
    if book_id is None:
        books = search_books(keyword)
        if not books:
            print("没有搜索到结果。")
            return
        for number, book in enumerate(books, 1):
            print(f"  [{number}] {book.title} | {book.author} | id={book.book_id}")
        while True:
            choice = ask_value("选择序号")
            if 1 <= int(choice) <= len(books):
                book_id = books[int(choice) - 1].book_id
                break
            print("错误: 序号超出范围。")
    output_value = input("输出目录（留空使用 novel_downloads）: ").strip().strip('"')
    fmt_value = input("格式 txt/epub（留空 txt）: ").strip().lower() or "txt"
    range_value = input("章节范围如 1-100（留空全部）: ").strip()
    download_novel(
        book_id,
        output_value or "novel_downloads",
        fmt=fmt_value if fmt_value in {"txt", "epub"} else "txt",
        chapter_range=range_value,
        on_progress=lambda done, total, title: print(f"[{done}/{total}] {title}"),
    )


def run_gui() -> None:
    """启动可视化界面，关闭窗口后返回主菜单。"""
    from .gui.app import main as gui_main

    gui_main()


def run_tool(action) -> None:
    while True:
        try:
            action()
        except BackToMainMenu:
            return
        except (FileNotFoundError, NotADirectoryError, OSError, RuntimeError, ValueError) as exc:
            print(f"错误: {exc}")
            print("请重新输入当前工具的参数，或输入 0 返回主菜单。")
            continue

        input("\n操作完成，按 Enter 返回主菜单...")
        return


def main() -> int:
    actions = {
        "1": run_image_decrypt,
        "2": run_media_to_mp4,
        "3": run_suffix_manager,
        "4": run_media_grab,
        "5": run_download_images,
        "6": run_fanqie_novel,
        "7": run_gui,
    }
    while True:
        print(
            "\n文件处理工具\n"
            "1. 图像混淆/解混淆\n"
            "2. 伪装媒体文件转 MP4\n"
            "3. 文件名标记管理（添加/移除标记、删除副本等）\n"
            "4. 网页媒体嗅探下载（含 m3u8 合并、B 站音视频合流）\n"
            "5. 图片批量下载（CSV/TXT 链接列表）\n"
            "6. 番茄小说搜索下载（仅供学习研究）\n"
            "7. 打开可视化界面\n"
            "0. 退出\n"
            "进入工具后，可随时输入 0 返回主菜单。"
        )
        choice = input("请选择: ").strip()
        if choice == "0":
            return 0
        action = actions.get(choice)
        if action is None:
            print("无效选项，请重新选择。")
            continue
        run_tool(action)


if __name__ == "__main__":
    raise SystemExit(main())
