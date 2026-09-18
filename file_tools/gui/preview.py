"""软件内媒体预览窗口：视频抽帧展示、图片直显、音频流信息，不打开浏览器。"""

import queue
import shutil
import tempfile
import threading
import tkinter as tk
from io import BytesIO
from pathlib import Path
from tkinter import ttk

from .theme import COLORS, FONTS, scale

try:
    from PIL import Image, ImageTk
except ImportError:  # pragma: no cover - Pillow 为必装依赖，此处仅防御
    Image = ImageTk = None

THUMB_WIDTH = 250
IMAGE_WIDTH = 420


class PreviewWindow(tk.Toplevel):
    """按资源生成预览卡片：视频显示多个时间点缩略图，图片直接展示。"""

    def __init__(self, master, resources: list, indices: list[int], proxy: str | None = None):
        super().__init__(master)
        self.title("媒体预览")
        self.geometry(f"{scale(900)}x{scale(640)}")
        self.configure(bg=COLORS["bg"])
        self.transient(master)

        self._resources = resources
        self._proxy = proxy
        self._photos: list[ImageTk.PhotoImage] = []
        self._queue: queue.Queue = queue.Queue()
        self._pending = len(indices)
        self._workdir = Path(tempfile.mkdtemp(prefix="ft_preview_"))
        self._poll_job: str | None = None

        header = tk.Frame(self, bg=COLORS["bg"])
        header.pack(fill="x", padx=scale(16), pady=(scale(12), scale(6)))
        tk.Label(
            header, text="媒体预览", bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["title"]
        ).pack(side="left")
        tk.Label(
            header,
            text="视频显示各时间点缩略图（内置 ffmpeg 抽帧）；点击缩略图可放大",
            bg=COLORS["bg"], fg=COLORS["text_muted"], font=FONTS["small"],
        ).pack(side="left", padx=(scale(12), 0))

        container = tk.Frame(self, bg=COLORS["bg"])
        container.pack(fill="both", expand=True, padx=scale(16), pady=(0, scale(14)))
        self._canvas = tk.Canvas(container, bg=COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)
        self._inner = tk.Frame(self._canvas, bg=COLORS["bg"])
        self._inner_window = self._canvas.create_window((0, 0), window=self._inner, anchor="nw")
        self._inner.bind(
            "<Configure>",
            lambda _e: self._canvas.configure(scrollregion=self._canvas.bbox("all")),
        )
        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfigure(self._inner_window, width=e.width),
        )
        self._canvas.bind_all("<MouseWheel>", self._on_wheel)

        self._cards: dict[int, dict] = {}
        for slot, index in enumerate(indices):
            resource = resources[index]
            card = tk.Frame(
                self._inner,
                bg=COLORS["card"],
                highlightbackground=COLORS["card_border"],
                highlightthickness=1,
            )
            card.pack(fill="x", padx=scale(4), pady=scale(6))
            head = tk.Frame(card, bg=COLORS["card"])
            head.pack(fill="x", padx=scale(14), pady=(scale(10), scale(4)))
            meta = (
                f"#{index + 1} {resource.kind_text} · {resource.label or '—'} · "
                f"{resource.size_text} · {resource.suffix or '无后缀'}"
            )
            tk.Label(
                head, text=meta, bg=COLORS["card"], fg=COLORS["text"], font=FONTS["base"]
            ).pack(anchor="w")
            shown_url = resource.url if len(resource.url) <= 120 else resource.url[:117] + "…"
            url_label = tk.Label(
                head,
                text=shown_url,
                bg=COLORS["card"], fg=COLORS["text_muted"], font=FONTS["small"],
                anchor="w", justify="left", wraplength=scale(820),
            )
            url_label.pack(anchor="w", fill="x")
            body = tk.Frame(card, bg=COLORS["card"])
            body.pack(fill="x", padx=scale(14), pady=(scale(2), scale(12)))
            status = tk.Label(
                body, text="正在生成预览…", bg=COLORS["card"], fg=COLORS["text_muted"],
                font=FONTS["small"],
            )
            status.pack(anchor="w")
            self._cards[slot] = {"body": body, "status": status, "meta": head}
            threading.Thread(
                target=self._fetch, args=(slot, index), daemon=True
            ).start()

        self.protocol("WM_DELETE_WINDOW", self._close)
        self._poll_job = self.after(120, self._poll)

    # -------- 后台取帧 --------

    def _fetch(self, slot: int, index: int) -> None:
        from ..core.media_grab import (
            AUDIO_SUFFIXES,
            IMAGE_SUFFIXES,
            capture_preview_frames,
            fetch_media_bytes,
        )

        resource = self._resources[index]
        try:
            if resource.suffix in IMAGE_SUFFIXES:
                self._queue.put((slot, "image", fetch_media_bytes(resource)))
            elif resource.kind == "dash-audio" or resource.suffix in AUDIO_SUFFIXES:
                info, _duration, _frames = capture_preview_frames(
                    resource, count=0, workdir=self._workdir, tag=f"s{slot}",
                    proxy=self._proxy,
                )
                self._queue.put((slot, "audio", info))
            else:
                info, _duration, frames = capture_preview_frames(
                    resource, count=3, workdir=self._workdir, tag=f"s{slot}",
                    proxy=self._proxy,
                )
                self._queue.put((slot, "frames", info, frames))
        except Exception as exc:  # noqa: BLE001 - 预览失败在窗口内呈现
            self._queue.put((slot, "error", str(exc)))

    def _poll(self) -> None:
        try:
            while True:
                message = self._queue.get_nowait()
                self._render(*message)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._poll_job = self.after(120, self._poll)

    # -------- 渲染 --------

    def _render(self, slot: int, kind: str, payload, *extra) -> None:
        card = self._cards.get(slot)
        if card is None or not self.winfo_exists():
            return
        body, status = card["body"], card["status"]
        if kind == "error":
            status.config(text=f"预览失败：{payload}", fg=COLORS["log_error"])
            self._pending -= 1
            return
        if kind == "audio":
            status.config(text=f"音频流 · {payload}", fg=COLORS["text_muted"])
            self._pending -= 1
            return
        status.config(text=payload, fg=COLORS["text_muted"])
        row = tk.Frame(body, bg=COLORS["card"])
        row.pack(anchor="w", pady=(scale(4), 0))
        if kind == "image":
            photo = self._photo_from_bytes(payload, width=IMAGE_WIDTH)
            if photo is not None:
                label = tk.Label(row, image=photo, bg=COLORS["card"])
                label.image = photo  # type: ignore[attr-defined]
                self._photos.append(photo)
                label.pack(anchor="w")
        else:  # frames
            for path in extra[0]:
                photo = self._photo_from_file(path, width=THUMB_WIDTH)
                if photo is None:
                    continue
                label = tk.Label(row, image=photo, bg=COLORS["card"], cursor="hand2")
                label.image = photo  # type: ignore[attr-defined]
                self._photos.append(photo)
                label.pack(side="left", padx=(0, scale(10)))
                label.bind("<Button-1>", lambda _e, p=path: self._show_large(p))
        self._pending -= 1

    def _photo_from_file(self, path: Path, width: int):
        return self._photo_from_bytes(path.read_bytes(), width=width)

    def _photo_from_bytes(self, data: bytes, width: int):
        if Image is None:
            return None
        try:
            image = Image.open(BytesIO(data))
            image.load()
        except Exception:  # noqa: BLE001 - 无法解码的图片按失败呈现
            return None
        ratio = max(1.0, image.width / max(width * 1.0, 1))
        size = (width, max(1, int(image.height / ratio)))
        rendered = image.convert("RGB").resize(size, Image.LANCZOS)
        photo = ImageTk.PhotoImage(rendered)
        return photo

    def _show_large(self, path: Path) -> None:
        photo = self._photo_from_file(path, width=800)
        if photo is None:
            return
        window = tk.Toplevel(self)
        window.title("缩略图放大")
        window.configure(bg=COLORS["bg"])
        label = tk.Label(window, image=photo, bg=COLORS["bg"])
        label.image = photo  # type: ignore[attr-defined]
        self._photos.append(photo)
        label.pack(padx=scale(10), pady=scale(10))

    # -------- 杂项 --------

    def _on_wheel(self, event) -> None:
        self._canvas.yview_scroll(-1 * (event.delta // 120), "units")

    def _close(self) -> None:
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        shutil.rmtree(self._workdir, ignore_errors=True)
        self.destroy()
