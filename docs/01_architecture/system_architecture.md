# 系统架构（System Architecture）

> 本文档描述系统分层与流转关系，是修改代码前必读。抽象描述，不含实现细节。

## 1. 分层模型

系统采用 **scenario 驱动的分层执行模型**，自上而下：

```
配置层    system.yaml + modules/*.yaml + scenarios/*.yaml
             │ 参数注入
编排层    ScenarioManager（prepare → tasks(loop) → cleanup）
             │ Task 列表
调度层    Runner（repeat / loop / 重试 / fail-fast）
             │ 逐个模块调用
模块层    wifi / emmc / ftp / photo / video / rtmp（一次测试动作）
             │ 调用通信接口
通信层    SerialConsole（串口） / FtpClient / RtmpReceiver
             │
硬件层    EVB 板（msh shell / FTP 服务 / RTMP 推流）
```

## 2. 职责边界（架构约定，勿破坏）

| 层 | 职责 | 不负责 |
|----|------|--------|
| Scenario | 怎么组合测试（流程 / 循环 / 持续时间） | 不实现测试动作 |
| Runner | 什么时候执行（调度 / 重试 / fail-fast） | 不关心怎么测 |
| Module | 怎么测（一次测试动作 + 参数接口） | 不感知循环 / 场景 |
| Config | 参数是什么 | 不包含逻辑 |

## 3. 控制流

```
启动
 → 加载 scenario（system + modules + scenario 三层配置合并）
 → 执行 prepare 动作（串口初始化、WiFi 连接、清理、FTP 就绪）
 → 按 loop 循环执行 tasks（每个 task 交给 Runner 调度到对应 Module）
 → 执行 cleanup 动作（停推流、关串口）
 → 生成报告，返回退出码
```

- 依赖关系：task 声明 depends；某模块 FAIL/ERROR 时依赖它的模块 SKIP；**SKIP 不阻断依赖**（主动跳过不算失败）。
- 模块按 `scenario.tasks` **声明顺序**执行（不再拓扑排序）。

## 4. 数据流概览

- **串口流**：命令下行 → EVB 执行 → 响应上行 → 哨兵 / 正则解析
- **产物流**：拍照/录像 → EVB 落盘 `/emmc` → FTP 下载到 PC → 校验
- **推流流**：EVB 编码 → RTMP → PC nginx-rtmp → ffprobe 探测

详见 [data_flow.md](data_flow.md)。
