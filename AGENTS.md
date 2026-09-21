# AGENTS.md

本文件为在此仓库中工作的代码助手提供项目说明。

## 项目结构

主分支只保留 `file_tools/` 本地文件处理工具包：

1. 核心工具位于 `file_tools/core/`，统一 CLI 入口为 `python -m file_tools`（懒加载核心模块）；可视化界面位于 `file_tools/gui/` 包，入口 `python -m file_tools.gui`；打包为 exe 用根目录 `python build_exe.py`。

已弃置功能仅存档于 `archive` 分支（当前只包含上海地铁票价 `shanghai_metro_fare/`，该分支不再保留任何 file_tools 历史版本——需要时看主分支 commit 记录）；不要把它们加回主分支。

用户输入、输出路径必须来自命令行参数或交互输入，不要在脚本中加入本机绝对路径或要求用户修改的路径常量。脚本自身附带的数据和模板可以通过 `Path(__file__)` 定位。

## 文件处理工具

核心工具在 `file_tools/core/`，每项均可独立 CLI 运行，GUI 与交互菜单在执行时才导入它们（`image_decrypt` 依赖较重，避免入口启动时加载）。

### `file_tools/core/image_decrypt.py`

- 原 `demo.py`，支持 5 种图像混淆/解混淆模式，每种模式均提供双向处理。
- 使用 Numba JIT 加速像素变换，基于 MD5 生成伪随机排列。
- 独立入口：`python -m file_tools.core.image_decrypt INPUT OUTPUT --operation {encrypt,decrypt} --mode MODE --key KEY`。
- 输入为目录时批量处理，支持 `--suffix`、`--recursive` 和 `--overwrite`，并保留相对目录结构。
- 依赖 `numpy`、`Pillow`、`numba`。

### `file_tools/core/image_convert.py`

- 图片格式转换（Pillow 重编码，webp/jpg/png/bmp 互转）。与 media_to_mp4 区别：那是 ffmpeg 无损封装（只换容器），本模块是真正的解码重编码。
- 透明通道转 jpg/bmp 自动垫白底（`_prepare`，先 `ImageOps.exif_transpose` 纠正方向）；动图只取首帧；`--quality` 仅 jpg/webp 生效。
- 与目标同后缀的文件跳过；目标重名跳过不覆盖；输出默认在原图同目录，`--output-dir` 时平铺存放（重名跳过）；坏图计失败不中断；`--delete-original` 成功后删原图（默认关）。
- 目录模式默认筛选 `SOURCE_SUFFIXES`（对齐 image_decrypt 的常见图片集合），`--ext` 可覆盖；转换前 `prepared.load()` 释放源文件句柄，Windows 上删除原图才不会因句柄占用失败。
- 独立入口：`python -m file_tools.core.image_convert SOURCE -t {jpg,png,webp,bmp} [-o DIR] [--quality N] [--delete-original] [--ext ...] [--recursive] [--dry-run]`；GUI 视图 `convert_view.py`（源路径可文件可目录 + 格式单选 + 质量）。

### `file_tools/core/media_to_mp4.py`

- 使用 ffmpeg 将真实内容为视频、但扩展名可能异常的文件无损封装为 MP4。
- 目录模式通过 `--suffix` 指定筛选后缀，支持 `--recursive`、`--output-dir`、`--overwrite` 和 `--dry-run`。
- 独立入口：`python -m file_tools.core.media_to_mp4 SOURCE [选项]`。
- **ffmpeg 内置策略（功能不出域）**：`find_ffmpeg()` 查找顺序为环境变量 `FILE_TOOLS_FFMPEG` → exe 同目录 → `imageio_ffmpeg` 包内置二进制（随 exe 打包）→ 系统 PATH；所有外部进程调用必须走 `run_hidden()`（Windows 下加 `CREATE_NO_WINDOW`，不弹 cmd 窗口），其他模块（如 media_grab）复用这两个函数。
- 普通图片、字体等非视频内容应报告转换失败，不应伪造 MP4。

### `file_tools/core/media_grab.py`

- 参考猫抓插件的网页媒体嗅探下载，识别范围对齐猫抓后缀表（`MEDIA_SUFFIXES`，视频/音频/清单 30 余种）；直连扫描标签属性（`src`/`href`/`data-*`）、JSON 字段（`url`/`source`/`file`）与裸 URL，还原 `\/`、`\u002F` 转义，相对地址经 `urljoin` 补全。
- **双嗅探模式**（CLI `--mode {direct,browser}` / GUI 单选；默认直连）：
  - 直连模式：requests 直接抓页面，失败自动 curl_cffi 浏览器指纹回退；仍失败时报错并提示可改用浏览器模式（不自动切换）。
  - 浏览器模式：`browser_sniff.py` 启动本机 Chrome/Edge（独立临时配置 + CDP），工具自动尝试播放页面视频（开播窗口 2 分钟内每 8 秒对暂停中的 video 执行 play，用户手动播放不受影响），并经 Network 事件捕获媒体地址（含完整请求头）；`Target.setAutoAttach`（flatten）把跨域 iframe/弹出的新标签一并纳入捕获；GUI 点「完成嗅探」按钮（stop_event）或关闭浏览器窗口即结束嗅探；失败只报错、不引导回直连。
- **嗅探浏览器驻留与预览复用**：GUI 嗅探用 `keep_open=True`，点「完成嗅探」后浏览器不关闭（`_stash_shared_session` 驻留，atexit 统一回收；用户手动关掉窗口则立即回收）；`open_tab_in_shared_browser()` 让浏览器模式预览在同一窗口开新标签页（浏览器级 CDP `Target.createTarget`），浏览器已关才回退系统浏览器。
- **HLS 主视频识别**（`_m3u8_overview`）：嗅探结束自动取回每个 m3u8 解析，把分辨率（AES 分段先解密再喂内置 `ffmpeg -i`，`parse_ffmpeg_resolution`）与时长写进 label（如 `1280x720 · 约110 分钟`，主清单标 `主清单 · 1080p/720p/360p`），体积估算（首段+中段采样 × 段数，`size_estimate=True`）进“大小”列显示带 ≈——很多站点主视频是无后缀带令牌的播放列表（如 `…/index.txt?t=…`），不识别就和预览小视频分不开；GUI 默认勾选体积估算最大的 m3u8。
- **不提供代理功能**（已整体移除）。下载走多级传输回退 `_TransportChain`（按主机记忆首次成功的方式）：直连 requests → curl_cffi 指纹 → SNI 精简（TLS SNI 用父域、Host 不变，用于被 SNI 阻断的 CDN；证书校验降级会在日志明确提示）→ 浏览器引擎（`BrowserHTTPSession` 页面内 fetch + CDP Fetch 域拦截响应 + IO 流式读出，请求上下文与真实播放器一致）。
- 内置 bilibili 适配：页面 `__INITIAL_STATE__` 取 bvid/cid/title，调 `x/player/playurl`（无需 wbi）拿 DASH 流，产出 `dash-video`/`dash-audio` 资源（带清晰度标签），下载主 CDN 失败自动换 `backupUrl`；选中视频+音频后用内置 ffmpeg 合流为以视频标题命名的 MP4。
- m3u8：主播放列表自动选最高带宽，分段并发下载合并（瞬时 5xx/限流失败的分段收尾串行补抓两轮）；AES-128 分段（`EXT-X-KEY`）依赖 `pycryptodome`/`cryptography`（懒导入）；m3u8 输出文件名优先用页面标题。
- 资源统一为 `MediaResource`（url/suffix/kind/label/size/title/headers/fallback_urls）；`sniff_media()` 直连嗅探（`probe=True` 时并发 HEAD 探测体积，上限 `PROBE_LIMIT`）、`sniff_media_browser()` 浏览器嗅探、`download_resources()` 下载选中资源（GUI 用）、`grab_media()` 保留序号流程（CLI/菜单用，先 `--list` 看明细再 `--pick`）。
- 预览分模式：直连模式用 `capture_preview_frames()`（内置 ffmpeg 抽帧，`gui/preview.py` 软件内缩略图，音频流只解析流信息）；浏览器模式用 `open_external_preview()`——本地 127.0.0.1 预览代理（`_PreviewProxy`，空闲 30 分钟自动关闭），优先在嗅探时打开的浏览器同一窗口开新标签页（回退系统浏览器打开），m3u8 经代理改写后由内置 `data/hls.min.js`（hls.js v1.5.20，Apache-2.0）播放——hls 播放页必须内联 `<script src="/hls.js">`（缺失则 Hls 未定义、预览放不出，selftest 有断言），代理转发自动走多级传输回退。
- 独立入口：`python -m file_tools.core.media_grab URL [-o OUTPUT] [--mode {direct,browser}] [--list] [--probe] [--pick N ...] [--all] [--no-mp4] [--referer URL] [--max-capture-seconds N]`。

### `file_tools/core/browser_sniff.py`

- 浏览器模式的全部 CDP 机制（依赖 `websocket-client`）：
  - `find_browser_exe()` 按 Chrome→Edge 常见路径查找浏览器。
  - `BrowserSession`：独立临时用户数据目录（不碰用户真实配置/Cookie/扩展）+ 随机 127.0.0.1 调试端口 + `--no-first-run` 等安全参数；结束即终止进程并删除临时目录；WebSocket 用 `suppress_origin` 免 `--remote-allow-origins` 宽松开关。
  - `CDPClient`：单读线程分发（响应按 id 路由、事件进列表）；`call()`/`send()` 支持 `session_id`（flatten 自动挂载的子会话）；`send()` 用于可能与 Fetch 拦截互锁的 `Page.navigate`（只发不等）。
  - `capture_via_browser()`：Network 事件 → `MediaRecorder`（纯逻辑、可离线测试）按后缀或 MIME 筛媒体地址（跳过 `blob:`/`data:`），录制完整请求头与页面标题；周期性对暂停中的视频自动播放（`_AUTO_PLAY_JS`）；`keep_open=True` 结束后浏览器经 `_stash_shared_session` 驻留、`open_tab_in_shared_browser()` 复用；`on_ready(session, cdp)` 钩子供自动化测试注入交互。
  - `BrowserHTTPSession`：伪装成 requests.Session 的浏览器引擎传输（页面内 fetch + 响应虹吸）；无头启动但覆盖 UA（去掉 HeadlessChrome 字样防 CDN 识别），先暖场导航到资源页面再取资源；CDP 事件按 URL 匹配，调用必须串行（`_TransportChain` 已加锁）。

### `file_tools/core/suffix_manager.py`

- 合并原 `dot1_suffix.py` 与 `delete_copy_files.py`：标记（如 `.1`、`副本`）由用户自定义。
- `add`：点开头标记追加到完整文件名末尾（`a.txt` → `a.txt.1`），文字标记加在扩展名前（`a.txt` → `a副本.txt`）；`remove` 为其逆操作（单层）；`delete` 删除文件名或主文件名以标记结尾的文件。
- 独立入口：`python -m file_tools.core.suffix_manager {add,remove,delete} TARGET --marker MARKER [--recursive] [--dry-run]`。
- 目标名冲突跳过；删除/重命名均有预览语义。

### `file_tools/core/image_rename.py`

- 图片批量重命名：把选中的图片**剪切**到「输出目录/统一名称」子文件夹下，按 `名称-1、名称-2…` 连续编号。
- 三个场景同为一条路径：选一个文件夹/若干图片 = 批量重命名；选多个文件夹 = 按给定顺序连续编号（合并）；目标文件夹已有 `名称-N` = 自动从最大编号后续接（追加，`next_index`）。
- 编号对所有后缀统一分配（绝不出现 `名称-1.jpg` 与 `名称-1.png` 并存），后缀原样保留（含大小写）；默认后缀 `{.jpg, .jpeg, .png}`（大小写不敏感），`collect_images` 文件夹内自然排序（`img-2` 在 `img-10` 前）、按 `resolve()` 去重，已在目标文件夹内的文件跳过。
- 独立入口：`python -m file_tools.core.image_rename SOURCE [SOURCE ...] -o OUTPUT -n NAME [--recursive] [--dry-run]`；GUI 视图 `rename_view.py`（源路径列表 + 添加文件夹/图片/移除选中）。

### `file_tools/core/fanqie_novel.py`

- 番茄小说搜索下载（仅供学习研究）。**纯后端薄客户端**：全部搜索/下载由内置
  `data/TomatoNovelDownloader.exe`（上游 Tomato-Novel-Downloader v2.4.15，MIT，
  许可文本在 data/ 内）完成；本模块以 `--server` 模式将其 spawn 在 127.0.0.1:38474
  （`TOMATO_WEB_ADDR`），经其 HTTP API（`/api/search`、`/api/preview/{id}`、
  `POST /api/jobs`、`GET /api/jobs` 轮询）驱动官方 API 明文链路；产物从其
  save_dir 复制到用户输出目录；后端进程全局复用，atexit 终止。
- 不要在此模块加入网页抓取/字体反混淆逻辑（上游 App 批量接口需闭源 X-Helios
  签名，社区四签名实测被服务端静默拒绝，网页正文方案已被本模块淘汰）。
- 独立入口：`python -m file_tools.core.fanqie_novel {search,download}`；GUI 视图 `novel_view.py`。

### `file_tools/core/download_images.py`

- 由根目录独立脚本改造并入：从 CSV（第一列）或 TXT（每行）读取图片 URL，支持 `#` 注释与空行。
- 并发下载（默认 4）、重试、失败不中断；文件名取自 URL，无扩展名按 `Content-Type` 补全，同名自动追加序号。
- 独立入口：`python -m file_tools.core.download_images -i LIST [-o OUTPUT] [--concurrency N] [--overwrite]`。

### `file_tools/gui/` 可视化界面包

- 布局：深色侧边栏导航 + 内容区（标题 + 白色卡片表单）+ 深色日志面板 + 状态栏，视图切换不销毁表单状态。
- `theme.py`：`enable_dpi_awareness()` 必须在创建 Tk 之前调用（进程级 DPI 感知，否则窗口和文件对话框在高分屏上模糊），`setup_theme()` 计算缩放比例并配置字体与 ttk 样式；所有尺寸经过 `scale()` 换算，新增控件不要写死像素。
- `app.py` `main()`：创建根窗口后先 `withdraw()`，构建与居中完成后再 `deiconify()` 一次性显示——防止启动时“先小窗后放大”的闪烁，勿改动此顺序。
- `runner.py`：任务在后台线程执行，print 经队列交给主线程，同一时间只允许一个任务；`submit()` 支持可选 `on_done(message, succeeded)` 完成回调（主线程执行，用于视图刷新嗅探结果）。
- `views/`：每个工具一个视图类（ID/TITLE/SUBTITLE + `build()` + `_run()`），在 `views/__init__.py` 注册；核心模块在 worker 内懒导入。`grab_view` 为两段式：选模式（直连/浏览器）→ 嗅探 → 资源表格（勾选/全选/预览/复制链接，双击行预览）→ 下载选中；直连模式预览在软件内抽帧，浏览器模式经本地代理在系统浏览器播放；`novel_view` 为搜索列表 + 下载表单（格式/章节范围/代理）；`rename_view` 为源路径列表（Treeview 多选，添加文件夹/图片、移除选中）+ 输出目录 + 统一名称，三场景（重命名/合并/追加）共用一次提交；`convert_view` 为源路径（文件/目录双浏览按钮）+ 格式单选 + 质量；`widgets.py` 的表单辅助照常复用。
- 入口：`python -m file_tools.gui`、交互菜单选项 9、`FileTools.exe`。

### `file_tools/selftest.py` 与 `build_exe.py`

- `python -m file_tools.selftest`（或 `FileTools.exe --selftest`）在当前环境冒烟测试各项核心工具（media_grab 用本地 HTTP 服务器测试嗅探/合并/AES 解密/ffmpeg 抽帧预览；download_images 用本地服务器测试下载；image_rename 用临时目录测试合并/追加/预览/递归；image_convert 用 PIL 造图测试透明垫白底/坏图容错/递归/删原图；fanqie_novel 与 browser_sniff 仅离线测试纯函数——媒体识别/CDP 事件消费/父域计算/播放列表改写；preview_proxy 离线测试本地预览代理的透传与 m3u8 改写，均不依赖外网、不启动浏览器），全部通过退出码 0。
- `python build_exe.py` 用 PyInstaller 打包 GUI 为 `dist/FileTools/FileTools.exe`（目录模式，`--onefile` 为单文件）；`--collect-all imageio_ffmpeg` 把 ffmpeg 打进产物，`core/data/`（番茄后端、hls.min.js）整体随包；构建前需 `pip install pyinstaller`。

## 环境与分支

- Python 3.10+
- 虚拟环境通常位于 `.venv/`
- 安装依赖：`pip install -r requirements.txt`（ffmpeg 由 `imageio-ffmpeg` 提供，系统无需安装）
- `archive` 分支为弃置功能存档（当前仅上海地铁票价工具），只读不改
