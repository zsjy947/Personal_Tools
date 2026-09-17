"""`python -m file_tools.gui` 与 PyInstaller 打包的入口脚本。

支持 `--selftest` 参数：在当前环境运行核心工具自检后退出（用于验证打包产物）。
"""

import sys

from file_tools.gui.app import main

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        from file_tools.selftest import main as selftest_main

        raise SystemExit(selftest_main())
    raise SystemExit(main())
