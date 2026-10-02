"""用户侧持久化基座：任务历史、监控规则、处理台账等文件的统一存放位置。

项目所有用户侧数据都收敛到这一个目录，避免散落各处；目录解析顺序：

1. 环境变量 ``FILE_TOOLS_DATA_DIR``（测试与便携场景用）；
2. win32：``%APPDATA%/FileTools``；
3. 其余平台（及无 APPDATA 时）：``~/.file_tools``。

目录不存在则创建；创建失败（权限等）时回退到系统临时目录下的小目录，
让"写失败静默"的功能（如任务历史）依然可用。每次调用都重新解析，
不做缓存——测试中改环境变量立即生效。
"""

import os
import sys
from pathlib import Path

ENV_DATA_DIR = "FILE_TOOLS_DATA_DIR"


def base_dir() -> Path:
    """返回用户数据目录（不存在则创建，见模块 docstring）。"""
    override = os.environ.get(ENV_DATA_DIR, "").strip()
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "win32" and os.environ.get("APPDATA"):
        path = Path(os.environ["APPDATA"]) / "FileTools"
    else:
        path = Path.home() / ".file_tools"
    try:
        path.mkdir(parents=True, exist_ok=True)
        return path
    except OSError:
        import tempfile

        fallback = Path(tempfile.gettempdir()) / "file_tools"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
