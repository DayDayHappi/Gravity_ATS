import time

import pytest

from ATS.core.cancellation import CancellationToken, OperationCancelled
from ATS.drivers import ftp_client


class FailingFtp:
    def connect(self, *args, **kwargs):
        raise OSError("offline")

    def close(self):
        pass


def test_ftp_connect_retry_sleep_is_cancellable(monkeypatch):
    monkeypatch.setattr(ftp_client, "FTP", FailingFtp)
    token = CancellationToken()
    client = ftp_client.FtpClient("192.0.2.1", retry=10, interval=30, cancellation_token=token)
    import threading
    threading.Timer(0.1, lambda: token.cancel("stop ftp")).start()

    started = time.monotonic()
    with pytest.raises(OperationCancelled):
        client.connect()
    assert time.monotonic() - started < 1.5


def test_ftp_size_does_not_swallow_cancellation():
    token = CancellationToken()
    token.cancel("stop size")
    client = ftp_client.FtpClient("192.0.2.1", cancellation_token=token)
    client._ftp = object()

    with pytest.raises(OperationCancelled):
        client.size("/emmc/VIDEO/test.h265")
