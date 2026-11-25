# Windows x64 便携工作台

1. 完整解压 ZIP 到可写目录，双击 `Start-Workbench.cmd`。
2. 打开“实验配置”。选择“原样运行 GNSS-SDR 配置”，在上游示例中选取配置，或浏览本机 .conf 文件。相对录制路径以 .conf 所在目录解析。跨电脑移动数据后，可在“录制文件映射”中按文件顺序选择录制。
3. 保存并启动。在原始模式下，接收机按 .conf 中的通道、环路、时长、监测与输出设置运行。每次运行保存原始配置和二进制摘要。
4. 需要按通道查看捕获和跟踪时，可选择“工作台实验”，填写输入格式、采样率、频点与时长。工作台为这次实验写入监测端口和转储路径，实际配置保存在实验目录的 `receiver.conf`。
5. 修改参数后点“保存并重启”。原始文件、定位输出和监测结果分别通过录制文件映射与实验目录访问。

## 用命令行复核

在便携目录运行以下命令。省略 `--output` 时程序自动在 `runs` 下创建新目录。每个 `--input` 按配置中的文件顺序映射一个本机文件。输出目录需为新目录。

```powershell
.\GNSS-SDR-Workbench.exe --receiver-config .\test.conf --input D:\recordings\test.iq --output .\comparison-01
```

Linux 接收机、构建信息、上游配置与源码归档在 `receiver/linux`。Windows 使用随附的 QEMU 运行 Linux。检测到已启用的 Windows Hypervisor Platform 时优先尝试 WHPX，其余环境使用软件模拟。处理速率取决于计算机和接收参数。文件回放使用本机录制，硬件输入还涉及客户机设备连接。关闭工作台前先停止接收机。

## 实验数据

工作台实验支持有符号实数和 IQ 的 int8、int16、float32。多字节数据为小端序。设置与实验结果分别保存在本机的 `local.json` 和 `runs`。请保留完整目录结构。
