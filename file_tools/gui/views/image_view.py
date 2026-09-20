"""图像混淆/解混淆视图。"""

from pathlib import Path
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
    set_widgets_enabled,
)
from .base import ToolView

IMAGE_FILETYPES = [
    ("图片文件", "*.bmp *.gif *.jpeg *.jpg *.png *.tif *.tiff *.webp"),
    ("所有文件", "*.*"),
]

# 下拉框展示文案 -> 传给核心函数的模式编号
IMAGE_MODES = {
    "方块混淆": "1",
    "行像素混淆": "2",
    "像素混淆": "3",
    "PicEncrypt 行": "4",
    "PicEncrypt 行+列": "5",
}


class ImageView(ToolView):
    ID = "image"
    TITLE = "图像混淆 / 解混淆"
    SUBTITLE = "五种双向像素混淆模式，支持单文件与目录批量处理。"
    RUN_TEXT = "开始处理"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)
        # 标签列定宽：切换单文件/目录时标签文字变化不引起输入框左右移动
        body.columnconfigure(0, minsize=scale(96))

        row = 0
        form_label(body, row, "处理方向")
        self.operation = tk.StringVar(value="decrypt")
        radio_row(body, row, self.operation, [("解混淆", "decrypt"), ("混淆", "encrypt")])

        row += 1
        form_label(body, row, "模式")
        self.mode_box = ttk.Combobox(body, state="readonly", values=list(IMAGE_MODES), width=24)
        form_field(body, row, self.mode_box)
        self.mode_box.current(2)
        self.mode_box.bind("<<ComboboxSelected>>", lambda _event: self._update_key_hint())

        row += 1
        self.key_label = form_label(body, row, "密钥")
        self.key = tk.StringVar()
        entry_row(body, row, self.key)
        self._update_key_hint()

        row += 1
        form_label(body, row, "处理对象")
        self.input_kind = tk.StringVar(value="file")
        radio_row(body, row, self.input_kind, [("单个文件", "file"), ("整个目录", "dir")])
        self.input_kind.trace_add("write", lambda *_args: self._update_kind())

        row += 1
        self.input_label = form_label(body, row, "输入图片路径")
        self.input_path = tk.StringVar()
        path_row(body, row, self.input_path, self._browse_input)

        row += 1
        self.output_label = form_label(body, row, "输出图片路径")
        self.output_path = tk.StringVar()
        path_row(body, row, self.output_path, self._browse_output)

        row += 1
        self.suffix_label = form_label(body, row, "筛选后缀")
        self.suffix = tk.StringVar()
        self.suffix_entry = entry_row(body, row, self.suffix)

        row += 1
        form_label(body, row, "目录选项")
        self.recursive = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        self._dir_checks = check_row(
            body, row, [("递归子目录", self.recursive), ("覆盖已有输出", self.overwrite)]
        )

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

        self._dir_only_widgets = [self.suffix_label, self.suffix_entry, *self._dir_checks]
        self._update_kind()

    # -------- 浏览按钮与联动 --------

    def _browse_input(self) -> None:
        if self.input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择图片目录")
        else:
            path = filedialog.askopenfilename(title="选择图片", filetypes=IMAGE_FILETYPES)
        if path:
            self.input_path.set(path)

    def _browse_output(self) -> None:
        if self.input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择输出目录")
        else:
            source = Path(self.input_path.get().strip().strip('"'))
            suffix = source.suffix or ".png"
            options = {
                "title": "保存输出图片",
                "defaultextension": suffix,
                "filetypes": IMAGE_FILETYPES,
            }
            if source.stem:
                options["initialfile"] = f"{source.stem}_output{suffix}"
            path = filedialog.asksaveasfilename(**options)
        if path:
            self.output_path.set(path)

    def _update_key_hint(self) -> None:
        mode = IMAGE_MODES[self.mode_box.get()]
        self.key_label.config(
            text="密钥" if mode in {"1", "2", "3"} else "密钥（0~1）"
        )

    def _update_kind(self) -> None:
        is_dir = self.input_kind.get() == "dir"
        self.input_label.config(text="输入目录" if is_dir else "输入图片路径")
        self.output_label.config(text="输出目录" if is_dir else "输出图片路径")
        set_widgets_enabled(self._dir_only_widgets, is_dir)

    # -------- 执行 --------

    def _run(self) -> None:
        input_path = self.input_path.get().strip().strip('"')
        output_path = self.output_path.get().strip().strip('"')
        key = self.key.get().strip()
        mode = IMAGE_MODES[self.mode_box.get()]
        operation = self.operation.get()
        is_dir = self.input_kind.get() == "dir"

        if not input_path:
            self.app.notify("请先选择输入路径。", error=True)
            return
        if not output_path:
            self.app.notify("请先选择输出路径。", error=True)
            return
        if not key:
            self.app.notify("请输入密钥。", error=True)
            return
        if mode in {"4", "5"}:
            try:
                numeric_key = float(key)
            except ValueError:
                self.app.notify("PicEncrypt 模式的密钥必须是 0 到 1 之间的数字。", error=True)
                return
            if not 0 < numeric_key < 1:
                self.app.notify("PicEncrypt 模式的密钥必须大于 0 且小于 1。", error=True)
                return
        if is_dir and Path(input_path) == Path(output_path):
            self.app.notify("批量处理的输出目录不能与输入目录相同。", error=True)
            return

        action_name = "混淆" if operation == "encrypt" else "解混淆"
        title = f"图像{action_name}（{self.mode_box.get()}）"
        suffix_text = self.suffix.get().strip()
        recursive = self.recursive.get()
        overwrite = self.overwrite.get()

        def worker() -> str:
            from ...core.image_decrypt import normalize_suffixes, process_image, process_image_directory

            if is_dir:
                summary = process_image_directory(
                    operation,
                    mode,
                    input_path,
                    key,
                    output_path,
                    suffixes=normalize_suffixes([suffix_text.replace(" ", ",")]),
                    recursive=recursive,
                    overwrite=overwrite,
                )
                return (
                    f"批量{action_name}完成：成功 {summary.processed}，"
                    f"跳过 {summary.skipped}，失败 {summary.failed}。"
                )
            process_image(operation, mode, input_path, key, output_path)
            return f"已{action_name}并保存: {output_path}"

        self.app.submit(title, self.run_button, worker)
