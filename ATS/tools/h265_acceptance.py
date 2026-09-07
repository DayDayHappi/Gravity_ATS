"""Run one H.265 file through the production TestService and record evidence."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ATS.application.models import RunRequest, RunStatus
from ATS.application.service import TestService


def build_request(file_path: str, output_dir: str = None) -> RunRequest:
    """Build an explicit single-file request without rewriting scenario YAML."""
    source = Path(file_path).expanduser().resolve()
    return RunRequest(
        scenario="video_integrity",
        module_overrides={
            "video_integrity": {
                "input": {
                    "source": "directory",
                    "directory": str(source.parent),
                    "selection": "explicit",
                    "explicit_files": [source.name],
                    "recursive": False,
                }
            }
        },
        output_dir=output_dir,
        no_interactive_wifi=True,
    )


def expectation_met(actual_status, expected: str) -> bool:
    actual = getattr(actual_status, "value", str(actual_status)).upper()
    return actual == str(expected).upper()


def result_to_dict(result) -> dict:
    return {
        "run_id": result.run_id,
        "scenario": result.scenario,
        "status": result.status.value,
        "exit_code": result.exit_code,
        "error": result.error,
        "log_dir": result.log_dir,
        "report_dir": result.report_dir,
        "report_paths": dict(result.report_paths),
        "results": [
            {
                "name": item.name,
                "module": item.module,
                "status": item.status,
                "message": item.message,
                "detail": item.detail,
                "artifacts": [artifact.to_dict() for artifact in item.artifacts],
            }
            for item in result.results
        ],
    }


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Gravity ATS H265 release acceptance")
    parser.add_argument("--file", required=True, help="H265/HEVC file, including paths with spaces/Chinese")
    parser.add_argument("--expect", choices=("PASS", "FAIL"), required=True)
    parser.add_argument("--json-out", default="")
    parser.add_argument("--output-dir", default=None)
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    source = Path(args.file).expanduser().resolve()
    if not source.is_file():
        print(f"Input file does not exist: {source}")
        return 2
    result = TestService().run(build_request(str(source), args.output_dir))
    evidence = result_to_dict(result)
    evidence["input_file"] = str(source)
    evidence["expected_status"] = args.expect
    evidence["expectation_met"] = expectation_met(result.status, args.expect)
    payload = json.dumps(evidence, ensure_ascii=False, indent=2)
    if args.json_out:
        destination = Path(args.json_out).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(payload, encoding="utf-8")
    print(payload)
    if result.status is RunStatus.ERROR:
        return 2
    return 0 if evidence["expectation_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
