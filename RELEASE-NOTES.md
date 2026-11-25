# v0.5.0 · 随包运行原始 GNSS-SDR

Windows x64 用户下载 `GNSS-SDR-Workbench-v0.5.0-win-x64.zip`，完整解压到可写目录并双击 `Start-Workbench.cmd`。首次打开“实验配置”，即可选择上游示例或自己的 .conf。便携包内含 Linux、QEMU、GNSS-SDR 和 Python。

- 接收机来自上游提交 `3132713b88a1b5b2ee8291bff8076574749349de`。以完整 Git 树校验基线，两次独立 Linux 构建得到相同的接收机 SHA-256，值为 `2e9769b9857895bc277d82e8d4b8910ff12416107867c021a4366a1f3f89f26e`。[上游源码](https://github.com/gnss-sdr/gnss-sdr/tree/3132713b88a1b5b2ee8291bff8076574749349de) · [构建记录](https://github.com/Doct0rLu/gnss-sdr-workbench/actions/runs/45528437081)
- “原样运行 GNSS-SDR 配置”保留 .conf 的字节和接收参数，支持原始路径映射。实验模式另行配置多频分支、监测端口、转储和回放时长。命令行 `--receiver-config` 可独立执行同一份配置。
- 修正天空图被最后一组 GSV 覆盖的问题，并支持按选定解的 UTC 回看。定位面板收录原生日志中的首解。调试页显示 Linux 接收机及 QEMU 的进程标识和接收机摘要。
- 30 秒 GPS L1 C/A 录制在 Windows 软件模拟环境中得到了导航电文和定位，界面后端收到 894 个跟踪监测数据包。另用同一录制的短片段验证了捕获 MAT 写入、峰形读取和逐通道转储。该次运行耗时约 12 分 28 秒。各频点历史实验的接收机版本和条件见 [M1 记录](M1-REGRESSION.md)。

工作台源码归档、对应的未修改接收机源码和 SHA-256 校验文件随 Release 分别提供。
