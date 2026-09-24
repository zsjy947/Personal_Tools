"""图片批量重命名视图：源文件/文件夹收集到「输出目录/统一名称」下连续编号。"""

import tkinter as tk
from tkinter import filedialog, ttk

from ..theme import COLORS, FONTS, scale
from ..widgets import (
    Card,
    check_row,
    entry_row,
    form_label,
    path_row,
    run_button_row,
)
from .base import ToolView


class RenameView(ToolView):
    ID = "rename"
    TITLE = "图片批量重命名"
    NAV = "批量重命名"
    SUBTITLE = (
        "把选中的图片或整个文件夹移动到「输出目录/统一名称」下，按 名称-1、名称-2… 连续编号"
        "（保留原后缀，编号不重复）；目标已有编号自动续接，支持多文件夹合并与追加。"
    )
    RUN_TEXT = "开始处理"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)

        row = 0
        form_label(body, row, "源路径")
        self.tree = ttk.Treeview(
            body,
            style="Rename.Treeview",
            columns=("path",),
            show="headings",
            selectmode="extended",
            height=6,
        )
        self.tree.heading("path", text="源文件 / 文件夹（按此顺序编号，双击行移除）")
        self.tree.column("path", width=scale(460), anchor="w", stretch=True)
        self.tree.grid(row=row, column=1, sticky="new", pady=scale(7))

        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=row, column=2, sticky="n", padx=(scale(8), 0), pady=scale(7))
        ttk.Button(
            buttons, text="添加文件夹", style="Ghost.TButton", command=self._add_folder
        ).pack(fill="x")
        ttk.Button(
            buttons, text="添加图片", style="Ghost.TButton", command=self._add_files
        ).pack(fill="x", pady=(scale(6), 0))
        ttk.Button(
            buttons, text="移除选中", style="Ghost.TButton", command=self._remove_selected
        ).pack(fill="x", pady=(scale(6), 0))
        ttk.Button(
            buttons, text="清空列表", style="Ghost.TButton", command=self._clear
        ).pack(fill="x", pady=(scale(6), 0))
        self.tree.bind("<Double-1>", lambda _event: self._remove_selected())

        row += 1
        form_label(body, row, "输出目录")
        self.output = tk.StringVar()
        path_row(body, row, self.output, self._browse_output)

        row += 1
        form_label(body, row, "统一名称")
        self.name = tk.StringVar()
        entry_row(body, row, self.name)
        ttk.Label(
            body,
            text="图片移动到 输出目录/统一名称/，重命名为 名称-1、名称-2…",
            style="Hint.TLabel",
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "选项")
        self.recursive = tk.BooleanVar(value=False)
        self.dry_run = tk.BooleanVar(value=True)
        check_row(
            body,
            row,
            [("文件夹含子目录一并收集", self.recursive), ("仅预览，不实际移动", self.dry_run)],
        )

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)
        self._configure_tree_style()

    def _configure_tree_style(self) -> None:
        """与资源表格同款观感；自行配置一次，首次打开本视图即生效。"""
        style = ttk.Style(self.tree)
        style.configure(
            "Rename.Treeview",
            background=COLORS["card"],
            fieldbackground=COLORS["card"],
            foreground=COLORS["text"],
            rowheight=scale(26),
            font=FONTS["base"],
            bordercolor=COLORS["card_border"],
            borderwidth=scale(1),
        )
        style.configure(
            "Rename.Treeview.Heading",
            background="#f1f5f9",
            foreground=COLORS["text_muted"],
            font=FONTS["small"],
            relief="flat",
        )
        style.map(
            "Rename.Treeview",
            background=[("selected", "#dbeafe")],
            foreground=[("selected", COLORS["text"])],
        )

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="选择源文件夹")
        if path:
            self.tree.insert("", "end", values=(path,))

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=[("图片", "*.jpg *.jpeg *.png"), ("所有文件", "*.*")],
        )
        for path in paths:
            self.tree.insert("", "end", values=(path,))

    def _remove_selected(self) -> None:
        self.tree.delete(*self.tree.selection())

    def _clear(self) -> None:
        self.tree.delete(*self.tree.get_children())

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output.set(path)

    def _sources(self) -> list[str]:
        return [self.tree.item(item, "values")[0] for item in self.tree.get_children()]

    def _run(self) -> None:
        sources = self._sources()
        output = self.output.get().strip().strip('"')
        name = self.name.get()
        if not sources:
            self.app.notify("请先添加至少一个源文件或文件夹。", error=True)
            return
        if not output:
            self.app.notify("请先选择输出目录。", error=True)
            return
        if not name.strip():
            self.app.notify("请先填写统一名称。", error=True)
            return
        recursive = self.recursive.get()
        dry_run = self.dry_run.get()

        def worker() -> str:
            from ...core.image_rename import rename_images

            summary = rename_images(
                sources, output, name, recursive=recursive, dry_run=dry_run
            )
            action = "预览移动" if dry_run else "移动"
            detail = f"{summary.moved}，跳过 {summary.skipped}，失败 {summary.failed}"
            return f"{action}完成: {detail}，详见运行日志。"

        title = "图片批量重命名" + ("（预览）" if dry_run else "")
        self.app.submit(title, self.run_button, worker)
