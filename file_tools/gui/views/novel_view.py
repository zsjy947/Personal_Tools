"""番茄小说搜索下载视图（仅供学习研究，请尊重作者版权）。"""

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..theme import scale
from ..widgets import Card, entry_row, form_label, path_row, radio_row, run_button_row
from .base import ToolView


class NovelView(ToolView):
    ID = "novel"
    TITLE = "番茄小说下载"
    SUBTITLE = (
        "按书名搜索或粘贴书籍 ID/链接，下载为 TXT/EPUB（内置官方 API 后端，正文为明文）；"
        "仅供学习研究，请尊重作者版权。"
    )
    RUN_TEXT = "开始下载"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)
        body.columnconfigure(0, minsize=scale(96))

        row = 0
        form_label(body, row, "书名/链接")
        search_box = ttk.Frame(body, style="Card.TFrame")
        self.keyword = tk.StringVar()
        self.keyword_entry = ttk.Entry(search_box, textvariable=self.keyword)
        self.keyword_entry.pack(side="left", fill="x", expand=True)
        self.search_button = ttk.Button(
            search_box, text="搜索", style="Accent.TButton", command=self._search
        )
        self.search_button.pack(side="left", padx=(scale(10), 0))
        search_box.grid(row=row, column=1, sticky="ew", pady=scale(7))
        ttk.Label(
            body, text="支持书名关键词或 fanqienovel.com 链接/书籍 ID",
            style="Hint.TLabel",
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "搜索结果")
        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=row, column=1, columnspan=2, sticky="nsew", pady=scale(7))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("title", "author", "words", "book_id"),
            show="headings",
            selectmode="browse",
            height=5,
        )
        for cid, text, width, anchor in (
            ("title", "书名", scale(200), "w"),
            ("author", "作者", scale(110), "w"),
            ("words", "字数", scale(80), "e"),
            ("book_id", "书籍 ID", scale(150), "w"),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, minwidth=scale(50), anchor=anchor)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.bind("<Double-1>", lambda _e: self._use_selected())
        self.result_hint = ttk.Label(body, text="尚未搜索", style="Hint.TLabel")
        self.result_hint.grid(row=row, column=2, sticky="nw")

        row += 1
        form_label(body, row, "输出目录")
        self.output_dir = tk.StringVar()
        path_row(body, row, self.output_dir, self._browse_output)
        ttk.Label(
            body, text="留空使用 novel_downloads", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "格式")
        self.fmt = tk.StringVar(value="txt")
        radio_row(body, row, self.fmt, [("TXT", "txt"), ("EPUB", "epub")])

        row += 1
        form_label(body, row, "章节范围")
        self.chapter_range = tk.StringVar()
        entry_row(body, row, self.chapter_range)
        ttk.Label(
            body, text="如 1-100 或 5；留空下载全部", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        self.run_button = run_button_row(body, row, self.RUN_TEXT, self._run)
        self.app.register_run_button(self.run_button)
        self.app.register_run_button(self.search_button)
        self._books: list = []

    # -------- 交互 --------

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _search(self) -> None:
        keyword = self.keyword.get().strip().strip('"')
        if not keyword:
            messagebox.showwarning("缺少参数", "请先输入书名或链接。")
            return

        def worker() -> str:
            from ...core.fanqie_novel import fetch_book, re_search_id, search_books

            match = re_search_id(keyword)
            if match:
                books = [fetch_book(match)]
            else:
                books = search_books(keyword)
            self._books = books
            print(f"搜索到 {len(books)} 本书籍")
            for number, book in enumerate(books, 1):
                words = f"{book.word_count}字" if book.word_count else "—"
                print(f"  [{number}] {book.title} | {book.author} | {words} | id={book.book_id}")
            if not books:
                return "没有搜索到结果。"
            return f"搜索完成：共 {len(books)} 本，双击结果行可选中。"

        def on_done(message: str, succeeded: bool) -> None:
            if not succeeded:
                return
            self.tree.delete(*self.tree.get_children())
            for book in getattr(self, "_books", []):
                self.tree.insert(
                    "", "end",
                    values=(book.title, book.author, book.word_count or "—", book.book_id),
                )
            self.result_hint.config(text=f"共 {len(getattr(self, '_books', []))} 本")

        self.app.submit("搜索番茄小说", self.search_button, worker, on_done=on_done)

    def _use_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        values = self.tree.item(selected[0], "values")
        if values:
            self.keyword.set(str(values[3]))

    # -------- 下载 --------

    def _run(self) -> None:
        keyword = self.keyword.get().strip().strip('"')
        if not keyword:
            messagebox.showwarning("缺少参数", "请先输入书名、链接或书籍 ID。")
            return
        from ...core.fanqie_novel import re_search_id

        book_id = re_search_id(keyword)
        if not book_id:
            selected = self.tree.selection()
            if selected:
                values = self.tree.item(selected[0], "values")
                book_id = str(values[3])
            else:
                messagebox.showwarning("未选择", "请先搜索并双击选择一本书，或直接粘贴链接/ID。")
                return
        output_dir = self.output_dir.get().strip().strip('"') or "novel_downloads"
        fmt = self.fmt.get()
        chapter_range = self.chapter_range.get().strip()

        def worker() -> str:
            from ...core.fanqie_novel import download_novel

            def progress(done: int, total: int, title: str) -> None:
                print(f"[{done}/{total}] {title}")

            summary = download_novel(
                book_id, output_dir,
                fmt=fmt, chapter_range=chapter_range,
                on_progress=progress,
            )
            failed = f"，失败 {summary.failed}" if summary.failed else ""
            return (
                f"下载完成：{summary.downloaded}/{summary.total} 章{failed}，"
                f"保存至 {summary.output}。"
            )

        self.app.submit("下载番茄小说", self.run_button, worker)
