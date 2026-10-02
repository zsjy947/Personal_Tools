"""核心模块共享的纯函数小工具（不依赖第三方库）。"""

from pathlib import Path


def normalize_suffixes(values: list[str] | None) -> set[str]:
    """把 "mp4 m3u8 ts"、"jpeg,png"、"gif，webp" 之类的输入规范成补点小写集合。

    兼容英文/中文逗号与空格分隔（原 media_grab 版实现，为三份重复实现中的超集）。
    """
    suffixes: set[str] = set()
    for value in values or []:
        for item in value.replace("，", ",").replace(" ", ",").split(","):
            item = item.strip().lower()
            if item:
                suffixes.add(item if item.startswith(".") else f".{item}")
    return suffixes


def unique_path(dest: Path) -> Path:
    """目标重名时自动追加序号（a.txt → a-1.txt → a-2.txt），不动已有文件。"""
    if not dest.exists():
        return dest
    counter = 1
    while True:
        candidate = dest.with_name(f"{dest.stem}-{counter}{dest.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1
