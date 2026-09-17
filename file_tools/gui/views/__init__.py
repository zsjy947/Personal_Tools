"""各工具视图与注册表。"""

from .base import ToolView
from .copy_view import CopyView
from .dot1_view import Dot1View
from .image_view import ImageView
from .media_view import MediaView

VIEW_CLASSES = (ImageView, MediaView, Dot1View, CopyView)
