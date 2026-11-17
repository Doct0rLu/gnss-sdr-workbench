# GNSS-SDR Workbench v0.3.1

Windows 本地接收机调试工作台。浏览器负责交互，Python 管理独立 GNSS-SDR 进程、监测接口和数据访问。前端与内核分开维护。

## 下载即用（推荐）

Windows 10/11 x64 用户请在 [Releases](https://github.com/Doct0rLu/gnss-sdr-workbench/releases/latest) 下载 [GNSS-SDR-Workbench-v0.3.1-win-x64.zip](https://github.com/Doct0rLu/gnss-sdr-workbench/releases/download/v0.3.1/GNSS-SDR-Workbench-v0.3.1-win-x64.zip)，完整解压后双击 `Start-Workbench.cmd`。它包含 Python、前端、接收机及运行 DLL，无需安装开发环境。接收机路径自动定位；只需选择自己的 IQ 文件。使用方式见 [PORTABLE.md](PORTABLE.md)。

Code → Download ZIP 仅为源码，适用于开发者。便携包不包含 IQ、开发者本机设置或历史运行结果。

## 从源码启动

需要 Python 3.11+，首次执行 `python -m pip install -r requirements.txt`。本机已具备这些依赖。双击 `start.cmd`，浏览器打开 http://127.0.0.1:8765。保持启动窗口开启。端口已占用时先关闭旧工作台窗口，或运行 `python server.py --port 8767 --open`。

当前工作区的 `local.json` 已配置接收机和真实 IQ 路径。独立复制时可用 `local.example.json` 建立自己的配置，也可以直接在界面选择文件。接收机 EXE 需要完整 DLL 环境，建议使用已收集依赖、支持 UTF-8 中文路径的便携构建；额外 DLL 目录可在 local.json 的 dll_dirs 设置。

## 操作顺序

1. 配置实验：浏览选择 EXE、IQ 或 .conf 文件，也可输入路径。设置时长、捕获快照通道、采样率、中频、通道数、环路带宽与搜索参数。高级配置文本可展开编辑。
2. 检查输入，保存配置。配置存储在本机 local.json，刷新后仍保留。
3. 启动实验，或使用“重启接收机”。配置窗口也可以“保存并重启”。重启先向当前进程发送 q，等待正常保存，再创建独立实验，不覆盖原来的输出。30 秒仍未结束时保留停止状态，界面给出提示。
4. 进入单通道或捕获工作区，使用统一时间轴查看和回放。实时跟随、暂停与回放只控制显示，接收机继续计算。

## 统一时间轴与事件回放

- **实时跟随**：持续读取所选通道的最新环路数据和对应捕获帧；“暂停查看”固定当前位置，接收机及写盘继续运行。
- **拖动回看**：拖动时间轴或使用方向键，进入暂停回放状态；所有环路图使用相同的横轴范围。可在同一位置切换通道、单通道与捕获工作区。
- **播放回放**：支持 0.25×、0.5×、1×、2×、4×；回放到已记录末端自动暂停。“实时跟随”可重新追上当前运行；已完成实验显示“回到末尾”。
- **点击事件**：自动选择事件所属通道，固定事件前后的窗口，并联动 PLL、DLL、C/N₀、相关器、锁定指标、捕获快照与对应日志。窗口可选 2/4/6/10 秒，事件位于窗口中央；新数据不会推走已固定的窗口。
- **播放事件片段**：从事件前的窗口起点播放，到窗口终点自动暂停。保留事件后可切换通道，对比同一时段其他通道的表现。
- **图表联动**：悬停时各环路图同步游标；点击图表可定位信号时间。更多 NCO、多普勒和 Prompt I/Q 放在可展开区域。
- **捕获帧联动**：按所选通道和时间，显示该时刻之前最近的捕获快照；不使用未来帧，不混入其他通道。上一帧/下一帧同时移动统一时间轴。捕获快照是离散记录，不做帧间插值。
- **导出切片**：导出当前显示的通道、游标、时间范围、事件、跟踪与捕获数据 JSON。

实时显示以约 200 ms 的调度间隔读取；同一时间最多一个图表读取任务，并只保留最新待处理位置。拖动和切换通道、实验时，旧任务结果不会覆盖新选择。显示速率由数据写盘和读取时间决定，不是无损呈现每一个原生采样历元。

## 工作区

| 工作区 | 实际数据 |
| --- | --- |
| 运行总览 | UDP C/N₀ 趋势、各通道观测状态、Prompt I/Q、运行进度、定位与日志 |
| 单通道 / 环路 | 跟踪 dump 的 PLL/DLL 鉴别器、NCO、E/P/L 相关器、锁定指标、多普勒与 Prompt I/Q |
| 捕获搜索 | 所选通道的历次 MAT73 快照、码延迟峰形、多普勒剖面、二维搜索网格、统计量/门限；全通道成功捕获记录来自 AcquisitionMonitor |
| 输入 I/Q | 文件时间切片、波形、Hann FFT 频谱、I/Q 散点、RMS/DC/满幅比例，支持原始 iq8 切片下载 |
| 卫星星座 | 最近完整 NMEA GSV 组的天空图、方位角、仰角和 C/N₀ |
| 事件 / 切片 | 捕获、跟踪启动、符号输出变化、周跳、失锁、运行停止等已观测事件；点击联动前后 2 秒环路与日志 |
| 数据文件 | 浏览本次目录内的原始日志、dump、MAT、配置、NMEA、定位输出，逐文件下载 |
| 调试接口 | PID、EXE、真实监测端口、数据 API、GDB 附加命令 |

暂停查看只冻结显示；停止与重启控制接收机进程。时间游标与切片不改变接收机闭环计算位置。

PLL 鉴别器依据当前源代码 atan/TWO_PI 显示为 cycle；DLL 为 chip；NCO 分别为 Hz 与 chip/s。输入 IQ 是文件中的原始复样本，频谱单位为 dB re 1 count。卫星天空图是方位/仰角图，I/Q 星座为另一类图。界面不把未知值填为观测结果。

## 数据与接口

每次实验保存在 `runs/<时间-随机编号>/`。包括有效配置 receiver.conf、manifest.json、原始 receiver.log、按信号时钟记录的 logs.jsonl/events.jsonl、接收机原生内部日志、抽样 telemetry.jsonl、acquisitions.jsonl、positions.jsonl、snapshot.json，以及接收机生成的 tracking_ch_*.dat、acquisition_*.mat、NMEA、RINEX、KML 等。

manifest 记录实际配置与 EXE 的 SHA256、输入大小和修改时间、进程命令、版本及退出状态。整份 IQ 没有自动做哈希。内存趋势最多每通道 2,400 点、日志 3,000 行、事件 300 条；原始文件仍保存在磁盘。UDP 不保证交付，抽样 telemetry.jsonl 不是全部数据包的归档。

Tracking dump 时间读取使用二分定位，每次最多返回 1,600 点，原始文件可单独下载。结构化日志按 256 行建立增量时间索引，查询前先按时间块筛选，再按通道取最近 600 行；事件接口最多返回最近 2,000 条。捕获快照索引缓存文件时间戳、大小与信号时间，回放时选择相应帧。老版本实验没有结构化日志时使用原有快照中的保留日志与事件，跟踪 dump 与捕获文件仍可按时间读取。实时写盘文件可能尚有未完整记录的尾部，读取时忽略该尾部。捕获网格保留峰附近 161 点剖面，并对全码延迟轴按列内最大值抽取为热图，避免均值采样抹去尖峰。

只监听 127.0.0.1，检查 Host 与 Origin。只允许下载实验目录内的普通文件。主要读取 API：

```text
GET /api/state?run=<id>
GET /api/inspect?run=<id>&kind=tracking&channel=0&start=10&end=12
GET /api/inspect?run=<id>&kind=acquisition&file=<name.mat>
GET /api/inspect?run=<id>&kind=iq&t=10
GET /api/raw-iq?run=<id>&t=10&count=8192
GET /api/inspect?run=<id>&kind=sky
GET /api/inspect?run=<id>&kind=files
GET /api/file?run=<id>&name=<filename>
POST /api/restart
```

## 当前适配与后续方向

已验证当前 Windows 便携 EXE、GPS L1 C/A、18 MS/s signed int8 I/Q、+20 kHz IF、抽取至 3 MS/s。当前文件输入为 File_Signal_Source/ibyte；样本数按 2 × 采样率 × 时长配置。捕获网格使用内核已有 dump_channel，每次实验选择一个通道；成功捕获消息覆盖各通道。跟踪二进制解析适配当前构建的 112 字节记录。

天空图当前展示最近 GSV，不随历史游标改变；日志时钟精度以接收机输出为准，跟踪启动优先关联捕获样本时刻。定位轨迹以首个定位解为相对原点。GDB 面板展示连接信息，还没有内置源码调试器。输入面板尚未接入抽取后的基带流。后续将继续做各阶段流式抽样接口、多通道捕获网格轮换、历史天空图、参数模板和干净 Windows 系统验收。

接收机内核与工作台分开维护，后续内核接口扩展单独提交上游。项目采用 GPL-3.0-or-later；便携版附接收机对应源码和第三方许可信息。local.json、runs、测试 IQ 与私人验收记录不进入公开源码。

## 验证

### 支持与回归检查

工作台配置、捕获监测和前端卫星标识支持 `Channel.signal=1C` 或 `B3`，按对应的 `Channels_*`、`Tracking_*`、`Acquisition_*` 参数处理。B3I 配置示例为 `templates/bds-b3i-m1-24m.conf`，需用户自行提供匹配 IQ。正常文件结束显示“结束”，文件尾保护提示显示“文件边界”，不当作失锁事件。15 项 Python 检查、JS 语法和回放状态检查通过。

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
node --check web/debug.js
node --check web/replay.js
node tests/replay-model.test.cjs
# 启动 server.py 后，真实 IQ + 重启 + 数据接口检查
python tests/integration_v02.py
```

公开发布检查见 RELEASE-NOTES.md。开发工作区的详细实验记录保存在被忽略的 verification/ 中，不含于公开源码。本轮没有做干净 Windows、硬件或长期运行验收。受控中断测试使用 test-inputs 中的派生文件和独立 runs 输出，配方单独记录，源 IQ 不修改。这些文件不进入源码包。


## 构建便携包

使用 Python 3.12 x64 的独立虚拟环境：

```powershell
python -m venv .build-venv
.build-venv/Scripts/python.exe -m pip install -r requirements-build.txt
.build-venv/Scripts/python.exe build_release.py --receiver C:/path/to/receiver-portable --receiver-source C:/path/to/matching-source.zip
```

输出到 release/。构建脚本只收集 EXE、资源、依赖与许可材料，排除本机 local.json、runs、test-inputs 和验收记录。接收机运行目录与匹配源码必须显式提供，避免意外捆绑不一致版本。

许可证：GPL-3.0-or-later。组件说明见 THIRD-PARTY.md。
