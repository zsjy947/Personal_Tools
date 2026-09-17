""".1 后缀管理视图。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import scale
from ..widgets import Card, check_row, form_label, path_row, radio_row, run_button_row
from .base import ToolView


class Dot1View(ToolView):
    ID = "dot1"
    TITLE = ".1 后缀管理"
    SUBTITLE = "批量添加或移除文件名末尾的 .1 后缀，默认仅预览。"
    RUN_TEXT = "开始重命名"

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
        form_label(body, row, "操作")
        self.operation = tk.StringVar(value="add")
        radio_row(
            body, row, self.operation, [("添加 .1 后缀", "add"), ("移除 .1 后缀", "remove")]
        )

        row += 1
        form_label(body, row, "选项")
        self.recursive = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        check_row(body, row, [("递归子目录", self.recursive), ("仅预览", self.dry_run)])

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
        operation = self.operation.get()
        dry_run = self.dry_run.get()
        recursive = self.recursive.get()

        def worker() -> str:
            from ...core.dot1_suffix import rename_dot1_files

            summary = rename_dot1_files(target, operation, recursive=recursive, dry_run=dry_run)
            action = "计划重命名" if dry_run else "已重命名"
            return f"完成：{action} {summary.renamed}，跳过 {summary.skipped}，失败 {summary.failed}。"

        title = f"{'添加' if operation == 'add' else '移除'} .1 后缀" + (
            "（仅预览）" if dry_run else ""
        )
        self.app.submit(title, self.run_button, worker)
