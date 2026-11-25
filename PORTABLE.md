# Windows x64 便携工作台

1. 完整解压 ZIP 到可写目录，双击 `Start-Workbench.cmd`。
2. 打开“实验配置”。选择“使用原始 GNSS-SDR 配置”，在上游示例中选取配置，或浏览本机 .conf 文件。相对录制路径以 .conf 所在目录解析。跨电脑移动数据后，可在“录制文件映射”中按文件顺序选择录制。
3. 保存并启动。在原始模式下，接收机按 .conf 中的通道、环路、时长、监测与输出设置运行。每次运行保存原始配置和二进制摘要。
4. 需要按通道查看捕获和跟踪时，可选择“工作台实验”，填写输入格式、采样率、频点与时长。工作台为这次实验写入监测端口和转储路径，实际配置保存在实验目录的 `receiver.conf`。
5. 调试捕获峰形时勾选“保存捕获峰网格”并选择通道。关闭网格可以减少写盘，捕获事件和跟踪环路仍可实时查看和回放。
6. 修改参数后点“保存并重启”。原始文件、定位输出和监测结果分别通过录制文件映射与实验目录访问。

## 用命令行复核

在便携目录运行以下命令。省略 `--output` 时程序自动在 `runs` 下创建新目录。每个 `--input` 按配置中的文件顺序映射一个本机文件。输出目录需为新目录。

```powershell
.\GNSS-SDR-Workbench.exe --receiver-config .\test.conf --input D:\recordings\test.iq --output .\comparison-01
```

也可在单独的空输出目录直接调用随包接收机。以下示例假设配置中的录制文件为绝对路径。

```powershell
& 'D:\GNSS-SDR-Workbench\receiver\bin\gnss-sdr.exe' --config_file=D:/experiment/test.conf --log_dir=.
```

工作台和这个命令使用同一个 Windows 可执行文件。构建记录在 `receiver/WINDOWS-BUILD.json`，上游示例在 `receiver/conf`。文件输入的相对路径由工作台换为本机路径，`original.conf` 与 `receiver.conf` 分别保存原文与有效配置。其余相对路径以实验输出目录为基准。使用辅助星历等外部文件时可在配置中指定绝对路径。

## 实验数据

工作台实验支持有符号实数和 IQ 的 int8、int16、float32。多字节数据为小端序。设置与实验结果分别保存在本机的 `local.json` 和 `runs`。请保留完整目录结构。

## 单文件实数 int16

对于有限的 `File_Signal_Source`、`item_type=short`，`samples=0` 从所设偏移读到最后一个完整的 int16 样本。正数以实际剩余样本数为上限。工作台时长覆盖文件末尾时也采用这个边界。原始配置按用户选择的通道调度运行，L5 重复回放可参考[L5 逐星实验](L5-REPEAT.md)。
