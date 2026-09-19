# AGENTS.md（archive 分支）

本分支**仅作为主分支移除功能的存档**，当前只保留上海地铁票价查询工具
（`shanghai_metro_fare/`）。该分支只读、不再开发。

## 要点

- `shanghai_metro_fare/`：上海地铁最短路径与票价查询，CLI（`metro_fare.py`）
  与自包含网页版（`index.html`），仅使用 Python 标准库；站点/线路数据在其
  `data/` 内，经 `fetch_data.py` 抓取生成（存档，不重新抓取）。
- 功能详细文档见 `shanghai_metro_fare/README.md` 与根 `README.md`。
- 主分支的文件处理工具集 `file_tools/` 及其历史版本不在本分支；需要时查
  `main` 分支的 commit 记录。不要把 `file_tools/`、`download_images.py`、
  `build_exe.py` 等加回本分支。
- 用户输入、输出路径必须来自命令行参数或交互输入，不要在脚本中写入本机
  绝对路径。
