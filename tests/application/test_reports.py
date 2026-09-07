import json

from ATS.application.reports import ReportDocument


def test_report_document_loads_unknown_artifact_types_without_gui_branches(tmp_path):
    path = tmp_path / "result.json"
    path.write_text(json.dumps({
        "summary": {"total": 1, "passed": 1},
        "results": [{
            "name": "dump", "module": "future_module", "status": "PASS",
            "elapsed_ms": 12, "message": "ok", "detail": "",
            "artifacts": [{"kind": "future-kind", "path": "x.dat", "label": "X", "metadata": {}}],
        }],
    }), encoding="utf-8")

    document = ReportDocument.load(path)

    assert document.summary["passed"] == 1
    assert document.results[0].artifacts[0].kind == "future-kind"
