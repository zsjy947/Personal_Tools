"""文件名标记/后缀管理视图（合并原 .1 后缀与删除副本工具）。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import scale
from ..widgets import (
    Card,
    check_row,
    entry_row,
    form_label,
    path_row,
    radio_row,
    run_button_row,
)
from .base import ToolView

OPERATIONS = [("添加标记", "add"), ("移除标记", "remove"), ("删除匹配文件", "delete")]


class SuffixView(ToolView):
    ID = "suffix"
    TITLE = "文件名标记管理"
    SUBTITLE = "按自定义标记（如 .1、副本）批量添加/移除文件名标记，或删除带标记的文件。"
    RUN_TEXT = "开始处理"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)

        row = 0
        form_label(body, row, "目标目录")
        self.target = tk.StringVar()
        path_row(body, row, self.target, self._browse_target)

        row += 1
        form_label(body, row, "文件名标记")
        self.marker = tk.StringVar(value=".1")
        entry_row(body, row, self.marker)
        ttk.Label(
            body,
            text="如 .1 或 副本；点开头的加在文件名末尾，文字标记加在扩展名前",
            style="Hint.TLabel",
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "操作")
        self.operation = tk.StringVar(value="add")
        radio_row(body, row, self.operation, OPERATIONS)

        row += 1
        form_label(body, row, "选项")
        self.recursive = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        check_row(
            body,
            row,
            [("递归处理子目录", self.recursive), ("仅预览，不实际执行", self.dry_run)],
        )

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

    def _browse_target(self) -> None:
        path = filedialog.askdirectory(title="选择目标目录")
        if path:
            self.target.set(path)

    def _run(self) -> None:
        target = self.target.get().strip().strip('"')
        if not target:
            messagebox.showwarning("缺少参数", "请先选择目标目录。")
            return
        marker = self.marker.get()
        operation = self.operation.get()
        recursive = self.recursive.get()
        dry_run = self.dry_run.get()

        def worker() -> str:
            from ...core.suffix_manager import manage_suffix

            summary = manage_suffix(
                target, marker, operation, recursive=recursive, dry_run=dry_run
            )
            if operation == "delete":
                action = "预览删除" if dry_run else "删除文件"
                detail = f"匹配 {summary.matched}，删除 {summary.deleted}，失败 {summary.failed}"
            else:
                action = "预览重命名" if dry_run else "重命名"
                detail = f"{summary.renamed}，跳过 {summary.skipped}，失败 {summary.failed}"
            return f"{action}完成: {detail}，详见运行日志。"

        title = "文件名标记管理（" + dict((v, k) for k, v in OPERATIONS)[operation] + "）"
        self.app.submit(title, self.run_button, worker)
