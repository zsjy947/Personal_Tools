"""工具视图基类与视图协议契约（新工具接入照此办理）。

视图协议：

1. 类属性：
   - ``ID``：视图唯一标识（注册表与 show_view 用）；
   - ``TITLE``：内容区标题（工具完整名称）；
   - ``SUBTITLE``：标题下的一句话说明；
   - ``NAV``：侧边栏分组内的动作短名（分组名已含对象，如「图片工具」下
     的「格式转换」），缺省回退 TITLE；
   - ``RUN_TEXT``：执行按钮文案，默认「执 行」。
2. ``build(parent)``：构建表单卡片，必须给 ``self.frame`` 赋值；只在首次
   切入时调用一次，视图切换不销毁表单状态。表单控件优先用 widgets.py 的
   辅助函数（form_label/entry_row/path_row/radio_row/check_row/
   run_button_row），尺寸一律经 ``theme.scale()`` 换算，不写死像素。
3. ``_run()``：执行入口。先做参数校验（不合法时 ``self.app.notify("…",
   error=True)`` 并 return），再定义闭包 ``worker() -> str``（返回一句话
   结果摘要），最后 ``self.app.submit(任务标题, self.run_button, worker[,
   on_done])`` 提交；任务完成/失败的弹窗与日志由 App 统一处理。
4. 纪律：
   - 核心模块在 worker 函数体内懒导入（``from ...core.xxx import …``），
     保证入口启动不加载重依赖（image_decrypt/media_grab 等）；
   - 执行按钮（及嗅探等会跑任务的按钮）经
     ``self.app.register_run_button(...)`` 注册，任务运行期间统一禁用；
   - 同一时间只允许一个任务（runner 单任务队列），重复提交会被拒绝；
   - 需要每次切入时刷新数据的视图覆写 ``on_show()``（首次在 build 之后
     紧接着也会调用一次）。
5. 注册：在 views/__init__.py 的 ``VIEW_GROUPS`` 对应分组里加入视图类。

参考实现：convert_view.py（标准表单）、grab_view.py（两段式交互）、
history_view.py（只读列表 + on_show 刷新）。
"""

import tkinter as tk


class ToolView:
    """一个工具页：在内容区构建表单卡片，并提供后台执行入口。"""

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

    def on_show(self) -> None:
        """视图每次切入内容区时调用（首次在 build 之后）；需要刷新的视图覆写。"""

    def _run(self) -> None:
        raise NotImplementedError
