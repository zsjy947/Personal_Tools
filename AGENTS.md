# AGENTS.md

本文件为在此仓库中工作的代码助手提供项目说明。

## 项目结构

项目分为三个独立部分：

1. `file_tools/`：本地文件处理工具包。核心工具位于 `file_tools/core/`，统一 CLI 入口为 `python -m file_tools`（懒加载核心模块）；可视化界面位于 `file_tools/gui/` 包，入口 `python -m file_tools.gui`；打包为 exe 用根目录 `python build_exe.py`。
2. `download_images.py`：独立的批量图片下载 CLI。
3. `shanghai_metro_fare/`：独立的上海地铁最短路径与票价工具。

用户输入、输出路径必须来自命令行参数或交互输入，不要在脚本中加入本机绝对路径或要求用户修改的路径常量。脚本自身附带的数据和模板可以通过 `Path(__file__)` 定位。

## 文件处理工具

核心工具在 `file_tools/core/`，每项均可独立 CLI 运行，GUI 与交互菜单在执行时才导入它们（`image_decrypt` 依赖较重，避免入口启动时加载）。

### `file_tools/core/image_decrypt.py`

- 原 `demo.py`，支持 5 种图像混淆/解混淆模式，每种模式均提供双向处理。
- 使用 Numba JIT 加速像素变换，基于 MD5 生成伪随机排列。
- 独立入口：`python -m file_tools.core.image_decrypt INPUT OUTPUT --operation {encrypt,decrypt} --mode MODE --key KEY`。
- 输入为目录时批量处理，支持 `--suffix`、`--recursive` 和 `--overwrite`，并保留相对目录结构。
- 依赖 `numpy`、`Pillow`、`numba`。

### `file_tools/core/media_to_mp4.py`

- 使用 ffmpeg 将真实内容为视频、但扩展名可能异常的文件无损封装为 MP4。
- 目录模式通过 `--suffix` 指定筛选后缀，支持 `--recursive`、`--output-dir`、`--overwrite` 和 `--dry-run`。
- 独立入口：`python -m file_tools.core.media_to_mp4 SOURCE [选项]`。
- ffmpeg 查找顺序：`PATH`，打包成 exe 后还支持放在 exe 同目录。
- 普通图片、字体等非视频内容应报告转换失败，不应伪造 MP4。

### `file_tools/core/dot1_suffix.py`

- 合并原 `modify.py` 和 `remove_dot1_suffix.py`。
- 支持添加或移除 `.1`，默认单层，`--recursive` 可递归。
- 两种操作均支持 `--dry-run`，目标名称冲突时跳过。
- 独立入口：`python -m file_tools.core.dot1_suffix {add,remove} TARGET [选项]`。

### `file_tools/core/delete_copy_files.py`

- 递归匹配文件名 stem 以“副本”结尾的文件。
- 默认仅预览，必须传入 `--execute` 才删除。
- 独立入口：`python -m file_tools.core.delete_copy_files TARGET [--execute]`。

### `file_tools/gui/` 可视化界面包

- 布局：深色侧边栏导航 + 内容区（标题 + 白色卡片表单）+ 深色日志面板 + 状态栏，视图切换不销毁表单状态。
- `theme.py`：`enable_dpi_awareness()` 必须在创建 Tk 之前调用（进程级 DPI 感知，否则窗口和文件对话框在高分屏上模糊），`setup_theme()` 计算缩放比例并配置字体与 ttk 样式；所有尺寸经过 `scale()` 换算，新增控件不要写死像素。
- `runner.py`：任务在后台线程执行，print 经队列交给主线程，同一时间只允许一个任务，结果在 `poll()` 中复位 busy 状态。
- `views/`：每个工具一个视图类（ID/TITLE/SUBTITLE + `build()` + `_run()`），在 `views/__init__.py` 注册；核心模块在 worker 内懒导入。
- `widgets.py`：卡片、导航项与表单行辅助，新视图复用 `form_label/form_field/path_row/radio_row/check_row/run_button_row`。
- 入口：`python -m file_tools.gui`、交互菜单选项 6、`FileTools.exe`。

### `file_tools/selftest.py` 与 `build_exe.py`

- `python -m file_tools.selftest`（或 `FileTools.exe --selftest`）在当前环境冒烟测试四项核心工具，全部通过退出码 0。
- `python build_exe.py` 用 PyInstaller 打包 GUI 为 `dist/FileTools/FileTools.exe`（目录模式，`--onefile` 为单文件）；产物自带全部依赖，构建前需 `pip install pyinstaller`。

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
