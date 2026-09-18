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


def _test_suffix_tool(workdir: Path) -> None:
    from .core.suffix_manager import manage_suffix

    target = workdir / "suffix"
    target.mkdir()
    (target / "a.txt").write_text("x")
    # .1 标记：添加到完整文件名末尾（与旧 dot1 工具行为一致）
    preview = manage_suffix(target, ".1", "add", dry_run=True)
    assert preview.renamed == 1 and (target / "a.txt").exists(), "预览不应改动文件"
    done = manage_suffix(target, ".1", "add")
    assert done.renamed == 1 and (target / "a.txt.1").exists(), "添加 .1 标记失败"
    back = manage_suffix(target, ".1", "remove")
    assert back.renamed == 1 and (target / "a.txt").exists(), "移除 .1 标记失败"

    # 副本标记：加在扩展名前，删除匹配文件（与旧 delete_copy 工具行为一致）
    (target / "b副本.txt").write_text("x")
    (target / "c.txt").write_text("x")
    removed = manage_suffix(target, "副本", "delete", dry_run=False)
    assert removed.deleted == 1 and not (target / "b副本.txt").exists(), "删除副本文件失败"
    assert (target / "c.txt").exists(), "不匹配的文件不应被删除"
    marked = manage_suffix(target, "副本", "add")
    assert marked.renamed == 2 and (target / "c副本.txt").exists(), "添加副本标记失败"


def _test_download_images(workdir: Path) -> None:
    from PIL import Image

    from .core.download_images import download_images

    site = workdir / "imgsite"
    site.mkdir()
    source = site / "pic.png"
    Image.new("RGB", (8, 8), (200, 30, 30)).save(source)

    server = _serve_directory(site)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        list_file = workdir / "urls.csv"
        list_file.write_text(
            f"# 注释行\n{base}/pic.png,{base}/ignored\n\n", encoding="utf-8"
        )
        out = workdir / "imgs"
        summary = download_images(list_file, out, concurrency=2, delay=0)
        assert summary.downloaded == 1 and (out / "pic.png").exists(), "图片下载失败"
        assert Image.open(out / "pic.png").size == (8, 8), "下载的图片内容不一致"
    finally:
        server.shutdown()


def _test_media_tool(workdir: Path) -> None:
    from .core.media_to_mp4 import convert_media, normalize_suffixes

    target = workdir / "media"
    target.mkdir()
    (target / "fake.jpeg").write_bytes(b"not a video")
    summary = convert_media(
        target, normalize_suffixes(["jpeg"]), dry_run=True
    )
    assert summary.converted == 1, "媒体预览计数不符"


def _serve_directory(directory: Path):
    """在本地随机端口起一个静态文件服务器，返回可 shutdown 的 server。"""
    import threading
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args) -> None:
            pass

    handler = partial(QuietHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _pkcs7(data: bytes) -> bytes:
    pad = 16 - len(data) % 16
    return data + bytes([pad]) * pad


def _test_media_grab(workdir: Path) -> None:
    from .core.media_grab import grab_media

    site = workdir / "site"
    site.mkdir()
    plaintext = [f"SEGMENT-{index:02d}-".encode() * 8 for index in range(4)]

    # 明文播放列表：4 个分段
    (site / "video.m3u8").write_text(
        "\n".join(
            [
                "#EXTM3U",
                "#EXT-X-VERSION:3",
                "#EXT-X-TARGETDURATION:2",
                "#EXT-X-MEDIA-SEQUENCE:0",
                *[f"seg{index}.ts" for index in range(4)],
                "#EXT-X-ENDLIST",
            ]
        ),
        encoding="ascii",
    )
    for index, payload in enumerate(plaintext):
        (site / f"seg{index}.ts").write_bytes(payload)

    # AES-128 加密播放列表（固定密钥与 IV，PKCS7 填充）
    try:
        from Crypto.Cipher import AES
    except ImportError:
        AES = None
    if AES is not None:
        key = b"0123456789abcdef"
        iv = bytes.fromhex("31323334353637383930313233343536")
        (site / "key.bin").write_bytes(key)
        (site / "enc.m3u8").write_text(
            "\n".join(
                [
                    "#EXTM3U",
                    "#EXT-X-VERSION:3",
                    '#EXT-X-KEY:METHOD=AES-128,URI="key.bin",IV=0x' + iv.hex(),
                    "#EXT-X-TARGETDURATION:2",
                    "#EXT-X-MEDIA-SEQUENCE:0",
                    "enc0.ts",
                    "#EXT-X-ENDLIST",
                ]
            ),
            encoding="ascii",
        )
        cipher = AES.new(key, AES.MODE_CBC, iv)
        (site / "enc0.ts").write_bytes(cipher.encrypt(_pkcs7(plaintext[0])))

    # 引用页面：video 标签里的相对 m3u8 + 外链 mp4
    (site / "index.html").write_text(
        '<html><body>'
        '<video src="video.m3u8"></video>'
        '<a href="http://cdn.example.com/movie.mp4">mp4</a>'
        "</body></html>",
        encoding="ascii",
    )

    server = _serve_directory(site)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"

        # 页面嗅探：video 标签里的 m3u8 + 链接里的 mp4
        listed = grab_media(f"{base}/index.html", workdir / "out_list", list_only=True)
        assert listed.found == 2, f"嗅探数量不符: {listed.found}"

        # m3u8 合并下载（不封装 MP4，断言合并内容与分段一致）
        out = workdir / "out_merge"
        summary = grab_media(f"{base}/index.html", out, picks=[1], to_mp4=False)
        merged = out / "video.ts"
        assert summary.downloaded == 1 and merged.exists(), "m3u8 合并下载失败"
        assert merged.read_bytes() == b"".join(plaintext), "合并内容与分段不一致"

        # 直接给 m3u8 地址也能下载
        direct = grab_media(f"{base}/video.m3u8", workdir / "out_direct", to_mp4=False)
        assert direct.downloaded == 1, "直连 m3u8 下载失败"

        # AES-128 解密路径（无 pycryptodome 时跳过）
        if AES is not None:
            out_enc = workdir / "out_enc"
            summary = grab_media(f"{base}/enc.m3u8", out_enc, to_mp4=False)
            decrypted = out_enc / "enc.ts"
            assert summary.downloaded == 1 and decrypted.exists(), "AES-128 m3u8 下载失败"
            assert decrypted.read_bytes() == plaintext[0], "AES-128 解密结果不一致"

        # 预览代理：m3u8 重写为本地地址、分段可回源播放
        import requests as http_client

        from .core.media_grab import build_preview_html, sniff_media, start_preview_server

        resources = sniff_media(f"{base}/index.html")
        _server, preview_base = start_preview_server(resources)
        try:
            playlist = http_client.get(f"{preview_base}/i/0", timeout=10)
            assert "mpegurl" in playlist.headers.get("Content-Type", ""), "预览 m3u8 类型不符"
            assert "/u/" in playlist.text, "m3u8 未重写为本地代理地址"
            seg_token = playlist.text.splitlines()[4].rsplit("/u/", 1)[1]
            segment = http_client.get(f"{preview_base}/u/{seg_token}", timeout=10)
            assert segment.content == plaintext[0], "预览代理分段内容不符"
            html = build_preview_html(preview_base, resources, [0, 1])
            assert "hls.js" in html and "<video" in html, "预览页生成不符"
        finally:
            _server.shutdown()
    finally:
        server.shutdown()


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="file_tools_selftest_") as tmp:
        workdir = Path(tmp)
        for name, test in (
            ("image_decrypt", _test_image_tool),
            ("suffix_manager", _test_suffix_tool),
            ("media_to_mp4", _test_media_tool),
            ("media_grab", _test_media_grab),
            ("download_images", _test_download_images),
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
