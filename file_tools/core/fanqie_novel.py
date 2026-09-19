"""番茄小说搜索与下载（仅供学习研究网络爬虫技术，请尊重作者版权，勿用于商业用途）。

下载链路参考开源项目 Tomato-Novel-Downloader 与 fanqie-novel-download 的公开实现：

- 书籍信息：解析 `fanqienovel.com/page/{book_id}` 的 `__INITIAL_STATE__`。
- 章节目录：`fanqienovel.com/api/reader/directory/detail?bookId=`（分卷+章节标题）。
- 章节正文：抓取 `fanqienovel.com/reader/{item_id}` 页面内嵌的
  `reader.chapterData.content`（新版站点已不再提供明文正文 API）。
- 正文反混淆：站点用随机文件名的字体把部分汉字映射到私有区码位（PUA），
  本模块下载混淆字体后，用 fontTools 提取字形轮廓，与系统中文字体的字形
  做归一化 Chamfer 距离匹配还原真实字符；映射按字体哈希缓存到本地。
- 输出：TXT 或 EPUB（标准库 zipfile 打包）。
"""

import argparse
import hashlib
import html as html_module
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import requests

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
MAX_PARAGRAPHS_HINT = 0  # 保留占位：正文按 <p> 自然分段

_ILLEGAL_RE = re.compile(r'[\\/:*?"<>|\r\n]+')
_FONT_URL_RE = re.compile(r"url\((https[^)]+?\.(?:woff2?|otf))\)")
_TAG_RE = re.compile(r"<[^>]+>")
_PUA_START, _PUA_END = 0xE000, 0xF8FF

# 参考字体候选（按优先级）：混淆字形与其中之一最接近
_REFERENCE_FONTS = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
)

# 高频常用字（大致按使用频率排序）：字形匹配分数接近时优先选常用字，
# 修复 一/－、这/达、发/犮 一类形状邻近误配
COMMON_CHARS = set(
    "一的一是不了在人有我他这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对"
    "小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动"
    "方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感见明问力理尔点文几定"
    "本公特做外孩相西果走将月十实向声车全信重三机工物气每并别真打太新比才便夫再书部水像眼等体却加电主界门"
    "利海受听表德少克代员许先口由死安写性马光白或住难望教命花结乐色更拉东神记处让母父应直字场平报友关放至"
    "张认接告入笑内英军候民岁往何度山觉路带万男边风解叫任金快原吃妈变通师立象数四失满战远格士音轻目条呢病"
    "始达深完今提求清王化空业思切怎非找片罗钱吗语元喜曾离飞科言干流欢约各即指合反题必该论交终林请医晚制球"
    "决传画保读运及则房早院量苦火布品近坐产答星精视五连司巴奇管类未朋且婚台夜青北队久乎越观落尽形影红爸百"
    "令周吧识步希亚术留市半热送兴造谈容极随演收首根讲整式取照办强石古华拿计您装似足双妻尼转诉米称丽客南领"
    "节衣站黑刻统断福城故历惊脸选包紧争另建维绝树系伤示愿持千史谁准联妇纪基买志静阿诗独复痛消社算义竟确酒"
    "需单治卡幸兰念举仅钟怕共毛句息功官待究跟穿室易游程号居考突皮哪费倒价图具刚脑永歌响商礼细专黄块脚味灵"
    "改据般破引食仍存众注笔甚某沉血备习校默务土微娘须试怀料调广苏显赛查密议底列富梦错座参八除跑亮假印设线"
    "温虽掉京初养香停际致阳纸李纳验助激够严证帝饭忘趣支春集丈木研班普导顿睡展跳获艺六波察群皇段急庭创区奥"
    "器谢弟店否害草排背止组州朝封睛板角况曲馆育忙质河续哥呼若推境遇雨标姐充围案伦护冷警贝著雪索剧啊船险烟"
    "依斗值帮汉慢佛肯闻唱沙局伴"
)


@dataclass
class BookInfo:
    book_id: str
    title: str = ""
    author: str = ""
    abstract: str = ""
    word_count: int = 0
    cover_url: str = ""
    chapters: list = field(default_factory=list)  # [{"item_id","title","volume"}]


@dataclass
class NovelSummary:
    total: int = 0
    downloaded: int = 0
    failed: int = 0
    output: str = ""


def _session(proxy: str | None = None) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": DEFAULT_UA,
        "Referer": "https://fanqienovel.com/",
        "Accept-Language": "zh-CN,zh;q=0.9",
    })
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    return session


def sanitize_filename(name: str) -> str:
    return _ILLEGAL_RE.sub("_", name).strip()[:80] or "未命名"


def parse_chapter_range(raw: str, total: int) -> tuple[int, int] | None:
    """把 "3-20" 之类的输入解析成 [起,止]（1 起，含端点）；空返回 None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    match = re.fullmatch(r"(\d+)\s*[-~]\s*(\d+)", raw)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
    else:
        start = end = int(raw)
    start = max(1, start)
    end = min(total, end)
    if start > end:
        raise ValueError(f"章节范围无效: {raw}")
    return start, end


# -------- 搜索与书籍信息 --------

def search_books(keyword: str, *, limit: int = 8, proxy: str | None = None) -> list[BookInfo]:
    """按书名搜索，返回候选书目。"""
    response = _session(proxy).get(
        "https://fanqienovel.com/api/author/search/search_book/v1",
        params={
            "query_type": 0, "query_word": keyword,
            "page_index": 0, "page_count": limit, "filter": "",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    items = (payload.get("data") or {}).get("search_book_data_list") or []
    books = []
    for item in items:
        books.append(
            BookInfo(
                book_id=str(item.get("book_id") or ""),
                title=item.get("book_name") or "未知书名",
                author=item.get("author") or "",
                abstract=(item.get("abstract") or "").strip(),
            )
        )
    return [b for b in books if b.book_id]


def fetch_book(book_id: str, *, proxy: str | None = None) -> BookInfo:
    """抓取书籍信息与完整章节目录。"""
    session = _session(proxy)
    response = session.get(f"https://fanqienovel.com/page/{book_id}", timeout=25)
    response.raise_for_status()
    text = response.text
    index = text.find("window.__INITIAL_STATE__")
    if index == -1:
        raise ValueError(f"书籍页面解析失败（可能不存在）: {book_id}")
    state, _end = json.JSONDecoder().raw_decode(text[text.find("{", index):])
    page = state.get("page") or {}
    book = BookInfo(
        book_id=str(page.get("bookId") or book_id),
        title=page.get("bookName") or "未知书名",
        author=page.get("author") or page.get("authorName") or "",
        abstract=(page.get("abstract") or page.get("description") or "").strip(),
        word_count=int(page.get("wordNumber") or 0),
        cover_url=page.get("thumbUri") or "",
    )
    directory = session.get(
        "https://fanqienovel.com/api/reader/directory/detail",
        params={"bookId": book.book_id},
        timeout=25,
    ).json()
    if directory.get("code") != 0:
        raise ValueError(f"章节目录获取失败: {directory.get('message') or directory.get('code')}")
    data = directory.get("data") or {}
    for volume_name, chapters in zip(
        data.get("volumeNameList") or [""], data.get("chapterListWithVolume") or []
    ):
        if not isinstance(chapters, list):
            continue
        for chapter in chapters:
            book.chapters.append({
                "item_id": str(chapter.get("itemId") or ""),
                "title": chapter.get("title") or "",
                "volume": volume_name if isinstance(volume_name, str) else "",
            })
    book.chapters = [c for c in book.chapters if c["item_id"]]
    if not book.chapters:
        raise ValueError("章节目录为空")
    return book


# -------- 正文抓取与反混淆 --------

def _cache_dir() -> Path:
    directory = Path(tempfile.gettempdir()) / "file_tools_fanqie"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


_font_maps: dict[str, dict[str, str]] = {}
_font_maps_lock = threading.Lock()
_font_build_lock = threading.Lock()  # 首次构建映射时防止并发线程重复计算


def _content_to_paragraphs(content: str) -> list[str]:
    """把章节 HTML（<article><p><blk>…）拆成段落列表并去标签。"""
    text = html_module.unescape(content)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"(?i)</h\d\s*>", "\n", text)  # 章节标题与正文分段
    plain = _TAG_RE.sub("", text)
    paragraphs = [line.strip() for line in plain.split("\n")]
    return [p for p in paragraphs if p]


def _load_reference_glyphs() -> list[tuple[str, "object", "object", int]]:
    """加载可用的系统中文字体，返回 (路径, glyphset, cmap, upem) 列表。"""
    from fontTools.ttLib import TTFont

    loaded = []
    for path in _REFERENCE_FONTS:
        if not os.path.exists(path):
            continue
        try:
            font = TTFont(path, fontNumber=0, lazy=True)
            loaded.append((path, font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm))
        except Exception:  # noqa: BLE001 - 单个字体损坏不影响其余
            continue
    if not loaded:
        raise RuntimeError(
            "未找到可用的系统中文字体（需要 msyh/simhei 等），无法还原混淆字符"
        )
    return loaded


def _glyph_signature(glyphset, name: str, upem: int):
    """字形轮廓均匀重采样为点集（归一化到 0..1000），供距离匹配。"""
    import numpy as np
    from fontTools.pens.recordingPen import RecordingPen

    pen = RecordingPen()
    try:
        glyphset[name].draw(pen)
    except Exception:
        return None, 0, 0.0, 0.0
    contours, current = [], []

    def _points(args):
        return [p for p in args if p is not None and len(p) == 2]

    for operator, args in pen.value:
        if operator == "moveTo":
            current = _points(args)
        elif operator == "lineTo":
            current.extend(_points(args))
        elif operator in ("qCurveTo", "curveTo"):
            current.extend(_points(args))
        elif operator == "closePath":
            if current:
                contours.append(current)
            current = []
    if current:
        contours.append(current)
    if not contours:
        return None, 0, 0.0, 0.0
    points = []
    total = sum(len(c) for c in contours)
    for contour in contours:
        take = max(2, int(48 * len(contour) / total))
        arr = np.asarray(contour, dtype=np.float64)
        picks = np.linspace(0, len(arr) - 1, min(take, len(arr)))
        points.append(arr[np.unique(picks.astype(int))])
    arr = np.vstack(points)
    minv = arr.min(axis=0)
    span = np.clip(arr.max(axis=0) - minv, 1, None)
    scale = 1000.0 / span.max()
    normalized = (arr - minv) * scale
    # 宽高使用归一化后的值（不同字体 upem 不同，原始单位不可比较）
    width, height = float(normalized[:, 0].max()), float(normalized[:, 1].max())
    return normalized[:48], len(contours), width, height


def _reference_index_file(path: str) -> Path:
    """参考字形索引的磁盘缓存路径（按字体路径与修改时间区分）。"""
    stat = os.stat(path)
    key = hashlib.md5(
        f"{path}|{stat.st_mtime_ns}|{stat.st_size}".encode()
    ).hexdigest()[:16]
    return _cache_dir() / f"refindex_{key}.npz"


def _load_reference_glyphs() -> "list[tuple]":
    """加载系统中文字体的字形签名索引（带磁盘缓存）。

    返回四个平行数组：字符、点集（pad 到 48 点）、轮廓数、归一化宽高。
    """
    import numpy as np

    all_chars, all_points, all_ncont, all_wh = [], [], [], []
    for path in _REFERENCE_FONTS:
        if not os.path.exists(path):
            continue
        cache = _reference_index_file(path)
        if cache.exists():
            try:
                data = np.load(cache, allow_pickle=True)
                all_chars.append(data["chars"])
                all_points.append(data["points"])
                all_ncont.append(data["ncont"])
                all_wh.append(data["wh"])
                continue
            except Exception:  # noqa: BLE001 - 缓存损坏则重建
                pass
        from fontTools.ttLib import TTFont

        font = TTFont(path, fontNumber=0, lazy=True)
        glyphset = font.getGlyphSet()
        cmap = font.getBestCmap()
        upem = font["head"].unitsPerEm
        chars, points, nconts, whs = [], [], [], []
        for code, name in cmap.items():
            if not (0x4E00 <= code <= 0x9FFF or 0x3000 <= code <= 0x303F
                    or 0xFF00 <= code <= 0xFFEF or 0x20 <= code <= 0x7E):
                continue
            signature = _glyph_signature(glyphset, name, upem)
            if signature[0] is None:
                continue
            normalized, ncont, width, height = signature
            chars.append(chr(code))
            points.append(normalized)
            nconts.append(ncont)
            whs.append((width, height))
        if not chars:
            continue
        np.savez_compressed(
            cache,
            chars=np.array(chars, dtype="U1"),
            points=_pad_points(points, np),
            ncont=np.array(nconts, dtype=np.int32),
            wh=np.array(whs, dtype=np.float64),
        )
        all_chars.append(np.array(chars, dtype="U1"))
        all_points.append(_pad_points(points, np))
        all_ncont.append(np.array(nconts, dtype=np.int32))
        all_wh.append(np.array(whs, dtype=np.float64))
    if not all_chars:
        raise RuntimeError(
            "未找到可用的系统中文字体（需要 msyh/simhei 等），无法还原混淆字符"
        )
    return (
        np.concatenate(all_chars),
        np.vstack(all_points),
        np.concatenate(all_ncont),
        np.vstack(all_wh),
    )


def _pad_points(points: list, np):
    """把不等长点集堆叠成 (N, 48, 2)，用 -9999 填充并在匹配时剔除。"""
    array = np.full((len(points), 48, 2), -9999.0)
    for i, item in enumerate(points):
        take = min(len(item), 48)
        array[i, :take] = item[:take]
    return array


def _match_font_map(font_data: bytes) -> dict[str, str]:
    """把混淆字体中全部 PUA 字形与系统字体字形匹配，返回映射。

    参考:把字形轮廓重采样为点集后，以双向 Chamfer 距离取最近字形。
    """
    import numpy as np
    from fontTools.ttLib import TTFont

    obf = TTFont(io.BytesIO(font_data))
    obf_glyphset = obf.getGlyphSet()
    obf_cmap = obf.getBestCmap()
    obf_upem = obf["head"].unitsPerEm

    ref_chars, ref_points, ref_ncont, ref_wh = _load_reference_glyphs()

    mapping: dict[str, str] = {}
    for code, name in obf_cmap.items():
        if not (_PUA_START <= code <= _PUA_END):
            continue
        signature = _glyph_signature(obf_glyphset, name, obf_upem)
        if signature[0] is None:
            continue
        points, ncont, width, height = signature
        mask = (
            (np.abs(ref_ncont - ncont) <= 1)
            & (np.abs(ref_wh[:, 0] - width) <= 0.35 * max(width, 1))
            & (np.abs(ref_wh[:, 1] - height) <= 0.35 * max(height, 1))
        )
        candidates = np.nonzero(mask)[0]
        if not len(candidates):
            continue
        A = np.full((48, 2), -9999.0)
        A[: len(points)] = points
        valid_a = A[:, 0] > -9000
        top = []  # [(score, char)] 保留 top-k，供常用字先验挑选
        # 分块计算：候选可能上万，一次性广播会占用过多内存
        for start in range(0, len(candidates), 2048):
            chunk = candidates[start:start + 2048]
            B = ref_points[chunk]                      # (C,48,2)，-9999 为填充
            diff = B[:, :, None, :] - A[None, None, :, :]  # (C,48B,48A,2)
            dist = np.sqrt((diff * diff).sum(-1))
            valid_b = B[:, :, 0] > -9000
            dist = np.where(valid_b[:, :, None], dist, 1e9)
            dist = np.where(valid_a[None, None, :], dist, 1e9)
            dmin_a = dist.min(axis=1)                  # 每个 A 点到候选字形最近距离
            dmin_b = dist.min(axis=2)                  # 候选字形每个点到 A 最近距离
            score = (
                (dmin_a * valid_a[None, :]).sum(axis=1) / max(int(valid_a.sum()), 1)
                + (dmin_b * valid_b).sum(axis=1) / np.maximum(valid_b.sum(axis=1), 1)
            )
            for local in np.argsort(score)[:24]:
                top.append((float(score[local]), str(ref_chars[chunk[local]])))
        if not top:
            continue
        top.sort()
        best_score, best_char = top[0]

        def _is_hanzi(ch: str) -> bool:
            return 0x4E00 <= ord(ch) <= 0x9FFF

        # 最佳候选不是汉字（标点/符号）时，正文里几乎不可能，改选最佳汉字候选
        if not _is_hanzi(best_char):
            for score_value, char in top[1:12]:
                if _is_hanzi(char) and score_value <= best_score * 2.5:
                    best_char, best_score = char, score_value
                    break
        # 常用字先验：分数接近（±35%）时优先选高频字
        for score_value, char in top[1:12]:
            if char in COMMON_CHARS and score_value <= best_score * 1.35:
                best_char, best_score = char, score_value
                break
        mapping[chr(code)] = best_char
    return mapping


def get_font_map(font_url: str, *, proxy: str | None = None) -> dict[str, str]:
    """获取（带缓存的）PUA→真实字符映射。缓存键为字体内容哈希。"""
    with _font_maps_lock:
        cached = _font_maps.get(font_url)
    if cached:
        return cached

    digest = hashlib.md5(font_url.encode()).hexdigest()[:12]
    map_file = _cache_dir() / f"fontmap_{digest}.json"
    with _font_build_lock:
        with _font_maps_lock:
            cached = _font_maps.get(font_url)
        if cached:
            return cached
        if map_file.exists():
            try:
                mapping = json.loads(map_file.read_text(encoding="utf-8"))
                with _font_maps_lock:
                    _font_maps[font_url] = mapping
                return mapping
            except Exception:  # noqa: BLE001 - 缓存损坏则重建
                pass
        font_data = _session(proxy).get(font_url, timeout=30).content
        content_digest = hashlib.md5(font_data).hexdigest()[:10]
        content_file = _cache_dir() / f"fontmap_{content_digest}.json"
        if content_file.exists():
            mapping = json.loads(content_file.read_text(encoding="utf-8"))
        else:
            mapping = _match_font_map(font_data)
            content_file.write_text(
                json.dumps(mapping, ensure_ascii=False), encoding="utf-8"
            )
        with _font_maps_lock:
            _font_maps[font_url] = mapping
        return mapping


def _deobfuscate(text: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return text
    return "".join(
        mapping.get(ch, ch) if _PUA_START <= ord(ch) <= _PUA_END else ch for ch in text
    )


def fetch_chapter(book: BookInfo, chapter: dict, session: requests.Session) -> tuple[str, list[str]]:
    """抓取单章：返回 (标题, 段落列表)。字体映射经 get_font_map 自动缓存。"""
    item_id = chapter["item_id"]
    response = session.get(f"https://fanqienovel.com/reader/{item_id}", timeout=25)
    response.raise_for_status()
    text = response.text
    index = text.find("window.__INITIAL_STATE__")
    if index == -1:
        raise RuntimeError("章节页面解析失败")
    state, _end = json.JSONDecoder().raw_decode(text[text.find("{", index):])
    chapter_data = (state.get("reader") or {}).get("chapterData") or {}
    content = chapter_data.get("content") or ""
    title = chapter_data.get("title") or chapter["title"]
    if not content:
        raise RuntimeError(f"章节内容为空: {title}")

    mapping: dict[str, str] = {}
    pua = {c for c in content if _PUA_START <= ord(c) <= _PUA_END}
    if pua:
        font_urls = [m.replace("\\u002F", "/") for m in _FONT_URL_RE.findall(text)]
        font_url = next(
            (u for u in font_urls if re.search(r"/[0-9a-f]{8,}\.woff2?$", u)),
            font_urls[0] if font_urls else "",
        )
        if not font_url:
            raise RuntimeError("未找到混淆字体地址")
        mapping = get_font_map(font_url, proxy=session.proxies.get("https") or None)
    paragraphs = _content_to_paragraphs(_deobfuscate(content, mapping))
    return title, paragraphs


# -------- 输出（TXT / EPUB） --------

def _write_txt(book: BookInfo, chapters: dict[str, tuple[str, list[str]]],
               order: list[dict], output: Path) -> None:
    lines = [book.title, f"作者：{book.author}", ""]
    if book.abstract:
        lines.extend([book.abstract, ""])
    for chapter in order:
        title, paragraphs = chapters[chapter["item_id"]]
        lines.extend(["", title, ""])
        lines.extend(paragraphs)
    output.write_text("\n".join(lines), encoding="utf-8")


_XHTML_HEAD = (
    '<?xml version="1.0" encoding="utf-8"?>\n'
    '<!DOCTYPE html>\n'
    '<html xmlns="http://www.w3.org/1999/xhtml" xml:lang="zh-CN">\n'
    '<head><meta charset="utf-8"/><title>{title}</title>'
    '<link rel="stylesheet" type="text/css" href="style.css"/></head>\n'
    '<body><h2>{title}</h2>\n'
)


def _chapter_xhtml(title: str, paragraphs: list[str]) -> str:
    body = "\n".join(f"<p>{html_module.escape(p)}</p>" for p in paragraphs)
    return _XHTML_HEAD.format(title=html_module.escape(title)) + body + "\n</body></html>\n"


def _write_epub(book: BookInfo, chapters: dict[str, tuple[str, list[str]]],
                order: list[dict], output: Path) -> None:
    uid = f"urn:fanqie:{book.book_id}"
    files: dict[str, tuple[bytes, int]] = {
        # (内容, zip 压缩方式) —— mimetype 必须首个且不压缩
        "mimetype": (b"application/epub+zip", zipfile.ZIP_STORED),
        "META-INF/container.xml": (
            '<?xml version="1.0"?>\n<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>',
            zipfile.ZIP_DEFLATED,
        ),
        "OEBPS/style.css": (
            "body{font-family:serif;line-height:1.7;margin:1em}"
            "h2{font-size:1.2em;margin:0.8em 0}p{text-indent:2em;margin:0.4em 0}",
            zipfile.ZIP_DEFLATED,
        ),
    }
    manifest, spine, nav_items, ncx_items = [], [], [], []
    for number, chapter in enumerate(order, 1):
        title, paragraphs = chapters[chapter["item_id"]]
        name = f"chapter_{number:05d}.xhtml"
        files[f"OEBPS/{name}"] = (_chapter_xhtml(title, paragraphs), zipfile.ZIP_DEFLATED)
        manifest.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{number}"/>')
        nav_items.append(f'<li><a href="{name}">{html_module.escape(title)}</a></li>')
        ncx_items.append(
            f'<navPoint id="n{number}" playOrder="{number}">'
            f'<navLabel><text>{html_module.escape(title)}</text></navLabel>'
            f'<content src="{name}"/></navPoint>'
        )

    meta_lines = [
        f"<dc:title>{html_module.escape(book.title)}</dc:title>",
        f"<dc:creator>{html_module.escape(book.author)}</dc:creator>",
        f"<dc:language>zh-CN</dc:language>",
        f"<dc:identifier id=\"uid\">{uid}</dc:identifier>",
        f"<dc:description>{html_module.escape(book.abstract[:300])}</dc:description>",
    ]
    files["OEBPS/content.opf"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="uid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">' + "".join(meta_lines) + "</metadata>"
        "<manifest>"
        '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        '<item id="css" href="style.css" media-type="text/css"/>'
        + "".join(manifest) +
        "</manifest><spine toc=\"ncx\">" + "".join(spine) + "</spine></package>",
        zipfile.ZIP_DEFLATED,
    )
    files["OEBPS/nav.xhtml"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">'
        "<head><meta charset=\"utf-8\"/><title>目录</title></head>"
        "<body><nav epub:type=\"toc\" id=\"toc\"><h1>目录</h1><ol>"
        + "".join(nav_items) + "</ol></nav></body></html>",
        zipfile.ZIP_DEFLATED,
    )
    files["OEBPS/toc.ncx"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">'
        f"<head><meta name=\"dtb:uid\" content=\"{uid}\"/></head>"
        "<docTitle><text>" + html_module.escape(book.title) + "</text></docTitle>"
        "<navMap>" + "".join(ncx_items) + "</navMap></ncx>",
        zipfile.ZIP_DEFLATED,
    )

    with zipfile.ZipFile(output, "w") as archive:
        for name, (data, method) in files.items():
            if isinstance(data, str):
                data = data.encode("utf-8")
            archive.writestr(zipfile.ZipInfo(name), data, compress_type=method)


# -------- 下载入口 --------

def download_novel(
    book_id: str,
    output_dir: str | Path = "novel_downloads",
    *,
    fmt: str = "txt",
    chapter_range: str = "",
    max_workers: int = 4,
    delay: float = 0.2,
    proxy: str | None = None,
    on_progress=None,
) -> NovelSummary:
    """下载整本（或指定范围）小说。on_progress(完成数, 总数, 章节标题)。"""
    if fmt not in {"txt", "epub"}:
        raise ValueError(f"不支持的格式: {fmt}")
    book = fetch_book(book_id, proxy=proxy)
    order = book.chapters
    bounds = parse_chapter_range(chapter_range, len(order))
    if bounds:
        order = order[bounds[0] - 1: bounds[1]]
    summary = NovelSummary(total=len(order))

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = ".txt" if fmt == "txt" else ".epub"
    output = output_dir / f"{sanitize_filename(book.title)}{suffix}"
    summary.output = str(output)

    session = _session(proxy)
    chapters: dict[str, tuple[str, list[str]]] = {}
    lock = threading.Lock()
    done = [0]
    stop = threading.Event()

    def fetch_one(chapter: dict) -> None:
        if stop.is_set():
            return
        for attempt in range(3):
            try:
                title, paragraphs = fetch_chapter(book, chapter, session)
                break
            except Exception as exc:  # noqa: BLE001 - 单章重试
                if attempt == 2:
                    with lock:
                        summary.failed += 1
                    print(f"下载失败: {chapter['title']} ({exc})", file=sys.stderr)
                    return
                time.sleep(1.0 + attempt)
        with lock:
            chapters[chapter["item_id"]] = (title, paragraphs)
            done[0] += 1
            summary.downloaded += 1
            if on_progress:
                on_progress(done[0], len(order), title)
        if delay > 0:
            time.sleep(delay)

    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        list(pool.map(fetch_one, order))

    if not chapters:
        raise RuntimeError("没有成功下载任何章节")
    if fmt == "txt":
        _write_txt(book, chapters, order, output)
    else:
        _write_epub(book, chapters, order, output)
    print(
        f"\n完成: 《{book.title}》{summary.downloaded}/{summary.total} 章"
        + (f"，失败 {summary.failed}" if summary.failed else "")
        + f" → {output}"
    )
    return summary


# -------- CLI --------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="番茄小说搜索与下载（仅供学习研究，请尊重作者版权）。"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    search_parser = sub.add_parser("search", help="按书名搜索")
    search_parser.add_argument("keyword", help="搜索关键词")

    download_parser = sub.add_parser("download", help="下载书籍（书页地址或 book_id）")
    download_parser.add_argument("book", help="书籍 ID 或 fanqienovel.com 书页地址")
    download_parser.add_argument("-o", "--output", type=Path, default=Path("novel_downloads"))
    download_parser.add_argument("--format", choices=("txt", "epub"), default="txt")
    download_parser.add_argument("--range", dest="chapter_range", help="章节范围，如 1-100（默认全部）")
    download_parser.add_argument("--workers", type=int, default=4, help="并发数（默认 4）")
    download_parser.add_argument("--proxy", help="HTTP 代理地址")

    args = parser.parse_args(argv)
    try:
        if args.command == "search":
            books = search_books(args.keyword)
            if not books:
                print("没有搜索到结果。")
                return 0
            for number, book in enumerate(books, 1):
                print(f"  [{number}] {book.title} | {book.author} | id={book.book_id}")
                if book.abstract:
                    print(f"      {book.abstract[:60]}")
            return 0
        book_id = args.book.rstrip("/").rsplit("/", 1)[-1]
        summary = download_novel(
            book_id, args.output,
            fmt=args.format, chapter_range=args.chapter_range,
            max_workers=args.workers, proxy=args.proxy,
            on_progress=lambda done, total, title: print(
                f"[{done}/{total}] {title}"
            ),
        )
        return 1 if summary.failed and not summary.downloaded else 0
    except (requests.RequestException, OSError, RuntimeError, ValueError) as exc:
        print(f"错误: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
