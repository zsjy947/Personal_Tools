"""GUI 任务历史留痕：JSONL 追加式记录，只读可查。

所有 GUI 任务经 `App.submit` → runner → `_finish_task`，在 `_finish_task`
单点调用 `record()` 即自动全覆盖；CLI 不记录（负面清单）。设计约束：

- 历史记录绝不允许影响任务本身——任何写入失败都静默吞掉；
- message 压成单行并截断至 500 字符（只是摘要，完整输出以日志面板为准，
  避免大段下载日志撑爆历史文件）；
- 文件超过 2MB 时轮转为最近 500 条，避免无限膨胀。
"""

import json
from datetime import datetime
from pathlib import Path

HISTORY_NAME = "history.jsonl"

MESSAGE_LIMIT = 500  # 单条 message 摘要截断长度
ROTATE_BYTES = 2 * 1024 * 1024  # 文件超过 2MB 触发轮转
ROTATE_KEEP = 500  # 轮转后保留的最近条数


def history_path() -> Path:
    from .userdata import base_dir

    return base_dir() / HISTORY_NAME


def _one_line(message, limit: int = MESSAGE_LIMIT) -> str:
    """压缩成单行摘要：所有空白（含换行）折成单个空格后截断。"""
    text = " ".join(str(message).split())
    return text[:limit]


def record(title, status, seconds, message="") -> None:
    """追加一条任务记录。

    status: bool（True=成功）；seconds: 耗时秒；message: 结果消息摘要。
    任何异常都静默吞掉——历史记录不允许影响任务本身。
    """
    try:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "title": str(title),
            "status": "ok" if status and status != "fail" else "fail",
            "seconds": round(float(seconds), 3),
            "message": _one_line(message),
        }
        path = history_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > ROTATE_BYTES:
            rotate(path)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except (OSError, TypeError, ValueError):
        pass


def rotate(path: Path) -> None:
    """轮转：把文件重写为最近 ROTATE_KEEP 条。"""
    try:
        lines = [line for line in path.read_text(encoding="utf-8",
                                                 errors="replace").splitlines()
                 if line.strip()]
        path.write_text(
            "".join(line + "\n" for line in lines[-ROTATE_KEEP:]), encoding="utf-8"
        )
    except OSError:
        pass


def read_recent(limit: int = 200) -> list[dict]:
    """读最近 limit 条记录（新的在前）；坏行跳过，文件缺失返回空列表。"""
    try:
        lines = history_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries: list[dict] = []
    for line in reversed(lines):
        if len(entries) >= limit:
            break
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def clear() -> None:
    """清空全部历史（删除文件）；失败静默。"""
    try:
        history_path().unlink(missing_ok=True)
    except OSError:
        pass
