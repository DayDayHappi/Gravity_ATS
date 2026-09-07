from types import SimpleNamespace

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.core.result import Response
from ATS.modules.wifi import WifiJoinModule


def test_wifi_post_join_stabilization_is_cancellable():
    token = CancellationToken()
    token.cancel("stop after IP")
    ctx = SimpleNamespace(
        skip_wifi=False,
        system_config={"wifi": {"default_ssid": "x", "default_password": "y"}},
        cancellation_token=token,
    )
    console = SimpleNamespace(exec_async=lambda *_args, **_kwargs: Response(success=True, matched="1.2.3.4"))

    with pytest.raises(OperationCancelled):
        WifiJoinModule({}).run(ctx, console)
