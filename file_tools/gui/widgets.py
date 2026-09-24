"""界面通用控件：卡片容器、侧边栏导航项与表单构建辅助。"""

import tkinter as tk
from tkinter import ttk

from .theme import COLORS, FONTS, scale


class Card(tk.Frame):
    """白色卡片容器，带 1 物理像素描边。"""

    def __init__(self, parent, **kwargs):
        super().__init__(
            parent,
            bg=COLORS["card"],
            highlightbackground=COLORS["card_border"],
            highlightthickness=scale(1),
            **kwargs,
        )


def round_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs):
    """在 Canvas 上绘制平滑圆角矩形。"""
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1,
        x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2,
        x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, **kwargs)


class NavItem(tk.Frame):
    """侧边栏导航项：悬停高亮，选中项以左侧强调条 + 加粗白字标识。"""

    def __init__(self, parent, text: str, command):
        super().__init__(parent, bg=COLORS["sidebar"], cursor="hand2")
        self._command = command
        self._active = False
        self._bar = tk.Frame(self, width=scale(3), bg=COLORS["sidebar"])
        self._bar.pack(side="left", fill="y")
        self._label = tk.Label(
            self,
            text=text,
            bg=COLORS["sidebar"],
            fg=COLORS["sidebar_text"],
            font=FONTS["nav"],
            anchor="w",
            padx=scale(11),
            pady=scale(9),
        )
        self._label.pack(side="left", fill="both", expand=True)
        for widget in (self, self._label):
            widget.bind("<Button-1>", lambda _event: self._command())
            widget.bind("<Enter>", lambda _event: self._hover(True))
            widget.bind("<Leave>", lambda _event: self._hover(False))

    def _hover(self, on: bool) -> None:
        if self._active:
            return
        bg = COLORS["sidebar_hover"] if on else COLORS["sidebar"]
        fg = "#f1f5f9" if on else COLORS["sidebar_text"]
        self._paint(bg, fg, FONTS["nav"])

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self._paint(COLORS["sidebar_hover"], "#ffffff", FONTS["nav_active"])
        else:
            self._paint(COLORS["sidebar"], COLORS["sidebar_text"], FONTS["nav"])

    def _paint(self, bg: str, fg: str, font) -> None:
        self.config(bg=bg)
        self._label.config(bg=bg, fg=fg, font=font)
        self._bar.config(bg=COLORS["accent"] if self._active else bg)


# -------- 表单构建辅助：label 列 + 控件列的两栏布局 --------

def form_label(parent, row: int, text: str, column: int = 0) -> ttk.Label:
    label = ttk.Label(parent, text=text, style="Field.TLabel")
    label.grid(row=row, column=column, sticky="wns", padx=(0, scale(10)))
    return label


def form_field(parent, row: int, widget, column: int = 1, columnspan: int = 1):
    widget.grid(
        row=row,
        column=column,
        columnspan=columnspan,
        sticky="ew",
        pady=scale(7),
    )
    return widget


def entry_row(parent, row: int, var) -> ttk.Entry:
    entry = ttk.Entry(parent, textvariable=var)
    form_field(parent, row, entry)
    return entry


def path_row(parent, row: int, var, browse_command) -> ttk.Frame:
    box = ttk.Frame(parent, style="Card.TFrame")
    entry = ttk.Entry(box, textvariable=var)
    entry.pack(side="left", fill="x", expand=True)
    button = ttk.Button(box, text="浏览", style="Ghost.TButton", command=browse_command)
    button.pack(side="left", padx=(scale(8), 0))
    form_field(parent, row, box)
    return box


def radio_row(parent, row: int, variable, options: list[tuple[str, str]]) -> list[ttk.Radiobutton]:
    box = ttk.Frame(parent, style="Card.TFrame")
    widgets = []
    for index, (text, value) in enumerate(options):
        button = ttk.Radiobutton(
            box, text=text, value=value, variable=variable, style="Option.TRadiobutton"
        )
        button.pack(side="left", padx=(0 if index == 0 else scale(22), 0))
        widgets.append(button)
    form_field(parent, row, box)
    return widgets


def check_row(parent, row: int, options: list[tuple[str, object]]) -> list[ttk.Checkbutton]:
    box = ttk.Frame(parent, style="Card.TFrame")
    widgets = []
    for index, (text, variable) in enumerate(options):
        button = ttk.Checkbutton(
            box, text=text, variable=variable, style="Option.TCheckbutton"
        )
        button.pack(side="left", padx=(0 if index == 0 else scale(20), 0))
        widgets.append(button)
    form_field(parent, row, box)
    return widgets


def run_button_row(parent, row: int, text: str, command) -> ttk.Button:
    bar = ttk.Frame(parent, style="Card.TFrame")
    button = ttk.Button(bar, text=text, style="Accent.TButton", command=command)
    button.pack(side="right")
    bar.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(scale(20), 0))
    return button


def set_widgets_enabled(widgets, enabled: bool) -> None:
    """统一切换 ttk 控件的可用状态。"""
    state = "!disabled" if enabled else "disabled"
    for widget in widgets:
        try:
            widget.state([state])
        except tk.TclError:
            pass
