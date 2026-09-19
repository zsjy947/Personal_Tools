"""把文件处理工具图形界面打包为 Windows exe。

在项目根目录执行（建议使用 .venv）：

    python build_exe.py             # 目录模式：dist/FileTools/FileTools.exe（启动快，推荐）
    python build_exe.py --onefile   # 单文件模式：dist/FileTools.exe（便于拷贝，启动需解压）

首次构建前安装打包工具：pip install pyinstaller

说明：
- 依赖 numpy/numba/llvmlite，产物体积较大（数百 MB）；目录模式免解压、启动更快，
  分发时打包整个 FileTools 文件夹即可。
- ffmpeg 通过 imageio-ffmpeg 内置进 exe，媒体转 MP4/嗅探合流等功能不依赖系统
  安装、也不会弹出外部命令行窗口（功能不出域）；如需替换版本，可把 ffmpeg.exe
  放到 exe 同目录。
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "FileTools"
APP_VERSION = "2.2"
ENTRY = ROOT / "file_tools" / "gui" / "__main__.py"
ICON = ROOT / "file_tools" / "gui" / "assets" / "app.ico"
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"

VERSION_TEMPLATE = """\
# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({major}, {minor}, 0, 0),
    prodvers=({major}, {minor}, 0, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable('040904b0', [
        StringStruct('CompanyName', 'xiegq02'),
        StringStruct('FileDescription', 'File processing tools (GUI)'),
        StringStruct('FileVersion', '{major}.{minor}.0.0'),
        StringStruct('InternalName', 'FileTools'),
        StringStruct('OriginalFilename', 'FileTools.exe'),
        StringStruct('ProductName', 'FileTools'),
        StringStruct('ProductVersion', '{major}.{minor}.0.0'),
      ]),
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])]),
  ],
)
"""


def ensure_pyinstaller() -> None:
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        sys.exit("未安装 PyInstaller，请先执行: pip install pyinstaller")


def ensure_icon() -> Path | None:
    """返回图标路径；缺失时用 Pillow 高分辨率绘制（渐变底 + 文档 + 下载角标）。"""
    if ICON.is_file():
        return ICON
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("未找到图标且缺少 Pillow，跳过自定义图标。")
        return None

    ICON.parent.mkdir(parents=True, exist_ok=True)
    final = 256
    ss = 4  # 超采样：1024 绘制后缩到 256，边缘平滑
    size = final * ss

    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # 垂直渐变蓝色底（先画 1×size 再拉伸），圆角蒙版
    top, bottom = (59, 130, 246), (30, 58, 138)
    column = Image.new("RGBA", (1, size))
    for y in range(size):
        t = y / (size - 1)
        column.putpixel(
            (0, y),
            tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,),
        )
    gradient = column.resize((size, size))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size - 1, size - 1), radius=int(size * 0.225), fill=255
    )
    image.paste(gradient, (0, 0), mask)
    draw = ImageDraw.Draw(image)

    # 白色文档（右上角折角）
    sheet = (int(size * 0.285), int(size * 0.20), int(size * 0.715), int(size * 0.80))
    draw.rounded_rectangle(sheet, radius=int(size * 0.055), fill=(255, 255, 255, 255))
    fold = int(size * 0.115)
    fx1, fy1 = sheet[2] - fold, sheet[1]
    draw.polygon(
        [(fx1, fy1), (sheet[2], fy1), (sheet[2], fy1 + fold)],
        fill=(191, 219, 254, 255),
    )
    draw.rounded_rectangle(
        (fx1, fy1, sheet[2], fy1 + fold), radius=int(size * 0.03), fill=(219, 234, 254, 255)
    )
    draw.polygon(
        [(fx1, fy1 + fold), (sheet[2], fy1 + fold), (sheet[2], fy1)],
        fill=(191, 219, 254, 255),
    )

    # 文档内容条
    bar_y = int(size * 0.36)
    for index, width in enumerate((0.27, 0.21, 0.24)):
        y = bar_y + index * int(size * 0.105)
        draw.rounded_rectangle(
            (int(size * 0.35), y, int(size * 0.35 + size * width), y + int(size * 0.045)),
            radius=int(size * 0.022),
            fill=(147, 197, 253, 255),
        )

    # 右下角下载角标：白圈 + 蓝底 + 白色下载箭头
    badge_c = (int(size * 0.685), int(size * 0.685))
    badge_r = int(size * 0.165)
    draw.ellipse(
        (badge_c[0] - badge_r, badge_c[1] - badge_r, badge_c[0] + badge_r, badge_c[1] + badge_r),
        fill=(255, 255, 255, 255),
    )
    inner_r = int(badge_r * 0.86)
    draw.ellipse(
        (badge_c[0] - inner_r, badge_c[1] - inner_r, badge_c[0] + inner_r, badge_c[1] + inner_r),
        fill=(37, 99, 235, 255),
    )
    shaft_w = int(badge_r * 0.30)
    top_y = badge_c[1] - int(badge_r * 0.52)
    bottom_y = badge_c[1] + int(badge_r * 0.10)
    draw.rounded_rectangle(
        (badge_c[0] - shaft_w // 2, top_y, badge_c[0] + shaft_w // 2, bottom_y),
        radius=shaft_w // 2,
        fill=(255, 255, 255, 255),
    )
    head_w = int(badge_r * 0.62)
    head_h = int(badge_r * 0.42)
    draw.polygon(
        [
            (badge_c[0], bottom_y + head_h),
            (badge_c[0] - head_w, bottom_y - int(head_h * 0.15)),
            (badge_c[0] + head_w, bottom_y - int(head_h * 0.15)),
        ],
        fill=(255, 255, 255, 255),
    )
    draw.rounded_rectangle(
        (badge_c[0] - int(badge_r * 0.42), bottom_y + int(head_h * 1.05),
         badge_c[0] + int(badge_r * 0.42), bottom_y + int(head_h * 1.05) + int(badge_r * 0.14)),
        radius=int(badge_r * 0.07),
        fill=(255, 255, 255, 255),
    )

    image = image.resize((final, final), Image.LANCZOS)
    image.save(
        ICON,
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print(f"已生成图标: {ICON}")
    return ICON


def write_version_file() -> Path:
    major, minor = APP_VERSION.split(".")[:2]
    path = BUILD_DIR / "version_info.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        VERSION_TEMPLATE.format(major=major, minor=minor), encoding="utf-8"
    )
    return path


def build(onefile: bool) -> None:
    ensure_pyinstaller()
    icon = ensure_icon()
    version_file = write_version_file()

    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--noconsole",
        "--name",
        APP_NAME,
        "--distpath",
        str(DIST_DIR),
        "--workpath",
        str(BUILD_DIR / "work"),
        "--specpath",
        str(BUILD_DIR),
        "--paths",
        str(ROOT),
        # 界面里的工具模块是执行任务时才导入，显式收集防止漏打包
        "--collect-submodules",
        "file_tools.core",
        # 内置 ffmpeg（imageio-ffmpeg）、curl_cffi（指纹回退）与 fonttools（小说反混淆）
        "--collect-all",
        "imageio_ffmpeg",
        "--collect-all",
        "curl_cffi",
        "--collect-all",
        "fonttools",
        "--version-file",
        str(version_file),
    ]
    if icon is not None:
        args += ["--icon", str(icon), "--add-data", f"{icon};assets"]
    args += ["--onefile" if onefile else "--onedir", str(ENTRY)]

    print("执行:", " ".join(args))
    subprocess.run(args, check=True, cwd=ROOT)

    output = DIST_DIR / f"{APP_NAME}.exe" if onefile else DIST_DIR / APP_NAME / f"{APP_NAME}.exe"
    print(f"\n构建完成: {output}")
    if not onefile:
        print(f"分发时请打包整个文件夹: {DIST_DIR / APP_NAME}")


def main() -> int:
    parser = argparse.ArgumentParser(description="打包文件处理工具图形界面为 exe。")
    parser.add_argument(
        "--onefile",
        action="store_true",
        help="单文件模式（免解压启动更快的是默认目录模式）",
    )
    args = parser.parse_args()
    build(onefile=args.onefile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
