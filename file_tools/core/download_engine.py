"""下载引擎选择层：yt-dlp 库内嵌为默认下载执行层，自研内核降为 legacy 兜底。

嗅探（media_grab）与预览链路保持自研不动；下载执行交给 yt-dlp 后，
m3u8/AES/直链与各站反爬由其内置提取器与社区更新消化，结束单人维护
下载规则的军备竞赛。引擎三选一：

- auto：环境里能找到 yt_dlp 就走 yt-dlp，否则自动回退 legacy（未装
  yt-dlp 的环境同样能跑）；
- ytdlp：强制 yt-dlp，未安装时报错；
- legacy：强制自研多级传输内核（media_grab.download_resources）。

对外签名与 media_grab.download_resources 保持一致（engine 追加在末尾），
grab_view 与 CLI 只需多传一个参数。yt_dlp 按项目纪律在函数体内懒导入。
"""

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from .media_grab import GrabSummary, MediaResource, _sanitize_stem
from .media_to_mp4 import find_ffmpeg

ENGINES = ("auto", "ytdlp", "legacy")

# B 站等 DASH 站点音视频对：让 yt-dlp 原生完成选清晰度 + 下载 + 合流
DASH_PAIR_FORMAT = "bv*+ba/b"

# yt-dlp 中断残留的临时后缀，重名跳过判定时不当作已有产物
_PART_SUFFIXES = (".part", ".ytdl", ".temp", ".tmp")


def _yt_dlp_available() -> bool:
    return importlib.util.find_spec("yt_dlp") is not None


def resolve_engine(engine: str, *, available: bool | None = None) -> str:
    """把 auto/ytdlp/legacy 解析为实际引擎；auto 按安装情况自动回退。"""
    if engine not in ENGINES:
        raise ValueError(f"未知下载引擎: {engine}（可选：{'/'.join(ENGINES)}）")
    if engine == "legacy":
        return "legacy"
    installed = _yt_dlp_available() if available is None else available
    if installed:
        return "ytdlp"
    if engine == "ytdlp":
        raise RuntimeError(
            "未安装 yt-dlp：pip install yt-dlp，或把下载引擎切换为「内置」。"
        )
    print("提示: 未安装 yt-dlp，自动回退内置下载引擎（legacy）。")
    return "legacy"


def build_ytdlp_opts(
    *,
    outtmpl: str,
    headers: dict[str, str] | None = None,
    format_spec: str | None = None,
    overwrite: bool = False,
    to_mp4: bool = True,
    concurrency: int = 8,
    timeout: float = 30,
    progress_hook=None,
) -> dict:
    """构造 yt-dlp 选项字典（纯函数，便于自检断言）。

    overwrites=False 是 yt-dlp 的“目标已存在就跳过”语义，对齐 legacy
    download_direct 的 overwrite=False 行为；ffmpeg_location 复用
    find_ffmpeg()（环境变量 → exe 同目录 → 内置 imageio-ffmpeg → PATH），
    打包产物内同样生效。
    """
    opts: dict = {
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        # 原生进度行按分片高频刷新，日志面板会被刷屏；改用自写钩子按 10% 节流
        "noprogress": True,
        "overwrites": overwrite,
        "socket_timeout": timeout,
        "concurrent_fragment_downloads": max(1, concurrency),
        "http_headers": {k: v for k, v in (headers or {}).items() if v},
    }
    if format_spec:
        opts["format"] = format_spec
    if to_mp4:
        opts["merge_output_format"] = "mp4"
    if progress_hook is not None:
        opts["progress_hooks"] = [progress_hook]
    ffmpeg = find_ffmpeg()
    if ffmpeg:
        opts["ffmpeg_location"] = ffmpeg
    return opts


@dataclass
class YtdlpTask:
    """一条 yt-dlp 下载任务（资源整理后的最小执行单元）。"""

    url: str
    outtmpl: str
    label: str
    headers: dict[str, str] = field(default_factory=dict)
    format_spec: str | None = None
    fallback_urls: list[str] = field(default_factory=list)
    is_dash_pair: bool = False  # 由 dash 音视频对合并成的页面任务


def _merged_headers(resource: MediaResource, referer: str | None) -> dict[str, str]:
    headers = {k: v for k, v in (resource.headers or {}).items() if v}
    if referer and not headers.get("Referer"):
        headers["Referer"] = referer
    return headers


def dash_pair_page_url(resources: list[MediaResource]) -> str | None:
    """同时勾选了同页面的 dash-video 与 dash-audio 时返回该页面地址。

    DASH 分离流单独下载难以直接播放；两者齐备时改为对页面单次调用
    yt-dlp（-f "bv*+ba/b"），由其原生完成选清晰度、下载与音视频合流。
    """
    audio_pages = {
        r.page_url for r in resources if r.kind == "dash-audio" and r.page_url
    }
    for resource in resources:
        if resource.kind == "dash-video" and resource.page_url in audio_pages:
            return resource.page_url
    return None


def _outtmpl_for(output_dir: Path, stem: str) -> str:
    # outtmpl 是 % 模板串：词干里的字面 % 须先转义，否则 yt-dlp 解析出错
    escaped = stem.replace("%", "%%")
    return str(output_dir / f"{escaped}.%(ext)s")


def plan_ytdlp_tasks(
    resources: list[MediaResource],
    output_dir: Path,
    *,
    referer: str | None = None,
) -> list[YtdlpTask]:
    """把资源列表整理为 yt-dlp 任务：dash 对合并为页面任务，其余逐条直下。

    直下任务的输出词干沿用 legacy download_direct 的命名规则（B 站单流
    用「标题 [清晰度]」、其余用标题或地址），两引擎产物名保持一致。
    """
    tasks: list[YtdlpTask] = []
    page_url = dash_pair_page_url(resources)
    if page_url:
        head = next(
            r for r in resources
            if r.kind == "dash-video" and r.page_url == page_url
        )
        title = head.title or head.label or "dash-video"
        tasks.append(
            YtdlpTask(
                url=page_url,
                outtmpl=_outtmpl_for(output_dir, _sanitize_stem(title)),
                label=title,
                headers=_merged_headers(head, referer),
                format_spec=DASH_PAIR_FORMAT,
                is_dash_pair=True,
            )
        )
        resources = [
            r for r in resources
            if not (r.page_url == page_url and r.kind in ("dash-video", "dash-audio"))
        ]

    for resource in resources:
        if not resource.url:
            continue
        if resource.kind.startswith("dash-"):
            base = (
                f"{resource.title} [{resource.label.split(' 时长')[0]}]"
                if resource.title else resource.label
            )
            stem = _sanitize_stem(base)
        else:
            stem = _sanitize_stem(resource.title or resource.url)
        tasks.append(
            YtdlpTask(
                url=resource.url,
                outtmpl=_outtmpl_for(output_dir, stem),
                label=resource.label or resource.kind_text,
                headers=_merged_headers(resource, referer),
                fallback_urls=list(resource.fallback_urls),
            )
        )
    return tasks


def _existing_output(output_dir: Path, outtmpl: str) -> Path | None:
    """overwrite=False 时按 outtmpl 词干匹配已有产物（任意扩展名）。

    yt-dlp 的最终扩展名随源而定（mp4/ts/mkv…），精确到后缀的判断会漏；
    按词干匹配保守跳过，宁可不重下也不无权限覆盖。中断残留（.part 等）
    不算已有产物。
    """
    stem = Path(outtmpl.replace("%%", "%")).with_suffix("").name
    if not output_dir.is_dir():
        return None
    for entry in output_dir.iterdir():
        if not entry.is_file() or entry.suffix.lower() in _PART_SUFFIXES:
            continue
        if entry.name == stem or entry.name.startswith(stem + "."):
            return entry
    return None


def _make_progress_hook(label: str):
    """把 yt-dlp 进度回调转成按 10% 节流的 print（经 runner 进日志面板）。"""
    state = {"stage": -1}

    def hook(payload: dict) -> None:
        status = payload.get("status")
        if status == "finished":
            if state["stage"] < 100:
                state["stage"] = 100
                print(f"yt-dlp: {label} 下载完成")
            return
        if status != "downloading":
            return
        total = payload.get("total_bytes") or payload.get("total_bytes_estimate")
        received = payload.get("downloaded_bytes") or 0
        if not total:
            return
        stage = int(received / total * 10)
        if stage > state["stage"]:
            state["stage"] = stage
            print(f"yt-dlp: {label} {stage * 10}%")

    return hook


def download_with_engine(
    resources: list[MediaResource],
    output_dir: str | Path,
    *,
    concurrency: int = 8,
    timeout: float = 30,
    to_mp4: bool = True,
    referer: str | None = None,
    overwrite: bool = False,
    keep_segments: bool = False,
    engine: str = "auto",
) -> GrabSummary:
    """按引擎执行下载：yt-dlp 或回退 legacy 自研内核。

    keep_segments 是 legacy 内核的调试参数，yt-dlp 引擎不使用（其临时
    文件自行清理）。
    """
    resolved = resolve_engine(engine)
    if resolved == "legacy":
        from .media_grab import download_resources as legacy_download

        return legacy_download(
            resources,
            output_dir,
            concurrency=concurrency,
            timeout=timeout,
            to_mp4=to_mp4,
            referer=referer,
            overwrite=overwrite,
            keep_segments=keep_segments,
            engine="legacy",
        )
    return _download_with_ytdlp(
        resources,
        output_dir,
        concurrency=concurrency,
        timeout=timeout,
        to_mp4=to_mp4,
        referer=referer,
        overwrite=overwrite,
    )


def _download_with_ytdlp(
    resources: list[MediaResource],
    output_dir: str | Path,
    *,
    concurrency: int,
    timeout: float,
    to_mp4: bool,
    referer: str | None,
    overwrite: bool,
) -> GrabSummary:
    import yt_dlp

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = GrabSummary(found=len(resources))
    if not resources:
        print("没有可下载的资源。")
        return summary

    for task in plan_ytdlp_tasks(resources, output_dir, referer=referer):
        if task.is_dash_pair:
            print(f"检测到音视频分离流成对勾选，交由 yt-dlp 合流下载: {task.label}")
        outcome = "failed"
        saved: Path | None = None
        candidates = [task.url, *task.fallback_urls]
        for attempt, candidate in enumerate(candidates, 1):
            if attempt > 1:
                print(f"主地址失败，改用备用地址 #{attempt - 1}: {candidate}")
            existing = _existing_output(output_dir, task.outtmpl)
            if existing is not None and not overwrite:
                print(f"跳过，目标已存在: {existing}")
                outcome = "skipped"
                break
            try:
                saved = _ytdlp_download_one(
                    yt_dlp, task, candidate, output_dir,
                    to_mp4=to_mp4, concurrency=concurrency,
                    timeout=timeout, overwrite=overwrite,
                )
            except Exception as exc:  # noqa: BLE001 - 单任务失败换候选/计失败
                print(f"下载失败: {candidate} ({exc})")
                saved = None
                outcome = "failed"
                continue
            outcome = "downloaded"
            break
        if outcome == "downloaded" and saved is not None:
            summary.downloaded += 1
            summary.outputs.append(str(saved))
            if task.is_dash_pair:
                summary.merged += 1
        elif outcome == "skipped":
            summary.skipped += 1
        else:
            summary.failed += 1
    print(
        f"\n完成: 下载 {summary.downloaded}，合流 {summary.merged}，"
        f"跳过 {summary.skipped}，失败 {summary.failed}"
    )
    return summary


def _ytdlp_download_one(
    yt_dlp,
    task: YtdlpTask,
    url: str,
    output_dir: Path,
    *,
    to_mp4: bool,
    concurrency: int,
    timeout: float,
    overwrite: bool,
) -> Path | None:
    """执行单条 yt-dlp 任务，返回最终文件路径；失败抛 DownloadError。"""
    opts = build_ytdlp_opts(
        outtmpl=task.outtmpl,
        headers=task.headers,
        format_spec=task.format_spec,
        overwrite=overwrite,
        to_mp4=to_mp4,
        concurrency=concurrency,
        timeout=timeout,
        progress_hook=_make_progress_hook(task.label),
    )
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
    if info is None:
        raise RuntimeError("yt-dlp 未返回下载信息")
    requested = (info.get("requested_downloads") or [{}])[-1]
    filepath = requested.get("filepath")
    if filepath and Path(filepath).exists():
        print(f"已保存: {filepath}")
        return Path(filepath)
    # 个别提取器不给 filepath：按词干回查目录里的新产物
    found = _existing_output(output_dir, task.outtmpl)
    if found is None:
        raise RuntimeError("yt-dlp 未产出目标文件")
    print(f"已保存: {found}")
    return found
