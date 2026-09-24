"""工具视图基类。"""

import tkinter as tk


class ToolView:
    """一个工具页：在内容区构建表单卡片，并提供后台执行入口。

    子类需声明 ID/TITLE/SUBTITLE/RUN_TEXT 并实现 `build` 与 `_run`。
    NAV 是侧边栏分组下的短名（分组名已含对象，如「图片」组下的「格式转换」），
    缺省回退到 TITLE；完整名称始终显示在内容区标题。
    """

    ID: str
    TITLE: str
    SUBTITLE: str
    NAV: str | None = None
    RUN_TEXT = "执 行"

    def __init__(self, app) -> None:
        self.app = app
        self.frame: tk.Frame | None = None
        self.run_button: tk.Button | None = None

    def build(self, parent) -> None:
        raise NotImplementedError

    def _run(self) -> None:
        raise NotImplementedError
