from ATS.application.service import TestService
from ATS.platform.resources import ResourceLocator


def test_service_exposes_scenario_and_port_discovery_without_gui_touching_core(tmp_path):
    app = tmp_path / "app"
    config = app / "ATS" / "config" / "scenarios"
    config.mkdir(parents=True)
    (config / "zeta.yaml").write_text("scenario:\n  name: zeta\n  tasks:\n    - module: emmc\n", encoding="utf-8")
    (app / "ATS" / "config" / "system.yaml").write_text(
        "serial:\n  port: auto\n  baudrate: 2000000\n", encoding="utf-8"
    )

    class Ports:
        def list_ports(self):
            return [type("P", (), {"device": "COM10"})()]

    class Services:
        resources = ResourceLocator(app_root=app, frozen=False)
        serial_ports = Ports()

    service = TestService(resource_locator=Services.resources, platform_services=Services())

    assert service.list_scenarios() == ["zeta"]
    assert [port.device for port in service.list_serial_ports()] == ["COM10"]
    description = service.describe_scenario("zeta")
    assert description.name == "zeta"
    assert [task.module for task in description.tasks] == ["emmc"]
