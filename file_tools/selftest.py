"""打包与安装自检：在当前解释器/冻结环境内运行全部核心工具的冒烟测试。

用法：`python -m file_tools.selftest` 或 `FileTools.exe --selftest`，
全部通过退出码为 0，否则为 1。
"""

import tempfile
from pathlib import Path


def _test_image_tool(workdir: Path) -> None:
    import numpy as np
    from PIL import Image

    from .core.image_decrypt import process_image

    source = workdir / "selftest.png"
    encrypted = workdir / "selftest_enc.png"
    decrypted = workdir / "selftest_dec.png"
    Image.new("RGBA", (64, 64), (18, 52, 86, 255)).save(source)

    process_image("encrypt", "3", source, "selftest-key", encrypted)
    process_image("decrypt", "3", encrypted, "selftest-key", decrypted)
    assert np.array_equal(np.array(Image.open(source)), np.array(Image.open(decrypted))), (
        "图像加解密往返后内容不一致"
    )


def _test_dot1_tool(workdir: Path) -> None:
    from .core.dot1_suffix import rename_dot1_files

    target = workdir / "dot1"
    target.mkdir()
    (target / "a.txt").write_text("x")
    preview = rename_dot1_files(target, "add", dry_run=True)
    assert preview.renamed == 1 and (target / "a.txt").exists(), "dot1 预览不应改动文件"
    done = rename_dot1_files(target, "add")
    assert done.renamed == 1 and (target / "a.txt.1").exists(), "dot1 添加后缀失败"


def _test_copy_tool(workdir: Path) -> None:
    from .core.delete_copy_files import delete_copy_files

    target = workdir / "copy"
    target.mkdir()
    (target / "b副本.txt").write_text("x")
    preview = delete_copy_files(target, execute=False)
    assert preview.matched == 1 and (target / "b副本.txt").exists(), "副本文件预览结果不符"


def _test_media_tool(workdir: Path) -> None:
    from .core.media_to_mp4 import convert_media, normalize_suffixes

    target = workdir / "media"
    target.mkdir()
    (target / "fake.jpeg").write_bytes(b"not a video")
    summary = convert_media(
        target, normalize_suffixes(["jpeg"]), dry_run=True
    )
    assert summary.converted == 1, "媒体预览计数不符"


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="file_tools_selftest_") as tmp:
        workdir = Path(tmp)
        for name, test in (
            ("image_decrypt", _test_image_tool),
            ("dot1_suffix", _test_dot1_tool),
            ("delete_copy_files", _test_copy_tool),
            ("media_to_mp4", _test_media_tool),
        ):
            try:
                test(workdir)
                print(f"PASS {name}")
            except Exception as exc:  # noqa: BLE001 - 自检需要汇总所有失败
                failures.append(f"{name}: {exc}")
                print(f"FAIL {name}: {exc}")
    if failures:
        print(f"\n自检失败 {len(failures)} 项")
        return 1
    print("\n自检全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
