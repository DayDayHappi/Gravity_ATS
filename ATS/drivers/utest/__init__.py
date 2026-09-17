"""utest 固件自检协议包（ADR-012 + ADR-011）。

协议唯一来源分布：
- ``_common.py``：公共协议（命令 / result 行正则 / 每项超时映射）。
- ``<case>_commands.py``：各 testcase 的 testcase 名 + 业务关键串正则。

业务代码只 import，不内联协议字符串。
"""
