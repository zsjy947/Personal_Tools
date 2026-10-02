"""局域网文件流服务：纯标准库 HTTP 服务内嵌 GUI（默认关、token 保护）。

手机 ↔ 电脑文件浏览/下载/上传 + 触发监控规则扫描。安全边界：

- 会话 token（启动时 `secrets.token_urlsafe` 生成），所有端点校验
  `?token=` 或 `X-Token` 头，失败 403；
- 共享模型为目录白名单，**至多一个标记为可上传**，其余只读；请求路径经
  `resolve()` 后必须落在白名单目录内（防 `..` 穿越与符号链接逃逸），越界 403；
- 页面 HTML 全部内联，无任何外部资源依赖；每个请求写一行日志经回调进
  GUI 日志面板。

明确不做（BACKLOG B5）：账号体系/多用户、HTTPS、二维码、Range 断点、
独立常驻进程。默认端口 38475（避开番茄后端 38474）。
"""

import argparse
import atexit
import json
import re
import secrets
import socket
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

DEFAULT_PORT = 38475
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2GB 上限，防误传撑爆内存

_PAGE_CSS = """
body{font-family:system-ui,sans-serif;margin:0;background:#f1f5f9;color:#1f2430}
main{max-width:720px;margin:0 auto;padding:16px}
h1{font-size:20px} h2{font-size:15px;margin:18px 0 6px}
.card{background:#fff;border:1px solid #d9dee7;border-radius:10px;padding:14px;margin:10px 0}
table{width:100%;border-collapse:collapse;font-size:14px}
td,th{padding:7px 6px;border-bottom:1px solid #eef1f5;text-align:left;word-break:break-all}
a{color:#2563eb;text-decoration:none}
.tag{font-size:12px;color:#6b7280}
.up{color:#059669;font-size:12px}
form input[type=submit]{background:#2563eb;color:#fff;border:0;border-radius:8px;
padding:8px 18px;font-size:14px;cursor:pointer}
"""


def lan_ip() -> str:
    """取局域网 IP（UDP connect 技巧，不实际发包）；失败回退主机名。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostname()
    finally:
        sock.close()


@dataclass
class Share:
    """一个共享目录；writable=True 表示可上传（白名单中至多一个）。"""

    path: str
    writable: bool = False


def _safe_join(base: Path, relative: str) -> Path | None:
    """把相对路径并入白名单目录；越界（..、符号链接逃逸）返回 None。"""
    try:
        target = (base / relative).resolve()
        target.relative_to(base)
    except (OSError, ValueError):
        return None
    return target


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class LanShare:
    """局域网服务宿主：start/stop + ThreadingHTTPServer 生命周期管理。"""

    def __init__(self, log_cb=None) -> None:
        self._log_cb = log_cb if log_cb is not None else (lambda text: None)
        self._server: ThreadingHTTPServer | None = None
        self._thread = None
        self.token = ""
        self.shares: list[Share] = []
        self.port = DEFAULT_PORT

    @property
    def running(self) -> bool:
        return self._server is not None

    def _log(self, text: str) -> None:
        self._log_cb(text)

    def start(self, shares: list[Share], *, port: int = DEFAULT_PORT,
              token: str | None = None, host: str = "0.0.0.0") -> str:
        """启动服务，返回可分享的完整 URL（含 token）。"""
        if self.running:
            raise RuntimeError("局域网服务已在运行。")
        shares = [share for share in shares if Path(share.path).is_dir()]
        if not shares:
            raise ValueError("没有可共享的目录（请先添加存在的目录）。")
        if sum(1 for share in shares if share.writable) > 1:
            raise ValueError("至多只能把一个目录标记为可上传。")
        self.shares = shares
        self.port = port
        self.token = token or secrets.token_urlsafe(16)
        server = ThreadingHTTPServer((host, port), _LanHandler)
        server.lan = self  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="LanShare", daemon=True
        )
        self._thread.start()
        atexit.register(self.stop)
        self._log(f"[局域网] 服务已启动：{len(shares)} 个共享目录，端口 {server.server_address[1]}")
        return self.url

    @property
    def url(self) -> str:
        port = self._server.server_address[1] if self._server else self.port
        return f"http://{lan_ip()}:{port}/?token={quote(self.token, safe='')}"

    def stop(self) -> None:
        if self._server is None:
            return
        atexit.unregister(self.stop)
        self._server.shutdown()
        self._server.server_close()
        self._server = None
        self._thread = None
        self._log("[局域网] 服务已停止。")


class _LanHandler(BaseHTTPRequestHandler):
    """局域网服务请求处理：全部端点先过 token，再过白名单路径。"""

    server_version = "FileToolsLan/1.0"

    @property
    def lan(self) -> LanShare:
        return self.server.lan  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        # 每个请求一行日志经回调进 GUI 日志面板（send_response 里调用）
        self.lan._log(f"[局域网] {self.address_string()} {format % args}")

    # ---- 鉴权与公共响应 ----

    def _token_ok(self, query: dict) -> bool:
        supplied = (query.get("token") or [""])[0] or self.headers.get("X-Token", "")
        return secrets.compare_digest(
            supplied.encode("utf-8"), self.lan.token.encode("utf-8")
        )

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _deny(self, status: int, note: str) -> None:
        self._send_html(
            f"<!doctype html><meta charset='utf-8'><main><div class='card'>{note}"
            f"</div><a href='javascript:history.back()'>返回</a></main>",
            status=status,
        )

    # ---- GET ----

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            # send_error 的 reason 不能用中文（状态行按 latin-1 编码会崩）
            self.send_error(403)
            return
        if parsed.path == "/":
            self._serve_home(query)
        elif parsed.path == "/browse":
            self._serve_browse(query)
        elif parsed.path == "/download":
            self._serve_download(query)
        else:
            self.send_error(404)

    def _share_by(self, query: dict):
        index = (query.get("dir") or [""])[0]
        if not index.isdigit() or int(index) >= len(self.lan.shares):
            return None
        return self.lan.shares[int(index)]

    def _serve_home(self, query: dict) -> None:
        rows = []
        upload_share = None
        for index, share in enumerate(self.lan.shares):
            name = Path(share.path).name or share.path
            tag = "<span class='up'>可上传</span>" if share.writable else "只读"
            rows.append(
                f"<div class='card'><a href='/browse?dir={index}"
                f"&token={quote(self.lan.token, safe='')}'><b>{_html_escape(name)}</b></a> "
                f"<span class='tag'>{tag} · {_html_escape(share.path)}</span></div>"
            )
            if share.writable:
                upload_share = index
        upload_html = ""
        if upload_share is not None:
            action = f"/upload?dir={upload_share}&token={quote(self.lan.token, safe='')}"
            upload_html = f"""
<h2>上传到「{_html_escape(Path(self.lan.shares[upload_share].path).name)}」</h2>
<div class="card"><form method="POST" action="{action}" enctype="multipart/form-data">
<input type="file" name="file" required>
<input type="submit" value="上传">
</form></div>"""
        page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FileTools 局域网共享</title><style>{_PAGE_CSS}</style></head><body><main>
<h1>📁 FileTools 局域网共享</h1>
{''.join(rows) or "<div class='card'>没有共享目录。</div>"}
{upload_html}
<div class="card tag">提示：仅限可信局域网使用；软件关闭即停止服务。
上传目录重名文件自动加序号，不会覆盖。</div>
</main></body></html>"""
        self._send_html(page)

    def _serve_browse(self, query: dict) -> None:
        share = self._share_by(query)
        if share is None:
            self._deny(400, "无效的共享目录。")
            return
        base = Path(share.path).resolve()
        relative = (query.get("p") or [""])[0]
        target = _safe_join(base, relative)
        if target is None or not target.is_dir():
            self._deny(403, "路径不在共享范围内。")
            return
        token = quote(self.lan.token, safe="")
        dir_param = (query.get("dir") or ["0"])[0]
        try:
            entries = sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        except OSError:
            entries = []
        rows = []
        if target != base:
            parent = _safe_join(base, str(Path(relative).parent))
            if parent is not None:
                rows.append(
                    f"<tr><td colspan='3'><a href='/browse?dir={dir_param}"
                    f"&p={quote(str(parent.relative_to(base)), safe='')}&token={token}'>↰ 上一级</a></td></tr>"
                )
        for entry in entries:
            display = _html_escape(entry.name)
            rel = quote(str(entry.relative_to(base)).replace("\\", "/"), safe="")
            if entry.is_dir():
                rows.append(
                    f"<tr><td colspan='3'><a href='/browse?dir={dir_param}"
                    f"&p={rel}&token={token}'>📁 {display}</a></td></tr>"
                )
            else:
                try:
                    stat = entry.stat()
                    size = _format_size(stat.st_size)
                    mtime = time_text(stat.st_mtime)
                except OSError:
                    size, mtime = "—", "—"
                rows.append(
                    f"<tr><td><a href='/download?dir={dir_param}&p={rel}"
                    f"&token={token}'>📄 {display}</a></td>"
                    f"<td class='tag'>{size}</td><td class='tag'>{mtime}</td></tr>"
                )
        page = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_html_escape(target.name)} — FileTools</title><style>{_PAGE_CSS}</style>
</head><body><main><h1>📁 {_html_escape(target.name)}</h1>
<div class="card"><table>{''.join(rows) or "<tr><td class='tag'>空目录</td></tr>"}
</table></div>
<p class="tag"><a href="/?token={token}">← 返回首页</a></p>
</main></body></html>"""
        self._send_html(page)

    def _serve_download(self, query: dict) -> None:
        share = self._share_by(query)
        if share is None:
            self.send_error(400)
            return
        target = _safe_join(Path(share.path).resolve(), (query.get("p") or [""])[0])
        if target is None or not target.is_file():
            self.send_error(403)
            return
        try:
            size = target.stat().st_size
            with target.open("rb") as handle:
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(size))
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename*=UTF-8''"
                    + quote(target.name),
                )
                self.end_headers()
                while chunk := handle.read(256 * 1024):
                    self.wfile.write(chunk)
        except OSError:
            self.send_error(404)

    # ---- POST ----

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if not self._token_ok(query):
            self.send_error(403)
            return
        if parsed.path == "/upload":
            self._serve_upload(query)
        elif parsed.path == "/api/scan":
            self._serve_scan()
        else:
            self.send_error(404)

    def _serve_upload(self, query: dict) -> None:
        share = self._share_by(query)
        if share is None or not share.writable:
            self._deny(403, "该目录不允许上传。")
            return
        content_type = self.headers.get("Content-Type", "")
        match = re.search(r'boundary="?([^";]+)"?', content_type)
        if "multipart/form-data" not in content_type or not match:
            self._deny(400, "上传必须是 multipart 表单。")
            return
        length = int(self.headers.get("Content-Length") or 0)
        if not 0 < length <= MAX_UPLOAD_BYTES:
            self._deny(400, "上传内容为空或超出大小上限。")
            return
        body = self.rfile.read(length)
        parsed = _parse_multipart(body, match.group(1))
        if parsed is None:
            self._deny(400, "未在表单中找到文件。")
            return
        filename, payload = parsed
        from .common import unique_path

        base = Path(share.path).resolve()
        dest = unique_path(base / filename)
        try:
            dest.write_bytes(payload)
        except OSError as exc:
            self._deny(500, f"写入失败: {exc}")
            return
        self.lan._log(f"[局域网] 上传完成: {dest.name}（{_format_size(len(payload))}）")
        token = quote(self.lan.token, safe="")
        self._send_html(
            f"<!doctype html><meta charset='utf-8'><main><div class='card'>"
            f"✅ 已上传 {_html_escape(dest.name)}（{_format_size(len(payload))}）"
            f"</div><a href='/browse?dir={(query.get('dir') or ['0'])[0]}"
            f"&token={token}'>查看目录</a> · <a href='/?token={token}'>首页</a></main>"
        )

    def _serve_scan(self) -> None:
        from .flow_watch import scan_now

        summary = scan_now(log_cb=self.lan._log)
        self._send_json({
            "processed": summary.get("processed", 0),
            "failed": summary.get("failed", 0),
            "waiting": summary.get("waiting", 0),
        })


def time_text(timestamp: float) -> str:
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _parse_multipart(body: bytes, boundary: str) -> tuple[str, bytes] | None:
    """手写最小 multipart 解析：返回 (文件名, 内容)，找不到文件部分返回 None。"""
    delimiter = b"--" + boundary.encode("utf-8")
    for section in body.split(delimiter):
        header_blob, sep, payload = section.partition(b"\r\n\r\n")
        if not sep:
            continue
        match = re.search(rb'filename="([^"]*)"', header_blob)
        if not match:
            continue
        name = match.group(1).decode("utf-8", errors="replace").strip()
        name = re.sub(r'[\\/:*?"<>|]+', "_", Path(name).name)
        if payload.endswith(b"\r\n"):
            payload = payload[:-2]  # 结尾 CRLF 属于协议分隔，不入文件
        return name or "upload.bin", payload
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="局域网文件共享服务（一般经 GUI 使用；命令行用于临时分享）。"
    )
    parser.add_argument("directories", nargs="+", help="要共享的目录（第一个可上传）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help=f"监听端口（默认 {DEFAULT_PORT}）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    shares = [
        Share(path=path, writable=index == 0)
        for index, path in enumerate(args.directories)
    ]
    lan = LanShare(log_cb=print)
    try:
        url = lan.start(shares, port=args.port)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1
    print("手机/其他设备请访问:", url)
    print("Ctrl+C 停止服务。")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        lan.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
