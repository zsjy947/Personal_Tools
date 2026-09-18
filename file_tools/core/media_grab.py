"""嗅探网页中的媒体资源并下载，支持 m3u8（HLS）合并下载。

实现思路参考浏览器插件“猫抓”：
- 后缀识别范围对齐猫抓的媒体类型表（视频/音频/图片流/直播清单），
  同时扫描标签属性（src/href/data-*）、JSON 字段（url/source/file 等）
  与页面内出现的裸 URL，相对地址自动补全。
- 针对 bilibili 等站点页面内不再内嵌播放地址的情况，内置站点适配：
  解析 `__INITIAL_STATE__` 后调用 playurl 接口获取 DASH 音视频流，
  下载选中的视频+音频后用内置 ffmpeg 合流封装为 MP4。
- 被反爬或网络阻断的站点：请求失败时自动尝试 curl_cffi 浏览器指纹回退，
  也可显式传入代理地址（GUI“代理”输入框 / CLI `--proxy`）。
- 预览：`open_preview()` 启动本地代理服务器并生成预览页（浏览器内直接播放，
  m3u8 经 hls.js 播放），避免点击资源链接触发浏览器下载。
- m3u8 自动解析分段列表（主播放列表选最高带宽），并发下载后无损合并，
  有 ffmpeg（内置优先）时直接封装 MP4。
- 支持 AES-128 加密分段（EXT-X-KEY，依赖 pycryptodome/cryptography）。
"""

import argparse
import concurrent.futures
import json
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from .media_to_mp4 import find_ffmpeg, run_hidden

# 对齐猫抓可识别的媒体后缀（视频 / 音频 / 直播清单 / B 站 DASH 流）
MEDIA_SUFFIXES = {
    # 视频
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv",
    ".mpg", ".mpeg", ".rm", ".rmvb", ".ts", ".vob", ".3gp", ".3g2",
    ".f4v", ".m2ts", ".mts", ".m4s",
    # 音频
    ".mp3", ".aac", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".wma",
    ".opus", ".aiff", ".aif", ".ape", ".mid",
    # 直播/点播清单
    ".m3u8", ".mpd",
}

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

MAX_SNIFF_RESULTS = 100
PROBE_LIMIT = 12  # 最多对前多少个资源做体积探测

# 标签属性与 JSON 字段中的资源地址
_ATTR_RE = re.compile(
    r"""(?:src|href|data-src|data-url|data-video|data-original|data-audio|data-audio-src|url|source|file|stream)["']?\s*[:=]\s*["']([^"']+)["']""",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"""https?://[^\s"'<>\\）】\]]+""", re.IGNORECASE)
_HLS_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')

BILIBILI_QUALITY = {
    127: "8K 超高清", 126: "杜比视界", 125: "HDR 真彩色", 120: "4K 超清",
    116: "1080P 60帧", 112: "1080P 高码率", 80: "1080P 高清",
    74: "720P 60帧", 64: "720P 高清", 32: "480P 清晰", 16: "360P 流畅",
}
BILIBILI_AUDIO = {
    30250: "杜比全景声", 30251: "Hi-Res 无损", 30280: "192kbps",
    30232: "132kbps", 30216: "64kbps",
}


@dataclass
class MediaResource:
    """嗅探到的一个媒体地址。"""

    url: str
    suffix: str
    kind: str  # m3u8 / media / dash-video / dash-audio
    label: str = ""
    size: int | None = None  # 字节；未知为 None
    title: str = ""  # 所属内容标题（如 B 站视频标题），用于输出文件命名
    page_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    fallback_urls: list[str] = field(default_factory=list)  # 主地址失败时依次尝试

    @property
    def kind_text(self) -> str:
        return {
            "m3u8": "HLS 播放列表",
            "media": "媒体文件",
            "dash-video": "DASH 视频",
            "dash-audio": "DASH 音频",
        }.get(self.kind, self.kind)

    @property
    def size_text(self) -> str:
        return _format_size(self.size)


def _format_size(size: int | None) -> str:
    if not size:
        return "未知"
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{size} B"
        size /= 1024  # type: ignore[operator]
    return f"{size} GB"


@dataclass
class SegmentKey:
    method: str
    uri: str | None
    iv: bytes | None


@dataclass
class MediaPlaylist:
    segments: list[str]
    key: SegmentKey | None = None
    media_sequence: int = 0
    init_uri: str | None = None


@dataclass
class Variant:
    bandwidth: int
    url: str
    resolution: str | None = None


@dataclass
class GrabSummary:
    found: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    merged: int = 0
    outputs: list[str] = field(default_factory=list)


# -------- 嗅探 --------

def normalize_suffixes(values: list[str] | None) -> set[str]:
    """把 "mp4 m3u8 ts" 之类的输入规范成 {".mp4", ".m3u8", ".ts"}。"""
    suffixes: set[str] = set()
    for value in values or []:
        for item in value.replace("，", ",").replace(" ", ",").split(","):
            item = item.strip().lower()
            if item:
                suffixes.add(item if item.startswith(".") else f".{item}")
    return suffixes


def url_suffix(url: str) -> str:
    """取 URL 路径部分的后缀（忽略查询参数），无后缀返回空串。"""
    return Path(urlparse(url).path).suffix.lower()


def _origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _new_session(referer: str | None = None, proxy: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Upgrade-Insecure-Requests": "1",
    })
    if referer:
        session.headers["Referer"] = referer
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def _fetch_via_curl(
    url: str, timeout: float, *, referer: str | None = None, proxy: str | None = None
) -> str | None:
    """curl_cffi 浏览器指纹回退；未安装或仍失败时返回 None。"""
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    kwargs: dict = {"timeout": timeout, "impersonate": "chrome"}
    if referer:
        kwargs["headers"] = {"Referer": referer}
    if proxy:
        kwargs["proxies"] = {"http": proxy, "https": proxy}
    try:
        response = curl_requests.get(url, **kwargs)
        response.raise_for_status()
        return response.text
    except Exception:  # noqa: BLE001 - 回退失败统一交由上层提示
        return None


def _connection_hint(exc: Exception, proxy: str | None, attempts: list[str] | None = None) -> str:
    detail = str(exc).strip() or exc.__class__.__name__
    if proxy:
        return (
            f"连接失败（经代理 {proxy}）：{detail}。"
            "请确认代理软件已开启且端口正确，浏览器扩展内置节点的话需在代理客户端开启 HTTP 端口。"
        )
    tried = "、".join(attempts) if attempts else "直连"
    return (
        f"连接失败：{detail}。已自动尝试 {tried} 与本地常见代理端口（系统代理、"
        "7890/7897/10809 等）均未成功。该站点可能被网络阻断——浏览器能打开通常是因为"
        "扩展自带远程节点；请开启代理客户端的系统代理/HTTP 端口，或在「代理」框填入其地址。"
    )


def _port_listening(port: int) -> bool:
    with socket.socket() as probe:
        probe.settimeout(0.4)
        return probe.connect_ex(("127.0.0.1", port)) == 0


COMMON_PROXY_PORTS = (7890, 7897, 10809, 10808, 1080, 8888, 8118, 2080, 9090, 1087, 33210)
_detected_proxy: str | None = None  # 嗅探自动探测成功的代理，下载时复用


def _candidate_proxies() -> list[str]:
    """候选代理：系统代理（注册表）优先，其后常见本地端口。"""
    candidates: list[str] = []
    try:
        import urllib.request

        for value in urllib.request.getproxies().values():
            if value and value not in candidates:
                candidates.append(value)
    except Exception:  # noqa: BLE001 - 系统代理读取失败不影响后续探测
        pass
    for port in COMMON_PROXY_PORTS:
        candidate = f"http://127.0.0.1:{port}"
        if candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _effective_proxy(proxy: str | None) -> str | None:
    return proxy or _detected_proxy


def _fetch_page(
    session: requests.Session, url: str, timeout: float, *, referer=None, proxy=None
) -> tuple[str, str]:
    """抓取页面文本：直连 → curl_cffi 指纹回退 → 自动探测本机代理；返回 (文本, 最终地址)。"""
    attempts: list[str] = []
    last_error: Exception | None = None
    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()
        if response.encoding is None:
            response.encoding = response.apparent_encoding
        return response.text, str(response.url)
    except (requests.ConnectionError, requests.Timeout) as exc:
        attempts.append("直连")
        last_error = exc

    text = _fetch_via_curl(url, timeout, referer=referer, proxy=proxy)
    if text is not None:
        return text, url

    global _detected_proxy
    for candidate in ([proxy] if proxy else _candidate_proxies()):
        parsed = urlparse(candidate)
        if (parsed.hostname or "").lower() in {"127.0.0.1", "localhost"}:
            if not _port_listening(parsed.port or 80):
                continue
        try:
            test_session = _new_session(referer, candidate)
            response = test_session.get(url, timeout=timeout)
            response.raise_for_status()
            if response.encoding is None:
                response.encoding = response.apparent_encoding
            if proxy is None:
                _detected_proxy = candidate
                print(f"直连失败，已自动使用本机代理: {candidate}")
            return response.text, str(response.url)
        except requests.RequestException:
            continue
    raise RuntimeError(_connection_hint(last_error, proxy, attempts))


def sniff_media(
    url: str,
    *,
    suffixes: set[str] | None = None,
    timeout: float = 15,
    referer: str | None = None,
    probe: bool = False,
    session: requests.Session | None = None,
    proxy: str | None = None,
) -> list[MediaResource]:
    """嗅探一个网页（或直连媒体地址）中的媒体资源。"""
    targets = suffixes or MEDIA_SUFFIXES
    direct_suffix = url_suffix(url)
    if direct_suffix in targets:
        return [
            MediaResource(
                url=url,
                suffix=direct_suffix,
                kind=_kind_of(url),
                headers={"Referer": referer} if referer else {},
            )
        ]

    own_session = session is None
    if own_session:
        session = _new_session(referer, proxy)
    text, page_url = _fetch_page(
        session, url, timeout, referer=referer, proxy=proxy
    )
    page_origin = _origin(page_url)

    results: list[MediaResource] = []
    seen: set[str] = set()

    def add(candidate: str, *, label: str = "", kind: str | None = None,
            size: int | None = None, headers: dict[str, str] | None = None) -> None:
        suffix = url_suffix(candidate)
        if suffix not in targets or candidate in seen:
            return
        seen.add(candidate)
        results.append(
            MediaResource(
                url=candidate,
                suffix=suffix,
                kind=kind or _kind_of(candidate),
                label=label,
                size=size,
                page_url=page_url,
                headers=headers or {"Referer": page_origin},
            )
        )

    # 站点适配（如 bilibili DASH）优先：页面里通常看不到这些地址
    if "bilibili.com" in urlparse(page_url).netloc:
        for resource in _bilibili_resources(session, text, page_url, timeout):
            if resource.url not in seen:
                seen.add(resource.url)
                results.append(resource)

    # JSON 转义还原（\/ 与 \u002F）后再做全局扫描
    unescaped = (
        text.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u0026", "&")
    )
    candidates: list[str] = []
    candidates.extend(urljoin(page_url, value.strip()) for value in _ATTR_RE.findall(unescaped))
    candidates.extend(match.rstrip(".,;)】》") for match in _URL_RE.findall(unescaped))
    for candidate in candidates:
        if len(results) >= MAX_SNIFF_RESULTS:
            break
        add(candidate)

    if probe:
        _probe_sizes(session, results, timeout=6)
    return results


def _kind_of(url: str) -> str:
    suffix = url_suffix(url)
    if suffix == ".m3u8":
        return "m3u8"
    if suffix == ".m4s":
        return "media"
    return "media"


def _probe_sizes(session: requests.Session, resources: list[MediaResource], timeout: float) -> None:
    """并发 HEAD 探测资源体积（失败则保持“未知”），仅探测前 PROBE_LIMIT 个。"""
    pending = [r for r in resources if r.size is None][:PROBE_LIMIT]

    def probe_one(resource: MediaResource) -> None:
        try:
            head = session.head(
                resource.url, timeout=timeout,
                headers={"Referer": resource.headers.get("Referer", "")} or None,
                allow_redirects=True,
            )
            length = head.headers.get("Content-Length")
            if head.status_code < 400 and length and length.isdigit():
                resource.size = int(length)
        except requests.RequestException:
            pass

    if not pending:
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        list(pool.map(probe_one, pending))


def print_resources(resources: list[MediaResource]) -> None:
    """按猫抓风格的表格打印嗅探结果（序号/类型/说明/大小/地址）。"""
    for index, resource in enumerate(resources, 1):
        label = resource.label or "—"
        print(
            f"  [{index}] {resource.kind_text} | {label} | "
            f"{resource.size_text} | {resource.suffix or '无后缀'} | {resource.url}"
        )


# -------- bilibili 站点适配 --------

def _extract_json_assign(text: str, marker: str):
    """提取 `window.xxx = {...};` 形式内嵌 JSON，失败返回 None。"""
    index = text.find(marker)
    if index == -1:
        return None
    start = text.find("{", index)
    if start == -1:
        return None
    try:
        obj, _end = json.JSONDecoder().raw_decode(text[start:])
    except ValueError:
        return None
    return obj


def _bilibili_resources(
    session: requests.Session, text: str, page_url: str, timeout: float
) -> list[MediaResource]:
    """从 bilibili 视频页解析 aid/cid/title 并调用 playurl 接口拿 DASH 流。"""
    state = _extract_json_assign(text, "window.__INITIAL_STATE__")
    video_data = (state or {}).get("videoData") or {}
    bvid, cid, title = video_data.get("bvid"), video_data.get("cid"), video_data.get("title")
    if not (bvid and cid):
        return []

    # 防风控：缺少 buvid3 时先访问一次首页拿 cookie
    if not any("buvid3" in name for name in session.cookies.keys()):
        try:
            session.get("https://www.bilibili.com/", timeout=timeout)
        except requests.RequestException:
            pass

    resources: list[MediaResource] = []
    headers = {"Referer": "https://www.bilibili.com/"}
    common = {"page_url": page_url, "headers": headers, "title": title or ""}
    try:
        payload = session.get(
            "https://api.bilibili.com/x/player/playurl",
            params={
                "bvid": bvid, "cid": cid, "qn": "80",
                "fnval": "16", "fnver": "0", "fourk": "1",
            },
            timeout=timeout,
        ).json()
    except (requests.RequestException, ValueError):
        return []
    if payload.get("code") != 0:
        return []
    data = payload.get("data") or {}

    dash = data.get("dash") or {}
    videos = list(dash.get("video") or [])
    audios = list(dash.get("audio") or [])
    timelength = data.get("timelength") or 0
    duration_hint = f" 时长{timelength / 60000:.0f}分钟" if timelength else ""

    # 同清晰度优先 AVC（兼容性最好），整体按清晰度从高到低
    videos.sort(key=lambda v: (v.get("id", 0), v.get("codecs", "").startswith("avc")), reverse=True)
    for video in videos:
        quality = BILIBILI_QUALITY.get(video.get("id"), f"{video.get('height', '?')}P")
        codecs = (video.get("codecs") or "unknown").split(".")[0]
        backup = [u for u in (video.get("backupUrl") or video.get("backup_url") or []) if u]
        resources.append(
            MediaResource(
                url=video.get("baseUrl") or video.get("base_url", ""),
                suffix=".m4s",
                kind="dash-video",
                label=f"{quality} {codecs}{duration_hint}",
                size=_dash_size(video),
                fallback_urls=backup,
                **common,
            )
        )
    for audio in sorted(audios, key=lambda a: a.get("bandwidth", 0), reverse=True):
        name = BILIBILI_AUDIO.get(audio.get("id"), f"{audio.get('bandwidth', 0) // 1000}kbps")
        backup = [u for u in (audio.get("backupUrl") or audio.get("backup_url") or []) if u]
        resources.append(
            MediaResource(
                url=audio.get("baseUrl") or audio.get("base_url", ""),
                suffix=".m4s",
                kind="dash-audio",
                label=f"音频 {name}",
                size=_dash_size(audio),
                fallback_urls=backup,
                **common,
            )
        )

    # 老接口只有 durl（FLV/MP4 直链）时兜底
    if not resources:
        for entry in data.get("durl") or []:
            resources.append(
                MediaResource(
                    url=entry.get("url", ""),
                    suffix=".mp4",
                    kind="media",
                    label=f"视频直链{duration_hint}",
                    size=entry.get("size"),
                    **common,
                )
            )
    return [r for r in resources if r.url]


def _dash_size(stream: dict) -> int | None:
    # bandwidth(bps) * 时长(s) / 8 估算；无时长时用 bandwidth 直接不可靠，返回 None
    return None


# -------- m3u8 解析 --------

def parse_m3u8(text: str, base_url: str) -> tuple[str, object]:
    """解析播放列表：返回 ("master", [Variant]) 或 ("media", MediaPlaylist)。"""
    lines = [line.strip() for line in text.splitlines()]
    if any(line.startswith("#EXT-X-STREAM-INF") for line in lines):
        variants: list[Variant] = []
        for index, line in enumerate(lines):
            if not line.startswith("#EXT-X-STREAM-INF"):
                continue
            attrs = dict(_HLS_ATTR_RE.findall(line.split(":", 1)[1]))
            uri = next(
                (
                    candidate
                    for candidate in lines[index + 1:]
                    if candidate and not candidate.startswith("#")
                ),
                None,
            )
            if uri:
                variants.append(
                    Variant(
                        bandwidth=int(attrs.get("BANDWIDTH", "0") or 0),
                        url=urljoin(base_url, uri),
                        resolution=attrs.get("RESOLUTION"),
                    )
                )
        if not variants:
            raise ValueError("m3u8 主播放列表中没有可用的子播放列表")
        return "master", variants

    segments: list[str] = []
    key: SegmentKey | None = None
    media_sequence = 0
    init_uri: str | None = None
    for line in lines:
        if line.startswith("#EXT-X-KEY"):
            attrs = dict(_HLS_ATTR_RE.findall(line.split(":", 1)[1]))
            method = attrs.get("METHOD", "NONE")
            uri = attrs.get("URI", "").strip('"') or None
            iv = _parse_iv(attrs.get("IV"))
            key = SegmentKey(method=method, uri=urljoin(base_url, uri) if uri else None, iv=iv)
        elif line.startswith("#EXT-X-MEDIA-SEQUENCE"):
            try:
                media_sequence = int(line.split(":", 1)[1])
            except ValueError:
                pass
        elif line.startswith("#EXT-X-MAP"):
            attrs = dict(_HLS_ATTR_RE.findall(line.split(":", 1)[1]))
            uri = attrs.get("URI", "").strip('"')
            if uri:
                init_uri = urljoin(base_url, uri)
        elif line and not line.startswith("#"):
            segments.append(urljoin(base_url, line))
    return "media", MediaPlaylist(
        segments=segments, key=key, media_sequence=media_sequence, init_uri=init_uri
    )


def _parse_iv(raw: str | None) -> bytes | None:
    if not raw:
        return None
    value = raw.strip().lower().removeprefix("0x")
    try:
        return bytes.fromhex(value)
    except ValueError:
        return None


# -------- 下载 --------

def _sanitize_stem(url_or_title: str, fallback: str = "index") -> str:
    stem = Path(url_or_title).stem if "/" in url_or_title else url_or_title
    stem = re.sub(r'[\\/:*?"<>|]+', "_", stem).strip()[:80]
    return stem or fallback


def _fetch_text(session: requests.Session, url: str, timeout: float) -> str:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    if response.encoding is None:
        response.encoding = response.apparent_encoding
    return response.text


def _request_with_retry(
    session: requests.Session, url: str, timeout: float, retries: int = 3
) -> bytes:
    last_error: Exception | None = None
    for _ in range(retries):
        try:
            response = session.get(url, timeout=timeout)
            response.raise_for_status()
            return response.content
        except requests.RequestException as exc:
            last_error = exc
    raise RuntimeError(f"分段下载失败 {url} ({last_error})")


def _decrypt_aes128(data: bytes, key: bytes, iv: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        padded = decryptor.update(data) + decryptor.finalize()
    except ImportError:
        try:
            from Crypto.Cipher import AES as _AES
        except ImportError as exc:
            raise RuntimeError(
                "该 m3u8 为 AES-128 加密，需要 pycryptodome 或 cryptography："
                "pip install pycryptodome"
            ) from exc
        padded = _AES.new(key, _AES.MODE_CBC, iv).decrypt(data)
    pad = padded[-1]
    if 0 < pad <= 16 and padded.endswith(bytes([pad]) * pad):
        padded = padded[:-pad]
    return padded


def download_direct(
    resource: MediaResource,
    output_dir: Path,
    *,
    session: requests.Session | None = None,
    timeout: float = 30,
    overwrite: bool = False,
    proxy: str | None = None,
) -> tuple[str, Path]:
    """流式下载单个媒体文件，返回 (状态, 保存路径)。"""
    if session is None:
        session = _new_session(resource.headers.get("Referer"), _effective_proxy(proxy))
    suffix = resource.suffix or ".bin"
    if resource.kind.startswith("dash-"):
        base_name = f"{resource.title} [{resource.label.split(' 时长')[0]}]" if resource.title else resource.label
        stem = _sanitize_stem(base_name)
    else:
        stem = _sanitize_stem(resource.url)
    destination = output_dir / f"{stem}{suffix}"
    if destination.exists() and not overwrite:
        print(f"跳过，目标已存在: {destination}")
        return "skipped", destination

    print(f"下载: {resource.label or ''} {resource.url}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")

    candidates = [resource.url, *resource.fallback_urls]
    last_error: Exception | None = None
    for attempt, candidate in enumerate(candidates, 1):
        if attempt > 1:
            print(f"主地址失败，改用备用地址 #{attempt - 1}: {candidate}")
        received = 0
        try:
            response = session.get(
                candidate, timeout=timeout, stream=True,
                headers={"Referer": resource.headers.get("Referer", "")} or None,
            )
            response.raise_for_status()
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        handle.write(chunk)
                        received += len(chunk)
            last_error = None
            break
        except requests.RequestException as exc:
            last_error = exc
            temporary.unlink(missing_ok=True)
    if last_error is not None:
        raise RuntimeError(f"全部地址尝试失败（{last_error}）")
    temporary.replace(destination)
    print(f"已保存: {destination}（{_format_size(received)}）")
    return "downloaded", destination


def download_m3u8(
    playlist_url: str,
    output_dir: Path,
    *,
    session: requests.Session,
    concurrency: int = 8,
    timeout: float = 30,
    to_mp4: bool = True,
    overwrite: bool = False,
    keep_segments: bool = False,
    referer: str | None = None,
) -> tuple[str, Path]:
    """下载 m3u8 全部分段并合并，返回 (状态, 最终文件路径)。"""
    text = _fetch_text(session, playlist_url, timeout)
    kind, payload = parse_m3u8(text, playlist_url)
    if kind == "master":
        payload_variants: list[Variant] = payload  # type: ignore[assignment]
        best = max(payload_variants, key=lambda variant: variant.bandwidth)
        print(
            f"主播放列表包含 {len(payload_variants)} 路画质，"
            f"自动选择最高带宽 {best.bandwidth or '未知'}"
            + (f"（{best.resolution}）" if best.resolution else "")
        )
        text = _fetch_text(session, best.url, timeout)
        kind, payload = parse_m3u8(text, best.url)

    playlist: MediaPlaylist = payload  # type: ignore[assignment]
    if not playlist.segments:
        raise ValueError("m3u8 中没有可下载的分段")

    stem = _sanitize_stem(playlist_url)
    final_path = output_dir / f"{stem}{'.mp4' if to_mp4 else '.ts'}"
    if final_path.exists() and not overwrite:
        print(f"跳过，目标已存在: {final_path}")
        return "skipped", final_path

    key_bytes: bytes | None = None
    if playlist.key and playlist.key.method != "NONE":
        if playlist.key.method != "AES-128":
            raise ValueError(f"不支持的加密方式: {playlist.key.method}")
        if playlist.key.uri is None:
            raise ValueError("EXT-X-KEY 缺少密钥地址")
        print("检测到 AES-128 加密，正在下载密钥…")
        key_bytes = _request_with_retry(session, playlist.key.uri, timeout)

    workdir = Path(tempfile.mkdtemp(prefix="m3u8_", dir=output_dir))
    try:
        init_data = b""
        if playlist.init_uri:
            print(f"下载初始化分段: {playlist.init_uri}")
            init_data = _request_with_retry(session, playlist.init_uri, timeout)

        total = len(playlist.segments)
        print(f"开始下载 {total} 个分段（并发 {concurrency}）…")
        done = 0
        lock = threading.Lock()
        progress_step = max(1, total // 10)

        def fetch_one(index: int) -> tuple[int, bytes]:
            data = _request_with_retry(
                session, playlist.segments[index], timeout
            )
            if key_bytes is not None:
                iv = playlist.key.iv if playlist.key and playlist.key.iv else (
                    (playlist.media_sequence + index).to_bytes(16, "big")
                )
                data = _decrypt_aes128(data, key_bytes, iv)
            return index, data

        def report(_future) -> None:
            nonlocal done
            with lock:
                done += 1
                if done % progress_step == 0 or done == total:
                    print(f"已下载 {done}/{total} 个分段")

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [pool.submit(fetch_one, i) for i in range(total)]
            for future in futures:
                future.add_done_callback(report)
            results = [
                future.result()
                for future in concurrent.futures.as_completed(futures)
            ]

        merged = workdir / "merged.ts"
        with merged.open("wb") as handle:
            if init_data:
                handle.write(init_data)
            for index, data in sorted(results):
                handle.write(data)
        print(f"分段合并完成: {merged.stat().st_size / 1024 / 1024:.2f} MB")
        saved_path = _finalize_output(merged, final_path, to_mp4)
    finally:
        if not keep_segments:
            shutil.rmtree(workdir, ignore_errors=True)

    return "downloaded", saved_path


def _finalize_output(merged: Path, final_path: Path, to_mp4: bool) -> Path:
    """优先用 ffmpeg 无损封装 MP4，失败或不可用时保留 TS。"""
    if to_mp4:
        ffmpeg = find_ffmpeg()
        if ffmpeg:
            result = run_hidden(
                [
                    ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
                    "-i", str(merged),
                    "-c", "copy",
                    "-movflags", "+faststart",
                    str(final_path),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode == 0 and final_path.exists():
                print(f"已封装 MP4: {final_path}")
                return final_path
            detail = result.stderr.strip().splitlines()
            print(
                "MP4 封装失败，保留 TS 文件: "
                + (detail[-1] if detail else f"ffmpeg 退出码 {result.returncode}"),
                file=sys.stderr,
            )
        else:
            print(
                "未找到 ffmpeg，保留 TS 文件；安装依赖后可用媒体转 MP4 工具转换",
                file=sys.stderr,
            )
    ts_path = final_path.with_suffix(".ts")
    shutil.move(str(merged), ts_path)
    print(f"已保存: {ts_path}")
    return ts_path


def _mux_dash(video: Path, audio: Path, output: Path, ffmpeg: str) -> bool:
    """将 DASH 视频/音频流无损合流为 MP4（全部内置执行，不弹外部窗口）。"""
    result = run_hidden(
        [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(video), "-i", str(audio),
            "-c", "copy", "-movflags", "+faststart",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and output.exists()


def _merge_dash_pairs(
    resources: list[MediaResource], saved: dict[int, Path], summary: GrabSummary, overwrite: bool
) -> None:
    """把同一页面选中的 DASH 视频+音频合流为单个 MP4，成功后删除分离流。"""
    videos = [(i, r) for i, r in enumerate(resources) if r.kind == "dash-video" and i in saved]
    audios = [(i, r) for i, r in enumerate(resources) if r.kind == "dash-audio" and i in saved]
    if not videos or not audios:
        return
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("未找到 ffmpeg，保留分离的视频/音频流（.m4s）", file=sys.stderr)
        return

    audio_path = saved[audios[0][0]]
    for index, resource in videos:
        stem = _sanitize_stem(resource.title or resource.label.split(" 时长")[0])
        output = saved[index].parent / f"{stem}.mp4"
        if output.exists() and not overwrite:
            print(f"跳过，目标已存在: {output}")
            summary.skipped += 1
            continue
        print(f"合流音视频: {output.name}")
        if _mux_dash(saved[index], audio_path, output, ffmpeg):
            saved[index].unlink(missing_ok=True)
            if len(audios) == 1:
                audio_path.unlink(missing_ok=True)
            summary.merged += 1
            summary.outputs.append(str(output))
            print(f"已合流: {output}")
        else:
            print(f"合流失败: {resource.url}（保留分离流）", file=sys.stderr)


# -------- 软件内预览（内置 ffmpeg 抽帧） --------

AUDIO_SUFFIXES = {".mp3", ".m4a", ".aac", ".flac", ".ogg", ".oga", ".opus", ".wav", ".wma", ".ape"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".avif", ".ico", ".tiff"}


def fetch_media_bytes(resource: MediaResource, *, timeout: float = 30) -> bytes:
    """下载资源原始字节（图片预览用），自动复用已探测的代理。"""
    session = _new_session(resource.headers.get("Referer"), _effective_proxy(None))
    response = session.get(resource.url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _ffmpeg_header_args(resource: MediaResource) -> list[str]:
    headers = {"User-Agent": DEFAULT_UA, **(resource.headers or {})}
    joined = "".join(f"{key}: {value}\r\n" for key, value in headers.items() if value)
    return ["-headers", joined] if joined else []


def _ffmpeg_proxy_args(resource: MediaResource, proxy: str | None) -> list[str]:
    # ffmpeg 的 http 代理选项只对 http:// 输入可靠；https 走代理暂不支持
    if not proxy or not resource.url.lower().startswith("http://"):
        return []
    return ["-http_proxy", proxy]


def _parse_ffmpeg_duration(stderr: str) -> float | None:
    match = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", stderr)
    if not match:
        return None
    hours, minutes, seconds = (float(part) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _ffmpeg_stream_info(
    resource: MediaResource, *, timeout: float, proxy: str | None
) -> tuple[str, float | None, bool]:
    """ffmpeg -i 读取流信息，返回 (描述文本, 时长秒, 是否含视频流)。"""
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("未找到内置 ffmpeg，无法生成预览")
    command = [
        ffmpeg, "-hide_banner", "-nostdin",
        *_ffmpeg_header_args(resource), *_ffmpeg_proxy_args(resource, proxy),
        "-rw_timeout", str(int(timeout * 1_000_000)),
        "-i", resource.url,
    ]
    result = run_hidden(
        command, capture_output=True, text=True, errors="replace",
        timeout=timeout + 15, check=False,
    )
    stderr = result.stderr or ""
    duration = _parse_ffmpeg_duration(stderr)
    video = re.search(r"Stream #.*?: Video: ([^,\n]+)", stderr)
    audio = re.search(r"Stream #.*?: Audio: ([^,\n]+)", stderr)
    parts = []
    if video:
        parts.append(f"视频 {video.group(1).strip()}")
    if audio:
        parts.append(f"音频 {audio.group(1).strip()}")
    if duration:
        parts.append(f"时长 {int(duration // 60)}:{int(duration % 60):02d}")
    return (" · ".join(parts) or "未解析到流信息"), duration, bool(video)


def capture_preview_frames(
    resource: MediaResource,
    *,
    count: int = 3,
    timeout: float = 25,
    proxy: str | None = None,
    workdir: Path,
    tag: str = "r",
) -> tuple[str, float | None, list[Path]]:
    """用内置 ffmpeg 从视频流抽取帧图片（软件内预览用）。

    返回 (流信息, 时长秒, 帧图片路径列表)；音频流只返回信息不给帧。
    """
    workdir.mkdir(parents=True, exist_ok=True)
    proxy = _effective_proxy(proxy)
    info, duration, has_video = _ffmpeg_stream_info(
        resource, timeout=timeout, proxy=proxy
    )
    if not has_video or count <= 0:
        return info, duration, []

    if duration and duration >= 4:
        stamps = [duration * factor for factor in (0.15, 0.45, 0.75)][:count]
    else:
        limit = max((duration or 2.0) - 0.2, 0)
        stamps = [min(1.0 + index * 2.0, limit) for index in range(count)]

    ffmpeg = find_ffmpeg()
    frames: list[Path] = []
    for index, stamp in enumerate(stamps):
        output = workdir / f"prev_{tag}_{index}.jpg"
        command = [
            ffmpeg, "-hide_banner", "-nostdin", "-loglevel", "error",
            *_ffmpeg_header_args(resource), *_ffmpeg_proxy_args(resource, proxy),
            "-rw_timeout", str(int(timeout * 1_000_000)),
            "-ss", f"{max(stamp, 0):.2f}", "-i", resource.url,
            "-frames:v", "1", "-q:v", "3", "-y", str(output),
        ]
        try:
            result = run_hidden(
                command, capture_output=True, text=True, errors="replace",
                timeout=timeout + 20, check=False,
            )
        except subprocess.TimeoutExpired:
            continue
        if result.returncode == 0 and output.exists() and output.stat().st_size > 0:
            frames.append(output)
    if not frames:
        raise RuntimeError(f"预览抽帧失败（{info}）")
    return info, duration, frames


# -------- 高层入口 --------

def download_resources(
    resources: list[MediaResource],
    output_dir: str | Path,
    *,
    concurrency: int = 8,
    timeout: float = 30,
    to_mp4: bool = True,
    referer: str | None = None,
    overwrite: bool = False,
    keep_segments: bool = False,
    proxy: str | None = None,
) -> GrabSummary:
    """下载已选中的媒体资源（GUI 嗅探列表勾选后调用）。"""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = GrabSummary(found=len(resources))
    if not resources:
        print("没有可下载的资源。")
        return summary

    proxy = _effective_proxy(proxy)
    saved: dict[int, Path] = {}
    for index, resource in enumerate(resources):
        try:
            session = _new_session(referer or resource.headers.get("Referer"), proxy)
            if resource.kind == "m3u8":
                status, path = download_m3u8(
                    resource.url,
                    output_dir,
                    session=session,
                    concurrency=concurrency,
                    timeout=timeout,
                    to_mp4=to_mp4,
                    overwrite=overwrite,
                    keep_segments=keep_segments,
                    referer=referer or resource.headers.get("Referer"),
                )
            else:
                status, path = download_direct(
                    resource, output_dir, session=session, timeout=timeout, overwrite=overwrite,
                    proxy=proxy,
                )
            if status != "failed":
                saved[index] = path
            setattr(summary, status, getattr(summary, status) + 1)
            if status == "downloaded":
                summary.outputs.append(str(path))
        except (requests.RequestException, RuntimeError, ValueError, OSError) as exc:
            print(f"下载失败: {resource.url} ({exc})", file=sys.stderr)
            summary.failed += 1

    _merge_dash_pairs(resources, saved, summary, overwrite)
    print(
        f"\n完成: 下载 {summary.downloaded}，合流 {summary.merged}，"
        f"跳过 {summary.skipped}，失败 {summary.failed}"
    )
    return summary


def grab_media(
    url: str,
    output_dir: str | Path,
    *,
    list_only: bool = False,
    picks: list[int] | None = None,
    grab_all: bool = False,
    suffixes: set[str] | None = None,
    concurrency: int = 8,
    timeout: float = 30,
    to_mp4: bool = True,
    referer: str | None = None,
    overwrite: bool = False,
    keep_segments: bool = False,
    probe: bool = False,
    proxy: str | None = None,
) -> GrabSummary:
    """嗅探并（可选）下载媒体资源，CLI 与交互菜单共用。"""
    resources = sniff_media(
        url, suffixes=suffixes, timeout=timeout, referer=referer, probe=probe, proxy=proxy
    )
    summary = GrabSummary(found=len(resources))
    if not resources:
        print("没有嗅探到媒体资源。")
        return summary
    print(f"嗅探到 {len(resources)} 个媒体资源:")
    print_resources(resources)
    if list_only:
        return summary

    if grab_all:
        selected = resources
    else:
        wanted = picks or [1]
        selected = [
            resources[index - 1]
            for index in wanted
            if 1 <= index <= len(resources)
        ]
        if not selected:
            print("选择的序号超出范围，未下载任何资源。")
            return summary
    return download_resources(
        selected,
        output_dir,
        concurrency=concurrency,
        timeout=timeout,
        to_mp4=to_mp4,
        referer=referer,
        overwrite=overwrite,
        keep_segments=keep_segments,
        proxy=proxy,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="嗅探网页中的媒体资源并下载；支持 m3u8 合并、B 站 DASH 音视频合流。"
    )
    parser.add_argument("url", help="网页地址或直接的媒体/m3u8 地址")
    parser.add_argument("-o", "--output", type=Path, default=Path("media_downloads"), help="输出目录（默认 media_downloads）")
    parser.add_argument("--list", action="store_true", help="仅列出嗅探结果（含类型/说明/大小/地址），不下载")
    parser.add_argument(
        "--pick",
        type=int,
        nargs="+",
        metavar="N",
        help="要下载的资源序号（1 起，先用 --list 查看结果，可空格给多个）",
    )
    parser.add_argument("--all", action="store_true", help="下载嗅探到的全部资源")
    parser.add_argument(
        "--suffix",
        nargs="+",
        metavar="EXT",
        help="嗅探的媒体后缀，默认按猫抓的常见视频/音频/清单后缀识别",
    )
    parser.add_argument("--concurrency", type=int, default=8, help="m3u8 分段下载并发数（默认 8）")
    parser.add_argument("--timeout", type=float, default=30, help="单次请求超时秒数（默认 30）")
    parser.add_argument("--referer", help="请求携带的 Referer（部分站点防盗链需要）")
    parser.add_argument(
        "--proxy",
        help="HTTP 代理地址（如 http://127.0.0.1:7890），用于访问拒绝直连/被阻断的站点",
    )
    parser.add_argument("--probe", action="store_true", help="列表时探测资源体积（HEAD 请求，稍慢）")
    parser.add_argument("--no-mp4", action="store_true", help="不封装 MP4，保留合并后的 TS")
    parser.add_argument("--overwrite", action="store_true", help="覆盖已有输出文件")
    parser.add_argument("--keep-segments", action="store_true", help="保留临时分段目录（调试用）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        summary = grab_media(
            args.url,
            args.output,
            list_only=args.list,
            picks=args.pick,
            grab_all=args.all,
            suffixes=normalize_suffixes(args.suffix),
            concurrency=args.concurrency,
            timeout=args.timeout,
            to_mp4=not args.no_mp4,
            referer=args.referer,
            overwrite=args.overwrite,
            keep_segments=args.keep_segments,
            probe=args.probe,
            proxy=args.proxy,
        )
    except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
