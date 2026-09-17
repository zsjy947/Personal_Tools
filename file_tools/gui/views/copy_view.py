"""删除“副本”文件视图。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import scale
from ..widgets import Card, form_label, path_row, radio_row, run_button_row
from .base import ToolView


class CopyView(ToolView):
    ID = "copy"
    TITLE = "删除“副本”文件"
    SUBTITLE = "递归查找文件名以“副本”结尾的文件，默认仅预览。"
    RUN_TEXT = "开始执行"

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
        form_label(body, row, "执行方式")
        self.execute = tk.BooleanVar(value=False)
        radio_row(body, row, self.execute, [("仅预览", False), ("实际删除", True)])

        row += 1
        ttk.Label(
            body, text="实际删除不可恢复，请谨慎操作", style="Danger.TLabel"
        ).grid(row=row, column=1, sticky="w", pady=(scale(2), 0))

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
        execute = self.execute.get()
        if execute and not messagebox.askyesno(
            "确认删除",
            "将实际删除所有文件名以“副本”结尾的文件，且不可恢复。\n确认继续？",
        ):
            return

        def worker() -> str:
            from ...core.delete_copy_files import delete_copy_files

            summary = delete_copy_files(target, execute=execute)
            if execute:
                return f"完成：匹配 {summary.matched}，删除 {summary.deleted}，失败 {summary.failed}。"
            return f"预览完成：匹配 {summary.matched} 个文件；选择“实际删除”后执行。"

        title = "删除“副本”文件" + ("（实际删除）" if execute else "（仅预览）")
        self.app.submit(title, self.run_button, worker)
