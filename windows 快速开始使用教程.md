# Windows 快速开始使用教程（傻瓜版）

> 本教程只针对 **Windows 电脑**，一步步照着做就能把环境装好、把开发板跑起来测试。
> 全程用「复制 → 粘贴 → 回车」的方式操作，不需要懂代码。

---

## 先搞清楚：这工程是干嘛的？

这工程就是一台「自动测试机」：让电脑（上位机）自动通过串口控制开发板，让它拍照、录像、推流，再把结果自动下载回来、自动判断对错、自动生成报告。

你要做的只有三件事：

1. **跑一次一键准备脚本**（自动装好 Python、依赖、ffmpeg、防火墙等一切）
2. **改一个配置文件**（告诉电脑你的 WiFi 密码和串口在哪）
3. **敲一条命令**（开始测试）

下面按顺序来。

---

## 第一步：打开「正确」的终端窗口

1. 按键盘 `Win + R`，输入 `powershell`，按回车。
2. 你会看到一个蓝底白字的窗口，这就是命令行。

> ⚠️ 一定要用 **PowerShell**，不要用「命令提示符（cmd）」。

---

## 第二步：进入工程目录

把下面这行**整行复制**，粘贴到 PowerShell 窗口里，按回车：

```powershell
cd D:\prj\Gravity_ATS
```

> 如果你的工程放在别的盘/别的文件夹，就把 `D:\prj\Gravity_ATS` 换成你的实际路径。
> （怎么找路径？在文件资源管理器里打开工程文件夹，点顶部的地址栏，复制那一整行。）

---

## 第三步：一键准备环境（最关键的一步）

复制下面这行，粘贴后按回车：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
```

这行命令会自动帮你做完下面这些事：

- ✅ 检查/安装 **Python**
- ✅ 建好虚拟环境 `.venv-cli`，装好所有依赖
- ✅ 检查 **ffmpeg / ffprobe / ffplay**（没有就自动用 winget 装）（这个过程由于网络原因可能会比较慢）
- ✅ 建好**防火墙规则**（让开发板能通过 FTP 把照片视频传回电脑）

> 💡 **嫌 ffmpeg 下载慢？** 可以在命令后面加一个参数 `-NoFfmpeg`，跳过 winget 下载：
>
> ```powershell
> powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1 -NoFfmpeg
> ```
>
> 然后你自己用别的方式（比如浏览器去 https://www.gyan.dev/ffmpeg/builds/ 下载压缩包，或从别的电脑拷贝）拿到三个文件：`ffmpeg.exe`、`ffprobe.exe`、`ffplay.exe`，
> 把它们放到工程的 `tools\ffmpeg\` 文件夹里就行了。程序会自动找到它们，以后再跑脚本也会识别到（这是免下载的官方推荐方式）。
> BSP组共享盘路径：Z:\软件工程\内部共享\BSP\ATS\tools\ffmpeg-9.0.1-full_build 


**过程中你可能会遇到：**

1. **弹出「用户账户控制」窗口问你要不要允许管理员权限** → 点「是」。
   （这个是为了配防火墙，必须点「是」，否则后面开发板的照片传不回来。）
2. **第一次没装 Python** → 脚本会提示你去 https://www.python.org/downloads/ 下载安装，
   装的时候**一定要勾选 `Add to PATH`**，装完再回到这里重跑一次第三步。

**跑完后，看最后几行：**

- 出现绿色的「**全部就绪**」 → 恭喜，环境 OK，继续下一步。
- 出现红色的「**待人工处理**」 → 把那些红字截图，照着提示去处理，处理完重跑一次第三步。

> 小技巧：这个脚本可以反复跑，跑多少次都不会重复安装、不会搞坏东西（幂等）。

---

## 第四步：改配置文件（告诉电脑你的板子信息）

用记事本打开这个文件：

```
ATS\config\system.yaml
```

只需确认/修改下面三处（用记事本的 `Ctrl+F` 搜索对应英文单词）：

### ① 串口（板子插在哪个口）

```yaml
serial:
  port: "auto"
```

- 大多数情况下**保持 `auto` 就行**，程序会自动帮你找到开发板。
- 如果自动找不到，改成你设备管理器里看到的实际端口，比如 `"COM10"`。

### ② WiFi 账号密码

```yaml
wifi:
  default_ssid: "sw_test_24g"
  default_password: "12345678"
```

- 把 `default_ssid` 改成你板子要连的 WiFi 名字。
- 把 `default_password` 改成这个 WiFi 的密码。
- 如果启动时想自己选 WiFi，就把 `interactive: true` 保持原样；想自动连就改成 `false`。

### ③ 电源控制器开关（大多数人这里要改！）

```yaml
power_switch:
  enabled: true
```

- **如果你没有插「串口电源控制器」这个硬件，把 `true` 改成 `false`。**
- 然后手动给开发板上电。
- 如果确实接了电源控制器，就保持 `true`。

改完保存文件（`Ctrl + S`）。

---

## 第五步：先「空跑」检查一遍（不碰板子，安全）

复制粘贴回车：

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --dry-run
```

- 这一步**不会真的测试板子**，只是检查配置有没有错。
- 看到结尾没有报红字、正常退出，就说明配置 OK。
- 顺便可以看有哪些功能、哪些场景：

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --list-scenarios
```

---

## 第六步：正式开始测试开发板

**在跑之前，确认硬件接好了：**

1. 开发板**已上电**。
2. 串口 USB 线**插到电脑上**了。
3. 摄像头**接好了**（要测拍照/录像的话）。

然后复制下面这条最常用的命令，回车：

```powershell
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario normal --no-interactive-wifi
```

- `normal` = 标准测试（eMMC + 拍照 + 录像 + 推流）
- `--no-interactive-wifi` = 用配置文件里写好的 WiFi，不弹选择框

程序会自己开始跑，屏幕上会不断打印进度。跑完会告诉你哪些 PASS、哪些 FAIL，并生成报告。

---

## 常用的几条命令（照着抄）

| 想做什么 | 用这条命令 |
|----------|-----------|
| 标准测试（拍照+录像+推流） | `.\.venv-cli\Scripts\python.exe -m ATS.main --scenario normal --no-interactive-wifi` |
| 压力测试（循环很多轮，时间很长） | `.\.venv-cli\Scripts\python.exe -m ATS.main --scenario stress --no-interactive-wifi` |
| 不联网的简单测试（不用 WiFi/FTP） | `.\.venv-cli\Scripts\python.exe -m ATS.main --scenario no_network` |
| 只看板子自检 | `.\.venv-cli\Scripts\python.exe -m ATS.main --scenario utest` |
| 空跑检查（不碰板子） | `.\.venv-cli\Scripts\python.exe -m ATS.main --dry-run` |
| 手动串口调试（像 Xcom 那样敲命令） | `.\.venv-cli\Scripts\python.exe -m ATS.main --terminal` |

> **第一次测试，建议先跑 `no_network`**（不联网、最简单、最快），确认板子串口能通、能拍照录像了，再跑 `normal` 这种联网全功能测试。

---

## 测试结果和日志在哪看？

每次测试跑完，结果保存在：

```
logs\<场景名>\<日期>\<时间>\
reports\<日期>\<时间>\        （normal 场景的报告）
```

- `run.log` —— 程序运行过程
- `serial.log` —— 开发板串口收发记录
- `photos/`、`videos/` —— 下载下来的照片和录像
- `report.html` —— 用浏览器打开看的测试报告

---

## 遇到问题怎么办？（常见坑）

| 现象 | 原因 | 怎么办 |
|------|------|--------|
| 提示 `Python was not found` | Windows 里 `python3` 会被商店空壳劫持 | 别用 `python3`，一定用 `.\.venv-cli\Scripts\python.exe` |
| 拍照每项卡很久、`FTP list 失败: timed out` | 防火墙规则把开发板 IP 锁死了 | 用**管理员** PowerShell 确认规则 `Gravity ATS CLI FTP - Board101` 的 `RemoteAddress` 是**网段** `192.168.1.0/24`（不是单个 IP）。开发板 IP 会漂移，必须写网段。 |
| 提示 `无候选串口` / 找不到板子 | USB 没插好、板子没上电 | 检查 USB 线、确认板子上电，重新插拔后再跑 |
| 报 `1935 端口未监听` | 没装 RTMP 服务端（nginx） | 这是**可忽略**的警告，只影响「画面预览」，不影响拍照/录像的判断结果 |
| 报告里出现 FAIL | 看 `run.log` 和 `serial.log` 排查 | 别只看最后一行，结合串口原文一起看 |

---

## 一句话总结（赶时间版）

```powershell
cd D:\prj\Gravity_ATS
powershell -ExecutionPolicy Bypass -File scripts\setup_windows.ps1
# 改好 ATS\config\system.yaml 里的 WiFi / 串口 / 电源开关
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario normal --no-interactive-wifi
#如果你没有路由器使用
.\.venv-cli\Scripts\python.exe -m ATS.main --scenario stress_NoFtp_NoRtmp
```

三条命令 + 改一个文件，搞定。
