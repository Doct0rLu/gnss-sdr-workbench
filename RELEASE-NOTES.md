# v0.6.5 · Windows x64 独立便携版

下载 `GNSS-SDR-Workbench-v0.6.5-win-x64.zip`，完整解压到可写目录，双击 `Start-Workbench.cmd`。接收机和运行库随包提供。

- 实时监测按游标增量读取跟踪历史，断线回到页面时可从游标继续或完整重同步。实机对照中，状态响应平均从 209 KB 降到 49 KB。
- 一份宽带 IQ 可以自动按频带分支，支持为各频带映射同步录制。实验配置支持原始 GNSS-SDR 配置以及工作台的信号、采样格式和监测设置。
- 捕获快照支持多通道选择和三维码相位、多普勒、评价量显示。时间轴联动跟踪环路、天空图和事件切片。
- 实验结束后可用已保存的伪距观测量和星历直接重算单点定位。高级选项提供 B1C 短录制首帧恢复。
- v0.6.5 的接收机二进制和 DLL 与 v0.6.4 一致。相同输入和配置的指定 PRN 对照中，新旧两版捕获、有效跟踪和星历名单一致，首解相差 20 ms。处理速度随信号、盲搜配置及主机负载变化。

[操作说明](https://github.com/Doct0rLu/gnss-sdr-workbench/blob/v0.6.5/PORTABLE.md) · [回归记录](https://github.com/Doct0rLu/gnss-sdr-workbench/blob/v0.6.5/NATIVE-REGRESSION.md)

源代码、对应的 GNSS-SDR 上游归档及 SHA-256 校验文件随 Release 提供。
