# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

这是一个个人 Python 脚本工具集，包含图像解密、视频转换、文件批量操作等独立工具。文件之间无相互依赖，每个 `.py` 文件可独立运行。

## 各文件功能说明

### demo.py — 图像解混淆/解密工具
- 支持 5 种解混淆模式（方块混淆、行像素混淆、像素混淆、PicEncrypt 行模式、PicEncrypt 行+列模式）
- 使用 Numba JIT 加速像素级图像变换，基于 MD5 哈希生成伪随机排列序列
- 交互式 CLI：输入图片路径、密钥（0-1 浮点数）、输出路径、解密模式
- 依赖：`numpy`、`Pillow`、`numba`、`hashlib`

### ts2mp4.py — TS 视频转 MP4（CLI 工具）
- 调用 ffmpeg 将 .ts 文件转换为 .mp4（`-c copy` 无损封装转换）
- `ts_to_mp4()`：单个文件转换；`batch_ts_to_mp4()`：批量转换文件夹内所有 .ts 文件
- 依赖：系统需安装 ffmpeg 并在 PATH 中
- 需在 `__main__` 中设置 `TS_FOLDER` 路径（当前为占位符 `your_folder_path_here`）

### modify.py — 文件批量重命名（单层目录）
- `add_dot1_to_files()`：对指定文件夹内所有文件添加 `.1` 后缀（如 `foo.mp4` → `foo.mp4.1`）
- `remove_dot1_from_files()`：移除该文件夹内所有 `.1` 结尾文件的后缀
- **注意**：仅处理指定目录的直接文件，**不递归子文件夹**
- 硬编码了目标路径 `target_folder`，使用前需修改

### remove_dot1_suffix.py — 递归移除 .1 后缀（CLI 工具）
- 递归遍历目录及所有子文件夹，将 `.1` 结尾的文件重命名为去掉 `.1` 的名称
- 支持 `--dry-run` 预览模式，目标文件已存在时自动跳过
- 用法：`python remove_dot1_suffix.py <目录> [--dry-run]`

### delete_copy_files.py — 递归删除"副本"文件（CLI 工具）
- 递归遍历目录及所有子文件夹，删除文件名（不含后缀）以"副本"结尾的文件
- 不限制具体后缀，如 `文档副本.txt`、`data 副本.log` 均会被匹配
- 支持 `--dry-run` 预览模式
- 用法：`python delete_copy_files.py <目录> [--dry-run]`

### download_images.py — 批量下载图片（CLI 工具）
- 读取 `url.csv` 中的图片 URL 列表，下载到 `downloaded_images/` 文件夹
- 自动跳过已存在的文件，下载失败时打印错误并继续
- 支持 `-i/--input` 指定 CSV 路径、`-o/--output` 指定输出目录
- 依赖：`requests`（已加入 requirements.txt）
- CSV 默认路径：脚本同目录下的 `url.csv`

### shanghai_metro_fare/ — 上海地铁最短路径与调价前后票价（单功能文件夹）
- 输入起点站和终点站，输出最短路径、里程，以及现行（2005 机制）/ 听证方案一 / 听证方案二 三套票价
- `metro_fare.py` 主 CLI：站名模糊匹配、Dijkstra 最短路径（haversine 直线距离 ×1.03 近似轨道里程，经官方示例校准）、区间票价表
- `index.html` 网页版：自包含单文件（数据内嵌），双击即用，站名自动补全 + 线路配色路径 + 票价对比卡片；模板在 `web_template.html`，数据更新后需跑 `python build_web.py` 重新生成
- 网页版 JS 与 CLI 算法同构（已在 10 组站点对交叉验证一致），可在 node 中提取 `<script>` 单独测试
- `fetch_data.py`：从高德地铁 srhdata JSON 抓取并解析 19 条常规线路（1-18 号线 + 浦江线，415 站），排除磁浮线/市域机场线/金山铁路，生成 `data/stations.json` + `edges.json`
- `python metro_fare.py --selftest` 用官方公布示例自检票价
- 纯标准库实现（网页版零依赖），Python 3.10+

## 环境

- Python 3.10（虚拟环境位于 `.venv/`）
- 依赖管理：`requirements.txt`（核心依赖：numpy 2.0.2、numba 0.60.0、Pillow 10.4.0）
- 激活虚拟环境：`.venv\Scripts\activate`（Windows）

## .vscode/launch.json

VS Code 调试配置：
- **Python: Current File**：使用 `debugpy` 调试当前打开的 Python 文件
- **Bash-Debug**：用于调试 shell 脚本（历史遗留，指向已不存在的路径）
