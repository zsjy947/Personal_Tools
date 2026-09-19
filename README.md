# 上海地铁票价查询（功能存档）

本分支仅用于**存档已从主分支（`main`）移除的功能**，当前只保留上海地铁票价查询工具。

- 主分支的本地文件处理工具集 `file_tools/` 不在本分支维护；其历史版本可通过
  `main` 分支的 commit 记录追溯（如 `e939d1a`、`14a460d`）。
- 本分支只读存档，不再开发；如需恢复某功能，从本分支检出后自行迁移。

## 功能说明

`shanghai_metro_fare/` 提供上海地铁最短路径与票价查询，含命令行版和自包含网页版，
仅使用 Python 标准库（无需安装依赖）：

```powershell
# 交互式查询
python shanghai_metro_fare/metro_fare.py

# 直接指定起终点
python shanghai_metro_fare/metro_fare.py 人民广场 陆家嘴

# 自检
python shanghai_metro_fare/metro_fare.py --selftest
```

网页版直接用浏览器打开 `shanghai_metro_fare/index.html` 即可离线使用。

详细说明见 [shanghai_metro_fare/README.md](shanghai_metro_fare/README.md)。

## 目录结构

```text
.
├── shanghai_metro_fare/     # 上海地铁票价查询（CLI + 网页版，存档内容）
│   ├── metro_fare.py        # 命令行入口
│   ├── index.html           # 自包含网页版
│   ├── data/                # 线路/站点数据
│   └── README.md            # 功能详细说明
├── AGENTS.md                # 本分支给代码助手的说明
└── README.md
```
