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


def _test_image_rename(workdir: Path) -> None:
    from .core.image_rename import rename_images

    root = workdir / "rename"
    a1 = root / "a1"
    a2 = root / "a2"
    a1.mkdir(parents=True)
    a2.mkdir()
    (a1 / "b2.jpg").write_bytes(b"1")
    (a1 / "b10.jpg").write_bytes(b"2")
    (a1 / "c.png").write_bytes(b"3")
    (a1 / "readme.txt").write_text("x")
    (a2 / "x.JPG").write_bytes(b"4")

    out = workdir / "rename_out"
    # 预览：不创建输出目录、不移动文件
    preview = rename_images([a1, a2], out, "漫画", dry_run=True)
    assert preview.found == 4 and preview.moved == 4, "预览计数不符"
    assert not out.exists(), "预览不应创建输出目录"

    # 多文件夹合并：自然排序 + 跨后缀统一编号 + 后缀大小写保留 + 非图片不动
    done = rename_images([a1, a2], out, "漫画")
    target = out / "漫画"
    assert done.moved == 4, "合并移动数量不符"
    assert sorted(path.name for path in target.iterdir()) == [
        "漫画-1.jpg", "漫画-2.jpg", "漫画-3.png", "漫画-4.JPG",
    ], "合并编号结果不符"
    assert not (a1 / "b2.jpg").exists(), "图片应被剪切到目标文件夹"
    assert (a1 / "readme.txt").exists(), "非图片文件不应被移动"

    # 追加：目标已有 漫画-1~4，新图片从 漫画-5 续接
    (a2 / "new.png").write_bytes(b"5")
    again = rename_images([a2], out, "漫画")
    assert again.moved == 1 and (target / "漫画-5.png").exists(), "追加编号未续接"
    assert (target / "漫画-1.jpg").exists(), "追加不应影响已有文件"

    # 目标文件夹内的文件再选进来会被跳过，不产生重复编号
    skip = rename_images([target], out, "漫画")
    assert skip.found == 0 and skip.moved == 0, "目标文件夹内的文件应被跳过"

    # 递归收集子目录
    (a1 / "sub").mkdir()
    (a1 / "sub" / "deep.jpg").write_bytes(b"6")
    recursive_out = workdir / "rename_rec"
    rec = rename_images([a1], recursive_out, "递归", recursive=True)
    assert rec.moved == 1 and (recursive_out / "递归" / "递归-1.jpg").exists(), "递归收集失败"


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


def _test_image_convert(workdir: Path) -> None:
    from PIL import Image, ImageDraw

    from .core.image_convert import convert_images

    source_dir = workdir / "convert_src"
    (source_dir / "sub").mkdir(parents=True)
    # 四角全透明、中间不透明红块（验证垫白底与透明度保留）
    canvas = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).rectangle((4, 4, 11, 11), fill=(255, 0, 0, 255))
    canvas.save(source_dir / "alpha.png")
    Image.new("RGB", (16, 16), (0, 255, 0)).save(source_dir / "plain.jpg")
    Image.new("RGB", (8, 8), (0, 0, 255)).save(source_dir / "sub" / "deep.png")
    (source_dir / "note.txt").write_text("x")
    (source_dir / "bad.webp").write_bytes(b"not an image")

    # 预览：只列计划不写文件（plain.jpg 同后缀跳过不计，坏图按后缀照常计入）
    preview = convert_images(source_dir, "jpg", dry_run=True)
    assert preview.converted == 2, "预览计数不符"
    assert not (source_dir / "alpha.jpg").exists(), "预览不应写文件"

    # png -> jpg：透明通道垫白底，输出 RGB；坏图计失败不中断
    done = convert_images(source_dir, "jpg")
    assert done.converted == 1 and done.failed == 1, "png 转 jpg 计数不符"
    jpg = Image.open(source_dir / "alpha.jpg")
    assert jpg.mode == "RGB", "png 转 jpg 应输出 RGB"
    # JPEG 有损压缩，用容差断言
    corner = jpg.getpixel((0, 0))
    assert all(channel >= 250 for channel in corner), f"透明角落应接近白底: {corner}"
    center = jpg.getpixel((8, 8))
    assert center[0] >= 250 and center[1] <= 8 and center[2] <= 8, f"不透明区域应接近原色: {center}"
    assert (source_dir / "alpha.png").exists(), "默认应保留原图"

    # webp 透明转 png：模式与透明度保留
    Image.new("RGBA", (16, 16), (255, 0, 0, 128)).save(source_dir / "rt.webp")
    to_png = convert_images(source_dir / "rt.webp", "png")
    png_image = Image.open(source_dir / "rt.png")
    assert to_png.converted == 1 and png_image.mode == "RGBA", "webp 转 png 应保留 RGBA"
    assert png_image.getpixel((0, 0))[3] == 128, "透明度应保留"

    # 同后缀跳过
    skip = convert_images(source_dir / "plain.jpg", "jpg")
    assert skip.converted == 0, "同后缀应跳过"

    # 递归收集 + 输出目录平铺（alpha.png 与已生成的 alpha.webp 目标重名会跳过）
    out = workdir / "convert_out"
    conv = convert_images(source_dir, "webp", output_dir=out, recursive=True)
    assert conv.converted == 4 and (out / "deep.webp").exists(), "递归 + 输出目录失败"

    # quality 参数与删除原图
    single = workdir / "convert_del"
    single.mkdir()
    Image.new("RGB", (8, 8), (10, 20, 30)).save(single / "one.bmp")
    with_quality = convert_images(single / "one.bmp", "webp", quality=90)
    assert with_quality.converted == 1 and (single / "one.webp").exists(), "转 webp 失败"
    deleted = convert_images(single / "one.webp", "png", delete_original=True)
    assert (
        deleted.converted == 1
        and (single / "one.png").exists()
        and not (single / "one.webp").exists()
    ), "删除原图失败"


def _test_media_tool(workdir: Path) -> None:
    from .core.common import normalize_suffixes
    from .core.media_to_mp4 import convert_media

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

        # 本测试覆盖的是 legacy 自研内核（yt-dlp 兜底路径），须显式指定引擎
        # m3u8 合并下载（不封装 MP4，断言合并内容与分段一致）
        out = workdir / "out_merge"
        summary = grab_media(f"{base}/index.html", out, picks=[1], to_mp4=False,
                             engine="legacy")
        merged = out / "video.ts"
        assert summary.downloaded == 1 and merged.exists(), "m3u8 合并下载失败"
        assert merged.read_bytes() == b"".join(plaintext), "合并内容与分段不一致"

        # 直接给 m3u8 地址也能下载
        direct = grab_media(f"{base}/video.m3u8", workdir / "out_direct", to_mp4=False,
                            engine="legacy")
        assert direct.downloaded == 1, "直连 m3u8 下载失败"

        # AES-128 解密路径（无 pycryptodome 时跳过）
        if AES is not None:
            out_enc = workdir / "out_enc"
            summary = grab_media(f"{base}/enc.m3u8", out_enc, to_mp4=False,
                                 engine="legacy")
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


def _test_download_engine(workdir: Path) -> None:
    from .core import download_engine as de
    from .core.media_grab import MediaResource

    # 引擎解析：legacy 直通；auto 按安装情况回退；强制 ytdlp 未装时报错
    assert de.resolve_engine("legacy") == "legacy"
    assert de.resolve_engine("auto", available=True) == "ytdlp"
    assert de.resolve_engine("auto", available=False) == "legacy"
    try:
        de.resolve_engine("ytdlp", available=False)
        raise AssertionError("强制 ytdlp 未安装应报错")
    except RuntimeError:
        pass
    try:
        de.resolve_engine("nope")
        raise AssertionError("未知引擎应报错")
    except ValueError:
        pass

    # opts 构造：headers 透传（空值过滤）、outtmpl、overwrite 语义、合流格式与 ffmpeg 定位
    opts = de.build_ytdlp_opts(
        outtmpl=str(workdir / "o" / "v.%(ext)s"),
        headers={"Referer": "https://p/", "Cookie": "k=1", "X-Empty": ""},
        format_spec="bv*+ba/b",
        overwrite=False,
        to_mp4=True,
        concurrency=4,
        timeout=12,
    )
    assert opts["outtmpl"].endswith("v.%(ext)s"), "outtmpl 未透传"
    assert opts["http_headers"] == {"Referer": "https://p/", "Cookie": "k=1"}, "headers 透传不符"
    assert opts["overwrites"] is False, "overwrite=False 应映射 overwrites: False"
    assert opts["format"] == "bv*+ba/b" and opts["merge_output_format"] == "mp4"
    assert opts["noplaylist"] is True and opts["concurrent_fragment_downloads"] == 4
    assert opts["socket_timeout"] == 12 and opts.get("ffmpeg_location"), "ffmpeg 定位缺失"
    no_mp4 = de.build_ytdlp_opts(outtmpl="x.%(ext)s", to_mp4=False)
    assert "merge_output_format" not in no_mp4, "to_mp4=False 不应强制 mp4"

    # dash 对判定：同页面 video+audio → 单次页面任务；缺边/异页 → 逐条直下
    page = "https://www.bilibili.com/video/BV1"
    pair = [
        MediaResource(
            url="https://cdn.example.com/v.m4s", suffix=".m4s", kind="dash-video",
            title="测试视频", label="1080P avc 时长2分钟", page_url=page,
            headers={"Referer": "https://www.bilibili.com/"},
        ),
        MediaResource(
            url="https://cdn.example.com/a.m4s", suffix=".m4s", kind="dash-audio",
            title="测试视频", label="音频 192kbps", page_url=page,
            headers={"Referer": "https://www.bilibili.com/"},
        ),
    ]
    out = workdir / "pair_out"
    tasks = de.plan_ytdlp_tasks(pair, out)
    assert len(tasks) == 1 and tasks[0].is_dash_pair, "成对勾选应合并为一个页面任务"
    assert tasks[0].url == page and tasks[0].format_spec == de.DASH_PAIR_FORMAT
    assert "测试视频" in tasks[0].outtmpl and "%(ext)s" in tasks[0].outtmpl
    assert tasks[0].headers.get("Referer") == "https://www.bilibili.com/"
    assert len(tasks[0].stream_fallback) == 2, "页面任务应携带逐流回退任务"

    video_only = [pair[0]]
    tasks = de.plan_ytdlp_tasks(video_only, out)
    assert len(tasks) == 1 and not tasks[0].is_dash_pair, "仅视频流应逐条直下"
    assert tasks[0].url.endswith("v.m4s"), "单流任务应指向流地址"
    assert "测试视频" in tasks[0].outtmpl and "1080P" in tasks[0].outtmpl, "单流命名应沿用 legacy 规则"

    diff_page = [
        MediaResource(url="https://cdn.example.com/v.m4s", suffix=".m4s",
                      kind="dash-video", page_url="https://p1"),
        MediaResource(url="https://cdn.example.com/a.m4s", suffix=".m4s",
                      kind="dash-audio", page_url="https://p2"),
    ]
    assert len(de.plan_ytdlp_tasks(diff_page, out)) == 2, "异页 dash 不应配对"

    # 多页面各有音视频对：每页各生成一个页面任务（各自带逐流回退）
    two_pages = [
        MediaResource(url="https://cdn.example.com/v1.m4s", suffix=".m4s",
                      kind="dash-video", title="甲", label="1080P", page_url="https://p/1"),
        MediaResource(url="https://cdn.example.com/a1.m4s", suffix=".m4s",
                      kind="dash-audio", title="甲", label="音频", page_url="https://p/1"),
        MediaResource(url="https://cdn.example.com/v2.m4s", suffix=".m4s",
                      kind="dash-video", title="乙", label="720P", page_url="https://p/2"),
        MediaResource(url="https://cdn.example.com/a2.m4s", suffix=".m4s",
                      kind="dash-audio", title="乙", label="音频", page_url="https://p/2"),
    ]
    tasks = de.plan_ytdlp_tasks(two_pages, out)
    assert len(tasks) == 2 and all(t.is_dash_pair for t in tasks), \
        f"两页 dash 对应产生两个页面任务: {len(tasks)}"
    assert all(len(t.stream_fallback) == 2 for t in tasks), "每个页面任务应有逐流回退"

    # 输出目录路径里的字面 % 同样要转义（outtmpl 整体是模板串）
    percent_dir = workdir / "dir%s"
    task = de.plan_ytdlp_tasks([pair[0]], percent_dir)[0]
    assert "dir%%s" in task.outtmpl, "目录段 % 未转义"
    assert de._existing_output(percent_dir, task.outtmpl) is None  # 未创建目录时安全返回 None

    # 词干中的字面 % 须转义，否则破坏 outtmpl 模板
    tricky = de.plan_ytdlp_tasks(
        [MediaResource(url="https://cdn.example.com/x.mp4", suffix=".mp4",
                       kind="media", title="100% 好")], out
    )
    assert "100%%" in tricky[0].outtmpl, "词干 % 未转义"

    # 重名跳过判定：同词干任意后缀算已有产物；.part 残留不算
    out.mkdir(parents=True)
    (out / "测试视频.mp4").write_bytes(b"x")
    pair_tmpl = de.plan_ytdlp_tasks(pair, out)[0].outtmpl
    assert de._existing_output(out, pair_tmpl) == out / "测试视频.mp4", "重名判定漏判"
    part_dir = workdir / "part_out"
    part_dir.mkdir()
    (part_dir / "测试视频.mp4.part").write_bytes(b"x")
    assert de._existing_output(part_dir, de.plan_ytdlp_tasks(pair, part_dir)[0].outtmpl) is None, \
        ".part 残留不应算已有产物"

    # 端到端：本地服务器 + yt-dlp generic 下载直链（无外网）
    site = workdir / "yt_site"
    site.mkdir()
    payload = b"0123456789abcdef" * 64
    (site / "clip.mp4").write_bytes(payload)
    (site / "backup.mp4").write_bytes(payload)
    server = _serve_directory(site)
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        resources = [
            MediaResource(url=f"{base}/clip.mp4", suffix=".mp4", kind="media",
                          headers={"Referer": f"{base}/"})
        ]
        out_dir = workdir / "yt_out"
        summary = de.download_with_engine(resources, out_dir, engine="ytdlp")
        assert summary.downloaded == 1 and summary.merged == 0, \
            f"yt-dlp 直链下载计数不符: {summary.downloaded}"
        saved = Path(summary.outputs[0])
        assert saved.exists() and saved.read_bytes() == payload, "yt-dlp 下载内容与源不一致"

        # 重名跳过：同词干再下一次应计入 skipped
        again = de.download_with_engine(resources, out_dir, engine="ytdlp")
        assert again.downloaded == 0 and again.skipped == 1, "重名应跳过而非重下"

        # yt-dlp 的 m3u8 路径：本地播放列表端到端。分段须是真实 TS 且编码带
        # 分辨率信息（H.264 自带 SPS/PPS，mpeg4 裸流重封装 MP4 会因
        # dimensions not set 失败），清单须带 EXTINF；无 ffmpeg 时跳过
        from .core.media_to_mp4 import find_ffmpeg, run_hidden

        ffmpeg = find_ffmpeg()
        hls_m3u8 = site / "hls.m3u8"
        if ffmpeg is not None:
            run_hidden(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=duration=2:size=160x120:rate=10",
                    "-c:v", "libx264", "-preset", "ultrafast",
                    "-f", "segment", "-segment_time", "1", "-reset_timestamps", "1",
                    str(site / "seg%d.ts"), "-y",
                ],
                capture_output=True, text=True, timeout=120, check=False,
            )
            segments = sorted(site.glob("seg*.ts"))
            if segments:
                lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:2"]
                for segment in segments:
                    lines += ["#EXTINF:1.0,", segment.name]
                lines.append("#EXT-X-ENDLIST")
                hls_m3u8.write_text("\n".join(lines), encoding="ascii")
        if hls_m3u8.is_file():
            out_hls = workdir / "yt_hls"
            summary = de.download_with_engine(
                [MediaResource(url=f"{base}/hls.m3u8", suffix=".m3u8", kind="m3u8",
                               title="hls视频")],
                out_hls, engine="ytdlp",
            )
            produced = list(out_hls.glob("hls视频.*")) if out_hls.is_dir() else []
            assert summary.downloaded == 1 and produced \
                and produced[0].stat().st_size > 0, "yt-dlp m3u8 下载失败"

        # 主地址失败 → fallback_urls 逐个兜底（对齐 legacy 候选循环语义）
        fallback = [
            MediaResource(url=f"{base}/missing.mp4", suffix=".mp4", kind="media",
                          fallback_urls=[f"{base}/backup.mp4"])
        ]
        out_fb = workdir / "yt_fb"
        summary = de.download_with_engine(fallback, out_fb, engine="ytdlp")
        assert summary.downloaded == 1 and (out_fb / "missing.mp4").exists() \
            and (out_fb / "missing.mp4").read_bytes() == payload, "备用地址兜底失败"

        # 未装 yt-dlp 时 auto → legacy 自动回退（替换可用性探测）
        original = de._yt_dlp_available
        de._yt_dlp_available = lambda: False
        try:
            out_legacy = workdir / "legacy_out"
            summary = de.download_with_engine(
                [MediaResource(url=f"{base}/clip.mp4", suffix=".mp4", kind="media")],
                out_legacy, engine="auto",
            )
            assert summary.downloaded == 1, "auto 回退 legacy 下载失败"
            assert (out_legacy / "clip.mp4").read_bytes() == payload, "legacy 回退内容不一致"
        finally:
            de._yt_dlp_available = original
    finally:
        server.shutdown()


def _test_flow_watch(workdir: Path) -> None:
    import os
    import time as _time

    from PIL import Image

    from .core import flow_watch as fw

    data_dir = workdir / "flow_userdata"
    os.environ["FILE_TOOLS_DATA_DIR"] = str(data_dir)
    try:
        # ① 纯函数：临时名/隐藏名跳过、类别归类、后缀规范化、重名递增
        assert fw.is_temp_name(Path("a/x.part")) and fw.is_temp_name(Path("x.tmp"))
        assert fw.is_temp_name(Path("~$doc.xlsx")) and fw.is_temp_name(Path(".hidden"))
        assert not fw.is_temp_name(Path("video.mp4"))
        assert fw.category_of(Path("a.JPG")) == "图片"
        assert fw.category_of(Path("b.mkv")) == "视频"
        assert fw.category_of(Path("c.7z")) == "压缩包"
        assert fw.category_of(Path("d.xyz")) == "其他"
        rule = fw.rule_from_dict({
            "name": "r", "watch_dir": "w", "action": "convert",
            "suffixes": ["WEBP", ".png"], "action_params": {"target_format": "jpg"},
        })
        assert rule.suffixes == {".webp", ".png"}, "后缀应规范为补点小写"
        assert fw.rule_matches(rule, Path("w/a.WEBP")) and not fw.rule_matches(rule, Path("w/a.gif"))
        assert not fw.rule_matches(rule, Path("w/a.webp.part")), "临时名应跳过"
        dest = fw.unique_path(workdir / "u" / "same.txt")
        assert str(dest).endswith("same.txt"), "无冲突时原名"
        (workdir / "u").mkdir()
        (workdir / "u" / "same.txt").write_text("x")
        assert fw.unique_path(workdir / "u" / "same.txt").name == "same-1.txt"

        # ② sort 动作端到端 + processed 台账 + undo 逆序回滚
        watch_dir = workdir / "watch"
        watch_dir.mkdir()
        (watch_dir / "clip.mp4").write_bytes(b"not really a video, just sort target")
        (watch_dir / "note.pdf").write_bytes(b"%PDF-sort-me")
        rules = [fw.Rule(name="归类", watch_dir=str(watch_dir), action=fw.ACTION_SORT)]
        watch = fw.FlowWatch(rules, log_cb=print, settle_seconds=0.0)
        first = watch.scan_once(require_stable=True)
        assert first["processed"] == 0 and first["waiting"] == 2, \
            f"第一轮只应登记快照: {first}"
        second = watch.scan_once(require_stable=True)
        assert second["processed"] == 2, f"第二轮应处理落定文件: {second}"
        assert (watch_dir / "视频" / "clip.mp4").is_file(), "视频应归入 视频子目录"
        assert (watch_dir / "文档" / "note.pdf").is_file(), "pdf 应归入 文档子目录"

        # processed 台账：第三轮不重复处理
        third = watch.scan_once(require_stable=True)
        assert third["processed"] == 0, "processed 台账应阻止重复处理"
        entries = fw._read_jsonl(fw._ledger_path(fw.PROCESSED_NAME))
        assert len(entries) == 4 and {e["rule"] for e in entries} == {"归类"}, \
            "源路径与移动目的地各应有台账（防递归规则重复识别）"

        undone, failures = fw.undo_last_batch()
        assert undone == 2 and not failures, f"撤销应还原 2 个移动: {undone}, {failures}"
        assert (watch_dir / "clip.mp4").is_file() and (watch_dir / "note.pdf").is_file(), \
            "撤销后文件应回到原位"
        assert not (watch_dir / "视频").exists() or not any((watch_dir / "视频").iterdir()), \
            "撤销后不应残留归档副本"
        again_undone, _ = fw.undo_last_batch()
        assert again_undone == 0, "同一批次不应重复回滚"

        # 递归分类规则：文件移入类别子目录后台账命中，不得被再次识别而无限改名
        rec_dir = workdir / "rec_watch"
        (rec_dir / "nested").mkdir(parents=True)
        (rec_dir / "nested" / "song.mp3").write_bytes(b"audio")
        rec_rules = [fw.Rule(name="递归归类", watch_dir=str(rec_dir),
                             action=fw.ACTION_SORT, recursive=True)]
        rec_watch = fw.FlowWatch(rec_rules, log_cb=print, settle_seconds=0.0)
        assert rec_watch.scan_once(require_stable=True)["processed"] == 0
        assert rec_watch.scan_once(require_stable=True)["processed"] == 1
        moved_song = rec_dir / "音频" / "song.mp3"
        assert moved_song.is_file(), "递归规则应把子目录文件归入顶层类别目录"
        undo_count = len(fw._read_jsonl(fw._ledger_path(fw.UNDO_NAME)))
        for _ in range(3):
            assert rec_watch.scan_once(require_stable=True)["processed"] == 0, \
                "移动后的文件不应被再次处理"
        assert moved_song.is_file(), "不应产生改名副本"
        assert len(fw._read_jsonl(fw._ledger_path(fw.UNDO_NAME))) == undo_count, \
            "台账命中后不应产生新的移动记录"

        # ③ convert 规则端到端：造 webp → 转出 jpg + 台账记录
        Image.new("RGB", (12, 12), (250, 120, 10)).save(watch_dir / "pic.webp")
        convert_rules = [fw.Rule(
            name="转格式", watch_dir=str(watch_dir), action=fw.ACTION_CONVERT,
            suffixes={".webp"},
            action_params={"target_format": "jpg", "quality": 90},
        )]
        watch2 = fw.FlowWatch(convert_rules, log_cb=print, settle_seconds=0.0)
        # 手动扫描（require_stable=False）：只按落定阈值判定，一轮即处理
        summary = watch2.scan_once(require_stable=False)
        assert summary["processed"] == 1, f"convert 规则应处理 1 个文件: {summary}"
        assert (watch_dir / "pic.jpg").is_file(), "应产出 jpg"
        assert (watch_dir / "pic.webp").exists(), "默认应保留原图"

        # 监控动作纪律：即使规则带了 delete_original，转换也必须保留原图
        Image.new("RGB", (8, 8), (7, 8, 9)).save(watch_dir / "keep.webp")
        keep_rules = [fw.Rule(
            name="保留原图", watch_dir=str(watch_dir), action=fw.ACTION_CONVERT,
            suffixes={".webp"},
            action_params={"target_format": "jpg", "delete_original": True},
        )]
        keep_watch = fw.FlowWatch(keep_rules, log_cb=print, settle_seconds=0.0)
        assert keep_watch.scan_once(require_stable=False)["processed"] == 1
        assert (watch_dir / "keep.webp").exists(), "监控 convert 不得删除原图"

        # mtime 在未来（时钟偏移/网络拷贝）应视为已落定，不得永远 waiting
        Image.new("RGB", (8, 8), (5, 6, 7)).save(watch_dir / "future.webp")
        future_stamp = _time.time() + 3600
        os.utime(watch_dir / "future.webp", (future_stamp, future_stamp))
        future_watch = fw.FlowWatch(keep_rules, log_cb=print, settle_seconds=30.0)
        got = future_watch.scan_once(require_stable=False)
        assert got["processed"] == 1, f"未来 mtime 文件应被处理: {got}"
        assert (watch_dir / "future.jpg").is_file()

        # 手动扫描的落定阈值仍然生效（默认 30s）：刚创建的文件不被处理
        strict_dir = workdir / "strict"
        strict_dir.mkdir()
        Image.new("RGB", (8, 8), (1, 2, 3)).save(strict_dir / "fresh.webp")
        strict_rules = [fw.Rule(
            name="转格式", watch_dir=str(strict_dir), action=fw.ACTION_CONVERT,
            suffixes={".webp"}, action_params={"target_format": "jpg"},
        )]
        skipped = fw.FlowWatch(strict_rules, log_cb=print).scan_once(require_stable=False)
        assert skipped["waiting"] == 1 and skipped["processed"] == 0, \
            "未到落定阈值的文件应等待"

        # 停止语义：stop 后 running 为 False，线程退出
        watch3 = fw.FlowWatch(convert_rules, log_cb=print, interval=1)
        watch3.start()
        assert watch3.running
        watch3.stop(timeout=5)
        assert not watch3.running, "stop 后监控线程应退出"
    finally:
        os.environ.pop("FILE_TOOLS_DATA_DIR", None)
        _ = _time  # time 模块保留给后续用例扩展


def _test_dedupe_images(workdir: Path) -> None:
    from PIL import Image, ImageDraw

    from .core.dedupe_images import RECYCLE_DIR_NAME, hamming, move_duplicates, scan

    # 同像素不同字节的两张图（压缩级别不同）+ 一张小尺寸同内容图
    # 图案须有明暗结构：纯渐变/纯色的 dHash 恒为 0，会与任何纯色图"重复"
    root = workdir / "dedupe"
    root.mkdir()
    base = Image.new("RGB", (64, 64), (240, 240, 240))
    ImageDraw.Draw(base).ellipse((4, 8, 44, 56), fill=(230, 60, 40))
    ImageDraw.Draw(base).rectangle((30, 4, 60, 34), fill=(30, 90, 220))
    base.save(root / "a.png", compress_level=1)
    base.save(root / "b.png", compress_level=9)
    base.resize((16, 16)).save(root / "c.png")  # 同内容小图：候选且尺寸更小
    Image.new("RGB", (64, 64), (10, 200, 90)).save(root / "different.png")
    (root / "notimage.txt").write_text("x")

    groups = scan(root)
    assert len(groups) == 1, f"同内容三张应归为一组: {len(groups)} 组"
    group = groups[0]
    assert len(group.candidates) == 2, "正本 1 张 + 候选 2 张"
    keeper_name = group.keeper.name
    assert keeper_name in ("a.png", "b.png"), f"正本应是全尺寸图: {keeper_name}"
    assert "c.png" in [p.name for p in group.candidates], "小尺寸同内容图应是候选"

    # 汉明距离纯函数
    assert hamming(0b1010, 0b0101) == 4 and hamming(123, 123) == 0

    summary = move_duplicates(groups)
    assert summary["moved"] == 2 and not summary["failed"], f"移动摘要不符: {summary}"
    recycle = root / RECYCLE_DIR_NAME
    assert (recycle / "c.png").is_file(), "候选应移入回收文件夹"
    assert (root / keeper_name).is_file(), "正本应留在原地"
    assert not (root / "c.png").exists(), "候选不应留在原目录"

    # 回收文件夹不重复进扫描
    assert scan(root) == [], "回收文件夹内容不应再次成组"

    # only 子集：只移动指定候选
    base.save(root / "d.png", compress_level=1)
    base.save(root / "e.png", compress_level=9)
    groups = scan(root)
    summary = move_duplicates(groups, only={root / "e.png"})
    assert summary["moved"] == 1 and (root / "d.png").is_file(), "only 子集应生效"


def _test_task_history(workdir: Path) -> None:
    import os

    from .core import task_history as th
    from .core.userdata import base_dir

    # FILE_TOOLS_DATA_DIR 优先（指向临时目录，不污染真实用户数据）
    data_dir = workdir / "userdata"
    os.environ["FILE_TOOLS_DATA_DIR"] = str(data_dir)
    try:
        assert base_dir() == data_dir, "FILE_TOOLS_DATA_DIR 应优先生效"
        assert data_dir.is_dir(), "base_dir 应创建目录"

        th.record("任务甲", True, 1.2345, "完成: 下载 3")
        th.record("任务乙", False, 0.5, "错误: " + "长" * 900)
        entries = th.read_recent()
        assert len(entries) == 2 and entries[0]["title"] == "任务乙", "read_recent 应新的在前"
        assert entries[0]["status"] == "fail" and entries[1]["status"] == "ok", "状态不符"
        assert len(entries[0]["message"]) == 500, "超长 message 应截断至 500 字符"
        assert abs(entries[1]["seconds"] - 1.234) < 0.001, "耗时应保留三位小数"
        assert "T" in entries[0]["ts"] and ":" in entries[0]["ts"], "ts 应为 ISO8601"
        assert set(entries[0]) == {"ts", "title", "status", "seconds", "message"}, "条目字段不符"

        # 坏行跳过：手工混入损坏行后仍能读出有效条目
        path = th.history_path()
        with path.open("a", encoding="utf-8") as handle:
            handle.write("这不是JSON\n")
        assert len(th.read_recent()) == 2, "坏行应跳过"

        # 轮转：文件超 2MB 时重写为最近 500 条，且最新记录仍可读
        for index in range(4600):
            th.record("批量", True, 0.1, f"第{index}批 " + "x" * 400)
        entries = th.read_recent(limit=10)
        assert "4599" in entries[0]["message"], "轮转后应能读到最新记录"
        lines = path.read_text(encoding="utf-8").splitlines()
        assert 500 <= len(lines) < 4600, f"轮转应控制文件行数: {len(lines)}"

        th.clear()
        assert th.read_recent() == [], "clear 后应为空"
    finally:
        os.environ.pop("FILE_TOOLS_DATA_DIR", None)


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
    from .core.media_grab import (
        _parent_host,
        _rewrite_playlist,
        parse_ffmpeg_resolution,
        parse_m3u8,
    )

    # ffmpeg -i 输出解析分辨率（HLS 清晰度识别用）
    sample = "\n".join([
        "Input #0, mpegts, from 'pipe:0':",
        "  Duration: 00:00:06.00, start: 1.400000, bitrate: 2500 kb/s",
        "  Stream #0:0[0x100]: Video: h264 (High) ([27][0][0][0] / 0x001B),"
        " yuv420p, 1920x1080 [SAR 1:1 DAR 16:9], 25 fps",
        "  Stream #0:1[0x101](und): Audio: aac (LC), 48000 Hz, stereo, fltp, 128 kb/s",
    ])
    assert parse_ffmpeg_resolution(sample) == "1920x1080", "ffmpeg 输出分辨率解析不符"
    assert parse_ffmpeg_resolution("no video line here") is None, "无视频流应返回 None"

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

        # hls 播放页必须引入 /hls.js（否则页面里 Hls 未定义，永远放不出视频）
        hls_page = _requests.get(
            proxy.player_url(f"{base}/index.m3u8", f"{base}/", "hls"), timeout=10
        )
        assert hls_page.status_code == 200, "hls 播放页应可访问"
        assert '<script src="/hls.js"></script>' in hls_page.text, "hls 播放页应引入 hls.js"
        assert "Hls.isSupported" in hls_page.text, "hls 播放页应包含 hls.js 播放逻辑"

        media_url = proxy.player_url(resource.url, resource.headers["Referer"], "file").replace(
            "/player?", "/media?"
        ).replace("&k=file", "")
        # 直接取 /media 端点（与播放页等价路径）；须带一次性令牌 t=，否则 403
        from urllib.parse import parse_qs, quote, urlparse

        query = parse_qs(urlparse(media_url).query)
        proxied = (
            f"{proxy.base_url}/media?u={quote(query['u'][0], safe='')}"
            f"&r={quote(query['r'][0], safe='')}&t={proxy.token}"
        )
        media = _requests.get(proxied, timeout=10)
        assert media.status_code == 200 and media.content == payload, "代理透传内容不一致"

        # 缺令牌/错令牌的 /media 与 /player 请求应被拒绝（403）
        for url_without_token in (
            proxied.rsplit("&t=", 1)[0],
            proxied + "-bad",
            proxy.player_url(resource.url, resource.headers["Referer"], "file").rsplit(
                "&t=", 1
            )[0],
        ):
            rejected = _requests.get(url_without_token, timeout=10)
            assert rejected.status_code == 403, "缺令牌的代理请求应返回 403"

        # Range 请求透传
        ranged = _requests.get(proxied, headers={"Range": "bytes=0-3"}, timeout=10)
        assert ranged.status_code in (200, 206) and ranged.content[:4] == payload[:4], "Range 请求应可用"

        # m3u8 改写
        playlist = _requests.get(
            f"{proxy.base_url}/media?u={quote(f'{base}/index.m3u8', safe='')}"
            f"&r={quote(f'{base}/', safe='')}&t={proxy.token}",
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


def _test_lan_share(workdir: Path) -> None:
    import io
    import os
    from urllib.parse import quote

    import requests as _requests

    from .core.lan_share import LanShare, Share, _parse_multipart

    data_dir = workdir / "lan_userdata"
    os.environ["FILE_TOOLS_DATA_DIR"] = str(data_dir)
    logs = io.StringIO()
    try:
        read_dir = workdir / "lan_read"
        write_dir = workdir / "lan_write"
        read_dir.mkdir()
        write_dir.mkdir()
        payload = b"LAN-SHARE-CONTENT-" * 32
        (read_dir / "video.mp4").write_bytes(payload)
        (read_dir / "sub").mkdir()
        # 显式 UTF-8：冻结 exe 不带 UTF-8 模式，隐式编码在中文 Windows 上落 GBK，
        # 客户端字节比较会因编码环境不同而假失败
        deep_content = "深层数据".encode("utf-8")
        (read_dir / "sub" / "deep.txt").write_bytes(deep_content)

        lan = LanShare(log_cb=logs.write)
        share_url = lan.start(
            [Share(path=str(read_dir)), Share(path=str(write_dir), writable=True)],
            token="selftest-token", host="127.0.0.1", port=0,
        )
        # 对外分享的 url 用局域网 IP；本测试直接访问实际绑定的 127.0.0.1
        assert share_url.startswith("http://") and "token=selftest-token" in share_url, \
            f"分享 URL 应含局域网地址与 token: {share_url}"
        try:
            base = f"http://127.0.0.1:{lan._server.server_address[1]}"
            auth = {"X-Token": "selftest-token"}

            # 无 token / 错 token → 403
            assert _requests.get(base + "/", timeout=10).status_code == 403, "无 token 应 403"
            bad = _requests.get(base + "/?token=wrong", timeout=10)
            assert bad.status_code == 403, "错 token 应 403"

            # 首页与目录浏览
            home = _requests.get(f"{base}/?token=selftest-token", timeout=10)
            assert home.status_code == 200 and "video.mp4" not in home.text
            assert "lan_read" in home.text and "可上传" in home.text, "首页应列出共享目录"
            browse = _requests.get(
                f"{base}/browse?dir=0&p=&token=selftest-token", timeout=10
            )
            assert browse.status_code == 200 and "video.mp4" in browse.text, "目录列表应含文件"

            # 子目录进入与下载（内容与源文件一致，按字节比较，不依赖客户端字符集嗅探）
            deep = _requests.get(
                f"{base}/download?dir=0&p={quote('sub/deep.txt', safe='')}"
                f"&token=selftest-token",
                timeout=10,
            )
            assert deep.status_code == 200 and deep.content == deep_content, \
                f"子目录文件应可下载 (HTTP {deep.status_code})"
            video = _requests.get(
                f"{base}/download?dir=0&p=video.mp4&token=selftest-token", timeout=10
            )
            assert video.content == payload, "下载内容应与源文件一致"

            # `..` 穿越 → 403；白名单外路径（dir= 越界）→ 400/403
            escape_path = quote("..\\lan_write", safe="")
            escape = _requests.get(
                f"{base}/download?dir=0&p={escape_path}&token=selftest-token",
                timeout=10,
            )
            assert escape.status_code == 403, "穿越白名单应 403"
            outside = _requests.get(
                f"{base}/download?dir=9&p=x&token=selftest-token", timeout=10
            )
            assert outside.status_code in (400, 403), "白名单外索引应拒绝"

            # multipart 纯函数解析：文件名与内容
            body = (
                b"--BND\r\nContent-Disposition: form-data; name=\"file\"; "
                b"filename=\"phone.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n"
                b"\xff\xd8JPEGDATA\r\n--BND--\r\n"
            )
            parsed = _parse_multipart(body, "BND")
            assert parsed == ("phone.jpg", b"\xff\xd8JPEGDATA"), f"multipart 解析不符: {parsed}"

            # 上传落盘（重名自动加序号，不覆盖）
            def upload(dir_index: int, name: str, content: bytes):
                boundary = "XBOUND"
                part = (
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                    f"filename=\"{name}\"\r\n\r\n"
                ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
                return _requests.post(
                    f"{base}/upload?dir={dir_index}&token=selftest-token",
                    data=part,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
                    timeout=10,
                )

            first = upload(1, "照片.jpg", b"one")
            assert first.status_code == 200 and (write_dir / "照片.jpg").read_bytes() == b"one"
            second = upload(1, "照片.jpg", b"two")
            assert second.status_code == 200 and (write_dir / "照片-1.jpg").read_bytes() == b"two", \
                "重名上传应加序号"
            (write_dir / "照片.jpg").write_bytes(b"original")

            # 只读目录上传 → 403
            readonly = upload(0, "no.txt", b"x")
            assert readonly.status_code == 403, "只读目录应拒绝上传"

            # /api/scan 返回 JSON 计数（无规则时全 0）
            scan = _requests.post(
                f"{base}/api/scan?token=selftest-token", timeout=30
            )
            assert scan.status_code == 200, "扫描端点应可用"
            counts = scan.json()
            assert {"processed", "failed", "waiting"} <= set(counts), f"扫描计数缺字段: {counts}"
        finally:
            lan.stop()
        assert not lan.running
        try:
            stopped = _requests.get(base + "/", timeout=5)
            assert stopped.status_code in (400, 403), "停止后应不可访问"
        except _requests.ConnectionError:
            pass  # 端口已关闭：连接被拒即服务确已停止
        assert "[局域网]" in logs.getvalue(), "请求日志应经回调写出"
    finally:
        os.environ.pop("FILE_TOOLS_DATA_DIR", None)


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory(prefix="file_tools_selftest_") as tmp:
        workdir = Path(tmp)
        for name, test in (
            ("image_decrypt", _test_image_tool),
            ("suffix_manager", _test_suffix_tool),
            ("image_rename", _test_image_rename),
            ("image_convert", _test_image_convert),
            ("media_to_mp4", _test_media_tool),
            ("media_grab", _test_media_grab),
            ("download_engine", _test_download_engine),
            ("download_images", _test_download_images),
            ("fanqie_novel", _test_fanqie_novel),
            ("browser_sniff", _test_browser_sniff),
            ("preview_proxy", _test_preview_proxy),
            ("task_history", _test_task_history),
            ("flow_watch", _test_flow_watch),
            ("dedupe_images", _test_dedupe_images),
            ("lan_share", _test_lan_share),
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
