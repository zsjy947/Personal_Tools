"""视频无损转 MP4 视图：只换容器、不重编码。"""

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


class MediaView(ToolView):
    ID = "media"
    TITLE = "视频无损转 MP4"
    NAV = "无损转 MP4"
    SUBTITLE = "把真实内容为视频的文件无损封装为 MP4（只换容器不重编码，ffmpeg 已内置，全程无外部窗口）。"
    RUN_TEXT = "开始转换"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)
        # 标签列定宽：切换单文件/目录时标签文字变化不引起输入框左右移动
        body.columnconfigure(0, minsize=scale(96))

        row = 0
        form_label(body, row, "处理对象")
        self.input_kind = tk.StringVar(value="file")
        radio_row(body, row, self.input_kind, [("单个文件", "file"), ("整个目录", "dir")])
        self.input_kind.trace_add("write", lambda *_args: self._update_kind())

        row += 1
        self.input_label = form_label(body, row, "输入文件路径")
        self.source = tk.StringVar()
        path_row(body, row, self.source, self._browse_input)

        row += 1
        self.suffix_label = form_label(body, row, "筛选后缀")
        self.suffix = tk.StringVar()
        self.suffix_entry = entry_row(body, row, self.suffix)

        row += 1
        form_label(body, row, "输出目录")
        self.output_dir = tk.StringVar()
        path_row(body, row, self.output_dir, self._browse_output)
        ttk.Label(
            body, text="留空表示保存到源文件所在目录", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "选项")
        self.recursive = tk.BooleanVar(value=False)
        self.overwrite = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=False)
        checks = check_row(
            body,
            row,
            [
                ("递归子目录", self.recursive),
                ("覆盖已有 MP4", self.overwrite),
                ("仅预览", self.dry_run),
            ],
        )
        self._dir_checks = [checks[0]]

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

        self._dir_only_widgets = [self.suffix_label, self.suffix_entry, *self._dir_checks]
        self._update_kind()

    # -------- 浏览按钮与联动 --------

    def _browse_input(self) -> None:
        if self.input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择媒体目录")
        else:
            path = filedialog.askopenfilename(title="选择媒体文件")
        if path:
            self.source.set(path)

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _update_kind(self) -> None:
        is_dir = self.input_kind.get() == "dir"
        self.input_label.config(text="输入目录" if is_dir else "输入文件路径")
        set_widgets_enabled(self._dir_only_widgets, is_dir)

    # -------- 执行 --------

    def _run(self) -> None:
        source = self.source.get().strip().strip('"')
        is_dir = self.input_kind.get() == "dir"
        suffix_text = self.suffix.get().strip()
        output_dir = self.output_dir.get().strip().strip('"')
        dry_run = self.dry_run.get()

        if not source:
            self.app.notify("请先选择输入路径。", error=True)
            return
        if is_dir and not suffix_text:
            self.app.notify("目录模式必须填写筛选后缀，例如 jpeg ts woff2。", error=True)
            return
        recursive = self.recursive.get()
        overwrite = self.overwrite.get()

        def worker() -> str:
            from ...core.common import normalize_suffixes
            from ...core.media_to_mp4 import convert_media

            summary = convert_media(
                source,
                normalize_suffixes([suffix_text]) if is_dir else set(),
                recursive=recursive if is_dir else False,
                output_dir=Path(output_dir) if output_dir else None,
                overwrite=overwrite,
                dry_run=dry_run,
            )
            action = "预览完成" if dry_run else "转换完成"
            return f"{action}：成功 {summary.converted}，跳过 {summary.skipped}，失败 {summary.failed}。"

        title = "视频无损转 MP4" + ("（仅预览）" if dry_run else "")
        self.app.submit(title, self.run_button, worker)
