"""各工具视图与注册表。"""

from .base import ToolView
from .download_view import DownloadView
from .grab_view import GrabView
from .image_view import ImageView
from .media_view import MediaView
from .novel_view import NovelView
from .rename_view import RenameView
from .suffix_view import SuffixView

VIEW_CLASSES = (ImageView, MediaView, GrabView, DownloadView, SuffixView, RenameView, NovelView)
