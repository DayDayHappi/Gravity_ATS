from types import SimpleNamespace

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.modules.rtmp import RtmpModule


class Server:
    def check_ready(self, timeout=8.0, cancellation_token=None):
        assert cancellation_token is not None
        cancellation_token.raise_if_cancelled()


def test_rtmp_module_passes_run_token_to_server_readiness():
    token = CancellationToken()
    token.cancel("operator stop")
    module = RtmpModule({})
    module._server = Server()
    ctx = SimpleNamespace(pc_ip="127.0.0.1", cancellation_token=token)

    with pytest.raises(OperationCancelled):
        module.run(ctx, SimpleNamespace())
