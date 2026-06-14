"""单层目录文件批量重命名工具：添加或移除 .1 后缀。

注意：仅处理指定目录的直接文件，不递归子文件夹。
"""

from pathlib import Path


def add_dot1_to_files(folder_path: str | Path) -> None:
    """对文件夹中所有文件，在其完整文件名（包括扩展名）后添加 '.1'。

    例如：'升旗视频.mp4' -> '升旗视频.mp4.1'

    Args:
        folder_path: 目标文件夹路径
    """
    folder = Path(folder_path)

    if not folder.exists():
        print(f"错误：文件夹 '{folder}' 不存在。")
        return

    if not folder.is_dir():
        print(f"错误：'{folder}' 不是一个文件夹。")
        return

    files = [f for f in folder.iterdir() if f.is_file()]

    if not files:
        print(f"文件夹 '{folder}' 中没有找到任何文件。")
        return

    renamed_count = 0
    for file_path in files:
        new_name = file_path.name + '.1'
        new_path = file_path.parent / new_name

        try:
            file_path.rename(new_path)
            print(f"已重命名: {file_path.name} -> {new_name}")
            renamed_count += 1
        except FileExistsError:
            print(f"跳过: {new_name} 已存在。")
        except PermissionError as e:
            print(f"权限错误，无法重命名 {file_path.name}: {e}")
        except Exception as e:
            print(f"重命名 {file_path.name} 时发生错误: {e}")

    print(f"\n操作完成。成功重命名 {renamed_count} 个文件。")


def remove_dot1_from_files(folder_path: str | Path) -> None:
    """对文件夹中所有以 '.1' 结尾的文件，移除末尾的 '.1'。

    例如：'升旗视频.mp4.1' -> '升旗视频.mp4'

    Args:
        folder_path: 目标文件夹路径
    """
    folder = Path(folder_path)

    if not folder.exists():
        print(f"错误：文件夹 '{folder}' 不存在。")
        return

    if not folder.is_dir():
        print(f"错误：'{folder}' 不是一个文件夹。")
        return

    files = [f for f in folder.iterdir() if f.is_file() and f.name.endswith('.1')]

    if not files:
        print(f"文件夹 '{folder}' 中没有找到以 '.1' 结尾的文件。")
        return

    renamed_count = 0
    for file_path in files:
        new_name = file_path.name[:-2]  # 去掉最后两个字符 '.1'
        new_path = file_path.parent / new_name

        if new_path.exists():
            print(f"跳过: 目标文件 '{new_name}' 已存在，无法重命名 {file_path.name}。")
            continue

        try:
            file_path.rename(new_path)
            print(f"已重命名: {file_path.name} -> {new_name}")
            renamed_count += 1
        except PermissionError as e:
            print(f"权限错误，无法重命名 {file_path.name}: {e}")
        except Exception as e:
            print(f"重命名 {file_path.name} 时发生错误: {e}")

    print(f"\n操作完成。成功移除 '.1' 后缀 {renamed_count} 个文件。")


if __name__ == "__main__":
    # 请将下面的路径替换为您想要操作的实际文件夹路径
    target_folder = r"your_target_folder_path_here"

    print(f"目标文件夹: {target_folder}")
    print("\n--- 执行移除 '.1' 操作 ---")
    remove_dot1_from_files(target_folder)
