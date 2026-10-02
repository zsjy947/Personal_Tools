"""目录监控自动化视图：规则表管理 + 总开关 + 撤销上一轮。

监控线程不属于 runner 单任务体系：FlowWatch 实例挂在 App（self.app.
flow_watch）上，日志经 app.watch_log 进日志队列；总开关默认停止且状态
不持久化——每次打开软件都需要手动启动（"可开关"的第二层）。
"""

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from ..theme import COLORS, FONTS, scale
from ..widgets import Card, check_row, form_label, radio_row
from .base import ToolView

CHECKED, UNCHECKED = "☑", "☐"

CONVERT_FORMATS = [("JPG", "jpg"), ("PNG", "png"), ("WEBP", "webp"), ("BMP", "bmp")]


class FlowView(ToolView):
    ID = "flow"
    TITLE = "目录监控自动化"
    NAV = "目录监控"
    SUBTITLE = (
        "规则盯目录：新文件落定后自动执行非破坏性动作（图片转格式 / 无损转 MP4 / "
        "按类型归类）。全程可开关、默认停止；移动类动作可「撤销上一轮」；已处理"
        "文件有台账，重启不重复处理。"
    )

    def build(self, parent) -> None:
        self.frame = Card(parent)
        body = ttk.Frame(self.frame, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=scale(20), pady=(scale(10), scale(18)))
        body.columnconfigure(0, weight=1)
        body.rowconfigure(2, weight=1)

        row = 0
        switch_bar = ttk.Frame(body, style="Card.TFrame")
        switch_bar.grid(row=row, column=0, sticky="ew")
        self.toggle_button = ttk.Button(
            switch_bar, text="启动监控", style="Accent.TButton",
            command=self._toggle_watch,
        )
        self.toggle_button.pack(side="left")
        self.status_label = ttk.Label(
            switch_bar,
            text="监控未运行（状态不保存，每次打开软件需手动启动）",
            style="Hint.TLabel",
        )
        self.status_label.pack(side="left", padx=(scale(12), 0))
        self.undo_button = ttk.Button(
            switch_bar, text="撤销上一轮", style="Ghost.TButton",
            command=self._undo_last_batch,
        )
        self.undo_button.pack(side="right")

        row += 1
        header = ttk.Frame(body, style="Card.TFrame")
        header.grid(row=row, column=0, sticky="ew", pady=(scale(14), scale(6)))
        ttk.Label(header, text="监控规则", style="Section.TLabel").pack(side="left")
        self.rule_hint = ttk.Label(header, text="", style="Hint.TLabel")
        self.rule_hint.pack(side="left", padx=(scale(10), 0))
        ttk.Button(header, text="添加规则", style="Ghost.TButton",
                   command=self._add_rule).pack(side="right")
        ttk.Button(header, text="编辑", style="Ghost.TButton",
                   command=self._edit_rule).pack(side="right", padx=(scale(8), 0))
        ttk.Button(header, text="删除", style="Ghost.TButton",
                   command=self._delete_rule).pack(side="right", padx=(scale(8), 0))

        row += 1
        table = ttk.Frame(body, style="Card.TFrame")
        table.grid(row=row, column=0, sticky="nsew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(
            table,
            style="Grab.Treeview",
            columns=("enabled", "name", "dir", "action", "params"),
            show="headings",
            selectmode="browse",
            height=9,
        )
        for cid, text, width, anchor, stretch in (
            ("enabled", "启用", scale(50), "center", False),
            ("name", "名称", scale(130), "w", False),
            ("dir", "监听目录", scale(230), "w", True),
            ("action", "动作", scale(100), "w", False),
            ("params", "参数", scale(180), "w", True),
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

        self._rules: list = []
        self._reload_rules()
        self._sync_master_ui()

    # -------- 规则表 --------

    def _reload_rules(self) -> None:
        from ...core.flow_watch import load_rules

        self._rules = load_rules()
        self.tree.delete(*self.tree.get_children())
        for index, rule in enumerate(self._rules):
            self.tree.insert(
                "", "end", iid=str(index),
                values=(
                    CHECKED if rule.enabled else UNCHECKED,
                    rule.name,
                    rule.watch_dir,
                    dict(self._action_options_display()).get(rule.action, rule.action),
                    rule.summary_text(),
                ),
            )
        enabled_count = sum(1 for rule in self._rules if rule.enabled)
        self.rule_hint.config(
            text=f"共 {len(self._rules)} 条规则，{enabled_count} 条启用"
        )

    @staticmethod
    def _action_options_display():
        from ...core.flow_watch import ACTION_TEXTS

        return ACTION_TEXTS

    def _on_click(self, event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        iid = self.tree.identify_row(event.y)
        column = self.tree.identify_column(event.x)
        if iid and column == "#1":
            self._toggle_enabled(int(iid))

    def _toggle_enabled(self, index: int) -> None:
        from ...core.flow_watch import save_rules

        self._rules[index].enabled = not self._rules[index].enabled
        save_rules(self._rules)
        self._reload_rules()
        if self._watch_running():
            self.app.notify("规则已修改：重启监控后生效。")

    def _selected_index(self) -> int | None:
        selection = self.tree.selection()
        return int(selection[0]) if selection else None

    def _add_rule(self) -> None:
        self._open_rule_dialog(None)

    def _edit_rule(self) -> None:
        index = self._selected_index()
        if index is None:
            self.app.notify("请先选中要编辑的规则。")
            return
        self._open_rule_dialog(index)

    def _delete_rule(self) -> None:
        from ...core.flow_watch import save_rules

        index = self._selected_index()
        if index is None:
            self.app.notify("请先选中要删除的规则。")
            return
        rule = self._rules[index]
        if not messagebox.askyesno("删除规则", f"确定删除规则「{rule.name}」？"):
            return
        del self._rules[index]
        save_rules(self._rules)
        self._reload_rules()

    # -------- 规则编辑对话框 --------

    def _open_rule_dialog(self, index: int | None) -> None:
        from ...core.flow_watch import save_rules

        rule = self._rules[index] if index is not None else None
        window = tk.Toplevel(self.frame)
        window.title("编辑规则" if rule else "添加规则")
        window.transient(self.frame)
        window.grab_set()
        body = ttk.Frame(window, style="Card.TFrame", padding=scale(16))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)

        name = tk.StringVar(value=rule.name if rule else "")
        watch_dir = tk.StringVar(value=rule.watch_dir if rule else "")
        recursive = tk.BooleanVar(value=rule.recursive if rule else False)
        suffixes_text = tk.StringVar(
            value=" ".join(sorted(rule.suffixes)) if rule else ""
        )
        action = tk.StringVar(
            value=rule.action if rule else "sort_by_type"
        )
        target_format = tk.StringVar(
            value=(rule.action_params or {}).get("target_format", "jpg") if rule else "jpg"
        )
        quality = tk.StringVar(
            value=str((rule.action_params or {}).get("quality", "") or "") if rule else ""
        )
        delete_original = tk.BooleanVar(
            value=bool((rule.action_params or {}).get("delete_original")) if rule else False
        )

        row = 0
        form_label(body, row, "规则名称")
        ttk.Entry(body, textvariable=name).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=scale(6)
        )

        row += 1
        form_label(body, row, "监听目录")
        dir_box = ttk.Frame(body, style="Card.TFrame")
        ttk.Entry(dir_box, textvariable=watch_dir).pack(
            side="left", fill="x", expand=True
        )

        def browse() -> None:
            path = filedialog.askdirectory(title="选择监听目录", parent=window)
            if path:
                watch_dir.set(path)

        ttk.Button(dir_box, text="浏览", style="Ghost.TButton",
                   command=browse).pack(side="left", padx=(scale(8), 0))
        dir_box.grid(row=row, column=1, columnspan=2, sticky="ew", pady=scale(6))

        row += 1
        form_label(body, row, "范围")
        check_row(body, row, [("递归子目录", recursive)])

        row += 1
        form_label(body, row, "后缀")
        ttk.Entry(body, textvariable=suffixes_text).grid(
            row=row, column=1, columnspan=2, sticky="ew", pady=scale(2)
        )
        row += 1
        ttk.Label(
            body, text="留空 = 全部文件；多个后缀用空格分隔，如：webp png",
            style="Hint.TLabel",
        ).grid(row=row, column=1, columnspan=2, sticky="w")

        row += 1
        form_label(body, row, "动作")
        options = [(text, value) for value, text in self._action_options_display().items()]
        radio_row(body, row, action, options)

        row += 1
        form_label(body, row, "转换参数")
        params_box = ttk.Frame(body, style="Card.TFrame")
        ttk.Label(params_box, text="目标格式", style="Hint.TLabel").pack(side="left")
        for text, value in CONVERT_FORMATS:
            ttk.Radiobutton(
                params_box, text=text, value=value, variable=target_format,
                style="Option.TRadiobutton",
            ).pack(side="left", padx=(scale(6), 0))
        ttk.Label(params_box, text="质量", style="Hint.TLabel").pack(
            side="left", padx=(scale(14), 0)
        )
        ttk.Entry(params_box, textvariable=quality, width=scale(5)).pack(
            side="left", padx=(scale(6), 0)
        )
        params_box.grid(row=row, column=1, columnspan=2, sticky="ew")

        row += 1
        check_row(body, row, [("转换成功后删除原图（不可撤销，慎选）", delete_original)])

        row += 1
        buttons = ttk.Frame(body, style="Card.TFrame")
        buttons.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(scale(14), 0))

        def save_and_close() -> None:
            from ...core.common import normalize_suffixes
            from ...core.flow_watch import ACTION_TEXTS

            rule_name = name.get().strip()
            directory = watch_dir.get().strip().strip('"')
            action_value = action.get()
            if not rule_name:
                self.app.notify("请填写规则名称。", error=True)
                return
            if not directory or not Path(directory).is_dir():
                self.app.notify("监听目录不存在，请重新选择。", error=True)
                return
            if action_value not in ACTION_TEXTS:
                self.app.notify("请选择有效动作。", error=True)
                return
            duplicated = any(
                other.name == rule_name and other is not rule
                for other in self._rules
            )
            if duplicated:
                self.app.notify("已有同名规则。", error=True)
                return
            params: dict = {}
            if action_value == "convert":
                quality_value = quality.get().strip()
                quality_number = None
                if quality_value:
                    try:
                        quality_number = int(quality_value)
                    except ValueError:
                        self.app.notify("质量必须是数字。", error=True)
                        return
                params = {
                    "target_format": target_format.get(),
                    "quality": quality_number,
                    "delete_original": delete_original.get(),
                }
            new_rule = self._rules[index] if rule else None
            if new_rule is None:
                from ...core.flow_watch import Rule

                new_rule = Rule(name=rule_name, watch_dir=directory,
                                action=action_value)
                self._rules.append(new_rule)
            new_rule.name = rule_name
            new_rule.watch_dir = directory
            new_rule.action = action_value
            new_rule.recursive = recursive.get()
            new_rule.suffixes = normalize_suffixes(
                suffixes_text.get().replace(",", " ").replace("，", " ").split()
            )
            new_rule.action_params = params
            save_rules(self._rules)
            self._reload_rules()
            if self._watch_running():
                self.app.notify("规则已保存：重启监控后生效。")
            window.destroy()

        ttk.Button(buttons, text="保存", style="Accent.TButton",
                   command=save_and_close).pack(side="right")
        ttk.Button(buttons, text="取消", style="Ghost.TButton",
                   command=window.destroy).pack(side="right", padx=(0, scale(8)))

    # -------- 总开关与撤销 --------

    def _watch_running(self) -> bool:
        return self.app.flow_watch is not None and self.app.flow_watch.running

    def _sync_master_ui(self) -> None:
        if self._watch_running():
            self.toggle_button.config(text="停止监控")
            self.status_label.config(
                text=f"监控中：间隔 {self.app.flow_watch.interval:g}s",
                foreground=COLORS["status_idle"],
            )
        else:
            self.toggle_button.config(text="启动监控")
            self.status_label.config(
                text="监控未运行（状态不保存，每次打开软件需手动启动）",
                foreground=COLORS["text_muted"],
            )

    def _toggle_watch(self) -> None:
        if self._watch_running():
            self.app.flow_watch.stop()
            self.app.flow_watch = None
            self._sync_master_ui()
            return
        from ...core.flow_watch import FlowWatch, load_rules

        rules = [rule for rule in load_rules() if rule.enabled]
        valid = [rule for rule in rules if Path(rule.watch_dir).is_dir()]
        skipped = len(rules) - len(valid)
        if not valid:
            self.app.notify("没有可启动的启用规则（先添加规则并确认目录存在）。", error=True)
            return
        watch = FlowWatch(valid, log_cb=self.app.watch_log)
        watch.start()
        self.app.flow_watch = watch
        if skipped:
            self.app.notify(f"{skipped} 条规则的目录不存在，本次未纳入监控。", error=True)
        self._sync_master_ui()

    def _undo_last_batch(self) -> None:
        from ...core.flow_watch import undo_last_batch

        undone, failures = undo_last_batch()
        if undone == 0 and not failures:
            self.app.notify("没有可撤销的操作。")
            return
        for line in failures:
            self.app.watch_log(f"[撤销] 跳过: {line}")
        self.app.notify(f"撤销完成：回滚 {undone} 个文件"
                        + (f"，{len(failures)} 个跳过（详见日志）" if failures else ""))

    def on_show(self) -> None:
        # 规则可能被 CLI/其他会话改过；总开关状态随 App 实时刷新
        if self.frame is not None:
            self._reload_rules()
            self._sync_master_ui()

    def _run(self) -> None:  # 协议占位：本视图用总开关而非执行按钮
        self._toggle_watch()
