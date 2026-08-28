# stress_traverse_photo_mode.yaml 注释去具体时长/次数（纯注释）

## 日期
2026-08-28

## 变更来源
Document Agent Request（写入 docs/05_handoff/next_step.md 末尾）：场景注释里的具体时长/次数措辞改为「自行按需配置」。

## 做了什么
纯注释修改，不动任何参数值/结构：

1. 第 1 行注释：`# 压测场景：遍历全部拍照模式 + video 3min + rtmp 10min，整轮循环 20 次`
   → `# 压测场景：遍历全部拍照模式（video/rtmp 时长与整轮循环次数自行按需配置）`
   （去掉写死的 3min/10min/20 次）。
2. 第 19 行 `repeat: 1` 行内注释：`# 每个模式各拍 50 次（Runner 每轮 repeat 都完整遍历一次 photo_modes）`
   → `# Runner 每轮 repeat 都完整遍历一次 photo_modes`
   （去掉「每个模式各拍 50 次」，因 repeat 已改 1，原注释与参数不符）。

photo_modes 的 TODO-CONFIRM（hdr 模式名待真机核实）保留不动。

## 改了哪些文件
- `ATS/config/scenarios/stress_traverse_photo_mode.yaml`（仅 2 处注释）

## 如何验证
1. `yaml.safe_load` 解析通过；loop.count=200、photo repeat=1、photo_modes 7 项、video/rtmp duration=20
   均与修改前一致 → PASS（参数值/结构未变）。
2. `grep` 确认第 1 行、第 19 行注释已按需求改写 → PASS。

## 文档影响
无（纯注释，无接口/配置语义变化）。
