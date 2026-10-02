"""重复图片清理视图：dHash 扫描预览 → 勾选确认 → 移入回收子文件夹（可逆）。"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..theme import scale
from ..widgets import Card, check_row, form_label, path_row, run_button_row
from .base import ToolView

CHECKED, UNCHECKED = "☑", "☐"


class DedupeView(ToolView):
    ID = "dedupe"
    TITLE = "重复图片清理"
    NAV = "重复清理"
    SUBTITLE = (
        "dHash 感知哈希找视觉重复图（同内容不同字节/重采样转存都能命中），"
        "每组保留分辨率最大的一张；候选移入「重复图片_回收」子文件夹，"
        "绝不直接删除，误判可自行搬回。"
    )
    RUN_TEXT = "扫描重复图片"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)
        body.rowconfigure(3, weight=1)

        row = 0
        form_label(body, row, "扫描目录")
        self.source = tk.StringVar()
        path_row(body, row, self.source, self._browse)
        ttk.Label(
            body, text="默认使用 Downloads", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "选项")
        self.recursive = tk.BooleanVar(value=False)
        check_row(body, row, [("递归子目录（回收文件夹本身不会重复进入）", self.recursive)])

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)

        row += 1
        header = ttk.Frame(body, style="Card.TFrame")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(scale(14), scale(6)))
        ttk.Label(header, text="扫描结果", style="Section.TLabel").pack(side="left")
        self.result_hint = ttk.Label(header, text="尚未扫描", style="Hint.TLabel")
        self.result_hint.pack(side="left", padx=(scale(10), 0))
        ttk.Label(
            header, text="点击“选择”列勾选候选（默认全选，正本不可勾）",
            style="Hint.TLabel",
        ).pack(side="right")
        self.move_button = ttk.Button(
            header, text="移入回收", style="Accent.TButton", command=self._move_checked
        )
        self.move_button.pack(side="right", padx=(0, scale(12)))
        self.app.register_run_button(self.move_button)

        row += 1
        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=row, column=0, columnspan=3, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("sel", "group", "keeper", "candidate", "distance"),
            show="headings",
            selectmode="none",
            height=10,
        )
        for cid, text, width, anchor, stretch in (
            ("sel", "选择", scale(44), "center", False),
            ("group", "组号", scale(50), "center", False),
            ("keeper", "保留正本", scale(230), "w", True),
            ("candidate", "重复候选", scale(230), "w", True),
            ("distance", "相似距离", scale(70), "e", False),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, minwidth=scale(40),
                             anchor=anchor, stretch=stretch)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Button-1>", self._on_click)
        body.rowconfigure(row, weight=1)

        self._groups: list = []
        self._checked: set[int] = set()  # 候选在展平列表中的下标

    # -------- 表单与交互 --------

    def _browse(self) -> None:
        path = filedialog.askdirectory(title="选择扫描目录")
        if path:
            self.source.set(path)

    def _on_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if iid and column == "#1":
            index = int(iid)
            if index in self._checked:
                self._checked.discard(index)
                self.tree.set(iid, "sel", UNCHECKED)
            else:
                self._checked.add(index)
                self.tree.set(iid, "sel", CHECKED)

    # -------- 扫描与移动 --------

    def _run(self) -> None:
        source = (
            self.source.get().strip().strip('"') or str(Path.home() / "Downloads")
        )
        if not Path(source).is_dir():
            self.app.notify("请先选择存在的扫描目录。", error=True)
            return
        recursive = self.recursive.get()

        def worker() -> str:
            from ...core.dedupe_images import scan

            groups = scan(source, recursive=recursive)
            self._groups = groups
            total = sum(len(group.candidates) for group in groups)
            return f"扫描完成：{len(groups)} 组重复，共 {total} 张候选图片。"

        def on_done(message: str, succeeded: bool) -> None:
            if succeeded:
                self._fill_tree()

        title = "重复图片扫描"
        self.app.submit(title, self.run_button, worker, on_done=on_done)

    def _fill_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._checked.clear()
        flat_index = 0
        for group_number, group in enumerate(self._groups, 1):
            for candidate in group.candidates:
                self.tree.insert(
                    "", "end", iid=str(flat_index),
                    values=(
                        CHECKED, f"第{group_number}组",
                        str(group.keeper), str(candidate), f"{group.distance}/64",
                    ),
                )
                self._checked.add(flat_index)
                flat_index += 1
        total = flat_index
        self.result_hint.config(
            text=f"{len(self._groups)} 组 · {total} 张候选" if self._groups else "未发现重复"
        )

    def _move_checked(self) -> None:
        if not self._groups:
            self.app.notify("请先扫描出重复分组。")
            return
        if not self._checked:
            self.app.notify("请先勾选要移入回收的候选图片。")
            return
        groups = self._groups
        checked = set(self._checked)

        def worker() -> str:
            from ...core.dedupe_images import move_duplicates

            # 仅移动被勾选的候选：按展平顺序取子集
            flat = [candidate for group in groups for candidate in group.candidates]
            only = {flat[index] for index in checked}
            summary = move_duplicates(groups, only=only, log_cb=print)
            return (
                f"移入回收完成：{summary['moved']} 张"
                + (f"，失败 {len(summary['failed'])}" if summary["failed"] else "")
                + "。误判可从「重复图片_回收」文件夹搬回。"
            )

        def on_done(message: str, succeeded: bool) -> None:
            if succeeded:
                self._run()  # 重新扫描刷新分组

        self.app.submit("重复图片移入回收", self.move_button, worker, on_done=on_done)
