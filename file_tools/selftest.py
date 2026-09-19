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

        # 软件内预览：本地生成样例视频后走 HTTP，用内置 ffmpeg 抽帧
        from .core.media_to_mp4 import find_ffmpeg, run_hidden

        ffmpeg = find_ffmpeg()
        sample = site / "sample.mp4"
        if ffmpeg is not None:
            run_hidden(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
                    "-c:v", "mpeg4", "-q:v", "5", "-y", str(sample),
                ],
                capture_output=True, text=True, timeout=120, check=False,
            )
        if sample.exists():
            from .core.media_grab import MediaResource, capture_preview_frames

            resource = MediaResource(url=f"{base}/sample.mp4", suffix=".mp4", kind="media")
            info, duration, frames = capture_preview_frames(
                resource, count=2, workdir=workdir / "prev", tag="t"
            )
            assert duration and abs(duration - 2.0) < 1.0, f"时长解析不符: {duration}"
            assert len(frames) == 2 and all(
                p.exists() and p.stat().st_size > 0 for p in frames
            ), "预览抽帧失败"
            assert "视频" in info, f"流信息不符: {info}"
    finally:
        server.shutdown()


def _test_fanqie_novel(workdir: Path) -> None:
    """离线测试：文件名清理、章节范围解析、书籍 ID 提取。"""
    from .core.fanqie_novel import parse_chapter_range, re_search_id, sanitize_filename

    assert sanitize_filename('a/b:c*d?"<>|.txt') == "a_b_c_d_.txt", "文件名清理不符"
    assert parse_chapter_range("3-10") == (3, 10), "范围解析不符"
    assert parse_chapter_range("") is None, "空范围应为 None"
    assert parse_chapter_range("7") == (7, 7), "单章范围不符"
    assert re_search_id("https://fanqienovel.com/page/7143038691944959011") == "7143038691944959011"
    assert re_search_id("7143038691944959011") == "7143038691944959011"
    assert re_search_id("十日终焉") is None, "书名不应被当作 ID"


def _test_browser_sniff(workdir: Path) -> None:
    """离线测试浏览器嗅探的纯逻辑：媒体识别、CDP 事件消费、父域与播放列表改写。"""
    from .core.browser_sniff import (
        MediaRecorder,
        find_browser_exe,
        is_media_url,
        url_suffix,
    )
    from .core.media_grab import _parent_host, _rewrite_playlist, parse_m3u8

    # 浏览器探测只查找、不启动
    exe = find_browser_exe()
    assert exe is None or exe.is_file(), "find_browser_exe 应返回可执行文件或 None"

    assert is_media_url("https://cdn.example.com/a/b.m3u8?token=1"), "后缀含查询参数应识别为媒体"
    assert is_media_url("https://cdn.example.com/manifest", mime="application/vnd.apple.mpegurl")
    assert not is_media_url("https://cdn.example.com/page.html"), "html 不应是媒体"
    assert not is_media_url("blob:https://example.com/uuid"), "blob: 地址应跳过"
    assert url_suffix("https://x.com/a/b.MP4?k=1") == ".mp4", "后缀应忽略大小写与查询参数"

    recorder = MediaRecorder()
    recorder.feed_request(
        "https://cdn.example.com/v.m3u8", resource_type="Manifest",
        referer="https://page.example.com/", headers={"Referer": "https://page.example.com/"},
    )
    recorder.feed_request("https://cdn.example.com/app.js", resource_type="Script")
    recorder.feed_response(
        "https://cdn.example.com/v.m3u8", status=200,
        mime="application/vnd.apple.mpegurl", size=1024,
    )
    recorder.feed_request("https://cdn.example.com/seg0.ts", resource_type="Media")
    ordered = recorder.ordered()
    assert [r.url for r in ordered] == [
        "https://cdn.example.com/v.m3u8", "https://cdn.example.com/seg0.ts",
    ], "事件消费后的媒体列表不符"
    assert ordered[0].kind == "m3u8" and ordered[0].status == 200 and ordered[0].size == 1024
    assert ordered[0].referer == "https://page.example.com/"

    # SNI 精简的父域计算
    assert _parent_host("z6v2p9a8.bkcdn.net") == "bkcdn.net", "三级域名父域不符"
    assert _parent_host("a.b.example.com") == "b.example.com", "多级域名父域不符"
    assert _parent_host("example.com") is None, "两级域名无父域"
    assert _parent_host("localhost") is None, "单标签主机无父域"

    # 预览代理的 m3u8 改写：相对/绝对地址与 EXT-X-KEY URI 都改写为本地代理地址
    text = "\n".join([
        "#EXTM3U",
        '#EXT-X-KEY:METHOD=AES-128,URI="key.bin"',
        "#EXT-X-TARGETDURATION:2",
        "seg0.ts",
        "https://other.example.com/x.ts",
    ])
    rewritten = _rewrite_playlist(text, "https://cdn.example.com/v/index.m3u8", "https://page/")
    kind, payload = parse_m3u8(rewritten, "http://127.0.0.1:1/player")
    assert kind == "media", "改写后仍是媒体播放列表"
    assert str(payload.key.uri).startswith("http://127.0.0.1:1/media?u="), "KEY URI 未改写为代理地址"
    assert all(s.startswith("http://127.0.0.1:1/media?u=") for s in payload.segments), "分段地址未改写为代理地址"
    assert 'URI="key.bin"' not in rewritten, "KEY 相对地址应被改写"
    assert "\nseg0.ts" not in rewritten, "分段相对地址应被改写"


def _test_preview_proxy(workdir: Path) -> None:
    """离线测试浏览器模式预览代理：本地文件经代理可播放页/媒体端点取回。"""
    import requests as _requests

    from .core import media_grab as mg

    site = workdir / "prev_site"
    site.mkdir()
    payload = b"0123456789abcdef" * 64
    (site / "video.mp4").write_bytes(payload)
    (site / "index.m3u8").write_text(
        "\n".join(["#EXTM3U", "#EXT-X-VERSION:3", "seg0.ts", "#EXT-X-ENDLIST"]),
        encoding="ascii",
    )
    (site / "seg0.ts").write_bytes(b"SEG-DATA")
    server = _serve_directory(site)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        proxy = mg._PreviewProxy()
        transport_ref = proxy.transport
        resource = mg.MediaResource(
            url=f"{base}/video.mp4", suffix=".mp4", kind="media",
            headers={"Referer": f"{base}/"},
        )
        player_url = proxy.player_url(resource.url, resource.headers["Referer"], "file")
        page = _requests.get(player_url, timeout=10)
        assert page.status_code == 200 and "video" in page.text, "播放页应包含 video 元素"

        media_url = proxy.player_url(resource.url, resource.headers["Referer"], "file").replace(
            "/player?", "/media?"
        ).replace("&k=file", "")
        # 直接取 /media 端点（与播放页等价路径）
        from urllib.parse import parse_qs, quote, urlparse

        query = parse_qs(urlparse(media_url).query)
        proxied = (
            f"{proxy.base_url}/media?u={quote(query['u'][0], safe='')}"
            f"&r={quote(query['r'][0], safe='')}"
        )
        media = _requests.get(proxied, timeout=10)
        assert media.status_code == 200 and media.content == payload, "代理透传内容不一致"

        # Range 请求透传
        ranged = _requests.get(proxied, headers={"Range": "bytes=0-3"}, timeout=10)
        assert ranged.status_code in (200, 206) and ranged.content[:4] == payload[:4], "Range 请求应可用"

        # m3u8 改写
        playlist = _requests.get(
            f"{proxy.base_url}/media?u={quote(f'{base}/index.m3u8', safe='')}"
            f"&r={quote(f'{base}/', safe='')}",
            timeout=10,
        )
        assert playlist.status_code == 200, "m3u8 代理失败"
        assert "/media?u=" in playlist.text and "\nseg0.ts" not in playlist.text, "m3u8 未改写为代理地址"
        # hls.js 内置可取
        hls = _requests.get(f"{proxy.base_url}/hls.js", timeout=10)
        assert hls.status_code == 200 and len(hls.content) > 100000, "内置 hls.js 应可提供"
        transport_ref.close()
        proxy._server.shutdown()
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
            ("fanqie_novel", _test_fanqie_novel),
            ("browser_sniff", _test_browser_sniff),
            ("preview_proxy", _test_preview_proxy),
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
