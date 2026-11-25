# GNSS-SDR Workbench v0.6.1

Windows x64 的 GNSS-SDR 配置、监测与回放界面。本版直接启动随包的 Windows 接收机进程。接收机基于提交 `3132713`，构建时应用 Windows 平台适配及有限文件 EOF 修复，保留上游捕获统计量、跟踪环路、电文解码和定位计算。[上游源码](https://github.com/gnss-sdr/gnss-sdr/tree/3132713b88a1b5b2ee8291bff8076574749349de) · [运行对照](NATIVE-REGRESSION.md)

同一份 M1 L5 录制在常规调度和上游确定性调度下的逐星捕获、跟踪及星历复验见[L5 重复实验](L5-REPEAT.md)。

## 下载使用

完整解压 win-x64 便携包到可写目录，双击 `Start-Workbench.cmd`。接收机、GNU Radio DLL 和界面所需运行库都在包内。[下载 v0.6.1](https://github.com/Doct0rLu/gnss-sdr-workbench/releases/tag/v0.6.1) · [操作说明](PORTABLE.md)

“使用原始 GNSS-SDR 配置”支持本机 .conf 和随包的上游示例。相对或已迁移的录制路径会解析到实际文件，实验目录同时保留原文和传给内核的配置。“工作台实验”提供多频、实数和 IQ 预设，并配置监测端口、转储与时长。

## 从源码启动

使用 Python 3.11 或更高版本执行 `python -m pip install -r requirements.txt`。把 v0.6.1 便携包的 `receiver` 目录放在 `server.py` 旁，双击 `start.cmd`。也可执行 `python server.py --port 8767 --open`。

## 输入格式

配置实验中选择“采样格式”，会同步更新适配器与滤波器输入类型；采样率、中频沿用录制参数。原始信号预览、实时跟随、时间轴回放与切片下载均使用同一格式。实数显示单路波形和双边频谱；IQ 显示 I/Q 波形、散点和频谱。浮点输入以录制幅值显示，整数输入显示原始计数值。

## 操作顺序

1. 配置实验：展开“信号与频点配置”，勾选信号并生成单频或组合配置；可选择各频点同步录制，或让多个频点复用一份宽带 IQ。在共享模式下填写采集中心、采样率和格式，生成后核对各支路 IF。浏览选择信号或 .conf 文件，也可输入路径。设置时长、捕获快照通道、采样率、中频、通道数、环路带宽与搜索参数。高级配置文本可展开编辑。
   M1 的 B1C、GPS L2C、GPS L5 单频录制以及 L1 C/A＋B1C＋B1I 跨频录制可直接选择对应的实验参数预设。输入本次已知 PRN 可定向捕获，留空则盲搜。
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
| 调试接口 | Windows 原生接收机进程、接收机和配置的 SHA-256、监测端口、数据 API |

暂停查看只冻结显示；停止与重启控制接收机进程。时间游标与切片不改变接收机闭环计算位置。

PLL 鉴别器依据当前源代码 atan/TWO_PI 显示为 cycle；DLL 为 chip；NCO 分别为 Hz 与 chip/s。输入 IQ 是文件中的原始复样本，频谱单位为 dB re 1 count。卫星天空图是方位/仰角图，I/Q 星座为另一类图。界面不把未知值填为观测结果。

## 数据与接口

每次实验保存在 `runs/<时间-随机编号>/`。包括有效配置 receiver.conf、manifest.json、原始 receiver.log、按信号时钟记录的 logs.jsonl/events.jsonl、接收机原生内部日志、抽样 telemetry.jsonl、acquisitions.jsonl、positions.jsonl、snapshot.json，以及接收机生成的 tracking_ch_*.dat、acquisition_*.mat、NMEA、RINEX、KML 等。

manifest 记录实际配置与接收机的 SHA-256、输入大小和修改时间、进程命令、版本及退出状态。整份 IQ 没有自动做哈希。内存趋势最多每通道 2,400 点、日志 3,000 行、事件 300 条；原始文件仍保存在磁盘。UDP 不保证交付，抽样 telemetry.jsonl 不是全部数据包的归档。

Tracking dump 时间读取使用二分定位，每次最多返回 1,600 点，原始文件可单独下载。结构化日志按 256 行建立增量时间索引，查询前先按时间块筛选，再按通道取最近 600 行；事件接口最多返回最近 2,000 条。捕获快照索引缓存文件时间戳、大小与信号时间，回放时选择相应帧。老版本实验没有结构化日志时使用原有快照中的保留日志与事件，跟踪 dump 与捕获文件仍可按时间读取。实时写盘文件可能尚有未完整记录的尾部，读取时忽略该尾部。捕获网格保留峰附近 161 点剖面，并对全码延迟轴按列内最大值抽取为热图，避免均值采样抹去尖峰。

只监听 127.0.0.1，检查 Host 与 Origin。只允许下载实验目录内的普通文件。主要读取 API：

```text
GET /api/state?run=<id>
GET /api/inspect?run=<id>&kind=tracking&channel=0&start=10&end=12
GET /api/inspect?run=<id>&kind=acquisition&file=<name.mat>
GET /api/inspect?run=<id>&kind=iq&t=10
GET /api/raw-input?run=<id>&t=10&count=8192
GET /api/inspect?run=<id>&kind=sky
GET /api/inspect?run=<id>&kind=files
GET /api/file?run=<id>&name=<filename>
POST /api/restart
```

## 当前适配与后续方向

v0.4 系列 Windows 接收机曾验证 17 类信号处理链运行、同频混合与双 RF 链路；实际定位回归包括 GPS L1 C/A 和北斗 B3I。GPS L1 C/A 录制使用 18 MS/s signed int8 I/Q、+20 kHz IF、抽取至 3 MS/s。文件输入支持实数 int8/byte、int16/short、float32/float，以及 IQ int8/ibyte、int16/ishort、float32/gr_complex；多字节格式为小端序。工作台按格式计算文件长度、接收机样本数与切片字节偏移；随包接收机支持将实数 int16 读到最后一个完整样本，其他格式的工作台时长计算保留原有的 100 ms 尾部余量。实数输入使用 Pass_Through 适配器与 Freq_Xlating_Fir_Filter 完成滤波、下变频和抽取，填写实际录制中频；IQ 整数输入使用对应的 Ibyte/Ishort_To_Complex。捕获网格使用内核已有 dump_channel，每次实验选择一个通道；成功捕获消息覆盖各通道。跟踪二进制解析适配当前构建的 112 字节记录。

天空图按 GGA 历元合并各星座的 GSV，拖动时间轴时使用游标处最近定位解的 UTC。定位面板收录原生首次定位和周期位置，事件的时间精度取决于接收机对应的输出。输入工作区可查看原始采样。

接收机内核与工作台分开维护，后续内核接口扩展单独提交上游。项目采用 GPL-3.0-or-later；便携版附接收机对应源码和第三方许可信息。local.json、runs、测试 IQ 与私人验收记录不进入公开源码。

## 验证

### 支持与回归检查

工作台信号目录与随附 GNSS-SDR 的 17 类处理链一致，支持同频多系统及多 RF 文件组合。配置、捕获监测、逐通道跟踪文件与前端卫星标识按原生绝对通道顺序处理。完整清单与验证层级见 [SIGNALS.md](SIGNALS.md)。B3I 配置示例为 `templates/bds-b3i-m1-24m.conf`，需用户自行提供匹配 IQ。正常文件结束显示“结束”，文件尾保护提示显示“文件边界”，不当作失锁事件。自动化检查包括输入格式、通道映射、天空图历元、首解、原样配置与回放状态。

```powershell
python -m unittest discover -s tests -v
node --check web/app.js
node --check web/debug.js
node --check web/replay.js
node tests/replay-model.test.cjs
# 启动 server.py 后，真实 IQ + 重启 + 数据接口检查
python tests/integration_v02.py
```

M1 单频录制的指定 PRN 与盲搜结果见 [M1 回归记录](M1-REGRESSION.md)。公开发布检查见 RELEASE-NOTES.md。开发工作区的详细实验记录保存在被忽略的 verification/ 中，不含于公开源码。本轮没有做干净 Windows、硬件或长期运行验收。受控中断测试使用 test-inputs 中的派生文件和独立 runs 输出，配方单独记录，源 IQ 不修改。这些文件不进入源码包。


## 构建便携包

在装有 MSYS2 UCRT64 开发依赖的构建机上使用固定提交的上游源码归档。所需包包括 GCC、CMake、Ninja、GNU Radio、VOLK、Boost、Armadillo、OpenBLAS、Abseil、gflags、glog、matio、pugixml、protobuf、OpenSSL、GnuTLS 和 python-mako。发布包的依赖版本见 `receiver/THIRD-PARTY.json`。以下命令在 PowerShell 中运行。

```powershell
python -m venv .build-venv
.build-venv/Scripts/python.exe -m pip install -r requirements-build.txt
.build-venv/Scripts/python.exe windows_native/build.py --archive D:/source/gnss-sdr-upstream.tar.gz --work D:/gnss-build
.build-venv/Scripts/python.exe build_release.py --receiver D:/gnss-build/receiver
```

构建脚本核对上游归档、Windows 平台和文件 EOF 补丁、PE 机器码和递归 DLL 导入。ZIP、源码与校验和输出到 `release`。便携目录中的 `receiver/windows_native` 包含对应的构建配方。[组件许可](THIRD-PARTY.md)
