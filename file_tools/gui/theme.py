"""界面主题：DPI 感知、缩放、配色、字体与 ttk 样式。

`enable_dpi_awareness()` 必须在创建 Tk 根窗口之前调用，
否则窗口和系统文件对话框都会被系统按低分辨率拉伸，显示模糊。
"""

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

APP_NAME = "文件处理工具"
APP_VERSION = "2.3"

COLORS = {
    "bg": "#eef1f5",
    "sidebar": "#0f172a",
    "sidebar_hover": "#1e293b",
    "sidebar_text": "#c7d0dd",
    "sidebar_group": "#8394ac",
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
        "nav_group": tkfont.Font(root=root, family=ui, size=9, weight="bold"),
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
        background="#fbfcfe",
        foreground=c["text"],
        borderwidth=scale(1.5),
        relief="solid",
        bordercolor="#96a7bc",
        lightcolor="#96a7bc",
        darkcolor="#96a7bc",
        focusthickness=0,
        padding=(scale(12), scale(4)),
        font=FONTS["base"],
    )
    style.map(
        "Ghost.TButton",
        background=[("pressed", "#e6ecf4"), ("active", "#f1f5f9")],
        foreground=[("active", c["text"])],
        bordercolor=[("pressed", "#6f8299"), ("active", "#6f8299")],
        lightcolor=[("active", "#6f8299")],
        darkcolor=[("active", "#6f8299")],
    )

    for name in ("Option.TCheckbutton", "Option.TRadiobutton"):
        style.configure(name, background=c["card"], foreground=c["text"], focuscolor=c["card"])
        style.map(
            name,
            background=[("active", c["card"])],
            foreground=[("disabled", "#b6bcc7")],
        )
    _install_round_indicators(style)

    style.configure(
        "Slim.Horizontal.TProgressbar",
        troughcolor="#e5e7eb",
        background=c["accent"],
        lightcolor=c["accent"],
        darkcolor=c["accent"],
        bordercolor="#e5e7eb",
        thickness=scale(4),
    )


# -------- 圆形指示器（单选=圆圈圆点，复选=圆圈对勾） --------

_INDICATOR_IMAGES: list = []  # 持有 PhotoImage 引用，防止被垃圾回收


def _install_round_indicators(style: ttk.Style) -> None:
    """用 PIL 绘制的圆形指示图替换默认方框选中样式，提升观感一致性。"""
    try:
        from PIL import Image, ImageDraw, ImageTk
    except ImportError:
        return

    size = max(14, scale(17))
    ss = 4  # 超采样倍数，缩放后边缘平滑
    accent = COLORS["accent"]
    ring_off, ring_hover, ring_disabled = "#9aa6b6", accent, "#cfd6e0"
    dot_disabled = "#a8c0e8"

    def photo(painter) -> "ImageTk.PhotoImage":
        img = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
        painter(ImageDraw.Draw(img), size * ss)
        rendered = img.resize((size, size), Image.LANCZOS)
        return ImageTk.PhotoImage(rendered)

    def ring(draw, s, color, *, dot=False, check=False, fill=None):
        width = max(2, int(s * 0.085))
        margin = width + int(s * 0.05)
        draw.ellipse([margin, margin, s - margin, s - margin], outline=color, width=width)
        if fill:
            inner = width + int(s * 0.05)
            draw.ellipse([inner, inner, s - inner, s - inner], fill=fill)
        if dot:
            radius = (s - 2 * margin) * 0.30
            center = s / 2
            draw.ellipse(
                [center - radius, center - radius, center + radius, center + radius],
                fill=color,
            )
        if check:
            stroke = max(2, int(s * 0.10))
            draw.line(
                [(s * 0.30, s * 0.52), (s * 0.44, s * 0.66), (s * 0.71, s * 0.34)],
                fill=color,
                width=stroke,
                joint="curve",
            )

    def circle_painter(color, **kwargs):
        return lambda draw, s: ring(draw, s, color, **kwargs)

    # 圆圈圆点（单选）：选中态实心圆点，未选中仅圆圈
    states = {
        "off": photo(circle_painter(ring_off)),
        "hover": photo(circle_painter(ring_hover)),
        "on": photo(circle_painter(accent, dot=True)),
        "off_dis": photo(circle_painter(ring_disabled)),
        "on_dis": photo(circle_painter(dot_disabled, dot=True)),
    }
    # 圆圈对勾（复选）：选中带底色对勾，未选中仅圆圈
    check_states = {
        "off": photo(circle_painter(ring_off)),
        "hover": photo(circle_painter(ring_hover)),
        "on": photo(circle_painter(accent, fill="#eff6ff", check=True)),
        "off_dis": photo(circle_painter(ring_disabled)),
        "on_dis": photo(circle_painter(dot_disabled, fill="#eff6ff", check=True)),
    }
    _INDICATOR_IMAGES.extend(states.values())
    _INDICATOR_IMAGES.extend(check_states.values())

    # 状态按“第一个匹配生效”：selected 必须排在 active 之前，
    # 否则悬停已选中项时圆点/对勾会被悬停圈盖掉
    style.element_create(
        "FileTools.radio", "image", states["off"],
        ("disabled selected", states["on_dis"]),
        ("disabled", states["off_dis"]),
        ("selected", states["on"]),
        ("active", states["hover"]),
    )
    style.element_create(
        "FileTools.check", "image", check_states["off"],
        ("disabled selected", check_states["on_dis"]),
        ("disabled", check_states["off_dis"]),
        ("selected", check_states["on"]),
        ("active", check_states["hover"]),
    )
    style.layout(
        "Option.TRadiobutton",
        [
            ("Radiobutton.padding", {
                "children": [
                    ("FileTools.radio", {"side": "left", "sticky": ""}),
                    ("Radiobutton.focus", {
                        "children": [("Radiobutton.label", {"sticky": ""})],
                        "sticky": "",
                    }),
                ],
                "sticky": "we",
            }),
        ],
    )
    style.layout(
        "Option.TCheckbutton",
        [
            ("Checkbutton.padding", {
                "children": [
                    ("FileTools.check", {"side": "left", "sticky": ""}),
                    ("Checkbutton.focus", {
                        "children": [("Checkbutton.label", {"sticky": ""})],
                        "sticky": "",
                    }),
                ],
                "sticky": "we",
            }),
        ],
    )
    gap = scale(6)
    style.configure("Option.TRadiobutton", padding=(gap, scale(2)))
    style.configure("Option.TCheckbutton", padding=(gap, scale(2)))
