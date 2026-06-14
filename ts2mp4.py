"""将 TS 文件转换为 MP4（基于 ffmpeg）。"""

import os
import subprocess


def ts_to_mp4(ts_file_path: str, output_mp4_path: str | None = None) -> str:
    """将单个 .ts 文件转换为 .mp4。

    Args:
        ts_file_path: 输入的 .ts 文件路径
        output_mp4_path: 输出的 .mp4 路径，默认与输入同目录同名

    Returns:
        输出文件的路径

    Raises:
        FileNotFoundError: 输入文件不存在
        RuntimeError: ffmpeg 转换失败
    """
    if not os.path.exists(ts_file_path):
        raise FileNotFoundError(f"TS 文件不存在：{ts_file_path}")

    if not output_mp4_path:
        file_dir = os.path.dirname(ts_file_path)
        file_name = os.path.splitext(os.path.basename(ts_file_path))[0]
        output_mp4_path = os.path.join(file_dir, f"{file_name}.mp4")

    ffmpeg_cmd = [
        "ffmpeg",
        "-i", ts_file_path,
        "-c", "copy",
        "-y",
        output_mp4_path,
    ]

    try:
        subprocess.run(ffmpeg_cmd, check=True)
        print(f"转换成功：{output_mp4_path}")
        return output_mp4_path

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"转换失败：{e}")


def batch_ts_to_mp4(folder_path: str) -> None:
    """批量将文件夹中所有 .ts 文件转换为 .mp4。

    Args:
        folder_path: 包含 .ts 文件的文件夹路径

    Raises:
        NotADirectoryError: 文件夹不存在
    """
    if not os.path.isdir(folder_path):
        raise NotADirectoryError(f"文件夹不存在：{folder_path}")

    ts_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".ts")]
    if not ts_files:
        print(f"文件夹 '{folder_path}' 中没有找到 .ts 文件。")
        return

    for file_name in ts_files:
        ts_path = os.path.join(folder_path, file_name)
        ts_to_mp4(ts_path)

    print(f"\n批量转换完成！共处理 {len(ts_files)} 个文件。")


if __name__ == "__main__":
    # 单个文件转换
    # TS_FILE = r"D:\视频\test.ts"
    # ts_to_mp4(TS_FILE)

    # 批量转换
    TS_FOLDER = r"your_folder_path_here"
    batch_ts_to_mp4(TS_FOLDER)
