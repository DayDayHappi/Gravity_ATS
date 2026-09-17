"""utest 模块包：每 testcase 一个模块（D2），替代原单文件 utest.py。

导入各 case 模块触发 @register；注册名 = utest_<case>（见 §5 映射表）。
"""
from . import efuse  # noqa: F401
from . import filesystem  # noqa: F401
from . import i2c  # noqa: F401
from . import imu  # noqa: F401
from . import pvt_auto  # noqa: F401
from . import pvt  # noqa: F401
from . import flash_xip_speed  # noqa: F401
from . import flash_read  # noqa: F401
