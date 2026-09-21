"""图片格式转换视图：Pillow 批量重编码（webp/jpg/png/bmp 互转）。"""

import tkinter as tk
from tkinter import filedialog, ttk

from ..theme import scale
from ..widgets import (
    Card,
    check_row,
    entry_row,
    form_field,
    form_label,
    path_row,
    radio_row,
    run_button_row,
)
from .base import ToolView

FORMATS = [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp")]


class ConvertView(ToolView):
    ID = "convert"
    TITLE = "图片格式转换"
    SUBTITLE = (
        "批量转换图片格式（重编码，与「伪装媒体文件转 MP4」的无损封装不同）："
        "透明通道转 JPG 自动垫白底，动图取首帧，转换成功后可选删除原图。"
    )
    RUN_TEXT = "开始转换"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)

        row = 0
        form_label(body, row, "源路径")
        self.source = tk.StringVar()
        box = ttk.Frame(body, style="Card.TFrame")
        entry = ttk.Entry(box, textvariable=self.source)
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(box, text="浏览文件", style="Ghost.TButton", command=self._browse_file).pack(
            side="left", padx=(scale(8), 0)
        )
        ttk.Button(box, text="浏览目录", style="Ghost.TButton", command=self._browse_dir).pack(
            side="left", padx=(scale(8), 0)
        )
        form_field(body, row, box)

        row += 1
        form_label(body, row, "目标格式")
        self.target_format = tk.StringVar(value="jpg")
        radio_row(body, row, self.target_format, FORMATS)

        row += 1
        form_label(body, row, "质量")
        self.quality = tk.StringVar(value="90")
        entry_row(body, row, self.quality)
        ttk.Label(
            body, text="1-100，仅 JPG/WEBP 生效，留空用默认值", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "输出目录")
        self.output = tk.StringVar()
        path_row(body, row, self.output, self._browse_output)
        ttk.Label(body, text="留空保存在原图同目录", style="Hint.TLabel").grid(
            row=row, column=2, sticky="w"
        )

        row += 1
        form_label(body, row, "选项")
        self.delete_original = tk.BooleanVar(value=False)
        self.recursive = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        check_row(
            body,
            row,
            [
                ("转换成功后删除原图", self.delete_original),
                ("递归子目录", self.recursive),
                ("仅预览，不实际转换", self.dry_run),
            ],
        )

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

    def _browse_file(self) -> None:
        path = filedialog.askopenfilename(
            title="选择图片",
            filetypes=[
                ("图片", "*.jpg *.jpeg *.png *.webp *.bmp *.gif *.tif *.tiff"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.source.set(path)

    def _browse_dir(self) -> None:
        path = filedialog.askdirectory(title="选择图片目录")
        if path:
            self.source.set(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output.set(path)

    def _run(self) -> None:
        source = self.source.get().strip().strip('"')
        if not source:
            self.app.notify("请先选择源图片或目录。", error=True)
            return
        output = self.output.get().strip().strip('"')
        target_format = self.target_format.get()
        quality_value = self.quality.get().strip()
        quality: int | None = None
        if quality_value:
            try:
                quality = int(quality_value)
            except ValueError:
                self.app.notify("质量必须是 1-100 的数字。", error=True)
                return
        delete_original = self.delete_original.get()
        recursive = self.recursive.get()
        dry_run = self.dry_run.get()

        def worker() -> str:
            from ...core.image_convert import convert_images

            summary = convert_images(
                source,
                target_format,
                output_dir=output or None,
                quality=quality,
                delete_original=delete_original,
                recursive=recursive,
                dry_run=dry_run,
            )
            action = "预览转换" if dry_run else "转换"
            detail = f"{summary.converted}，跳过 {summary.skipped}，失败 {summary.failed}"
            return f"{action}完成: {detail}，详见运行日志。"

        title = "图片格式转换（" + target_format.upper() + "）"
        self.app.submit(title, self.run_button, worker)
