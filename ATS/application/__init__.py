"""应用服务层（Application Service，ADR-016）。

跨模块系统级协调：板卡健康监测、恢复协调、运行时协同控制。不属于 Scenario
Task，也不属于具体业务模块。

职责分离（红线）：
- ``BoardHealthMonitor`` 只监测（输出 HealthEvent），不认识 PowerSwitch。
- ``RecoveryCoordinator`` 只协调（消费健康状态、决策、调度恢复）。
- ``RecoveryBackend`` 只适配恢复能力（PowerCycle → ctx.power_switch.reboot()）。
- ``PowerSwitch`` 只上下电。
- Module 不认识 Recovery；Runner 不认识具体硬件。
"""
