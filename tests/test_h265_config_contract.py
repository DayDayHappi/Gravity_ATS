from ATS.drivers.h265_validator import H265Validator


class Locator:
    def find_tool(self, name, preferred=None):
        return preferred or name


def test_h265_validator_does_not_mutate_caller_config():
    locator = Locator()
    config = {
        "_resource_locator": locator,
        "analysis": {"decode_check": True},
        "input": {"patterns": ["*.h265"]},
    }

    validator = H265Validator(config)

    assert config["_resource_locator"] is locator
    assert validator.config is not config
