"""跨模块共享上下文。

模块之间通过 ``Context`` 传递数据，避免模块直接互相 import：
- ``wifi`` 连上后把 ``evb_ip`` 放进 ctx
- ``ftp`` 连上后把 ``ftp_client`` 放进 ctx
- ``photo``/``video`` 从 ctx 取 ``ftp_client`` 验证文件

这样模块间只约定"数据契约"（ctx 里的 key），不约定"代码依赖"，
新增/删减模块不会牵连其他模块。
"""


class Context:
    """本次测试运行的全局共享上下文。

    用属性访问 + dict 存储二合一：``ctx.evb_ip`` 等价于 ``ctx["evb_ip"]``。
    未设置的属性返回 None，避免 KeyError 打断流程。
    """

    # 约定的 key（仅作文档，不强制）
    # evb_ip:        str     WiFi 连上后 EVB 的 IP
    # pc_ip:         str     PC 与 EVB 通信的本机 IP（RTMP 推流目标）
    # ftp_client:    FtpClient  FTP 服务器启动并连上后的客户端实例
    # wifi_ssid:     str     实际连接的 SSID
    # skip_wifi:     bool    WiFi 已交互连上，跳过 wifi 用例
    # console:       SerialConsole  串口控制台（由 runner 注入）

    def __init__(self):
        self._data = {}

    def __getattr__(self, name):
        # 注意：仅对未在 __dict__ 中定义的属性生效；_data 走本路径
        if name.startswith("_"):
            raise AttributeError(name)
        return self._data.get(name)

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value

    def __getitem__(self, key):
        return self._data.get(key)

    def __setitem__(self, key, value):
        self._data[key] = value

    def __contains__(self, key):
        return key in self._data

    def as_dict(self) -> dict:
        return dict(self._data)

    def cleanup(self):
        """清理上下文持有的资源（如 FTP 连接）。由 runner 在结束时调用。"""
        ftp = self._data.get("ftp_client")
        if ftp is not None:
            try:
                ftp.close()
            except Exception:
                pass
        self._data.clear()
