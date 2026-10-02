"""一次性重复图片清理：零依赖 dHash 感知哈希分组，候选移入回收子文件夹。

dHash（差异哈希）：图片转灰度缩到 9×8，比较每行相邻像素得 64bit 指纹；
汉明距离 ≤ 阈值（默认 8/64）视为重复。分组后每组保留"分辨率最大（并列取
文件更大）"者为正本，其余为候选——**候选移入 `<扫描目录>/重复图片_回收/`，
绝不直接删除**，误判可从回收文件夹手动搬回。

接口分两步供 GUI 预览与确认：
- `scan(directory)`：纯扫描，返回分组列表（不动任何文件）；
- `move_duplicates(groups, only=None)`：把（选中）候选移入回收文件夹。

embedding 语义查重明确不做（BACKLOG B2）；本模块是一次性工具，非监控。
"""

from dataclasses import dataclass, field
from pathlib import Path

from .common import unique_path

# 与 image_convert 的常见图片集合对齐，另加动图/常见截图片种
IMAGE_SUFFIXES = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".tif", ".tiff",
    ".avif", ".ico",
}

RECYCLE_DIR_NAME = "重复图片_回收"
DEFAULT_THRESHOLD = 8  # 64bit 汉明距离阈值


@dataclass
class DuplicateGroup:
    """一组视觉重复图片：keeper 为保留正本，candidates 为待处理候选。"""

    keeper: Path
    _hash: int = 0  # 组代表指纹（分组合并用，不对外）
    candidates: list[Path] = field(default_factory=list)
    distance: int = 0  # 候选与正本的最大汉明距离（相似度展示用）


def dhash(image) -> int:
    """PIL 图片 → 64bit dHash 指纹（先纠转 EXIF 方向再比较，避免手机照片误判）。"""
    from PIL import ImageOps

    small = ImageOps.exif_transpose(image).convert("L").resize((9, 8))
    pixels = list(small.getdata())
    bits = 0
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits = (bits << 1) | (1 if pixels[base + col] > pixels[base + col + 1] else 0)
    return bits


def hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def scan(
    directory: str | Path, *, recursive: bool = False,
    threshold: int = DEFAULT_THRESHOLD,
) -> list[DuplicateGroup]:
    """扫描目录中的重复图片（纯只读）；坏图跳过，回收文件夹不参与。"""
    from PIL import Image

    root = Path(directory).expanduser()
    if not root.is_dir():
        raise FileNotFoundError(f"目录不存在: {root}")
    entries = root.rglob("*") if recursive else root.iterdir()
    fingerprints: list[tuple[Path, int]] = []
    for path in entries:
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if RECYCLE_DIR_NAME in path.relative_to(root).parts:
            continue  # 回收文件夹（含递归子层）不再进扫描
        try:
            with Image.open(path) as image:
                fingerprints.append((path, dhash(image)))
        except Exception:  # noqa: BLE001 - 坏图/非图片静默跳过
            continue

    groups: list[DuplicateGroup] = []
    hashes: list[int] = []  # 与 groups 一一对应的组代表指纹
    for path, bits in fingerprints:
        matched = None
        for index, group_hash in enumerate(hashes):
            if hamming(bits, group_hash) <= threshold:
                matched = index
                break
        if matched is None:
            groups.append(DuplicateGroup(keeper=path, _hash=bits))
            hashes.append(bits)
        else:
            group = groups[matched]
            group.candidates.append(path)
            group.distance = max(group.distance, hamming(bits, hashes[matched]))

    # 正本选择：分辨率最大（并列取文件更大）者为保留者，原 keeper 若非最优
    # 则与最优候选互换
    for group in groups:
        members = [group.keeper, *group.candidates]
        best = max(members, key=_rank)
        if best is not group.keeper:
            index = group.candidates.index(best)
            group.candidates[index] = group.keeper
            group.keeper = best
    return [group for group in groups if group.candidates]


def _rank(path: Path) -> tuple[int, int]:
    """正本排序键：分辨率像素总数优先，并列取文件字节大。"""
    from PIL import Image

    try:
        with Image.open(path) as image:
            pixels = image.width * image.height
    except Exception:  # noqa: BLE001
        pixels = 0
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return pixels, size


def move_duplicates(
    groups: list[DuplicateGroup],
    root: str | Path | None = None,
    *,
    only: set[Path] | None = None,
    log_cb=None,
) -> dict:
    """把候选移入 `<root>/重复图片_回收/`（默认 root 取正本所在目录）。

    only 指定候选子集（GUI 勾选）；重名自动追加序号；返回 {"moved", "failed"}。
    """
    log = log_cb if log_cb is not None else (lambda text: None)
    moved = 0
    failed: list[str] = []
    recycle_cache: dict[Path, Path] = {}
    for group in groups:
        root_dir = Path(root).expanduser() if root else group.keeper.parent
        recycle = recycle_cache.get(root_dir)
        if recycle is None:
            recycle = root_dir / RECYCLE_DIR_NAME
            recycle_cache[root_dir] = recycle
        for candidate in group.candidates:
            if only is not None and candidate not in only:
                continue
            if not candidate.is_file():
                continue
            try:
                recycle.mkdir(parents=True, exist_ok=True)
                dest = unique_path(recycle / candidate.name)
                candidate.replace(dest)
                moved += 1
                log(f"已移入回收: {candidate.name}（正本 {group.keeper.name}）")
            except OSError as exc:
                failed.append(f"{candidate.name}: {exc}")
    return {"moved": moved, "failed": failed}
