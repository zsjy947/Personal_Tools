"""任务历史视图：所有 GUI 任务的只读留痕（时间/任务/结果/耗时/消息摘要）。"""

import tkinter as tk
from tkinter import messagebox, ttk

from ..theme import COLORS, FONTS, scale
from ..widgets import Card
from .base import ToolView


def _seconds_text(value) -> str:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return "—"
    if seconds >= 60:
        return f"{int(seconds // 60)}:{int(seconds % 60):02d}"
    return f"{seconds:.1f}s"


class HistoryView(ToolView):
    ID = "history"
    TITLE = "任务历史"
    NAV = "任务历史"
    SUBTITLE = (
        "所有 GUI 任务自动留痕（成功/失败、耗时、消息摘要），只读可查；"
        "双击行查看完整消息。记录保存在用户数据目录，不回传任何服务器。"
    )

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.rowconfigure(1, weight=1)
        body.columnconfigure(0, weight=1)

        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=0, column=0, sticky="ew", pady=(0, scale(8)))
        ttk.Label(
            actions, text="最近 200 条（新的在前）", style="Hint.TLabel"
        ).pack(side="left")
        ttk.Button(actions, text="清空历史", style="Ghost.TButton",
                   command=self._clear).pack(side="right")
        ttk.Button(actions, text="刷新", style="Ghost.TButton",
                   command=self._reload).pack(side="right", padx=(0, scale(8)))

        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=1, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("time", "task", "result", "elapsed", "message"),
            show="headings",
            selectmode="browse",
            height=12,
        )
        for cid, text, width, anchor, stretch in (
            ("time", "时间", scale(150), "w", False),
            ("task", "任务", scale(170), "w", False),
            ("result", "结果", scale(70), "center", False),
            ("elapsed", "耗时", scale(70), "e", False),
            ("message", "消息摘要", scale(320), "w", True),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, minwidth=scale(50),
                             anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.tag_configure("ok", foreground=COLORS["status_idle"])
        self.tree.tag_configure("fail", foreground=COLORS["status_fail"])
        self.tree.bind("<Double-1>", self._on_double_click)

        self._entries: list[dict] = []
        self._reload()

    def on_show(self) -> None:
        # 每次切入都重读：别的视图刚跑完的任务立即出现在历史里
        if self.frame is not None:
            self._reload()

    def _reload(self) -> None:
        from ...core.task_history import read_recent

        self._entries = read_recent(200)
        self.tree.delete(*self.tree.get_children())
        for entry in self._entries:
            ok = entry.get("status") == "ok"
            self.tree.insert(
                "", "end", tags=("ok" if ok else "fail",),
                values=(
                    entry.get("ts", "—"),
                    entry.get("title", "—"),
                    "成功" if ok else "失败",
                    _seconds_text(entry.get("seconds")),
                    entry.get("message", ""),
                ),
            )

    def _on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if not iid:
            return
        index = self.tree.index(iid)
        if index >= len(self._entries):
            return
        entry = self._entries[index]
        window = tk.Toplevel(self.frame)
        window.title(f"任务消息 — {entry.get('title', '')}")
        window.transient(self.frame)
        window.geometry(f"{scale(560)}x{scale(360)}")
        text = tk.Text(
            window, wrap="word", state="normal",
            bg=COLORS["log_bg"], fg=COLORS["log_fg"],
            insertbackground=COLORS["log_fg"],
            relief="flat", borderwidth=0,
            padx=scale(12), pady=scale(10), font=FONTS["mono"],
        )
        text.pack(fill="both", expand=True)
        text.insert(
            "1.0",
            f"时间: {entry.get('ts', '—')}\n"
            f"任务: {entry.get('title', '—')}\n"
            f"结果: {'成功' if entry.get('status') == 'ok' else '失败'}"
            f"（{_seconds_text(entry.get('seconds'))}）\n"
            f"---\n{entry.get('message', '')}\n",
        )
        text.config(state="disabled")

    def _clear(self) -> None:
        from ...core.task_history import clear

        if not messagebox.askyesno("清空历史", "确定删除全部任务历史记录？"):
            return
        clear()
        self._reload()
        self.app.notify("任务历史已清空。")
