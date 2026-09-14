"""eMMC 固件协议定义：命令与超时的唯一维护位置。

本文件不发送串口、不读取 YAML，也不安排测试次数或时长。
"""
EMMC_FORMAT_COMMAND = "mkfs -t elm sd"
EMMC_MOUNT_COMMAND = "mount sd /emmc elm"
EMMC_CD_COMMAND = "cd /emmc"
# preclean 动作回根目录命令（避免上次运行残留当前目录）
EMMC_CD_ROOT_COMMAND = "cd /"
EMMC_FORMAT_TIMEOUT = 60.0
EMMC_MOUNT_TIMEOUT = 15.0
EMMC_CD_TIMEOUT = 10.0
EMMC_CD_ROOT_TIMEOUT = 5.0
