# 个人 Python 工具集

项目由三个相互独立的部分组成：本地文件处理工具集、图片下载 CLI 和上海地铁票价查询。

## 文件处理工具集

`file_tools/` 集中存放本地文件处理脚本，推荐通过统一交互入口启动：

```powershell
python -m file_tools
```

菜单提供以下功能：

1. 图像混淆/解混淆
2. 伪装媒体文件转 MP4
3. 添加 `.1` 后缀
4. 移除 `.1` 后缀
5. 删除文件名以“副本”结尾的文件

每项工具也可以独立使用命令行参数运行。

### 图像混淆/解混淆

支持方块混淆、行像素混淆、像素混淆以及两种 PicEncrypt 模式，每种模式均可双向处理：

```powershell
python -m file_tools.image_decrypt INPUT OUTPUT --operation encrypt --mode 1 --key KEY
python -m file_tools.image_decrypt INPUT OUTPUT --operation decrypt --mode 1 --key KEY

# 批量处理目录，保留子目录结构
python -m file_tools.image_decrypt INPUT_DIR OUTPUT_DIR --operation encrypt --mode 1 --key KEY --recursive

# 只处理指定后缀
python -m file_tools.image_decrypt INPUT_DIR OUTPUT_DIR --operation decrypt --mode 1 --key KEY --suffix png webp
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
python -m file_tools.media_to_mp4 INPUT

# 按后缀批量处理目录
python -m file_tools.media_to_mp4 TARGET --suffix jpeg woff2 ts

# 递归预览
python -m file_tools.media_to_mp4 TARGET --suffix jpeg,wOFF2,ts --recursive --dry-run
```

可选参数包括 `--output-dir`、`--overwrite`、`--recursive` 和 `--dry-run`。实际转换需要安装 [ffmpeg](https://ffmpeg.org/) 并将其加入 `PATH`。

### `.1` 后缀管理

```powershell
python -m file_tools.dot1_suffix add TARGET
python -m file_tools.dot1_suffix remove TARGET --recursive --dry-run
```

- 默认只处理目标目录的直接文件。
- `--recursive` 递归处理子目录。
- `--dry-run` 只预览，不重命名。
- 添加时跳过已经以 `.1` 结尾的文件，目标名称冲突时也会跳过。

### 删除“副本”文件

递归匹配文件名（不含扩展名）以“副本”结尾的文件。默认仅预览，必须使用 `--execute` 才会实际删除：

```powershell
python -m file_tools.delete_copy_files TARGET
python -m file_tools.delete_copy_files TARGET --execute
```

## 图片下载 CLI

`download_images.py` 是独立工具，不属于 `file_tools` 菜单。CSV 每行第一列应为一个图片 URL：

```powershell
python download_images.py --input URLS.csv --output OUTPUT_DIR
```

短参数和其他选项：

```powershell
python download_images.py -i URLS.csv -o downloaded_images --timeout 30 --delay 0.5
```

- `--input` 为必需参数。
- `--output` 默认是当前目录下的 `downloaded_images/`。
- 已存在文件会被跳过。
- 下载采用流式写入，单个 URL 失败不会中断其余任务。
- 依赖 `requests`。

## 上海地铁票价

`shanghai_metro_fare/` 是独立工具，提供命令行版和自包含网页版：

```powershell
python shanghai_metro_fare/metro_fare.py
python shanghai_metro_fare/metro_fare.py 人民广场 陆家嘴
python shanghai_metro_fare/metro_fare.py --selftest
```

网页版可直接打开 `shanghai_metro_fare/index.html`。详细说明见 [shanghai_metro_fare/README.md](shanghai_metro_fare/README.md)。

## 环境要求

- Python 3.10+
- Python 依赖：`pip install -r requirements.txt`
- 媒体转 MP4 功能额外需要系统安装 ffmpeg
- 上海地铁工具只使用 Python 标准库

## 目录结构

```text
.
├── file_tools/
│   ├── __init__.py
│   ├── __main__.py
│   ├── image_decrypt.py
│   ├── media_to_mp4.py
│   ├── dot1_suffix.py
│   └── delete_copy_files.py
├── download_images.py
├── shanghai_metro_fare/
├── requirements.txt
├── CLAUDE.md
└── README.md
```

所有用户文件路径均通过命令行参数或交互菜单传入，不需要修改脚本源码。
