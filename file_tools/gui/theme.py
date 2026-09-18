"""界面主题：DPI 感知、缩放、配色、字体与 ttk 样式。

`enable_dpi_awareness()` 必须在创建 Tk 根窗口之前调用，
否则窗口和系统文件对话框都会被系统按低分辨率拉伸，显示模糊。
"""

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

APP_NAME = "文件处理工具"
APP_VERSION = "2.1"

COLORS = {
    "bg": "#eef1f5",
    "sidebar": "#0f172a",
    "sidebar_hover": "#1e293b",
    "sidebar_text": "#c7d0dd",
    "sidebar_footer": "#475569",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_disabled": "#9ca3af",
    "card": "#ffffff",
    "card_border": "#d9dee7",
    "hover": "#f3f4f6",
    "text": "#1f2430",
    "text_muted": "#6b7280",
    "log_bg": "#0f172a",
    "log_fg": "#cbd5e1",
    "log_error": "#f87171",
    "log_success": "#4ade80",
    "log_title": "#93c5fd",
    "status_idle": "#059669",
    "status_busy": "#d97706",
    "status_fail": "#dc2626",
    "danger": "#dc2626",
}

FONTS: dict[str, tkfont.Font] = {}

_scale = 1.0


def scale(px: float) -> int:
    """按屏幕缩放比例换算设计像素，保证高分屏下间距和控件不变形。"""
    return max(1, round(px * _scale))


def enable_dpi_awareness() -> None:
    """声明进程 DPI 感知（仅 Windows），必须在创建 Tk 窗口前调用。"""
    if sys.platform != "win32":
        return
    import ctypes

    try:  # Windows 10 1703+：每显示器感知 V2
        handle = ctypes.c_void_p(-4)
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(handle):
            return
    except (AttributeError, OSError):
        pass
    try:  # Windows 8.1+：每显示器感知
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except (AttributeError, OSError):
        pass
    try:  # Windows Vista+：系统 DPI 感知
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def _pick_family(root: tk.Tk, candidates: list[str], fallback: str) -> str:
    families = set(tkfont.families(root))
    for name in candidates:
        if name in families:
            return name
    return fallback


def setup_theme(root: tk.Tk) -> None:
    """初始化缩放比例、字体与全局 ttk 样式，需在创建任何控件前调用。"""
    global _scale
    dpi = root.winfo_fpixels("1i")
    _scale = max(1.0, dpi / 96.0)
    root.tk.call("tk", "scaling", dpi / 72.0)

    ui = _pick_family(root, ["Microsoft YaHei UI", "Microsoft YaHei"], "TkDefaultFont")
    mono = _pick_family(root, ["Cascadia Mono", "Consolas"], "TkFixedFont")
    FONTS.update({
        "base": tkfont.Font(root=root, family=ui, size=9),
        "small": tkfont.Font(root=root, family=ui, size=8),
        "button": tkfont.Font(root=root, family=ui, size=9, weight="bold"),
        "section": tkfont.Font(root=root, family=ui, size=10, weight="bold"),
        "title": tkfont.Font(root=root, family=ui, size=15, weight="bold"),
        "nav": tkfont.Font(root=root, family=ui, size=10),
        "nav_active": tkfont.Font(root=root, family=ui, size=10, weight="bold"),
        "mono": tkfont.Font(root=root, family=mono, size=9),
    })

    style = ttk.Style(root)
    style.theme_use("clam")

    c = COLORS
    style.configure(".", background=c["bg"], foreground=c["text"], font=FONTS["base"])
    style.configure("TFrame", background=c["bg"])
    style.configure("Card.TFrame", background=c["card"])

    style.configure("TLabel", background=c["bg"], foreground=c["text"])
    style.configure("Title.TLabel", font=FONTS["title"], foreground=c["text"])
    style.configure("Subtitle.TLabel", font=FONTS["small"], foreground=c["text_muted"])
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"])
    style.configure("Section.TLabel", background=c["card"], font=FONTS["section"])
    style.configure(
        "Field.TLabel", background=c["card"], foreground=c["text_muted"]
    )
    style.map(
        "Field.TLabel",
        foreground=[("disabled", "#b6bcc7")],
    )
    style.configure(
        "Hint.TLabel", background=c["card"], foreground=c["text_muted"], font=FONTS["small"]
    )
    style.configure(
        "Danger.TLabel", background=c["card"], foreground=c["danger"], font=FONTS["small"]
    )

    style.configure(
        "TEntry",
        fieldbackground=c["card"],
        foreground=c["text"],
        bordercolor=c["card_border"],
        lightcolor=c["card_border"],
        darkcolor=c["card_border"],
        insertcolor=c["text"],
        padding=scale(5),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", c["accent"])],
        lightcolor=[("focus", c["accent"])],
        darkcolor=[("focus", c["accent"])],
        fieldbackground=[("disabled", "#f3f4f6")],
    )

    style.configure(
        "TCombobox",
        fieldbackground=c["card"],
        background=c["card"],
        foreground=c["text"],
        arrowcolor=c["text_muted"],
        bordercolor=c["card_border"],
        lightcolor=c["card_border"],
        darkcolor=c["card_border"],
        arrowsize=scale(13),
        padding=scale(5),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", c["card"])],
        bordercolor=[("focus", c["accent"])],
        lightcolor=[("focus", c["accent"])],
    )
    root.option_add("*TCombobox*Listbox.background", c["card"])
    root.option_add("*TCombobox*Listbox.foreground", c["text"])
    root.option_add("*TCombobox*Listbox.selectBackground", "#dbeafe")
    root.option_add("*TCombobox*Listbox.selectForeground", c["text"])
    root.option_add("*TCombobox*Listbox.font", FONTS["base"])

    style.configure(
        "Accent.TButton",
        background=c["accent"],
        foreground="#ffffff",
        borderwidth=0,
        relief="flat",
        focusthickness=scale(1),
        padding=(scale(20), scale(7)),
        font=FONTS["button"],
    )
    style.map(
        "Accent.TButton",
        background=[("disabled", c["accent_disabled"]), ("active", c["accent_hover"])],
        foreground=[("disabled", "#f3f4f6"), ("active", "#ffffff")],
        focuscolor=[("!disabled", "#bfdbfe")],
    )
    style.configure(
        "Ghost.TButton",
        background=c["card"],
        foreground=c["text_muted"],
        borderwidth=scale(1),
        relief="flat",
        bordercolor=c["card_border"],
        lightcolor=c["card_border"],
        darkcolor=c["card_border"],
        padding=(scale(10), scale(3)),
    )
    style.map(
        "Ghost.TButton",
        background=[("active", c["hover"])],
        foreground=[("active", c["text"])],
        lightcolor=[("active", c["card_border"])],
        darkcolor=[("active", c["card_border"])],
    )

    for name in ("Option.TCheckbutton", "Option.TRadiobutton"):
        style.configure(name, background=c["card"], foreground=c["text"], focuscolor=c["card"])
        style.map(
            name,
            background=[("active", c["card"])],
            foreground=[("disabled", "#b6bcc7")],
        )
    style.map(
        "Option.TCheckbutton",
        indicatorcolor=[("selected", c["accent"])],
    )
    style.map(
        "Option.TRadiobutton",
        indicatorcolor=[("selected", c["accent"])],
    )

    style.configure(
        "Slim.Horizontal.TProgressbar",
        troughcolor="#e5e7eb",
        background=c["accent"],
        lightcolor=c["accent"],
        darkcolor=c["accent"],
        bordercolor="#e5e7eb",
        thickness=scale(4),
    )
