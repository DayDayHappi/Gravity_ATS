from ATS.application.interaction import NonInteractiveInteractionProvider


def test_noninteractive_provider_never_reads_stdin_and_uses_defaults(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("stdin used")))
    provider = NonInteractiveInteractionProvider()

    assert provider.confirm("continue?", default=True) is True
    assert provider.choose("pick", ["first", "second"], default_index=1) == "second"
    assert provider.ask_text("ssid", default="configured") == "configured"
