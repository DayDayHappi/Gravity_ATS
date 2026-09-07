"""Non-destructive EVB serial probe used by Windows release acceptance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ATS.core.serial_console import SerialConsole, detect_port
from ATS.platform.serial_ports import PySerialPortProvider


def probe_serial(port: str, baudrate: int, *, console_factory=SerialConsole) -> dict:
    """Exercise ready, health-check, synchronous and asynchronous serial paths."""
    console = console_factory(
        port=str(port),
        baudrate=int(baudrate),
        timeout=0.2,
        ready_timeout=10,
        sentinel_timeout=5,
    )
    result = {
        "port": str(port),
        "baudrate": int(baudrate),
        "ready": False,
        "health_check": False,
        "exec_sync": False,
        "exec_async": False,
        "ok": False,
        "error": "",
    }
    try:
        console.open()
        result["ready"] = bool(console.wait_for_ready())
        if not result["ready"]:
            result["error"] = "msh ready prompt not detected"
            return result
        result["health_check"] = bool(console.health_check())
        sync = console.exec_sync(
            'echo "ATS_WIN_SYNC_OK"',
            expect=r"(?m)^[ \t]*ATS_WIN_SYNC_OK[ \t]*$",
            timeout=5.0,
        )
        result["exec_sync"] = bool(sync.success)
        async_response = console.exec_async(
            'echo "ATS_WIN_ASYNC_OK"',
            expect=r"(?m)^[ \t]*ATS_WIN_ASYNC_OK[ \t]*$",
            result_timeout=5.0,
        )
        result["exec_async"] = bool(async_response.success)
        result["ok"] = all(
            result[key]
            for key in ("ready", "health_check", "exec_sync", "exec_async")
        )
        if not result["ok"]:
            result["error"] = "one or more serial contract checks failed"
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result
    finally:
        console.close()


def write_probe_json(path, result: dict) -> str:
    destination = Path(path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(destination)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Gravity ATS Windows EVB serial probe")
    parser.add_argument("--port", default="auto")
    parser.add_argument("--baudrate", type=int, default=2_000_000)
    parser.add_argument("--json-out", default="")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    port = args.port
    baudrate = args.baudrate
    if port in ("auto", "", None):
        port, detected = detect_port(
            baudrate=baudrate,
            interactive=False,
            port_provider=PySerialPortProvider(),
        )
        if not port:
            result = {
                "port": "",
                "baudrate": baudrate,
                "ok": False,
                "error": "EVB serial port not detected",
            }
            if args.json_out:
                write_probe_json(args.json_out, result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2
        baudrate = detected
    result = probe_serial(port, baudrate)
    if args.json_out:
        write_probe_json(args.json_out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
