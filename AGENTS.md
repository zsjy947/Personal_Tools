# AGENTS.md

本文件为在此仓库中工作的代码助手提供项目说明。

## 项目结构

主分支只保留 `file_tools/` 本地文件处理工具包：

1. 核心工具位于 `file_tools/core/`，统一 CLI 入口为 `python -m file_tools`（懒加载核心模块）；可视化界面位于 `file_tools/gui/` 包，入口 `python -m file_tools.gui`；打包为 exe 用根目录 `python build_exe.py`。

已弃置功能（上海地铁票价 `shanghai_metro_fare/`、根目录版图片下载脚本、旧版 `.1` 后缀/删除副本工具）归档在 `archive` 分支，仅作存档不维护；不要把它们加回主分支。

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
- **ffmpeg 内置策略（功能不出域）**：`find_ffmpeg()` 查找顺序为环境变量 `FILE_TOOLS_FFMPEG` → exe 同目录 → `imageio_ffmpeg` 包内置二进制（随 exe 打包）→ 系统 PATH；所有外部进程调用必须走 `run_hidden()`（Windows 下加 `CREATE_NO_WINDOW`，不弹 cmd 窗口），其他模块（如 media_grab）复用这两个函数。
- 普通图片、字体等非视频内容应报告转换失败，不应伪造 MP4。

### `file_tools/core/media_grab.py`

- 参考猫抓插件的网页媒体嗅探下载，识别范围对齐猫抓后缀表（`MEDIA_SUFFIXES`，视频/音频/清单 30 余种）；扫描标签属性（`src`/`href`/`data-*`）、JSON 字段（`url`/`source`/`file`）与裸 URL，还原 `\/`、`\u002F` 转义，相对地址经 `urljoin` 补全。
- 内置 bilibili 适配：页面 `__INITIAL_STATE__` 取 bvid/cid/title，调 `x/player/playurl`（无需 wbi）拿 DASH 流，产出 `dash-video`/`dash-audio` 资源（带清晰度标签），下载主 CDN 失败自动换 `backupUrl`；选中视频+音频后用内置 ffmpeg 合流为以视频标题命名的 MP4。
- m3u8：主播放列表自动选最高带宽，分段并发下载合并；AES-128 分段（`EXT-X-KEY`）依赖 `pycryptodome`/`cryptography`（懒导入）。
- 资源统一为 `MediaResource`（url/suffix/kind/label/size/title/headers/fallback_urls）；`sniff_media()` 嗅探（`probe=True` 时并发 HEAD 探测体积，上限 `PROBE_LIMIT`）、`download_resources()` 下载选中资源（GUI 用）、`grab_media()` 保留序号流程（CLI/菜单用，先 `--list` 看明细再 `--pick`）。
- 全链路支持代理（GUI「代理」框 / CLI `--proxy`，嗅探与下载共用）；连接被拒时 `_fetch_page()` 自动走 curl_cffi 浏览器指纹回退（懒导入），仍失败则抛出带代理提示的错误。
- 预览：`start_preview_server()` 本地代理服务器（`/i/<序号>` 直接代理资源、`/u/<token>` 代理 m3u8 重写后的分段/密钥地址）+ `open_preview()` 生成预览页用浏览器内嵌播放（m3u8 走 hls.js），不触发浏览器下载。
- 独立入口：`python -m file_tools.core.media_grab URL [-o OUTPUT] [--list] [--probe] [--pick N ...] [--all] [--no-mp4] [--referer URL] [--proxy URL]`。

### `file_tools/core/suffix_manager.py`

- 合并原 `dot1_suffix.py` 与 `delete_copy_files.py`：标记（如 `.1`、`副本`）由用户自定义。
- `add`：点开头标记追加到完整文件名末尾（`a.txt` → `a.txt.1`），文字标记加在扩展名前（`a.txt` → `a副本.txt`）；`remove` 为其逆操作（单层）；`delete` 删除文件名或主文件名以标记结尾的文件。
- 独立入口：`python -m file_tools.core.suffix_manager {add,remove,delete} TARGET --marker MARKER [--recursive] [--dry-run]`。
- 目标名冲突跳过；删除/重命名均有预览语义。

### `file_tools/core/download_images.py`

- 由根目录独立脚本改造并入：从 CSV（第一列）或 TXT（每行）读取图片 URL，支持 `#` 注释与空行。
- 并发下载（默认 4）、重试、失败不中断；文件名取自 URL，无扩展名按 `Content-Type` 补全，同名自动追加序号。
- 独立入口：`python -m file_tools.core.download_images -i LIST [-o OUTPUT] [--concurrency N] [--overwrite]`。

### `file_tools/gui/` 可视化界面包

- 布局：深色侧边栏导航 + 内容区（标题 + 白色卡片表单）+ 深色日志面板 + 状态栏，视图切换不销毁表单状态。
- `theme.py`：`enable_dpi_awareness()` 必须在创建 Tk 之前调用（进程级 DPI 感知，否则窗口和文件对话框在高分屏上模糊），`setup_theme()` 计算缩放比例并配置字体与 ttk 样式；所有尺寸经过 `scale()` 换算，新增控件不要写死像素。
- `app.py` `main()`：创建根窗口后先 `withdraw()`，构建与居中完成后再 `deiconify()` 一次性显示——防止启动时“先小窗后放大”的闪烁，勿改动此顺序。
- `runner.py`：任务在后台线程执行，print 经队列交给主线程，同一时间只允许一个任务；`submit()` 支持可选 `on_done(message, succeeded)` 完成回调（主线程执行，用于视图刷新嗅探结果）。
- `views/`：每个工具一个视图类（ID/TITLE/SUBTITLE + `build()` + `_run()`），在 `views/__init__.py` 注册；核心模块在 worker 内懒导入。`grab_view` 为两段式：嗅探 → 资源表格（勾选/全选/预览/复制链接，双击行预览）→ 下载选中；`widgets.py` 的表单辅助照常复用。
- 入口：`python -m file_tools.gui`、交互菜单选项 6、`FileTools.exe`。

### `file_tools/selftest.py` 与 `build_exe.py`

- `python -m file_tools.selftest`（或 `FileTools.exe --selftest`）在当前环境冒烟测试五项核心工具（media_grab 用本地 HTTP 服务器测试嗅探/合并/AES 解密；download_images 用本地服务器测试下载，均不依赖外网），全部通过退出码 0。
- `python build_exe.py` 用 PyInstaller 打包 GUI 为 `dist/FileTools/FileTools.exe`（目录模式，`--onefile` 为单文件）；`--collect-all imageio_ffmpeg` 把 ffmpeg 打进产物；构建前需 `pip install pyinstaller`。

## 环境与分支

- Python 3.10+
- 虚拟环境通常位于 `.venv/`
- 安装依赖：`pip install -r requirements.txt`（ffmpeg 由 `imageio-ffmpeg` 提供，系统无需安装）
- `archive` 分支为弃置功能存档（上海地铁票价、旧工具），只读不改
