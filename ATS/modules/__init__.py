"""模块层包初始化。

导入所有模块子模块以触发 @register 注册。
新增模块时，在此追加一行 import 即可（或新建模块文件后在这里加导入）。
"""
from . import base  # noqa: F401
from . import wifi  # noqa: F401  (注册 wifi_scan, wifi_join)
from . import emmc  # noqa: F401
from . import ftp  # noqa: F401
from . import photo  # noqa: F401
from . import video  # noqa: F401
from . import rtmp  # noqa: F401
from . import download  # noqa: F401
from . import video_integrity  # noqa: F401
