"""图片批量下载视图。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import scale
from ..widgets import (
    Card,
    check_row,
    entry_row,
    form_label,
    path_row,
    run_button_row,
)
from .base import ToolView

LIST_FILETYPES = [
    ("链接列表", "*.csv *.txt"),
    ("所有文件", "*.*"),
]


class DownloadView(ToolView):
    ID = "download"
    TITLE = "图片批量下载"
    SUBTITLE = "从 CSV/TXT 链接列表（每行第一列）并发下载图片，自动补全扩展名。"
    RUN_TEXT = "开始下载"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)

        row = 0
        form_label(body, row, "链接列表")
        self.list_path = tk.StringVar()
        path_row(body, row, self.list_path, self._browse_list)

        row += 1
        form_label(body, row, "输出目录")
        self.output_dir = tk.StringVar()
        path_row(body, row, self.output_dir, self._browse_output)
        ttk.Label(
            body, text="留空使用 downloaded_images", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "并发数")
        self.concurrency = tk.StringVar(value="4")
        entry_row(body, row, self.concurrency)

        row += 1
        form_label(body, row, "选项")
        self.overwrite = tk.BooleanVar(value=False)
        check_row(body, row, [("覆盖已存在的同名文件", self.overwrite)])
        ttk.Label(
            body,
            text="同名文件自动追加序号；失败自动重试并继续下载后续链接",
            style="Hint.TLabel",
        ).grid(row=row, column=2, sticky="w")

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

    def _browse_list(self) -> None:
        path = filedialog.askopenfilename(title="选择链接列表", filetypes=LIST_FILETYPES)
        if path:
            self.list_path.set(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _run(self) -> None:
        list_path = self.list_path.get().strip().strip('"')
        if not list_path:
            messagebox.showwarning("缺少参数", "请先选择 CSV/TXT 链接列表。")
            return
        try:
            concurrency = int(self.concurrency.get().strip())
        except ValueError:
            concurrency = 0
        if concurrency <= 0:
            messagebox.showwarning("参数无效", "并发数必须是正整数。")
            return
        output_dir = self.output_dir.get().strip().strip('"') or "downloaded_images"
        overwrite = self.overwrite.get()

        def worker() -> str:
            from ...core.download_images import download_images

            summary = download_images(
                list_path, output_dir, concurrency=concurrency, overwrite=overwrite
            )
            return (
                f"下载完成: 共 {summary.total}，新增 {summary.downloaded}，"
                f"跳过 {summary.skipped}，失败 {summary.failed}，详见运行日志。"
            )

        self.app.submit("图片批量下载", self.run_button, worker)
