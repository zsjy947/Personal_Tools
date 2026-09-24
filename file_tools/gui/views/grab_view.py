"""网页媒体嗅探下载视图：双模式嗅探 + 资源列表 + 预览 + 勾选下载（参考猫抓交互）。"""

import threading
import tkinter as tk
from tkinter import filedialog, ttk

from ..theme import COLORS, FONTS, scale
from ..widgets import Card, check_row, form_label, path_row, radio_row
from .base import ToolView

CHECKED, UNCHECKED = "☑", "☐"

MODE_DIRECT = "direct"
MODE_BROWSER = "browser"


class GrabView(ToolView):
    ID = "grab"
    TITLE = "网页媒体下载"
    NAV = "网页下载"
    SUBTITLE = (
        "嗅探网页中的视频/音频资源（对齐猫抓识别范围，支持 B 站 DASH 音视频合流）。"
        "直连模式直接请求页面；浏览器模式打开本机浏览器播放视频并捕获地址，"
        "适合被网络阻断或反爬的站点。"
    )
    RUN_TEXT = "下载选中"

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(1, weight=1)

        row = 0
        form_label(body, row, "网页地址")
        url_box = ttk.Frame(body, style="Card.TFrame")
        self.url = tk.StringVar()
        self.url_entry = ttk.Entry(url_box, textvariable=self.url)
        self.url_entry.pack(side="left", fill="x", expand=True)
        self.sniff_button = ttk.Button(
            url_box, text="嗅探资源", style="Accent.TButton", command=self._sniff
        )
        self.sniff_button.pack(side="left", padx=(scale(10), 0))
        # 仅在浏览器模式嗅探运行期间可用：点一下提前结束捕获并收掉浏览器
        self.finish_button = ttk.Button(
            url_box, text="完成嗅探", style="Ghost.TButton", command=self._finish_sniff
        )
        self.finish_button.pack(side="left", padx=(scale(8), 0))
        self.finish_button.state(["disabled"])
        url_box.grid(row=row, column=1, sticky="ew", pady=scale(7))

        row += 1
        form_label(body, row, "嗅探模式")
        self.mode = tk.StringVar(value=MODE_DIRECT)
        radio_row(
            body, row, self.mode,
            [("直连模式（默认）", MODE_DIRECT), ("浏览器模式", MODE_BROWSER)],
        )
        self.mode_hint = ttk.Label(
            body,
            text="直连失败时可在提示后改用浏览器模式",
            style="Hint.TLabel",
        )
        self.mode_hint.grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "输出目录")
        self.output_dir = tk.StringVar()
        path_row(body, row, self.output_dir, self._browse_output)
        ttk.Label(
            body, text="留空使用 media_downloads", style="Hint.TLabel"
        ).grid(row=row, column=2, sticky="w")

        row += 1
        form_label(body, row, "选项")
        self.to_mp4 = tk.BooleanVar(value=True)
        check_row(
            body, row,
            [("视频流自动封装 MP4（内置 ffmpeg，勾选视频+音频会先合流）", self.to_mp4)],
        )

        row += 1
        header = ttk.Frame(body, style="Card.TFrame")
        header.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(scale(14), scale(6)))
        ttk.Label(header, text="嗅探结果", style="Section.TLabel").pack(side="left")
        self.result_hint = ttk.Label(header, text="尚未嗅探", style="Hint.TLabel")
        self.result_hint.pack(side="left", padx=(scale(10), 0))
        self.result_hint_right = ttk.Label(
            header, text="点击“选择”列勾选，双击行预览", style="Hint.TLabel"
        )
        self.result_hint_right.pack(side="right")

        row += 1
        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=row, column=0, columnspan=3, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("sel", "type", "label", "size", "fmt", "url"),
            show="headings",
            selectmode="none",
            height=9,
        )
        for cid, text, width, anchor, stretch in (
            ("sel", "选择", scale(44), "center", False),
            ("type", "类型", scale(90), "w", False),
            ("label", "清晰度 / 说明", scale(170), "w", False),
            ("size", "大小", scale(70), "e", False),
            ("fmt", "格式", scale(54), "w", False),
            ("url", "地址", scale(340), "w", True),
        ):
            self.tree.heading(cid, text=text)
            self.tree.column(
                cid,
                width=width,
                minwidth=scale(40) if cid == "sel" else scale(60),
                anchor=anchor,
                stretch=stretch,
            )
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        hsb = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        style = ttk.Style(self.tree)
        style.configure(
            "Grab.Treeview",
            background=COLORS["card"],
            fieldbackground=COLORS["card"],
            foreground=COLORS["text"],
            rowheight=scale(26),
            font=FONTS["base"],
            bordercolor=COLORS["card_border"],
            borderwidth=scale(1),
        )
        style.configure(
            "Grab.Treeview.Heading",
            background="#f1f5f9",
            foreground=COLORS["text_muted"],
            font=FONTS["small"],
            relief="flat",
        )
        style.map(
            "Grab.Treeview",
            background=[("selected", "#dbeafe")],
            foreground=[("selected", COLORS["text"])],
        )
        body.rowconfigure(row, weight=1)

        self.tree.bind("<Button-1>", self._on_click)
        self.tree.bind("<Double-1>", self._on_double_click)

        row += 1
        actions = ttk.Frame(body, style="Card.TFrame")
        actions.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(scale(10), 0))
        ttk.Button(actions, text="全选", style="Ghost.TButton", command=self._check_all).pack(side="left")
        ttk.Button(actions, text="清空选择", style="Ghost.TButton", command=self._uncheck_all).pack(
            side="left", padx=(scale(8), 0)
        )
        ttk.Button(actions, text="预览选中", style="Ghost.TButton", command=self._preview).pack(
            side="left", padx=(scale(8), 0)
        )
        ttk.Button(actions, text="复制链接", style="Ghost.TButton", command=self._copy_links).pack(
            side="left", padx=(scale(8), 0)
        )
        self.run_button = ttk.Button(
            actions, text=self.RUN_TEXT, style="Accent.TButton", command=self._run
        )
        self.run_button.pack(side="right")

        self.app.register_run_button(self.sniff_button)
        self.app.register_run_button(self.run_button)
        self._resources: list = []
        self._checked: set[str] = set()
        self._sniffed: list = []
        self._sniff_mode: str = MODE_DIRECT
        self._sniff_stop: threading.Event | None = None

    # -------- 列表交互 --------

    def _browse_output(self) -> None:
        path = filedialog.askdirectory(title="选择输出目录")
        if path:
            self.output_dir.set(path)

    def _on_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if iid and column == "#1":  # “选择”列
            self._toggle(iid)

    def _on_double_click(self, event) -> None:
        iid = self.tree.identify_row(event.y)
        if iid:
            self._preview_items([iid])

    def _toggle(self, iid: str) -> None:
        if iid in self._checked:
            self._checked.discard(iid)
            self.tree.set(iid, "sel", UNCHECKED)
        else:
            self._checked.add(iid)
            self.tree.set(iid, "sel", CHECKED)

    def _check_all(self) -> None:
        for iid in self.tree.get_children():
            self._checked.add(iid)
            self.tree.set(iid, "sel", CHECKED)

    def _uncheck_all(self) -> None:
        self._checked.clear()
        for iid in self.tree.get_children():
            self.tree.set(iid, "sel", UNCHECKED)

    def _preview(self) -> None:
        self._preview_items(sorted(self._checked, key=lambda i: self.tree.index(i)))

    def _preview_items(self, iids: list[str]) -> None:
        indices = [i for i in (self._iid_index(iid) for iid in iids) if i is not None]
        if not indices:
            self.app.notify("请先勾选或双击要预览的资源。")
            return
        if self._sniff_mode == MODE_BROWSER:
            # 浏览器模式的资源多来自被阻断站点：经本地代理在系统浏览器中播放
            from ...core.media_grab import open_external_preview

            try:
                for index in indices[:5]:
                    open_external_preview(self._resources[index])
                self.app.notify(
                    f"已在系统浏览器中打开 {min(len(indices), 5)} 个资源的预览页。"
                )
            except Exception as exc:  # noqa: BLE001 - 预览失败直接反馈
                self.app.notify(f"预览失败: {exc}", error=True)
            return
        from ..preview import PreviewWindow

        try:
            PreviewWindow(self.frame, self._resources, indices[:10])
        except Exception as exc:  # noqa: BLE001 - 预览窗口创建失败直接反馈
            self.app.notify(f"预览失败: {exc}", error=True)

    def _copy_links(self) -> None:
        links = [
            self._resources[self._iid_index(iid)].url
            for iid in sorted(self._checked, key=lambda i: self.tree.index(i))
            if self._iid_index(iid) is not None
        ]
        if not links:
            self.app.notify("请先勾选要复制链接的资源。")
            return
        self.frame.clipboard_clear()
        self.frame.clipboard_append("\n".join(links))
        self.app.notify(f"已复制 {len(links)} 个链接到剪贴板。")

    def _iid_index(self, iid: str) -> int | None:
        try:
            return self.tree.index(iid)
        except tk.TclError:
            return None

    def _fill_tree(self, resources: list) -> None:
        self.tree.delete(*self.tree.get_children())
        self._checked.clear()
        self._resources = resources
        for resource in resources:
            self.tree.insert(
                "",
                "end",
                values=(
                    UNCHECKED,
                    resource.kind_text,
                    resource.label or "—",
                    resource.size_text,
                    resource.suffix or "无后缀",
                    resource.url,
                ),
            )
        # 默认勾选推荐组合：B 站选最佳视频+最佳音频；普通页面选第一个 HLS/媒体
        default: list[int] = []
        videos = [i for i, r in enumerate(resources) if r.kind == "dash-video"]
        audios = [i for i, r in enumerate(resources) if r.kind == "dash-audio"]
        if videos:
            default.append(videos[0])
            if audios:
                default.append(audios[0])
        elif resources:
            m3u8s = [i for i, r in enumerate(resources) if r.kind == "m3u8"]
            # 多个播放列表时默认选体积估算最大的（通常是主视频的最高清晰度）
            default.append(
                max(m3u8s, key=lambda i: resources[i].size or 0) if m3u8s else 0
            )
        for index in default:
            iid = self.tree.get_children()[index]
            self._checked.add(iid)
            self.tree.set(iid, "sel", CHECKED)
        self.result_hint.config(text=f"共 {len(resources)} 个资源")

    # -------- 嗅探与下载 --------

    def _sniff(self) -> None:
        url = self.url.get().strip().strip('"')
        if not url:
            self.app.notify("请先输入网页或媒体地址。")
            return
        mode = self.mode.get()
        self._sniff_mode = mode
        stop_event = threading.Event()
        self._sniff_stop = stop_event

        def worker() -> str:
            if mode == MODE_BROWSER:
                from ...core.media_grab import sniff_media_browser

                resources = sniff_media_browser(
                    url, stop_event=stop_event, keep_open=True
                )
                self._sniffed = resources
                if not resources:
                    return (
                        "浏览器嗅探结束，未捕获到媒体资源："
                        "请确认已在浏览器中播放视频后重试。"
                    )
                return (
                    f"浏览器嗅探完成：共 {len(resources)} 个资源。"
                    "浏览器保持打开，预览将在其新标签页播放；请在列表中勾选后下载。"
                )

            from ...core.media_grab import sniff_media

            resources = sniff_media(url, probe=True)
            print(f"嗅探到 {len(resources)} 个媒体资源")
            self._sniffed = resources
            if not resources:
                return (
                    "未嗅探到媒体资源：可尝试直连媒体/m3u8 地址，"
                    "或检查页面是否需要登录；也可改用「浏览器模式」嗅探。"
                )
            return f"嗅探完成：共 {len(resources)} 个资源，请在列表中勾选后下载。"

        def on_done(message: str, succeeded: bool) -> None:
            self._sniff_stop = None
            self.finish_button.state(["disabled"])
            if succeeded:
                self._fill_tree(self._sniffed)
                self.result_hint_right.config(
                    text="双击行预览（在嗅探浏览器的新标签页播放）"
                    if mode == MODE_BROWSER else "双击行软件内预览"
                )

        started = self.app.submit("嗅探媒体资源", self.sniff_button, worker, on_done=on_done)
        if not started:
            self._sniff_stop = None
        elif mode == MODE_BROWSER:
            self.finish_button.state(["!disabled"])

    def _finish_sniff(self) -> None:
        """提前结束浏览器嗅探：置位停止事件；浏览器保持打开供预览复用。"""
        if self._sniff_stop is not None and not self._sniff_stop.is_set():
            self._sniff_stop.set()
            self.app.notify("正在结束嗅探（浏览器保持打开）…")

    def _run(self) -> None:
        if not self._resources:
            self.app.notify("请先嗅探出资源列表，再勾选下载。")
            return
        selected = [
            self._resources[self._iid_index(iid)]
            for iid in sorted(self._checked, key=lambda i: self.tree.index(i))
            if self._iid_index(iid) is not None
        ]
        if not selected:
            self.app.notify("请先在列表中勾选要下载的资源。")
            return
        output_dir = self.output_dir.get().strip().strip('"') or "media_downloads"
        to_mp4 = self.to_mp4.get()

        def worker() -> str:
            from ...core.media_grab import download_resources

            summary = download_resources(selected, output_dir, to_mp4=to_mp4)
            return (
                f"下载完成：下载 {summary.downloaded}，合流 {summary.merged}，"
                f"跳过 {summary.skipped}，失败 {summary.failed}，详见运行日志。"
            )

        self.app.submit("网页媒体下载", self.run_button, worker)
