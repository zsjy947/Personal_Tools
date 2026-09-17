"""工具视图基类。"""

import tkinter as tk


class ToolView:
    """一个工具页：在内容区构建表单卡片，并提供后台执行入口。

    子类需声明 ID/TITLE/SUBTITLE/RUN_TEXT 并实现 `build` 与 `_run`。
    """

    ID: str
    TITLE: str
    SUBTITLE: str
    RUN_TEXT = "执 行"

    def __init__(self, app) -> None:
        self.app = app
        self.frame: tk.Frame | None = None
        self.run_button: tk.Button | None = None

    def build(self, parent) -> None:
        raise NotImplementedError

    def _run(self) -> None:
        raise NotImplementedError
