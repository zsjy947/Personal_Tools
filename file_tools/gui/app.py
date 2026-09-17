"""应用主窗口：侧边栏导航、内容区、日志面板与状态栏。"""

import io
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, scrolledtext, ttk

from .runner import POLL_INTERVAL_MS, TaskRunner
from .theme import (
    APP_NAME,
    APP_VERSION,
    COLORS,
    FONTS,
    enable_dpi_awareness,
    scale,
    setup_theme,
)
from .views import VIEW_CLASSES
from .widgets import Card, NavItem, round_rect

MAX_LOG_LINES = 3000

ERROR_PREFIXES = ("错误", "处理失败", "转换失败", "删除失败", "重命名失败", "Traceback")
SUCCESS_PREFIXES = ("成功", "完成", "已保存", "文件已保存", "跳过")


def _classify_line(line: str) -> str:
    text = line.strip()
    if text.startswith("====="):
        return "title"
    if text.startswith(ERROR_PREFIXES):
        return "error"
    if text.startswith(SUCCESS_PREFIXES):
        return "success"
    return ""


def _icon_path() -> Path | None:
    if getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
        candidates = [base / "assets" / "app.ico", Path(sys.executable).parent / "app.ico"]
    else:
        candidates = [Path(__file__).resolve().parent / "assets" / "app.ico"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


class App:
    """承载侧边栏、各工具视图、日志面板与状态栏的主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.views = {cls.ID: cls(self) for cls in VIEW_CLASSES}
        self._nav_items: dict[str, NavItem] = {}
        self._run_buttons: list[ttk.Button] = []

        root.title(APP_NAME)
        root.minsize(scale(920), scale(660))
        root.configure(bg=COLORS["bg"])
        self._apply_window_icon()

        self.runner = TaskRunner(self._append_log)
        self._build_status_bar()
        main = tk.Frame(root, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)
        self._build_sidebar(main)
        self._build_body(main)

        self.show_view(VIEW_CLASSES[0].ID)
        self._set_status(COLORS["status_idle"], "就绪")
        self._center_window(scale(1020), scale(680))
        self.root.after(POLL_INTERVAL_MS, self._poll)

    # -------- 窗口骨架 --------

    def _build_status_bar(self) -> None:
        bar = tk.Frame(
            self.root,
            bg=COLORS["card"],
            highlightbackground=COLORS["card_border"],
            highlightthickness=1,
        )
        bar.pack(side="bottom", fill="x")
        self._status_dot = tk.Label(
            bar, text="●", bg=COLORS["card"], fg=COLORS["status_idle"], font=FONTS["small"]
        )
        self._status_dot.pack(side="left", padx=(scale(14), scale(6)), pady=scale(6))
        self._status_label = tk.Label(
            bar,
            text="就绪",
            bg=COLORS["card"],
            fg=COLORS["text_muted"],
            font=FONTS["small"],
            anchor="w",
        )
        self._status_label.pack(side="left")
        self._progress = ttk.Progressbar(
            bar, mode="indeterminate", style="Slim.Horizontal.TProgressbar", length=scale(140)
        )

    def _build_sidebar(self, parent) -> None:
        bar = tk.Frame(parent, bg=COLORS["sidebar"], width=scale(216))
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)

        header = tk.Frame(bar, bg=COLORS["sidebar"])
        header.pack(fill="x", padx=scale(16), pady=(scale(18), scale(14)))
        logo = tk.Canvas(
            header,
            width=scale(38),
            height=scale(38),
            bg=COLORS["sidebar"],
            highlightthickness=0,
        )
        round_rect(
            logo,
            1,
            1,
            scale(38) - 1,
            scale(38) - 1,
            scale(10),
            fill=COLORS["accent"],
            outline="",
        )
        logo.create_text(
            scale(38) / 2 + 1, scale(38) / 2 + 1, text="文", fill="#ffffff", font=FONTS["title"]
        )
        logo.pack(side="left")
        titles = tk.Frame(header, bg=COLORS["sidebar"])
        titles.pack(side="left", padx=(scale(10), 0))
        tk.Label(
            titles, text=APP_NAME, bg=COLORS["sidebar"], fg="#f8fafc", font=FONTS["section"]
        ).pack(anchor="w")
        tk.Label(
            titles, text="File Tools", bg=COLORS["sidebar"], fg=COLORS["sidebar_footer"],
            font=FONTS["small"],
        ).pack(anchor="w")

        tk.Frame(bar, bg=COLORS["sidebar_hover"], height=1).pack(
            fill="x", padx=scale(12), pady=(0, scale(10))
        )

        nav_host = tk.Frame(bar, bg=COLORS["sidebar"])
        nav_host.pack(fill="x", padx=scale(10))
        for cls in VIEW_CLASSES:
            item = NavItem(nav_host, cls.TITLE, lambda vid=cls.ID: self.show_view(vid))
            item.pack(fill="x", pady=scale(1))
            self._nav_items[cls.ID] = item

        tk.Label(
            bar,
            text=f"v{APP_VERSION} · 本地运行",
            bg=COLORS["sidebar"],
            fg=COLORS["sidebar_footer"],
            font=FONTS["small"],
        ).pack(side="bottom", pady=scale(12))

    def _build_body(self, parent) -> None:
        body = tk.Frame(parent, bg=COLORS["bg"])
        body.pack(side="left", fill="both", expand=True, padx=scale(16), pady=scale(12))

        pane = tk.PanedWindow(
            body,
            orient="vertical",
            bg=COLORS["bg"],
            sashwidth=scale(6),
            sashrelief="flat",
            opaqueresize=True,
            bd=0,
        )
        pane.pack(fill="both", expand=True)

        content = tk.Frame(pane, bg=COLORS["bg"])
        header = tk.Frame(content, bg=COLORS["bg"])
        header.pack(fill="x", pady=(0, scale(10)))
        self._header_title = ttk.Label(header, text="", style="Title.TLabel")
        self._header_title.pack(anchor="w")
        self._header_subtitle = ttk.Label(header, text="", style="Subtitle.TLabel")
        self._header_subtitle.pack(anchor="w", pady=(scale(2), 0))
        self._view_host = tk.Frame(content, bg=COLORS["bg"])
        self._view_host.pack(fill="both", expand=True)
        pane.add(content, minsize=scale(360), stretch="always")

        self._build_log_card(pane)

    def _build_log_card(self, pane) -> None:
        card = Card(pane)
        header = ttk.Frame(card, style="Card.TFrame")
        header.pack(fill="x", padx=scale(14), pady=(scale(10), scale(6)))
        ttk.Label(header, text="运行日志", style="Section.TLabel").pack(side="left")
        self._autoscroll = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            header, text="自动滚动", variable=self._autoscroll, style="Option.TCheckbutton"
        ).pack(side="right", padx=(scale(12), 0))
        ttk.Button(
            header, text="复制", style="Ghost.TButton", command=self._copy_log
        ).pack(side="right")
        ttk.Button(
            header, text="清空", style="Ghost.TButton", command=self._clear_log
        ).pack(side="right", padx=(scale(8), 0))

        self.log_text = scrolledtext.ScrolledText(
            card,
            wrap="word",
            state="disabled",
            bg=COLORS["log_bg"],
            fg=COLORS["log_fg"],
            insertbackground=COLORS["log_fg"],
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
            selectbackground="#334155",
            font=FONTS["mono"],
            height=7,
            padx=scale(12),
            pady=scale(8),
        )
        self.log_text.pack(fill="both", expand=True, padx=scale(10), pady=(0, scale(10)))
        for tag, color in (
            ("error", COLORS["log_error"]),
            ("success", COLORS["log_success"]),
            ("title", COLORS["log_title"]),
        ):
            self.log_text.tag_configure(tag, foreground=color)
        pane.add(card, minsize=scale(180), stretch="never")

    # -------- 视图切换与任务 --------

    def show_view(self, view_id: str) -> None:
        for view in self.views.values():
            if view.frame is not None:
                view.frame.pack_forget()
        view = self.views[view_id]
        if view.frame is None:
            view.build(self._view_host)
        view.frame.pack(fill="both", expand=True)
        self._header_title.config(text=view.TITLE)
        self._header_subtitle.config(text=view.SUBTITLE)
        for vid, item in self._nav_items.items():
            item.set_active(vid == view_id)

    def register_run_button(self, button: ttk.Button) -> None:
        self._run_buttons.append(button)

    def submit(self, title: str, button: ttk.Button, worker) -> None:
        if not self.runner.submit(title, worker):
            messagebox.showinfo("提示", "已有任务在执行，请等待其完成。")
            return
        for run_button in self._run_buttons:
            run_button.state(["disabled"])
        self._progress.pack(side="right", padx=scale(14), pady=scale(8))
        self._progress.start(16)
        self._set_status(COLORS["status_busy"], f"正在执行：{title}…")

    def _poll(self) -> None:
        result = self.runner.poll()
        if result is not None:
            self._finish_task(*result)
        self.root.after(POLL_INTERVAL_MS, self._poll)

    def _finish_task(self, message: str, succeeded: bool) -> None:
        for run_button in self._run_buttons:
            run_button.state(["!disabled"])
        self._progress.stop()
        self._progress.pack_forget()
        self._append_log(f"\n{message}\n", tag="success" if succeeded else "error")
        summary = (message or "").splitlines()[0]
        if succeeded:
            self._set_status(COLORS["status_idle"], summary or "任务完成")
            messagebox.showinfo("完成", message or "任务执行完成，详见运行日志。")
        else:
            self._set_status(COLORS["status_fail"], summary or "执行失败")
            messagebox.showerror("执行失败", message)

    def _set_status(self, color: str, text: str) -> None:
        self._status_dot.config(fg=color)
        self._status_label.config(text=text)

    # -------- 日志区 --------

    def _append_log(self, text: str, tag: str | None = None) -> None:
        self.log_text.config(state="normal")
        if tag:
            self.log_text.insert("end", text, tag)
        else:
            for line in text.splitlines(keepends=True):
                self.log_text.insert("end", line, _classify_line(line))
        end_line = int(self.log_text.index("end-1c").split(".")[0])
        if end_line > MAX_LOG_LINES:
            self.log_text.delete("1.0", f"{end_line - MAX_LOG_LINES}.0")
        if self._autoscroll.get():
            self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _copy_log(self) -> None:
        content = self.log_text.get("1.0", "end").strip()
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self._set_status(COLORS["status_idle"], "日志已复制到剪贴板")

    # -------- 杂项 --------

    def _apply_window_icon(self) -> None:
        icon = _icon_path()
        if icon is not None:
            try:
                self.root.iconbitmap(str(icon))
            except tk.TclError:
                pass

    def _center_window(self, width: int, height: int) -> None:
        self.root.update_idletasks()
        x = max(0, (self.root.winfo_screenwidth() - width) // 2)
        y = max(0, (self.root.winfo_screenheight() - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")


def _ensure_streams() -> None:
    # 窗口版 exe 中 sys.stdout/stderr 为 None，补空实现避免 print 触发异常
    if sys.stdout is None:
        sys.stdout = io.StringIO()
    if sys.stderr is None:
        sys.stderr = io.StringIO()


def main() -> int:
    enable_dpi_awareness()
    _ensure_streams()
    root = tk.Tk()
    setup_theme(root)
    App(root)
    root.mainloop()
    return 0
