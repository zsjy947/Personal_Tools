# 个人 Python 工具集

主分支仅保留本地文件处理工具集 `file_tools/`；已弃置的功能（上海地铁票价查询等）
归档在 `archive` 分支，需要时可随时检出，不在主分支维护。

## 文件处理工具集

`file_tools/` 集中存放本地文件处理脚本，推荐通过统一交互入口启动：

```powershell
python -m file_tools
```

菜单提供以下功能：

1. 图像混淆/解混淆
2. 伪装媒体文件转 MP4
3. 文件名标记管理（添加/移除标记、删除副本等）
4. 网页媒体嗅探下载（含 m3u8 合并、B 站音视频合流）
5. 图片批量下载（CSV/TXT 链接列表）
6. 打开可视化界面

每项工具也可以独立使用命令行参数运行，核心模块位于 `file_tools/core/`。

### 可视化界面

图形界面为深色侧边栏 + 卡片表单布局，已做高 DPI 适配（高分屏不模糊），路径一律通过资源管理器对话框选择，执行过程与结果汇总显示在底部日志区。窗口在完成构建与定位后一次性显示，启动无闪烁。三种启动方式：

```powershell
# 1. 双击打包产物（推荐，见下文构建方法）
dist\FileTools\FileTools.exe

# 2. 命令行启动
python -m file_tools.gui

# 3. 统一交互菜单中选择「6. 打开可视化界面」
python -m file_tools
```

界面只依赖标准库 tkinter；各工具在执行时才加载自身依赖，缺少依赖时界面仍能打开，仅对应工具执行时报错。

### 打包成 exe

不再使用 `.pyw` 脚本启动，改为用 PyInstaller 打包（需先 `pip install pyinstaller`）：

```powershell
python build_exe.py             # 目录模式：dist/FileTools/FileTools.exe，启动快，分发整个文件夹
python build_exe.py --onefile   # 单文件模式：dist/FileTools.exe，便于拷贝，启动需解压
```

- 产物自带 Python 与全部依赖（含 numpy/numba/Pillow），体积约 150 MB。
- ffmpeg 通过 `imageio-ffmpeg` 一并打包进 exe：媒体转 MP4、m3u8 封装、B 站音视频
  合流全部内置执行，不依赖系统安装，也不会弹出外部命令行窗口；如需替换版本，
  把 `ffmpeg.exe` 放到 exe 同目录即可。
- 可用 `FileTools.exe --selftest` 验证打包产物内核心工具是否正常。

### 图像混淆/解混淆

支持方块混淆、行像素混淆、像素混淆以及两种 PicEncrypt 模式，每种模式均可双向处理：

```powershell
python -m file_tools.core.image_decrypt INPUT OUTPUT --operation encrypt --mode 1 --key KEY
python -m file_tools.core.image_decrypt INPUT OUTPUT --operation decrypt --mode 1 --key KEY

# 批量处理目录，保留子目录结构
python -m file_tools.core.image_decrypt INPUT_DIR OUTPUT_DIR --operation encrypt --mode 1 --key KEY --recursive

# 只处理指定后缀
python -m file_tools.core.image_decrypt INPUT_DIR OUTPUT_DIR --operation decrypt --mode 1 --key KEY --suffix png webp
```

- 模式 1 至 3 的密钥为字符串。
- 模式 4 至 5 的密钥为大于 0 且小于 1 的数字。
- 模式 1 使用 `32 × 32` 方块网格，图片宽度和高度都必须能被 32 整除。
- `--operation encrypt` 执行混淆，`--operation decrypt` 执行解混淆；默认解混淆。
- 输入为目录时自动启用批量模式，默认处理常见图片格式；支持 `--suffix`、`--recursive` 和 `--overwrite`。
- 批量输出会保留输入目录中的相对目录结构，默认跳过已有文件。
- 依赖 `numpy`、`Pillow` 和 `numba`。

### 伪装媒体文件转 MP4

处理真实内容为视频、但扩展名可能是 `.jpeg`、`.woff2`、`.ts` 等任意后缀的文件。工具由 ffmpeg 探测真实内容，并使用 `-c copy` 无损封装为 MP4；普通图片、字体等非视频文件无法转换。

```powershell
# 单个文件
python -m file_tools.core.media_to_mp4 INPUT

# 按后缀批量处理目录
python -m file_tools.core.media_to_mp4 TARGET --suffix jpeg woff2 ts

# 递归预览
python -m file_tools.core.media_to_mp4 TARGET --suffix jpeg,wOFF2,ts --recursive --dry-run
```

可选参数包括 `--output-dir`、`--overwrite`、`--recursive` 和 `--dry-run`。ffmpeg 已随依赖内置（`imageio-ffmpeg`），无需系统安装；调用过程隐藏控制台窗口。也可用环境变量 `FILE_TOOLS_FFMPEG` 指定自定义 ffmpeg。

### 网页媒体嗅探下载

参考猫抓插件的识别方式：媒体后缀表对齐猫抓可识别范围（视频/音频/直播清单共 30 余种），同时扫描标签属性（`src`/`href`/`data-*`）、JSON 字段（`url`/`source`/`file` 等）与页面中的裸 URL，JSON 转义自动还原，相对地址自动补全。

- 可视化界面中先「嗅探资源」得到列表（类型/清晰度/大小/格式/地址），支持勾选、
  全选、浏览器预览、复制链接，再「下载选中」。
- 预览在软件内完成：预览窗口用内置 ffmpeg 抽取视频各时间点缩略图（音频显示流信息，
  图片直接展示），点击缩略图可放大，不打开浏览器。
- 连接被重置/拒绝直连的站点：在界面「代理」框或 CLI `--proxy` 填入代理地址
  （如 `http://127.0.0.1:7890`）；不填时代也会自动回退——先尝试 curl_cffi 浏览器
  指纹，再探测系统代理与本机常见代理端口（7890/7897/10809 等），探测成功的代理
  会自动用于后续下载。注意：浏览器扩展内置远程节点时本机并无代理端口，需在代理
  客户端开启 HTTP/系统代理后工具才能使用。
- 内置 bilibili 站点适配：解析页面 `__INITIAL_STATE__` 后调用 playurl 接口获取
  DASH 音视频流，勾选视频+音频后自动用内置 ffmpeg 合流为单个 MP4（以视频标题命名）；
  主 CDN 失败自动切换备用 CDN。
- m3u8（HLS）自动解析分段列表，并发下载合并，支持主播放列表选最高画质与
  AES-128 加密分段（依赖 `pycryptodome`）。

```powershell
# 嗅探并列出资源明细（类型/说明/大小/地址）
python -m file_tools.core.media_grab https://www.bilibili.com/video/BVxxxxxxxx --list --probe

# 先 --list 查看，再按序号下载（视频+音频一起选会自动合流 MP4）
python -m file_tools.core.media_grab https://www.bilibili.com/video/BVxxxxxxxx --pick 1 5

# 直接给 m3u8 地址
python -m file_tools.core.media_grab https://cdn.example.com/video.m3u8 --no-mp4
```

- 默认识别的后缀覆盖猫抓常见类型（`mp4 m4s mkv webm flv ts m3u8 mpd mp3 flac …`），可用 `--suffix` 调整。
- `--output` 指定输出目录（默认 `media_downloads/`），`--overwrite` 覆盖已有文件，`--referer` 处理防盗链。

### 文件名标记管理

合并原「添加/移除 .1 后缀」与「删除副本文件」两个工具：标记由用户自定义（如 `.1`、`副本`），
一次完成添加、移除或删除。

```powershell
# 添加标记：.1 追加到文件名末尾（a.txt -> a.txt.1）
python -m file_tools.core.suffix_manager add TARGET --marker .1

# 移除标记（与添加互逆，单层）
python -m file_tools.core.suffix_manager remove TARGET --marker .1 --recursive

# 删除带标记的文件：文字标记匹配主文件名末尾（b副本.txt 匹配“副本”）
python -m file_tools.core.suffix_manager delete TARGET --marker 副本
```

- 点开头的标记加在完整文件名末尾，文字标记加在扩展名之前；移除/删除同时兼容两种位置。
- `--dry-run` 仅预览（GUI 中默认勾选「仅预览」）。
- 目标名称冲突时跳过；`--recursive` 递归处理子目录。

### 图片批量下载

由原根目录独立脚本改造并入 `file_tools`：输入 CSV（取每行第一列）或 TXT（每行一个 URL）链接列表，并发下载图片。

```powershell
python -m file_tools.core.download_images -i URLS.csv -o downloaded_images
python -m file_tools.core.download_images -i urls.txt --concurrency 4 --overwrite
```

- 文件名取自 URL；无扩展名时按响应 `Content-Type` 补全；同名自动追加序号。
- 已存在文件默认跳过（`--overwrite` 覆盖）；单文件失败自动重试且不中断其余任务。
- 支持 `#` 注释行与空行；依赖 `requests`。

## 归档：archive 分支

`git checkout archive` 可查看历史功能存档（上海地铁票价工具、根目录版图片下载脚本、
旧版 `.1` 后缀/删除副本工具等）。该分支仅作存档，不再维护；如需恢复某个功能，
从该分支检出对应目录即可。

## 环境要求

- Python 3.10+
- Python 依赖：`pip install -r requirements.txt`（ffmpeg 由 `imageio-ffmpeg` 提供，无需系统安装）
- 打包 exe：`pip install pyinstaller` 后运行 `python build_exe.py`

## 目录结构

```text
.
├── file_tools/
│   ├── __main__.py          # CLI 交互菜单（懒加载核心模块）
│   ├── selftest.py          # 核心/打包产物自检
│   ├── core/                # 五项核心工具（可独立 CLI 运行）
│   │   ├── image_decrypt.py
│   │   ├── media_to_mp4.py  # ffmpeg 内置查找（imageio-ffmpeg → PATH）
│   │   ├── media_grab.py    # 网页媒体嗅探（猫抓式识别 + B 站 DASH + m3u8）
│   │   ├── suffix_manager.py# 文件名标记管理（增/删标记、删文件）
│   │   └── download_images.py
│   └── gui/                 # tkinter 可视化界面包
│       ├── __main__.py      # python -m file_tools.gui / PyInstaller 入口
│       ├── app.py           # 主窗口：侧边栏、内容区、日志、状态栏
│       ├── theme.py         # DPI 感知、缩放、配色与 ttk 样式
│       ├── widgets.py       # 通用控件与表单辅助
│       ├── runner.py        # 后台任务执行器（支持完成回调）
│       ├── views/           # 各工具视图（嗅探页含资源列表/预览/勾选）
│       └── assets/app.ico   # 应用图标
├── build_exe.py             # PyInstaller 打包脚本（内置 ffmpeg）
├── requirements.txt
├── AGENTS.md
└── README.md
```

所有用户文件路径均通过命令行参数或交互菜单传入，不需要修改脚本源码。
