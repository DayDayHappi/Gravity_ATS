"""cam_test 业务判据正则离线单测（utest 新增 cam_test，Level 1）。

锁定 `drivers/utest/cam_commands.py` 的 BUSINESS_RES[0]：

- 对实测行 `sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok` **命中**；
- 对不等值行 `sif0  [0xf9000254]=0x0000030c (expect 0x0000030d) ok` **不命中**
  （验证回引 \\1 强校验语义：val 必须 == expect）；
- 对缺失/异常行不命中。

不真机依赖，纯正则语义锁定。
"""
import re
import unittest

from ATS.drivers.utest import cam_commands

_SIF0_OK = "sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok"


class CamCommandsTest(unittest.TestCase):

    def test_testcase_name(self):
        self.assertEqual(cam_commands.TESTCASE, "cam_test")
        self.assertEqual(len(cam_commands.BUSINESS_RES), 1)

    def test_match_real_sample(self):
        # 实测样例行（含前导空格与行内多空格）命中
        self.assertIsNotNone(re.search(cam_commands.BUSINESS_RES[0], _SIF0_OK))

    def test_strong_check_value_mismatch(self):
        # expect 值与实测值不等 → 回引 \1 不满足 → 不命中（强校验）
        mismatch = "sif0  [0xf9000254]=0x0000030c (expect 0x0000030d) ok"
        self.assertIsNone(re.search(cam_commands.BUSINESS_RES[0], mismatch))

    def test_no_ok_suffix_no_match(self):
        # 缺尾 ok → 不命中
        no_ok = "sif0  [0xf9000254]=0x0000030c (expect 0x0000030c)"
        self.assertIsNone(re.search(cam_commands.BUSINESS_RES[0], no_ok))

    def test_other_register_dump_no_match(self):
        # 同段其他寄存器 dump 行（无 expect/ok）不命中
        csi0 = "csi0  [0xf9000258]=0x00000000"
        self.assertIsNone(re.search(cam_commands.BUSINESS_RES[0], csi0))

    def test_ansi_stripped_leading_whitespace_tolerated(self):
        # ANSI 剥离后仅保留行首空白也能命中（\s+ 容忍）
        line = "  sif0  [0xf9000254]=0x0000030c (expect 0x0000030c) ok\n"
        self.assertIsNotNone(re.search(cam_commands.BUSINESS_RES[0], line))


class CamModuleRegistrationTest(unittest.TestCase):

    def test_module_registered(self):
        import ATS.modules.utest  # noqa: F401  触发各 case 模块 @register
        from ATS.modules.base import get_module_cls
        mod = get_module_cls("utest_cam")
        self.assertIsNotNone(mod)
        self.assertEqual(mod.testcase, "cam_test")
        self.assertEqual(mod.business_res, cam_commands.BUSINESS_RES)


if __name__ == "__main__":
    unittest.main()
