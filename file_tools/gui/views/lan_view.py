"""局域网共享视图：总开关（默认关）+ 共享目录白名单 + 大字可复制连接 URL。

服务状态不持久化——每次打开软件都是停止态，与目录监控一致（"用完即关"）。
仅限可信局域网使用：纯 HTTP + token，无 HTTPS（BACKLOG B5）。
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk

from ..theme import COLORS, FONTS, scale
from ..widgets import Card
from .base import ToolView


class LanView(ToolView):
    ID = "lan"
    TITLE = "局域网共享"
    NAV = "局域网共享"
    SUBTITLE = (
        "把目录共享给同一局域网的手机/电脑：浏览、下载，可标记一个上传目录；"
        "还能远程触发一次目录监控扫描。token 保护、默认关闭、软件关闭即停止，"
        "请仅在可信局域网使用。"
    )

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(0, weight=1)

        row = 0
        switch_bar = ttk.Frame(body, style="Card.TFrame")
        switch_bar.grid(row=row, column=0, sticky="ew")
        self.toggle_button = ttk.Button(
            switch_bar, text="启动服务", style="Accent.TButton",
            command=self._toggle_service,
        )
        self.toggle_button.pack(side="left")
        self.status_label = ttk.Label(
            switch_bar, text="服务未运行（默认关闭，状态不保存）",
            style="Hint.TLabel",
        )
        self.status_label.pack(side="left", padx=(scale(12), 0))
        ttk.Label(switch_bar, text="端口", style="Hint.TLabel").pack(
            side="left", padx=(scale(18), scale(4))
        )
        self.port = tk.StringVar(value="38475")
        self.port_entry = ttk.Entry(switch_bar, textvariable=self.port, width=scale(7))
        self.port_entry.pack(side="left")

        row += 1
        self.url_box = ttk.Frame(body, style="Card.TFrame")
        self.url_box.grid(row=row, column=0, sticky="ew", pady=(scale(12), 0))
        self.url_label = tk.Label(
            self.url_box, text="", bg=COLORS["log_bg"], fg="#93c5fd",
            font=FONTS["mono"], padx=scale(12), pady=scale(10), anchor="w",
        )
        self.url_label.pack(side="left", fill="x", expand=True)
        self.copy_button = ttk.Button(
            self.url_box, text="复制网址", style="Ghost.TButton",
            command=self._copy_url,
        )
        self.copy_button.pack(side="left", padx=(scale(8), 0))
        # 未启动时不占高度：网格移除由 _sync_ui 控制

        row += 1
        header = ttk.Frame(body, style="Card.TFrame")
        header.grid(row=row, column=0, sticky="ew", pady=(scale(14), scale(6)))
        ttk.Label(header, text="共享目录", style="Section.TLabel").pack(side="left")
        ttk.Label(
            header, text="至多一个目录标记为「可上传」，其余只读",
            style="Hint.TLabel",
        ).pack(side="left", padx=(scale(10), 0))
        self.add_button = ttk.Button(header, text="添加目录", style="Ghost.TButton",
                                     command=self._add_dir)
        self.add_button.pack(side="right")
        self.remove_button = ttk.Button(header, text="移除选中", style="Ghost.TButton",
                                        command=self._remove_dir)
        self.remove_button.pack(side="right", padx=(scale(8), 0))
        self.upload_button = ttk.Button(
            header, text="标记为可上传", style="Ghost.TButton",
            command=self._mark_upload,
        )
        self.upload_button.pack(side="right", padx=(scale(8), 0))

        row += 1
        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(0, scale(8)))
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("writable", "dir"),
            show="headings",
            selectmode="browse",
            height=6,
        )
        self.tree.heading("writable", text="权限")
        self.tree.heading("dir", text="目录")
        self.tree.column("writable", width=scale(90), minwidth=scale(60),
                         anchor="center", stretch=False)
        self.tree.column("dir", width=scale(360), minwidth=scale(120),
                         anchor="w", stretch=True)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=vsb.set)
        body.rowconfigure(row, weight=1)

        row += 1
        ttk.Label(
            body,
            text="说明：服务把本机目录经 HTTP 暴露到局域网（纯 HTTP + 访问令牌，"
                 "无 HTTPS/账号体系）；「触发扫描」会对目录监控规则立即执行一轮"
                 "（需先在「目录监控」里配置规则）。",
            style="Hint.TLabel", wraplength=scale(680), justify="left",
        ).grid(row=row, column=0, sticky="ew")

        self._shares: list = []  # core.lan_share.Share
        self._sync_ui()

    # -------- 共享目录管理 --------

    def _reload_tree(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for index, share in enumerate(self._shares):
            self.tree.insert(
                "", "end", iid=str(index),
                values=("可上传" if share.writable else "只读", share.path),
            )

    def _add_dir(self) -> None:
        path = filedialog.askdirectory(title="选择要共享的目录")
        if not path:
            return
        if any(Path(share.path) == Path(path) for share in self._shares):
            self.app.notify("该目录已在共享列表中。")
            return
        from ...core.lan_share import Share

        self._shares.append(Share(path=path))
        self._reload_tree()

    def _remove_dir(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self.app.notify("请先选中要移除的目录。")
            return
        del self._shares[int(selection[0])]
        self._reload_tree()

    def _mark_upload(self) -> None:
        selection = self.tree.selection()
        if not selection:
            self.app.notify("请先选中要标记为可上传的目录。")
            return
        index = int(selection[0])
        target = self._shares[index]
        if target.writable:
            target.writable = False  # 再点一次取消
        else:
            for share in self._shares:
                share.writable = False
            target.writable = True
        self._reload_tree()

    # -------- 服务开关 --------

    def _toggle_service(self) -> None:
        if self.app.lan_share is not None and self.app.lan_share.running:
            self.app.lan_share.stop()
            self.app.lan_share = None
            self._sync_ui()
            return
        from ...core.lan_share import LanShare

        try:
            port = int(self.port.get().strip())
        except ValueError:
            self.app.notify("端口必须是数字。", error=True)
            return
        if not 1 <= port <= 65535:
            self.app.notify("端口必须在 1-65535 之间。", error=True)
            return
        if not self._shares:
            self.app.notify("请先添加要共享的目录。", error=True)
            return
        lan = LanShare(log_cb=self.app.watch_log)
        try:
            lan.start(self._shares, port=port)
        except (OSError, RuntimeError, ValueError) as exc:
            self.app.notify(f"启动失败: {exc}", error=True)
            return
        self.app.lan_share = lan
        self._sync_ui()

    def _sync_ui(self) -> None:
        running = self.app.lan_share is not None and self.app.lan_share.running
        # 运行中的服务持有白名单快照：目录编辑改不动已运行实例，统一禁用
        state = "disabled" if running else "!disabled"
        for widget in (self.add_button, self.remove_button, self.upload_button):
            try:
                widget.state([state])
            except tk.TclError:
                pass
        if running:
            self.toggle_button.config(text="停止服务")
            self.status_label.config(
                text="服务运行中 · 关闭软件即停止", foreground=COLORS["status_idle"]
            )
            self.url_label.config(text=self.app.lan_share.url)
            self.url_box.grid()
            self.port_entry.state(["disabled"])
        else:
            self.toggle_button.config(text="启动服务")
            self.status_label.config(
                text="服务未运行（默认关闭，状态不保存）",
                foreground=COLORS["text_muted"],
            )
            self.url_box.grid_remove()
            self.port_entry.state(["!disabled"])

    def _copy_url(self) -> None:
        if self.app.lan_share is None:
            return
        self.frame.clipboard_clear()
        self.frame.clipboard_append(self.app.lan_share.url)
        self.app.notify("连接网址已复制，手机浏览器打开即可访问。")

    def _run(self) -> None:  # 协议占位：本视图用总开关而非执行按钮
        self._toggle_service()

    def on_show(self) -> None:
        if self.frame is not None:
            self._sync_ui()
