"""文件处理工具集的统一交互入口。"""

from pathlib import Path

from .delete_copy_files import delete_copy_files
from .dot1_suffix import rename_dot1_files
from .image_decrypt import process_image
from .media_to_mp4 import convert_media, normalize_suffixes


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
    while True:
        operation_value = ask_value("操作：1 混淆 / 2 解混淆")
        if operation_value in {"1", "2"}:
            operation = "encrypt" if operation_value == "1" else "decrypt"
            break
        print("错误: 操作必须是 1 或 2。")

    print("\n模式: 1 方块 / 2 行像素 / 3 像素 / 4 PicEncrypt 行 / 5 PicEncrypt 行+列")
    input_path = Path(ask_value("输入图片路径").strip('"'))
    output_path = Path(ask_value("输出图片路径（包含扩展名）").strip('"'))

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

    process_image(operation, mode, input_path, key, output_path)


def run_media_to_mp4() -> None:
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


def run_dot1(operation: str) -> None:
    path = Path(ask_value("目标目录").strip('"'))
    rename_dot1_files(
        path,
        operation,
        recursive=ask_yes_no("递归处理子目录"),
        dry_run=ask_yes_no("仅预览，不重命名", default=True),
    )


def run_delete_copy_files() -> None:
    path = Path(ask_value("目标目录").strip('"'))
    execute = ask_yes_no("确认实际删除匹配文件；选择否仅预览")
    delete_copy_files(path, execute=execute)


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
        "3": lambda: run_dot1("add"),
        "4": lambda: run_dot1("remove"),
        "5": run_delete_copy_files,
    }
    while True:
        print(
            "\n文件处理工具\n"
            "1. 图像混淆/解混淆\n"
            "2. 伪装媒体文件转 MP4\n"
            "3. 添加 .1 后缀\n"
            "4. 移除 .1 后缀\n"
            "5. 删除文件名以‘副本’结尾的文件\n"
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
