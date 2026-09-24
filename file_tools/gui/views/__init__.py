"""各工具视图与注册表（侧边栏按 VIEW_GROUPS 分组展示）。"""

from .base import ToolView
from .convert_view import ConvertView
from .download_view import DownloadView
from .grab_view import GrabView
from .image_view import ImageView
from .media_view import MediaView
from .novel_view import NovelView
from .rename_view import RenameView
from .suffix_view import SuffixView

# 侧边栏分组：（分组名，视图类…）；分组名承担「对象」，视图 NAV 只写动作短名
VIEW_GROUPS = (
    ("图片", (ImageView, ConvertView, RenameView, DownloadView)),
    ("媒体", (MediaView, GrabView)),
    ("文件 / 小说", (SuffixView, NovelView)),
)

VIEW_CLASSES = tuple(cls for _title, classes in VIEW_GROUPS for cls in classes)
