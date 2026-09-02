"""文件处理工具的可视化界面。

基于标准库 tkinter 实现，所有路径均通过系统资源管理器对话框选择。
工具模块在执行任务时才导入：即使缺少第三方依赖，界面仍能打开，
仅对应工具在执行时报错提示。
"""

import queue
import sys
import threading
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


IMAGE_FILETYPES = [
    ("图片文件", "*.bmp *.gif *.jpeg *.jpg *.png *.tif *.tiff *.webp"),
    ("所有文件", "*.*"),
]

# 下拉框展示文案 -> 传给核心函数的模式编号
IMAGE_MODES = {
    "1 方块": "1",
    "2 行像素": "2",
    "3 像素": "3",
    "4 PicEncrypt 行": "4",
    "5 PicEncrypt 行+列": "5",
}


def _add_label(parent, row: int, text: str) -> ttk.Label:
    widget = ttk.Label(parent, text=text)
    widget.grid(row=row, column=0, sticky="e", padx=(8, 4), pady=4)
    return widget


def _add_path_row(parent, row: int, var, browse_command) -> ttk.Entry:
    entry = ttk.Entry(parent, textvariable=var)
    entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
    button = ttk.Button(parent, text="浏览...", width=8, command=browse_command)
    button.grid(row=row, column=2, padx=(4, 8), pady=4)
    return entry


class _QueueWriter:
    """把 print 输出转发到线程安全队列，由主线程刷入日志区。"""

    def __init__(self, log_queue: queue.Queue) -> None:
        self._queue = log_queue

    def write(self, text: str) -> None:
        if text:
            self._queue.put(text)

    def flush(self) -> None:
        pass


class FileToolsGUI:
    """承载各文件处理工具标签页的主窗口。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.log_queue: queue.Queue = queue.Queue()
        self.result_queue: queue.Queue = queue.Queue()
        self.writer = _QueueWriter(self.log_queue)
        self.busy = False

        root.title("文件处理工具")
        root.minsize(640, 560)

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(8, 4))

        self._build_image_tab()
        self._build_media_tab()
        self._build_dot1_tab()
        self._build_copy_tab()
        self._build_log_area()

        self.root.after(100, self._poll_events)

    # -------- 窗口构建 --------

    def _build_image_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="图像混淆/解混淆")
        frame.columnconfigure(1, weight=1)

        row = 0
        _add_label(frame, row, "操作")
        ops = ttk.Frame(frame)
        ops.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.image_operation = tk.StringVar(value="decrypt")
        ttk.Radiobutton(ops, text="解混淆", variable=self.image_operation, value="decrypt").pack(side="left")
        ttk.Radiobutton(ops, text="混淆", variable=self.image_operation, value="encrypt").pack(side="left", padx=(12, 0))

        row += 1
        _add_label(frame, row, "模式")
        self.image_mode_box = ttk.Combobox(frame, state="readonly", values=list(IMAGE_MODES), width=22)
        self.image_mode_box.current(2)
        self.image_mode_box.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.image_mode_box.bind("<<ComboboxSelected>>", lambda _event: self._update_key_hint())

        row += 1
        self.image_key_label = _add_label(frame, row, "密钥（任意字符串）")
        self.image_key = tk.StringVar()
        ttk.Entry(frame, textvariable=self.image_key).grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        row += 1
        _add_label(frame, row, "处理对象")
        kinds = ttk.Frame(frame)
        kinds.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.image_input_kind = tk.StringVar(value="file")
        ttk.Radiobutton(
            kinds, text="单个文件", variable=self.image_input_kind, value="file"
        ).pack(side="left")
        ttk.Radiobutton(
            kinds, text="整个目录", variable=self.image_input_kind, value="dir"
        ).pack(side="left", padx=(12, 0))
        self.image_input_kind.trace_add("write", lambda *_args: self._update_image_kind())

        row += 1
        self.image_input_label = _add_label(frame, row, "输入图片路径")
        self.image_input = tk.StringVar()
        _add_path_row(frame, row, self.image_input, self._browse_image_input)

        row += 1
        self.image_output_label = _add_label(frame, row, "输出图片路径（含扩展名）")
        self.image_output = tk.StringVar()
        _add_path_row(frame, row, self.image_output, self._browse_image_output)

        row += 1
        self.image_suffix_label = _add_label(frame, row, "筛选后缀（留空=常见格式）")
        self.image_suffix = tk.StringVar()
        self.image_suffix_entry = ttk.Entry(frame, textvariable=self.image_suffix)
        self.image_suffix_entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4)

        row += 1
        _add_label(frame, row, "目录选项")
        dir_opts = ttk.Frame(frame)
        dir_opts.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.image_recursive = tk.BooleanVar(value=False)
        self.image_recursive_check = ttk.Checkbutton(
            dir_opts, text="递归子目录", variable=self.image_recursive
        )
        self.image_recursive_check.pack(side="left")
        self.image_overwrite = tk.BooleanVar(value=False)
        self.image_overwrite_check = ttk.Checkbutton(
            dir_opts, text="覆盖已有输出", variable=self.image_overwrite
        )
        self.image_overwrite_check.pack(side="left", padx=(12, 0))

        row += 1
        self.image_run_button = ttk.Button(frame, text="执 行", command=self._run_image)
        self.image_run_button.grid(row=row, column=1, sticky="w", padx=4, pady=(12, 4))

        self._update_image_kind()

    def _build_media_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="伪装媒体转 MP4")
        frame.columnconfigure(1, weight=1)

        row = 0
        _add_label(frame, row, "处理对象")
        kinds = ttk.Frame(frame)
        kinds.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.media_input_kind = tk.StringVar(value="file")
        ttk.Radiobutton(
            kinds, text="单个文件", variable=self.media_input_kind, value="file"
        ).pack(side="left")
        ttk.Radiobutton(
            kinds, text="整个目录", variable=self.media_input_kind, value="dir"
        ).pack(side="left", padx=(12, 0))
        self.media_input_kind.trace_add("write", lambda *_args: self._update_media_kind())

        row += 1
        self.media_input_label = _add_label(frame, row, "输入文件路径")
        self.media_input = tk.StringVar()
        _add_path_row(frame, row, self.media_input, self._browse_media_input)

        row += 1
        self.media_suffix_label = _add_label(frame, row, "筛选后缀（必填，空格或逗号分隔）")
        self.media_suffix = tk.StringVar()
        self.media_suffix_entry = ttk.Entry(frame, textvariable=self.media_suffix)
        self.media_suffix_entry.grid(row=row, column=1, sticky="ew", padx=4, pady=4)
        self.media_recursive = tk.BooleanVar(value=False)
        self.media_recursive_check = ttk.Checkbutton(
            frame, text="递归子目录", variable=self.media_recursive
        )
        self.media_recursive_check.grid(row=row, column=2, padx=(4, 8), pady=4)

        row += 1
        _add_label(frame, row, "输出目录（留空=源文件目录）")
        self.media_output_dir = tk.StringVar()
        _add_path_row(frame, row, self.media_output_dir, self._browse_media_output)

        row += 1
        _add_label(frame, row, "选项")
        opts = ttk.Frame(frame)
        opts.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.media_overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="覆盖已有 MP4", variable=self.media_overwrite).pack(side="left")
        self.media_dry_run = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="仅预览，不调用 ffmpeg", variable=self.media_dry_run).pack(
            side="left", padx=(12, 0)
        )

        row += 1
        self.media_run_button = ttk.Button(frame, text="执 行", command=self._run_media)
        self.media_run_button.grid(row=row, column=1, sticky="w", padx=4, pady=(12, 4))

        self._update_media_kind()

    def _build_dot1_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text=".1 后缀")
        frame.columnconfigure(1, weight=1)

        row = 0
        _add_label(frame, row, "目标目录")
        self.dot1_target = tk.StringVar()
        _add_path_row(frame, row, self.dot1_target, self._browse_dot1)

        row += 1
        _add_label(frame, row, "操作")
        ops = ttk.Frame(frame)
        ops.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.dot1_operation = tk.StringVar(value="add")
        ttk.Radiobutton(ops, text="添加 .1 后缀", variable=self.dot1_operation, value="add").pack(side="left")
        ttk.Radiobutton(
            ops, text="移除 .1 后缀", variable=self.dot1_operation, value="remove"
        ).pack(side="left", padx=(12, 0))

        row += 1
        _add_label(frame, row, "选项")
        opts = ttk.Frame(frame)
        opts.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.dot1_recursive = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="递归子目录", variable=self.dot1_recursive).pack(side="left")
        self.dot1_dry_run = tk.BooleanVar(value=True)
        ttk.Checkbutton(opts, text="仅预览，不重命名", variable=self.dot1_dry_run).pack(
            side="left", padx=(12, 0)
        )

        row += 1
        self.dot1_run_button = ttk.Button(frame, text="执 行", command=self._run_dot1)
        self.dot1_run_button.grid(row=row, column=1, sticky="w", padx=4, pady=(12, 4))

    def _build_copy_tab(self) -> None:
        frame = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(frame, text="删除“副本”文件")
        frame.columnconfigure(1, weight=1)

        row = 0
        _add_label(frame, row, "目标目录")
        self.copy_target = tk.StringVar()
        _add_path_row(frame, row, self.copy_target, self._browse_copy)

        row += 1
        _add_label(frame, row, "执行方式")
        modes = ttk.Frame(frame)
        modes.grid(row=row, column=1, sticky="w", padx=4, pady=4)
        self.copy_execute = tk.BooleanVar(value=False)
        ttk.Radiobutton(
            modes, text="仅预览", variable=self.copy_execute, value=False
        ).pack(side="left")
        ttk.Radiobutton(
            modes, text="实际删除", variable=self.copy_execute, value=True
        ).pack(side="left", padx=(12, 0))

        row += 1
        self.copy_run_button = ttk.Button(frame, text="执 行", command=self._run_copy)
        self.copy_run_button.grid(row=row, column=1, sticky="w", padx=4, pady=(12, 4))

    def _build_log_area(self) -> None:
        frame = ttk.LabelFrame(self.root, text="运行日志")
        frame.pack(fill="x", padx=8, pady=(0, 8))
        bar = ttk.Frame(frame)
        bar.pack(fill="x", padx=4, pady=(4, 0))
        ttk.Button(bar, text="清空日志", width=10, command=self._clear_log).pack(side="right")
        self.log_text = scrolledtext.ScrolledText(frame, height=9, wrap="word", state="disabled")
        self.log_text.pack(fill="x", padx=4, pady=4)

    # -------- 浏览按钮 --------

    def _browse_image_input(self) -> None:
        if self.image_input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择图片目录")
        else:
            path = filedialog.askopenfilename(title="选择图片", filetypes=IMAGE_FILETYPES)
        if path:
            self.image_input.set(path)

    def _browse_image_output(self) -> None:
        if self.image_input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择输出目录")
        else:
            input_path = Path(self.image_input.get().strip().strip('"'))
            suffix = input_path.suffix or ".png"
            options = {
                "title": "保存输出图片",
                "defaultextension": suffix,
                "filetypes": IMAGE_FILETYPES,
            }
            if input_path.stem:
                options["initialfile"] = f"{input_path.stem}_output{suffix}"
            path = filedialog.asksaveasfilename(**options)
        if path:
            self.image_output.set(path)

    def _browse_media_input(self) -> None:
        if self.media_input_kind.get() == "dir":
            path = filedialog.askdirectory(title="选择媒体目录")
        else:
            path = filedialog.askopenfilename(title="选择媒体文件")
        if path:
            self.media_input.set(path)

    def _browse_media_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.media_output_dir.set(path)

    def _browse_dot1(self) -> None:
        path = filedialog.askdirectory(title="选择目标目录")
        if path:
            self.dot1_target.set(path)

    def _browse_copy(self) -> None:
        path = filedialog.askdirectory(title="选择目标目录")
        if path:
            self.copy_target.set(path)

    # -------- 联动状态 --------

    def _update_key_hint(self) -> None:
        mode = IMAGE_MODES[self.image_mode_box.get()]
        self.image_key_label.config(
            text="密钥（任意字符串）" if mode in {"1", "2", "3"} else "密钥（0 到 1 之间的数字）"
        )

    def _update_image_kind(self) -> None:
        is_dir = self.image_input_kind.get() == "dir"
        self.image_input_label.config(text="输入目录" if is_dir else "输入图片路径")
        self.image_output_label.config(text="输出目录" if is_dir else "输出图片路径（含扩展名）")
        state = "normal" if is_dir else "disabled"
        for widget in (
            self.image_suffix_label,
            self.image_suffix_entry,
            self.image_recursive_check,
            self.image_overwrite_check,
        ):
            widget.config(state=state)

    def _update_media_kind(self) -> None:
        is_dir = self.media_input_kind.get() == "dir"
        self.media_input_label.config(text="输入目录" if is_dir else "输入文件路径")
        state = "normal" if is_dir else "disabled"
        for widget in (self.media_suffix_label, self.media_suffix_entry, self.media_recursive_check):
            widget.config(state=state)

    # -------- 日志与任务调度 --------

    def _poll_events(self) -> None:
        chunks = []
        try:
            while True:
                chunks.append(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        if chunks:
            self.log_text.config(state="normal")
            self.log_text.insert("end", "".join(chunks))
            self.log_text.see("end")
            self.log_text.config(state="disabled")

        try:
            button, message, succeeded = self.result_queue.get_nowait()
        except queue.Empty:
            pass
        else:
            if succeeded:
                self._task_done(button, message)
            else:
                self._task_failed(button, message)

        self.root.after(100, self._poll_events)

    def _clear_log(self) -> None:
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _start_task(self, title: str, button: ttk.Button, worker) -> None:
        if self.busy:
            messagebox.showinfo("提示", "已有任务在执行，请等待其完成。")
            return
        self.busy = True
        button.config(state="disabled")
        self.log_queue.put(f"\n===== {title} =====\n")

        def runner() -> None:
            try:
                with redirect_stdout(self.writer), redirect_stderr(self.writer):
                    message = worker()
            except (
                FileNotFoundError,
                NotADirectoryError,
                OSError,
                RuntimeError,
                ValueError,
            ) as exc:
                self.result_queue.put((button, f"错误: {exc}", False))
            except Exception:
                self.log_queue.put(traceback.format_exc())
                self.result_queue.put((button, "发生意外错误，详见运行日志。", False))
            else:
                self.result_queue.put((button, message, True))

        threading.Thread(target=runner, daemon=True).start()

    def _task_done(self, button: ttk.Button, message: str) -> None:
        self.busy = False
        button.config(state="normal")
        messagebox.showinfo("完成", message or "任务执行完成，详见运行日志。")

    def _task_failed(self, button: ttk.Button, message: str) -> None:
        self.busy = False
        button.config(state="normal")
        messagebox.showerror("执行失败", message)

    # -------- 各工具执行入口 --------

    def _run_image(self) -> None:
        input_path = self.image_input.get().strip().strip('"')
        output_path = self.image_output.get().strip().strip('"')
        key = self.image_key.get().strip()
        mode = IMAGE_MODES[self.image_mode_box.get()]
        operation = self.image_operation.get()
        is_dir = self.image_input_kind.get() == "dir"

        if not input_path:
            messagebox.showwarning("缺少参数", "请先选择输入路径。")
            return
        if not output_path:
            messagebox.showwarning("缺少参数", "请先选择输出路径。")
            return
        if not key:
            messagebox.showwarning("缺少参数", "请输入密钥。")
            return
        if mode in {"4", "5"}:
            try:
                numeric_key = float(key)
            except ValueError:
                messagebox.showwarning("密钥无效", "模式 4 和 5 的密钥必须是 0 到 1 之间的数字。")
                return
            if not 0 < numeric_key < 1:
                messagebox.showwarning("密钥无效", "模式 4 和 5 的密钥必须大于 0 且小于 1。")
                return
        if is_dir and Path(input_path) == Path(output_path):
            messagebox.showwarning("参数无效", "批量处理的输出目录不能与输入目录相同。")
            return

        action_name = "混淆" if operation == "encrypt" else "解混淆"
        title = f"图像{action_name}（模式 {mode}）"
        suffix_text = self.image_suffix.get().strip()
        recursive = self.image_recursive.get()
        overwrite = self.image_overwrite.get()

        def worker() -> str:
            from .image_decrypt import normalize_suffixes, process_image, process_image_directory

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

        self._start_task(title, self.image_run_button, worker)

    def _run_media(self) -> None:
        source = self.media_input.get().strip().strip('"')
        is_dir = self.media_input_kind.get() == "dir"
        suffix_text = self.media_suffix.get().strip()
        output_dir = self.media_output_dir.get().strip().strip('"')
        dry_run = self.media_dry_run.get()

        if not source:
            messagebox.showwarning("缺少参数", "请先选择输入路径。")
            return
        if is_dir and not suffix_text:
            messagebox.showwarning("缺少参数", "目录模式必须填写筛选后缀，例如 jpeg ts woff2。")
            return
        recursive = self.media_recursive.get()
        overwrite = self.media_overwrite.get()

        def worker() -> str:
            from .media_to_mp4 import convert_media, normalize_suffixes

            summary = convert_media(
                source,
                normalize_suffixes([suffix_text.replace(" ", ",")]) if is_dir else set(),
                recursive=recursive if is_dir else False,
                output_dir=Path(output_dir) if output_dir else None,
                overwrite=overwrite,
                dry_run=dry_run,
            )
            action = "预览完成" if dry_run else "转换完成"
            return f"{action}：成功 {summary.converted}，跳过 {summary.skipped}，失败 {summary.failed}。"

        title = "伪装媒体转 MP4" + ("（仅预览）" if dry_run else "")
        self._start_task(title, self.media_run_button, worker)

    def _run_dot1(self) -> None:
        target = self.dot1_target.get().strip().strip('"')
        if not target:
            messagebox.showwarning("缺少参数", "请先选择目标目录。")
            return
        operation = self.dot1_operation.get()
        dry_run = self.dot1_dry_run.get()
        recursive = self.dot1_recursive.get()

        def worker() -> str:
            from .dot1_suffix import rename_dot1_files

            summary = rename_dot1_files(
                target,
                operation,
                recursive=recursive,
                dry_run=dry_run,
            )
            action = "计划重命名" if dry_run else "已重命名"
            return f"完成：{action} {summary.renamed}，跳过 {summary.skipped}，失败 {summary.failed}。"

        title = f"{'添加' if operation == 'add' else '移除'} .1 后缀" + ("（仅预览）" if dry_run else "")
        self._start_task(title, self.dot1_run_button, worker)

    def _run_copy(self) -> None:
        target = self.copy_target.get().strip().strip('"')
        if not target:
            messagebox.showwarning("缺少参数", "请先选择目标目录。")
            return
        execute = self.copy_execute.get()
        if execute and not messagebox.askyesno(
            "确认删除",
            "将实际删除所有文件名以“副本”结尾的文件，且不可恢复。\n确认继续？",
        ):
            return

        def worker() -> str:
            from .delete_copy_files import delete_copy_files

            summary = delete_copy_files(target, execute=execute)
            if execute:
                return f"完成：匹配 {summary.matched}，删除 {summary.deleted}，失败 {summary.failed}。"
            return f"预览完成：匹配 {summary.matched} 个文件；选择“实际删除”后执行。"

        title = "删除“副本”文件" + ("（实际删除）" if execute else "（仅预览）")
        self._start_task(title, self.copy_run_button, worker)


def main() -> int:
    root = tk.Tk()
    FileToolsGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
