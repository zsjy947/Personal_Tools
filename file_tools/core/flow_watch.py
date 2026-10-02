"""文件流自动化：目录监控规则引擎（纯标准库轮询 + 非破坏性动作 + 全程可开关）。

从"我发起它执行"升级为"它替我盯着"：规则定义监听目录与动作（图片转格式 /
无损转 MP4 / 按类型归类），监控线程按间隔轮询，对"落定"的新文件执行动作。

安全纪律（负面清单的正面表述）：
- 动作 v1 仅三类**非破坏性**动作，明确不做 delete 类动作；移动类动作在
  执行前写 undo 台账（undo.jsonl），`undo_last_batch()` 可逆序回滚上一轮；
- 开关三层：进程内 start()/stop()；GUI 总开关（默认停止、状态不持久化，
  每次打开 GUI 都是停止态）；单规则 enabled 勾选；
- processed 台账（processed.jsonl：路径 + size + mtime 摘要）保证重启后
  不重复处理；`.part/.tmp` 等临时名与隐藏文件一律跳过；
- 日志经 log_cb 回调注入 GUI 日志队列，**回调内不得直接碰 Tk**。

线程纪律：监控线程是独立 daemon 线程（不属于 runner 单任务短任务队列），
归属 App；**扫描互斥用模块级锁**——所有 FlowWatch 实例共享一把
_SCAN_LOCK，GUI 常驻监控、手动扫描与局域网 /api/scan 的任意并发都不会
同时处理同一目录（否则 convert 双写产物、sort 双移动会损坏/丢失数据）。
"""

import argparse
import json
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .common import normalize_suffixes, unique_path

# 全部 FlowWatch 实例共享的扫描互斥锁（跨实例：GUI 监控 vs /api/scan vs CLI）
_SCAN_LOCK = threading.Lock()

ACTION_CONVERT = "convert"
ACTION_TO_MP4 = "to_mp4"
ACTION_SORT = "sort_by_type"

ACTION_TEXTS = {
    ACTION_CONVERT: "图片转格式",
    ACTION_TO_MP4: "无损转 MP4",
    ACTION_SORT: "按类型归类",
}

# 临时/隐藏文件：下载器与办公软件的中间态，绝不处理
_TEMP_SUFFIXES = {".part", ".tmp", ".crdownload", ".download", ".partial", ".tmp~"}
_TEMP_PREFIXES = ("~$", ".")

RULES_NAME = "rules.json"
PROCESSED_NAME = "processed.jsonl"
UNDO_NAME = "undo.jsonl"

LEDGER_ROTATE_BYTES = 2 * 1024 * 1024  # 台账超 2MB 轮转
PROCESSED_KEEP = 5000
UNDO_KEEP = 2000


@dataclass
class Rule:
    """一条监控规则；suffixes 为空表示监听目录内全部非临时文件。"""

    name: str
    watch_dir: str
    action: str  # convert / to_mp4 / sort_by_type
    enabled: bool = True
    recursive: bool = False
    suffixes: set[str] = field(default_factory=set)
    action_params: dict = field(default_factory=dict)

    def summary_text(self) -> str:
        """动作参数摘要（规则表「参数」列）。"""
        params = self.action_params or {}
        if self.action == ACTION_CONVERT:
            parts = [f"→ {params.get('target_format', 'jpg')}"]
            if params.get("quality"):
                parts.append(f"质量 {params['quality']}")
            return "，".join(parts) + "（保留原图）"
        if self.action == ACTION_TO_MP4:
            return "无损封装（ffmpeg -c copy）"
        return "图片/视频/音频/文档/压缩包/其他"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "enabled": self.enabled,
            "watch_dir": self.watch_dir,
            "recursive": self.recursive,
            "suffixes": sorted(self.suffixes),
            "action": self.action,
            "action_params": dict(self.action_params),
        }


def rule_from_dict(data: dict) -> Rule:
    suffixes = normalize_suffixes(data.get("suffixes") or [])
    return Rule(
        name=str(data.get("name", "")),
        watch_dir=str(data.get("watch_dir", "")),
        action=str(data.get("action", "")),
        enabled=bool(data.get("enabled", True)),
        recursive=bool(data.get("recursive", False)),
        suffixes=suffixes,
        action_params=dict(data.get("action_params") or {}),
    )


def rules_path() -> Path:
    from .userdata import base_dir

    return base_dir() / RULES_NAME


def load_rules(config_path: str | Path | None = None) -> list[Rule]:
    """读规则表；默认取 userdata 下的 rules.json，坏文件/缺失返回空表。"""
    path = Path(config_path).expanduser() if config_path else rules_path()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(payload, list):
        return []
    rules = []
    for item in payload:
        if isinstance(item, dict) and item.get("name") and item.get("watch_dir"):
            rules.append(rule_from_dict(item))
    return rules


def save_rules(rules: list[Rule], config_path: str | Path | None = None) -> None:
    path = Path(config_path).expanduser() if config_path else rules_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([rule.to_dict() for rule in rules], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _ledger_path(name: str) -> Path:
    from .userdata import base_dir

    return base_dir() / name


def _append_jsonl(path: Path, entry: dict) -> None:
    """追加一条 JSONL；写失败静默（台账/撤销不允许影响监控本身）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _read_jsonl(path: Path) -> list[dict]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            entries.append(entry)
    return entries


def _rewrite_jsonl(path: Path, entries: list[dict]) -> None:
    try:
        path.write_text(
            "".join(
                json.dumps(entry, ensure_ascii=False) + "\n" for entry in entries
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


# -------- 文件判定（纯函数） --------

def is_temp_name(path: Path) -> bool:
    name = path.name
    return (
        name.startswith(_TEMP_PREFIXES)
        or name.endswith("~")
        or path.suffix.lower() in _TEMP_SUFFIXES
    )


CATEGORY_MAP = {
    "图片": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif",
            ".tiff", ".avif", ".ico", ".heic", ".svg"},
    "视频": {".mp4", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv",
            ".m4v", ".ts", ".3gp", ".mpg", ".mpeg", ".m3u8", ".mpd"},
    "音频": {".mp3", ".flac", ".wav", ".ogg", ".oga", ".m4a", ".aac",
            ".opus", ".wma", ".ape", ".mid"},
    "文档": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
            ".txt", ".md", ".epub", ".mobi", ".csv"},
    "压缩包": {".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".iso"},
}

CATEGORY_OTHER = "其他"


def category_of(path: Path) -> str:
    suffix = path.suffix.lower()
    for category, suffixes in CATEGORY_MAP.items():
        if suffix in suffixes:
            return category
    return CATEGORY_OTHER


def rule_matches(rule: Rule, path: Path) -> bool:
    """路径级匹配判定（落定判定另由 FlowWatch 负责）。"""
    if is_temp_name(path):
        return False
    if rule.suffixes and path.suffix.lower() not in rule.suffixes:
        return False
    return True


# -------- 撤销台账（undo.jsonl） --------

def _record_undo(batch: str, steps: list[tuple[str, str]]) -> None:
    """移动执行前调用：记录逆向操作（src → dst 的反向）。"""
    stamp = datetime_now_iso()
    for src, dst in steps:
        _append_jsonl(_ledger_path(UNDO_NAME), {
            "batch": batch, "ts": stamp, "op": "move", "src": src, "dst": dst,
        })


def datetime_now_iso() -> str:
    from datetime import datetime

    return datetime.now().isoformat(timespec="seconds")


def undo_last_batch() -> tuple[int, list[str]]:
    """逆序回滚最近一个批次的移动操作；返回 (成功条数, 失败消息列表)。

    只有成功回滚的条目会从台账移除，失败条目保留——再次调用会重试同一批次。
    与扫描共用以模块级锁（读改写 undo.jsonl 期间不允许监控线程追加/轮转）。
    """
    with _SCAN_LOCK:
        return _undo_last_batch_locked()


def _undo_last_batch_locked() -> tuple[int, list[str]]:
    path = _ledger_path(UNDO_NAME)
    entries = _read_jsonl(path)
    if not entries:
        return 0, ["没有可撤销的操作。"]
    last_batch = entries[-1].get("batch")
    batch_indexes = [
        index for index, entry in enumerate(entries)
        if entry.get("batch") == last_batch
    ]
    undone_indexes: set[int] = set()
    failures: list[str] = []
    for index in reversed(batch_indexes):
        entry = entries[index]
        src, dst = Path(entry.get("src", "")), Path(entry.get("dst", ""))
        if not dst.is_file():
            continue  # 目标已不在（用户手动动过）：视为无需回滚
        if src.exists():
            failures.append(f"原位置已存在同名文件，跳过: {src.name}")
            continue
        try:
            src.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(dst), str(src))
            undone_indexes.add(index)
        except OSError as exc:
            failures.append(f"{dst.name}: {exc}")
    if undone_indexes:
        _rewrite_jsonl(
            path, [e for i, e in enumerate(entries) if i not in undone_indexes]
        )
    return len(undone_indexes), failures


def _rotate_ledger(path: Path, keep: int) -> None:
    try:
        if path.exists() and path.stat().st_size > LEDGER_ROTATE_BYTES:
            entries = _read_jsonl(path)
            _rewrite_jsonl(path, entries[-keep:])
    except OSError:
        pass


# -------- 动作执行 --------

class FlowWatch:
    """目录监控器：轮询线程 + 单轮扫描（scan_once 供手动与局域网触发复用）。"""

    def __init__(
        self,
        rules: list[Rule],
        log_cb=None,
        *,
        interval: float = 10.0,
        settle_seconds: float = 30.0,
    ) -> None:
        self.rules = list(rules)
        self._log_cb = log_cb if log_cb is not None else (lambda text: None)
        self.interval = max(1.0, interval)
        self.settle_seconds = max(0.0, settle_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._scan_lock = _SCAN_LOCK
        self._previous: dict[str, tuple[int, float]] = {}  # 上轮快照（落定判定）
        self._failed: dict[str, tuple[int, float]] = {}  # 本会话失败退避（不持久化）
        self._batch = ""
        self._processed = self._load_processed()

    # ---- 生命周期 ----

    def _log(self, text: str) -> None:
        self._log_cb(text)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="FlowWatch", daemon=True
        )
        self._thread.start()
        self._log(
            f"[监控] 已启动：{len([r for r in self.rules if r.enabled])} 条启用规则，"
            f"间隔 {self.interval:g}s，落定阈值 {self.settle_seconds:g}s"
        )

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                # 扫描轮次（如长转换）未结束：保留线程引用，running 仍为 True，
                # 防止立刻再启第二个监控实例形成并发扫描
                self._log("[监控] 警告: 最后一轮扫描尚未结束，停止仍在进行。")
                return
        self._thread = None
        self._log("[监控] 已停止。")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.scan_once(require_stable=True)
            except Exception as exc:  # noqa: BLE001 - 单轮异常绝不终止监控线程
                self._log(f"[监控] 轮询异常: {exc}")
            self._stop_event.wait(self.interval)

    # ---- 扫描 ----

    def scan_once(self, *, require_stable: bool) -> dict:
        """单轮扫描。require_stable=True 为后台轮询（连续两轮一致 + 落定阈值）；
        False 为手动/局域网触发（仅要求文件早于落定阈值，立即处理）。"""
        with self._scan_lock:
            return self._scan_locked(require_stable)

    def _scan_locked(self, require_stable: bool) -> dict:
        self._batch = uuid.uuid4().hex
        summary = {"processed": 0, "failed": 0, "waiting": 0}
        now = time.time()
        waiting: dict[str, tuple[int, float]] = {}
        for rule in self.rules:
            if not rule.enabled:
                continue
            root = Path(rule.watch_dir).expanduser()
            if not root.is_dir():
                continue
            entries = root.rglob("*") if rule.recursive else root.iterdir()
            for path in entries:
                if not path.is_file() or not rule_matches(rule, path):
                    continue
                key = str(path.resolve())
                try:
                    stat = path.stat()
                except OSError:
                    continue
                snapshot = (stat.st_size, stat.st_mtime)
                age = now - stat.st_mtime
                if age < 0:
                    # mtime 在未来（相机/他机时钟偏移、网络拷贝常见）：视为已落定，
                    # 否则 age 恒为负会让文件永远停在 waiting
                    age = self.settle_seconds
                if age < self.settle_seconds:
                    waiting[key] = snapshot  # 太新：等它落定
                    summary["waiting"] += 1
                    continue
                if require_stable and self._previous.get(key) != snapshot:
                    waiting[key] = snapshot  # 第一轮见到：下一轮复查
                    summary["waiting"] += 1
                    continue
                if self._processed.get(key) == snapshot:
                    continue  # 已处理过同一内容：台账命中跳过
                if self._failed.get(key) == snapshot:
                    continue  # 本会话内失败过：退避不再重试（重启会话后重新尝试）
                ok, message, extras = self._apply(rule, path)
                if ok:
                    self._processed[key] = snapshot
                    _append_jsonl(_ledger_path(PROCESSED_NAME), {
                        "batch": self._batch, "ts": datetime_now_iso(),
                        "rule": rule.name, "path": key,
                        "size": snapshot[0], "mtime": snapshot[1],
                    })
                    # 移动类动作把目的地也记入台账：递归规则下移动后的新路径
                    # 不能被再次识别为"新文件"（否则会无限改名膨胀）
                    for extra_key, extra_size, extra_mtime in extras:
                        self._processed[extra_key] = (extra_size, extra_mtime)
                        _append_jsonl(_ledger_path(PROCESSED_NAME), {
                            "batch": self._batch, "ts": datetime_now_iso(),
                            "rule": rule.name, "path": extra_key,
                            "size": extra_size, "mtime": extra_mtime,
                        })
                    self._failed.pop(key, None)
                    summary["processed"] += 1
                    self._log(f"[监控] {rule.name}: {message}")
                else:
                    self._failed[key] = snapshot
                    summary["failed"] += 1
                    self._log(f"[监控] {rule.name} 失败: {message}")
        self._previous = waiting
        _rotate_ledger(_ledger_path(PROCESSED_NAME), PROCESSED_KEEP)
        _rotate_ledger(_ledger_path(UNDO_NAME), UNDO_KEEP)
        return summary

    # ---- 动作 ----

    def _apply(self, rule: Rule, path: Path) -> tuple[bool, str, list[tuple[str, int, float]]]:
        """对单个已落定文件执行动作。

        返回 (是否处理成功, 消息, 追加台账条目)——移动类动作把目的地路径也
        记入 processed 台账（防止递归规则下把移动后的文件再当新文件处理）。
        """
        try:
            if rule.action == ACTION_SORT:
                return self._apply_sort(rule, path)
            if rule.action == ACTION_CONVERT:
                return *self._apply_convert(rule, path), []
            if rule.action == ACTION_TO_MP4:
                return *self._apply_to_mp4(rule, path), []
            return False, f"未知动作: {rule.action}", []
        except Exception as exc:  # noqa: BLE001 - 单文件失败不中断整轮
            return False, f"{path.name}: {exc}", []

    def _apply_sort(self, rule: Rule, path: Path) -> tuple[bool, str, list[tuple[str, int, float]]]:
        category = category_of(path)
        dest_dir = Path(rule.watch_dir).expanduser() / category
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = unique_path(dest_dir / path.name)
        # 移动前先记撤销台账（非破坏性纪律：任何移动都可逆）
        _record_undo(self._batch, [(str(path.resolve()), str(dest.resolve()))])
        shutil.move(str(path), str(dest))
        try:
            stat = dest.stat()
            extras = [(str(dest.resolve()), stat.st_size, stat.st_mtime)]
        except OSError:
            extras = []
        return True, f"{path.name} → {category}/", extras

    def _apply_convert(self, rule: Rule, path: Path) -> tuple[bool, str]:
        from .image_convert import convert_images

        params = rule.action_params or {}
        target_format = str(params.get("target_format") or "jpg")
        quality = params.get("quality")
        # 监控动作纪律：非破坏性。即使规则文件里带了 delete_original，
        # 也强制保留原图（删除只属于用户主动发起的转换任务）
        summary = convert_images(
            path,
            target_format,
            quality=int(quality) if quality else None,
        )
        if summary.converted:
            return True, f"{path.name} → {target_format.upper()}"
        if summary.skipped:
            return True, f"{path.name} 已是 {target_format.upper()}，跳过"
        return False, f"{path.name} 转换失败（详见日志）"

    def _apply_to_mp4(self, rule: Rule, path: Path) -> tuple[bool, str]:
        from .media_to_mp4 import convert_media

        summary = convert_media(path)
        if summary.converted:
            return True, f"{path.name} → MP4（无损封装）"
        if summary.skipped:
            return True, f"{path.name} 的 MP4 已存在，跳过"
        return False, f"{path.name} 不是可封装的视频内容"

    # ---- processed 台账 ----

    def _load_processed(self) -> dict[str, tuple[int, float]]:
        entries = {}
        for entry in _read_jsonl(_ledger_path(PROCESSED_NAME)):
            key = entry.get("path")
            if key and isinstance(entry.get("size"), int):
                entries[key] = (entry["size"], entry.get("mtime") or 0.0)
        return entries


def scan_now(log_cb=None) -> dict:
    """按 userdata 当前规则手动扫一轮（GUI 停止态与局域网 /api/scan 用）。"""
    rules = [rule for rule in load_rules() if rule.enabled]
    watch = FlowWatch(rules, log_cb=log_cb)
    return watch.scan_once(require_stable=False)


# -------- CLI（核心可独立运行） --------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="目录监控规则引擎：对落定的新文件执行非破坏性动作"
                    "（图片转格式 / 无损转 MP4 / 按类型归类）。"
    )
    parser.add_argument("command", choices=("run", "once"),
                        help="run 持续监控（Ctrl+C 停止）；once 单轮扫描后退出")
    parser.add_argument("--config", type=Path,
                        help="规则表路径（默认 userdata 下的 rules.json）")
    parser.add_argument("--rule", metavar="NAME",
                        help="只执行指定名称的规则（默认全部启用规则）")
    parser.add_argument("--interval", type=float, default=10.0,
                        help="run 模式轮询间隔秒数（默认 10）")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    rules = load_rules(args.config)
    if args.rule:
        rules = [rule for rule in rules if rule.name == args.rule]
        if not rules:
            print(f"没有名为 {args.rule!r} 的规则。", file=sys.stderr)
            return 1
    rules = [rule for rule in rules if rule.enabled]
    if not rules:
        print("没有启用中的规则（先在 GUI 或 rules.json 里配置）。", file=sys.stderr)
        return 1
    watch = FlowWatch(rules, log_cb=print, interval=args.interval)
    if args.command == "once":
        summary = watch.scan_once(require_stable=False)
        print(f"单轮扫描完成: 处理 {summary['processed']}，失败 {summary['failed']}"
              f"，等待落定 {summary['waiting']}")
        return 0
    watch.start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass
    finally:
        watch.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
