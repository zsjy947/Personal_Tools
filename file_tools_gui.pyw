"""双击启动文件处理工具图形界面（Windows，无控制台窗口）。

优先使用项目 .venv 中的 pythonw，保证依赖版本与开发环境一致；
未找到 venv 时回退到当前解释器直接启动。
"""

import os
import subprocess
import sys


def _launch_with_venv() -> bool:
    root_dir = os.path.dirname(os.path.abspath(__file__))
    pythonw = os.path.join(root_dir, ".venv", "Scripts", "pythonw.exe")
    if not os.path.isfile(pythonw):
        return False
    subprocess.Popen([pythonw, "-m", "file_tools.gui"], cwd=root_dir)
    return True


if __name__ == "__main__":
    if not _launch_with_venv():
        from file_tools.gui import main

        sys.exit(main())
