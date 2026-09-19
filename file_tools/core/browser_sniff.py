"""浏览器嗅探模式：启动本机浏览器 + CDP 捕获网络请求中的媒体地址（参考猫抓）。

设计要点（安全边界）：
- 浏览器使用独立的临时用户数据目录（%TEMP% 下随机目录），绝不读写用户的
  真实配置（无 Cookie/历史/扩展泄漏风险）；结束后终止进程并删除临时目录。
- 远程调试端口随机选取并只绑定 127.0.0.1；WebSocket 连接不带 Origin 头
  （新版本 Chrome 要求来源校验，省去 --remote-allow-origins 宽松开关）。
- 只用我们亲自启动的浏览器实例（进程句柄在手），结束即回收；
  `--no-first-run --no-default-browser-check` 避免首次运行向导干扰。

捕获原理：Network.requestWillBeSent / responseReceived 事件里筛出媒体地址
（对齐 media_grab.MEDIA_SUFFIXES 与 MIME 类型），即使请求最终失败
（如站点被网络阻断），地址本身仍可被捕获——与猫抓在播放失败页面上的行为一致。

另提供 `BrowserHTTPSession`：把浏览器网络栈伪装成 requests.Session
（CDP Fetch 域 + IO 流式读取），用于 Python 直连被 TLS 指纹/SNI 阻断、
只有真实浏览器能连通的站点下载。
"""

import base64
import json
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

import requests

try:  # websocket-client 为浏览器模式必需依赖，缺失时延迟报错而非导入崩溃
    import websocket
except ImportError:  # pragma: no cover - 依赖缺失在启动浏览器时给出明确提示
    websocket = None

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

# 与 media_grab.MEDIA_SUFFIXES 保持一致（此处独立定义避免循环导入）
MEDIA_SUFFIXES = {
    ".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv",
    ".mpg", ".mpeg", ".rm", ".rmvb", ".ts", ".vob", ".3gp", ".3g2",
    ".f4v", ".m2ts", ".mts", ".m4s",
    ".mp3", ".aac", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".wma",
    ".opus", ".aiff", ".aif", ".ape", ".mid",
    ".m3u8", ".mpd",
}

MEDIA_MIME_KEYWORDS = ("video/", "audio/", "mpegurl", "dash+xml", "mp2t")

_BROWSER_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
)


def find_browser_exe() -> Path | None:
    """查找本机 Chrome / Edge（Windows 10/11 必带 Edge），找不到返回 None。"""
    for candidate in _BROWSER_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def url_suffix(url: str) -> str:
    try:
        return Path(urlparse(url).path).suffix.lower()
    except ValueError:
        return ""


def is_media_url(url: str, mime: str = "", resource_type: str = "") -> bool:
    """判断一个请求地址是否为媒体资源（后缀或 MIME 任一命中）。"""
    if not url or url.startswith(("data:", "blob:")):
        return False
    if url_suffix(url) in MEDIA_SUFFIXES:
        return True
    return any(keyword in (mime or "").lower() for keyword in MEDIA_MIME_KEYWORDS)


@dataclass
class CapturedMedia:
    """一次浏览器会话中捕获到的媒体地址。"""

    url: str
    suffix: str
    kind: str  # m3u8 / media
    mime: str = ""
    status: int | None = None
    size: int | None = None
    resource_type: str = ""
    referer: str = ""
    request_headers: dict[str, str] = field(default_factory=dict)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class CDPClient:
    """Chrome DevTools Protocol 客户端：单读线程分发响应与事件。"""

    def __init__(self, ws_url: str, timeout: float = 30):
        if websocket is None:
            raise RuntimeError(
                "浏览器模式需要 websocket-client 依赖：pip install websocket-client"
            )
        self.ws = websocket.create_connection(
            ws_url, timeout=timeout, suppress_origin=True
        )
        self.seq = 0
        self._send_lock = threading.Lock()
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._waiters: dict[int, "queue.Queue[dict]"] = {}
        self.closed = False

        import queue

        self._queue_module = queue

        def reader() -> None:
            try:
                while True:
                    raw = self.ws.recv()
                    if not raw:
                        return
                    message = json.loads(raw)
                    rid = message.get("id")
                    if rid is not None:
                        with self._lock:
                            waiter = self._waiters.pop(rid, None)
                        if waiter is not None:
                            waiter.put(message)
                    else:
                        with self._lock:
                            self._events.append(message)
            except Exception:
                pass
            finally:
                self.closed = True

        threading.Thread(target=reader, daemon=True).start()

    def send(self, method: str, **params) -> None:
        """发送命令但不等待响应（用于 Page.navigate 等可能与 Fetch 拦截互锁的调用）。"""
        with self._send_lock:
            self.ws.send(json.dumps({"id": 0, "method": method, "params": params}))

    def call(self, method: str, timeout: float = 30, **params) -> dict:
        with self._send_lock:
            self.seq += 1
            rid = self.seq
            waiter: "queue.Queue[dict]" = self._queue_module.Queue()
            with self._lock:
                self._waiters[rid] = waiter
            self.ws.send(json.dumps({"id": rid, "method": method, "params": params}))
        try:
            message = waiter.get(timeout=timeout)
        except Exception:
            with self._lock:
                self._waiters.pop(rid, None)
            raise TimeoutError(f"CDP 调用超时: {method}") from None
        if "error" in message:
            raise RuntimeError(f"{method}: {message['error'].get('message')}")
        return message.get("result", {})

    def wait_event(
        self, method: str, timeout: float = 30, predicate=None
    ) -> dict:
        deadline = time.time() + timeout
        with self._lock:
            while True:
                for index, event in enumerate(self._events):
                    if event.get("method") == method and (
                        predicate is None or predicate(event)
                    ):
                        return self._events.pop(index)
                remaining = deadline - time.time()
                if remaining <= 0:
                    raise TimeoutError(f"CDP 事件超时: {method}")
                self._lock.release()
                time.sleep(min(0.05, remaining))
                self._lock.acquire()

    def drain_events(self) -> list[dict]:
        with self._lock:
            events, self._events = self._events, []
        return events

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001 - 关闭失败无需处理
            pass


class BrowserSession:
    """启动并管理一个带 CDP 调试端口的独立浏览器实例。

    visible=True 时窗口可见（嗅探用，用户在浏览器里播放视频）；
    visible=False 以 headless 模式运行（浏览器引擎下载回退用）。
    """

    def __init__(self, url: str = "about:blank", *, visible: bool = True,
                 user_agent: str | None = None):
        self.exe = find_browser_exe()
        if self.exe is None:
            raise RuntimeError("未找到本机 Chrome/Edge，无法启动浏览器模式。")
        if websocket is None:
            raise RuntimeError(
                "浏览器模式需要 websocket-client 依赖：pip install websocket-client"
            )
        self.port = _free_port()
        self.profile_dir = Path(tempfile.mkdtemp(prefix="ft_browser_"))
        self.process: subprocess.Popen | None = None
        self.cdp: CDPClient | None = None
        self.visible = visible
        self._closed = False
        self._user_agent = user_agent
        self._start(url)

    # -------- 生命周期 --------

    def _start(self, url: str) -> None:
        args = [
            str(self.exe),
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-session-crashed-bubble",
            "--hide-crash-restore-bubble",
            "--autoplay-policy=no-user-gesture-required",
        ]
        if self._user_agent:
            # 无头模式 UA 自带 HeadlessChrome 字样，会被部分 CDN 识别拒绝
            args.append(f"--user-agent={self._user_agent}")
        if not self.visible:
            args.append("--headless=new")
            args += ["--window-size=800,600"]
        else:
            args += ["--window-size=1280,860"]
        args.append(url)
        creationflags = 0
        import sys

        if sys.platform == "win32" and not self.visible:
            creationflags |= subprocess.CREATE_NO_WINDOW
        self.process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        if not self._wait_debug_port(20):
            self.close()
            raise RuntimeError("浏览器调试端口启动超时，浏览器模式不可用。")

    def _wait_debug_port(self, timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False
            try:
                requests.get(f"http://127.0.0.1:{self.port}/json/version", timeout=2)
                return True
            except requests.RequestException:
                time.sleep(0.25)
        return False

    def alive(self) -> bool:
        return (
            not self._closed
            and self.process is not None
            and self.process.poll() is None
        )

    def page_targets(self) -> list[dict]:
        try:
            targets = requests.get(
                f"http://127.0.0.1:{self.port}/json", timeout=3
            ).json()
        except (requests.RequestException, ValueError):
            return []
        return [t for t in targets if t.get("type") == "page"]

    def attach_page(self, url_contains: str = "", timeout: float = 20) -> CDPClient:
        """连接到页面级调试端点；默认取第一个页面，可用 URL 关键字选择。"""
        deadline = time.time() + timeout
        target = None
        while time.time() < deadline:
            targets = self.page_targets()
            if url_contains:
                target = next(
                    (t for t in targets if url_contains in (t.get("url") or "")), None
                )
            elif targets:
                target = targets[0]
            if target is not None and target.get("webSocketDebuggerUrl"):
                break
            time.sleep(0.3)
        if target is None or not target.get("webSocketDebuggerUrl"):
            raise RuntimeError("未能连接到浏览器页面调试端点。")
        self.cdp = CDPClient(target["webSocketDebuggerUrl"])
        return self.cdp

    def close(self) -> None:
        """终止浏览器进程并清理临时配置目录（幂等）。"""
        if self._closed:
            return
        self._closed = True
        if self.cdp is not None:
            self.cdp.close()
            self.cdp = None
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    pass
        shutil.rmtree(self.profile_dir, ignore_errors=True)

    def __enter__(self) -> "BrowserSession":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


class MediaRecorder:
    """从 CDP 网络事件中收集媒体地址（可离线测试的纯逻辑）。"""

    def __init__(self) -> None:
        self.records: dict[str, CapturedMedia] = {}
        self.page_title = ""
        self.page_url = ""

    def feed_request(self, url: str, *, resource_type: str = "", referer: str = "",
                     headers: dict[str, str] | None = None) -> CapturedMedia | None:
        if not is_media_url(url, resource_type=resource_type):
            return None
        record = self.records.get(url)
        if record is None:
            record = CapturedMedia(
                url=url,
                suffix=url_suffix(url),
                kind="m3u8" if url_suffix(url) == ".m3u8" else "media",
                resource_type=resource_type,
                referer=referer,
                request_headers=dict(headers or {}),
            )
            self.records[url] = record
        else:
            if resource_type:
                record.resource_type = resource_type
            if referer:
                record.referer = referer
        return record

    def feed_response(self, url: str, *, status: int | None = None, mime: str = "",
                      size: int | None = None) -> CapturedMedia | None:
        if not url or url.startswith(("data:", "blob:")):
            return None
        mime_lower = (mime or "").lower()
        known = self.records.get(url)
        if known is None:
            if not any(k in mime_lower for k in MEDIA_MIME_KEYWORDS):
                return None
            known = CapturedMedia(
                url=url,
                suffix=url_suffix(url),
                kind="m3u8" if "mpegurl" in mime_lower else "media",
                mime=mime,
            )
            self.records[url] = known
        if status:
            known.status = status
        if mime:
            known.mime = mime
        if size:
            known.size = size
        return known

    def ordered(self) -> list[CapturedMedia]:
        return list(self.records.values())


def capture_via_browser(
    url: str,
    *,
    max_seconds: float = 900,
    on_capture=None,
    on_status=None,
    on_ready=None,
) -> tuple[list[CapturedMedia], str, str]:
    """打开浏览器访问 url，捕获网络层出现的媒体地址。

    结束条件：用户关闭浏览器（进程退出），或达到 max_seconds。
    on_ready(session, cdp)：浏览器就绪后的回调（自动化测试注入交互用）。
    返回 (捕获列表, 页面标题, 最终页面地址)。
    """
    recorder = MediaRecorder()
    with BrowserSession(url, visible=True) as session:
        cdp = session.attach_page()
        cdp.call("Network.enable")
        cdp.call("Page.enable")
        cdp.call("Runtime.enable")
        if on_ready:
            try:
                on_ready(session, cdp)
            except Exception:  # noqa: BLE001 - 自动化钩子失败不阻断捕获
                pass
        if on_status:
            on_status(
                "浏览器已打开：请在浏览器中播放视频；捕获会实时显示，"
                "关闭浏览器窗口即可结束嗅探返回列表。"
            )
        deadline = time.time() + max_seconds
        announced: set[str] = set()
        last_title_check = 0.0
        while session.alive() and time.time() < deadline:
            for event in cdp.drain_events():
                _consume_event(recorder, event)
            for record in recorder.ordered():
                if record.url not in announced:
                    announced.add(record.url)
                    if on_capture:
                        on_capture(record)
            if time.time() - last_title_check > 3:
                last_title_check = time.time()
                _refresh_page_info(cdp, recorder)
            time.sleep(0.5)
        # 收尾前最后扫一遍，并尽力取一次标题
        for event in cdp.drain_events():
            _consume_event(recorder, event)
        _refresh_page_info(cdp, recorder)
    return recorder.ordered(), recorder.page_title, recorder.page_url


def _consume_event(recorder: MediaRecorder, event: dict) -> None:
    method = event.get("method")
    params = event.get("params", {})
    if method == "Network.requestWillBeSent":
        request = params.get("request", {})
        headers = {
            k: v for k, v in (request.get("headers") or {}).items()
            if not k.startswith(":") and k.lower() != "cookie"
        }
        recorder.feed_request(
            request.get("url", ""),
            resource_type=params.get("type", ""),
            referer=headers.get("Referer") or headers.get("referer") or "",
            headers=headers,
        )
    elif method == "Network.responseReceived":
        response = params.get("response", {})
        headers = response.get("headers", {}) or {}
        size = None
        for key in ("content-length", "Content-Length"):
            value = headers.get(key)
            if isinstance(value, str) and value.isdigit():
                size = int(value)
                break
        recorder.feed_response(
            response.get("url", ""),
            status=response.get("status"),
            mime=response.get("mimeType", ""),
            size=size,
        )


def _refresh_page_info(cdp: CDPClient, recorder: MediaRecorder) -> None:
    try:
        result = cdp.call(
            "Runtime.evaluate",
            expression="JSON.stringify([document.title, location.href])",
            returnByValue=True,
            timeout=5,
        )
        value = result.get("result", {}).get("value")
        if isinstance(value, str):
            parsed = json.loads(value)
            if isinstance(parsed, list) and len(parsed) == 2:
                recorder.page_title = parsed[0] or recorder.page_title
                recorder.page_url = parsed[1] or recorder.page_url
    except Exception:  # noqa: BLE001 - 页面信息获取失败不影响捕获
        pass


class BrowserHTTPSession:
    """用浏览器网络栈模拟 requests.Session 的最小接口（get/text/content/stream）。

    供 media_grab 在 Python 直连与 SNI 精简回退均失败后兜底使用。
    采用「页面内 fetch + 响应虹吸」：先导航到资源所属页面（建立真实
    会话上下文），再在页面里对资源地址发起 fetch，经 CDP Fetch 域
    拦截响应并用 IO 域流式读出——请求的 TLS 指纹、上下文与头信息
    和真实播放器完全一致。
    """

    def __init__(
        self,
        referer: str | None = None,
        user_agent: str = DEFAULT_UA,
        extra_headers: dict[str, str] | None = None,
    ):
        self.referer = referer
        self.user_agent = user_agent
        self.extra_headers = dict(extra_headers or {})
        self._session: BrowserSession | None = None
        self._cdp: CDPClient | None = None
        self._warmed_up = False

    def _ensure(self, page_url: str | None = None) -> CDPClient:
        fresh = self._session is None or not self._session.alive()
        if fresh:
            if self._session is not None:
                self._session.close()
            # 无头模式的 UA 带 HeadlessChrome 字样会被部分 CDN 识别拒绝，覆盖为正常 UA
            self._session = BrowserSession(page_url or "about:blank", visible=False,
                                           user_agent=self.user_agent)
            cdp = self._session.attach_page()
            cdp.call("Page.enable")
            cdp.call("Runtime.enable")
            self._cdp = cdp
            self._warmed_up = False
        if page_url and not self._warmed_up:
            self._warmup(page_url)
            # 暖场完成后才启用响应拦截，避免把页面自身的请求全部挂起
            self._cdp.call("Fetch.enable", patterns=[{"requestStage": "Response"}])
        assert self._cdp is not None
        return self._cdp

    def _warmup(self, page_url: str) -> None:
        """导航到资源所属页面并等加载完成，建立与会话一致的上下文。"""
        assert self._cdp is not None and self._session is not None
        self._cdp.send("Page.navigate", url=page_url)
        deadline = time.time() + 30
        while time.time() < deadline and self._session.alive():
            time.sleep(0.5)
            try:
                state = self._cdp.call(
                    "Runtime.evaluate", expression="document.readyState", timeout=5
                )["result"].get("value")
                if state == "complete":
                    break
            except (TimeoutError, RuntimeError):
                continue
        self._warmed_up = True

    def get(self, url: str, timeout: float = 60, stream: bool = False,
            referer: str | None = None, headers: dict[str, str] | None = None,
            **_kwargs):
        # 暖场页面：优先用请求头里的 Referer（资源所属页面），否则用会话 Referer
        page_url = (headers or {}).get("Referer") or referer or self.referer
        warmup_url = page_url if page_url and page_url.split("#")[0] != url else None
        cdp = self._ensure(warmup_url)
        fetch_headers = dict(self.extra_headers)
        for key, value in (headers or {}).items():
            if value and key.lower() not in ("user-agent", "cookie", "host"):
                fetch_headers[key] = value
        header_js = json.dumps(fetch_headers, ensure_ascii=False)
        expression = (
            "(()=>{window.__ft = fetch(" + json.dumps(url) +
            ",{cache:'no-store',headers:" + header_js + "})"
            ".then(r=>window.__fts=r.status).catch(e=>window.__fts='err:'+e.name);"
            "return 'started';})()"
        )
        try:
            cdp.call("Runtime.evaluate", expression=expression, returnByValue=True,
                     timeout=15)
        except (TimeoutError, RuntimeError):
            pass  # evaluate 超时不代表 fetch 未发出

        # 等待该 URL 的响应被 Fetch 域暂停（可能夹带页面自身的其他请求）
        deadline = time.time() + max(30, timeout)
        paused = None
        while time.time() < deadline:
            event = cdp.wait_event("Fetch.requestPaused", timeout=max(1, deadline - time.time()))
            params = event["params"]
            if (params.get("request", {}).get("url") or "").split("#")[0] == url:
                paused = params
                break
            cdp.call("Fetch.failRequest", requestId=params["requestId"],
                     errorReason="Aborted")
        if paused is None:
            raise RuntimeError("浏览器引擎请求未收到响应（超时）")
        status = paused.get("responseStatusCode") or 0
        response_headers = {
            entry["name"]: entry["value"] for entry in paused.get("responseHeaders", [])
        }
        if status >= 400:
            cdp.call("Fetch.failRequest", requestId=paused["requestId"], errorReason="Aborted")
            raise RuntimeError(f"浏览器引擎请求失败: HTTP {status}")

        stream_handle = cdp.call(
            "Fetch.takeResponseBodyAsStream", requestId=paused["requestId"]
        ).get("stream")
        cdp.call("Fetch.failRequest", requestId=paused["requestId"], errorReason="Aborted")

        def iter_bytes(chunk_size: int = 512 * 1024):
            # 顺序读取（部分流不支持随机访问 offset）
            while True:
                chunk = cdp.call(
                    "IO.read", handle=stream_handle, size=chunk_size,
                    timeout=max(30, timeout),
                )
                data = base64.b64decode(chunk.get("data", ""))
                if not data:
                    if chunk.get("eof"):
                        return
                    # 空数据且未到 EOF：短暂等待后继续
                    time.sleep(0.05)
                    continue
                yield data

        return _BrowserResponse(status, response_headers, iter_bytes(), stream)

    def close(self) -> None:
        if self._session is not None:
            self._session.close()
            self._session = None
            self._cdp = None


class _BrowserResponse:
    """BrowserHTTPSession.get 的返回值：对齐 requests.Response 的最小接口。"""

    def __init__(self, status_code: int, headers: dict, byte_iter, streamed: bool):
        self.status_code = status_code
        self.headers = headers
        self._iter = byte_iter
        self._streamed = streamed
        self._cached: bytes | None = None if streamed else b"".join(byte_iter)

    @property
    def content(self) -> bytes:
        if self._cached is None:
            self._cached = b"".join(self._iter)
        return self._cached

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size: int = 512 * 1024):
        if self._cached is not None:
            view = memoryview(self._cached)
            for start in range(0, len(view), chunk_size):
                yield bytes(view[start:start + chunk_size])
            return
        buffer = b""
        for chunk in self._iter:
            buffer += chunk
            while len(buffer) >= chunk_size:
                yield buffer[:chunk_size]
                buffer = buffer[chunk_size:]
        if buffer:
            yield buffer

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def close(self) -> None:  # requests 兼容
        pass


def sniff_browser_media(url: str, **kwargs) -> tuple[list[CapturedMedia], str, str]:
    """capture_via_browser 的别名（供 media_grab 统一入口调用）。"""
    return capture_via_browser(url, **kwargs)
