# CLAUDE.md

本文件为在此仓库中工作的代码助手提供项目说明。

## 项目结构

项目分为三个独立部分：

1. `file_tools/`：本地文件处理工具包，统一入口为 `python -m file_tools`，另有 tkinter 可视化界面 `python -m file_tools.gui`（双击根目录 `file_tools_gui.pyw` 启动）。
2. `download_images.py`：独立的批量图片下载 CLI。
3. `shanghai_metro_fare/`：独立的上海地铁最短路径与票价工具。

用户输入、输出路径必须来自命令行参数或交互输入，不要在脚本中加入本机绝对路径或要求用户修改的路径常量。脚本自身附带的数据和模板可以通过 `Path(__file__)` 定位。

## 文件处理工具

### `file_tools/image_decrypt.py`

- 原 `demo.py`，支持 5 种图像混淆/解混淆模式，每种模式均提供双向处理。
- 使用 Numba JIT 加速像素变换，基于 MD5 生成伪随机排列。
- 独立入口：`python -m file_tools.image_decrypt INPUT OUTPUT --operation {encrypt,decrypt} --mode MODE --key KEY`。
- 输入为目录时批量处理，支持 `--suffix`、`--recursive` 和 `--overwrite`，并保留相对目录结构。
- 依赖 `numpy`、`Pillow`、`numba`。

### `file_tools/media_to_mp4.py`

- 使用 ffmpeg 将真实内容为视频、但扩展名可能异常的文件无损封装为 MP4。
- 目录模式通过 `--suffix` 指定筛选后缀，支持 `--recursive`、`--output-dir`、`--overwrite` 和 `--dry-run`。
- 独立入口：`python -m file_tools.media_to_mp4 SOURCE [选项]`。
- 普通图片、字体等非视频内容应报告转换失败，不应伪造 MP4。

### `file_tools/dot1_suffix.py`

- 合并原 `modify.py` 和 `remove_dot1_suffix.py`。
- 支持添加或移除 `.1`，默认单层，`--recursive` 可递归。
- 两种操作均支持 `--dry-run`，目标名称冲突时跳过。
- 独立入口：`python -m file_tools.dot1_suffix {add,remove} TARGET [选项]`。

### `file_tools/delete_copy_files.py`

- 递归匹配文件名 stem 以“副本”结尾的文件。
- 默认仅预览，必须传入 `--execute` 才删除。
- 独立入口：`python -m file_tools.delete_copy_files TARGET [--execute]`。

### `file_tools/gui.py`

- tkinter 可视化界面，五个标签页对应上述五项工具，路径一律通过系统资源管理器对话框选择。
- 顶层只依赖标准库；各工具模块在执行任务时才导入，缺少依赖时界面仍能打开。
- 工具任务在后台线程执行，控件值只在主线程读取，print 输出经队列刷入窗口底部日志区。
- 入口：`python -m file_tools.gui`、`file_tools_gui.pyw`（双击启动，优先使用 `.venv` 解释器）、交互菜单选项 6。

## 图片下载

### `download_images.py`

- 从 CSV 第一列读取 URL，流式下载到指定目录。
- `--input` 为必需参数，`--output`、`--timeout`、`--delay` 可配置。
- 自动跳过已有文件，单个下载失败时继续。
- 用法：`python download_images.py -i URLS.csv [-o OUTPUT_DIR]`。
- 依赖 `requests`。

## 上海地铁票价

`shanghai_metro_fare/` 保持为独立个体，不加入 `file_tools` 菜单。

- `metro_fare.py`：站名匹配、路径计算和三套票价方案。
- `index.html`：自包含网页版。
- `web_template.html`：网页模板。
- `build_web.py`：将数据嵌入模板并生成 `index.html`。
- `fetch_data.py`：获取并生成 `data/stations.json` 与 `data/edges.json`。
- 自检：`python shanghai_metro_fare/metro_fare.py --selftest`。
- 核心功能只使用 Python 标准库。

## 环境

- Python 3.10+
- 虚拟环境通常位于 `.venv/`
- 安装依赖：`pip install -r requirements.txt`
- 媒体封装功能要求系统安装 ffmpeg 并加入 `PATH`
