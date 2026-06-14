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
- 使用前需修改 `__main__` 中的硬编码路径 `TS_FOLDER`

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

## 环境

- Python 3.10（虚拟环境位于 `.venv/`）
- 依赖管理：`requirements.txt`（核心依赖：numpy 2.0.2、numba 0.60.0、Pillow 10.4.0）
- 激活虚拟环境：`.venv\Scripts\activate`（Windows）

## .vscode/launch.json

VS Code 调试配置：
- **Python: Current File**：使用 `debugpy` 调试当前打开的 Python 文件
- **Bash-Debug**：用于调试 shell 脚本（历史遗留，指向已不存在的路径）
