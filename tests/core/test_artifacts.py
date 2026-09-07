import json

from ATS.core.artifacts import Artifact
from ATS.core.reporter import write_json
from ATS.core.result import TestResult


def test_artifact_round_trip_and_report_is_generic(tmp_path):
    artifact = Artifact(kind="custom-dump", path=str(tmp_path / "x.bin"), label="dump", metadata={"size": 3})
    result = TestResult(name="x", module="x", status="PASS", artifacts=[artifact])

    path = write_json([result], str(tmp_path))
    data = json.loads(open(path, encoding="utf-8").read())

    assert data["results"][0]["artifacts"] == [artifact.to_dict()]
    assert Artifact.from_dict(data["results"][0]["artifacts"][0]) == artifact
