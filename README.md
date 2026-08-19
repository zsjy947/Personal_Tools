# 个人 Python 脚本工具集

个人日常使用的 Python 小工具集合：图像解密、视频转换、文件批量操作、图片下载、地铁票价查询等。每个 `.py` 文件相互独立，可单独运行。

## 工具一览

| 工具 | 功能 | 用法 |
|---|---|---|
| `demo.py` | 图像解混淆/解密（5 种模式） | `python demo.py`（交互式） |
| `ts2mp4.py` | TS 视频转 MP4 | `python ts2mp4.py`（需设置 `TS_FOLDER`） |
| `modify.py` | 批量添加/移除 `.1` 后缀（单层目录） | `python modify.py`（需修改 `target_folder`） |
| `remove_dot1_suffix.py` | 递归移除 `.1` 后缀 | `python remove_dot1_suffix.py <目录> [--dry-run]` |
| `delete_copy_files.py` | 递归删除"副本"文件 | `python delete_copy_files.py <目录> [--dry-run]` |
| `download_images.py` | 批量下载图片 | `python download_images.py [-i url.csv] [-o 输出目录]` |
| `shanghai_metro_fare/` | 上海地铁最短路径与票价 | 详见 [shanghai_metro_fare/README.md](shanghai_metro_fare/README.md) |

## 各工具说明

### demo.py — 图像解混淆/解密
- 支持 5 种解混淆模式：方块混淆、行像素混淆、像素混淆、PicEncrypt 行模式、PicEncrypt 行+列模式
- 使用 Numba JIT 加速像素级图像变换，基于 MD5 哈希生成伪随机排列序列
- 交互式 CLI：输入图片路径、密钥（0-1 浮点数）、输出路径、解密模式
- 依赖：`numpy`、`Pillow`、`numba`

### ts2mp4.py — TS 视频转 MP4
- 调用 ffmpeg 将 .ts 文件转换为 .mp4（`-c copy` 无损封装转换）
- `ts_to_mp4()`：单个文件转换；`batch_ts_to_mp4()`：批量转换文件夹内所有 .ts 文件
- 依赖：系统需安装 ffmpeg 并在 PATH 中
- 需在 `__main__` 中设置 `TS_FOLDER` 路径（当前为占位符）

### modify.py — 文件批量重命名（单层目录）
- `add_dot1_to_files()`：对指定文件夹内所有文件添加 `.1` 后缀（如 `foo.mp4` → `foo.mp4.1`）
- `remove_dot1_from_files()`：移除该文件夹内所有 `.1` 结尾文件的后缀
- **注意**：仅处理指定目录的直接文件，**不递归子文件夹**
- 硬编码了目标路径 `target_folder`，使用前需修改

### remove_dot1_suffix.py — 递归移除 .1 后缀
- 递归遍历目录及所有子文件夹，将 `.1` 结尾的文件重命名为去掉 `.1` 的名称
- 支持 `--dry-run` 预览模式，目标文件已存在时自动跳过

### delete_copy_files.py — 递归删除"副本"文件
- 递归遍历目录及所有子文件夹，删除文件名（不含后缀）以"副本"结尾的文件
- 不限制具体后缀，如 `文档副本.txt`、`data 副本.log` 均会被匹配
- 支持 `--dry-run` 预览模式

### download_images.py — 批量下载图片
- 读取 CSV 中的图片 URL 列表，批量下载到指定文件夹
- 自动跳过已存在的文件，下载失败时打印错误并继续
- `-i/--input` 指定 CSV 路径（默认脚本同目录下的 `url.csv`），`-o/--output` 指定输出目录（默认 `downloaded_images/`）
- 依赖：`requests`

### shanghai_metro_fare/ — 上海地铁最短路径与票价查询
- 输入起点站和终点站，输出最短路径、里程，以及现行 / 听证方案一 / 听证方案二三套票价
- 命令行版 `metro_fare.py` + 自包含网页版 `index.html`（数据内嵌，双击即用）
- 纯标准库实现，详见 [shanghai_metro_fare/README.md](shanghai_metro_fare/README.md)

## 环境要求

- Python 3.10+（虚拟环境位于 `.venv/`）
- 安装依赖：`pip install -r requirements.txt`（numpy、numba、Pillow、requests）
- `ts2mp4.py` 需要系统安装 [ffmpeg](https://ffmpeg.org/) 并加入 PATH
- `shanghai_metro_fare/` 纯标准库实现，无需第三方依赖

## 目录结构

```
.
├── demo.py                  # 图像解混淆/解密
├── ts2mp4.py                # TS 视频转 MP4
├── modify.py                # 批量重命名（.1 后缀，单层）
├── remove_dot1_suffix.py    # 递归移除 .1 后缀
├── delete_copy_files.py     # 递归删除"副本"文件
├── download_images.py       # 批量下载图片
├── shanghai_metro_fare/     # 上海地铁票价（CLI + 网页版）
├── requirements.txt
├── CLAUDE.md                # Claude Code 项目指引
└── README.md
```

## 注意事项

- 各工具相互独立，无公共依赖，每个 `.py` 文件可单独运行
- 部分工具（`modify.py`、`ts2mp4.py`）含占位路径，使用前请先修改
- 删除类操作（`delete_copy_files.py`）建议先用 `--dry-run` 预览
