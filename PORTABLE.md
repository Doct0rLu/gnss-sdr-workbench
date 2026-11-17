# Windows 便携版 / Windows portable release

适用 Windows 10/11 x64。无需安装 Python、Node、MSYS2 或 GNU Radio。

1. 完整解压 ZIP 到可写目录，保留所有子目录。
2. 双击 `Start-Workbench.cmd`，浏览器打开本地工作台。
3. 配置实验 → 浏览选择自己的信号文件并选择采样格式 → 检查输入 → 保存配置 → 启动。

接收机路径由程序自动定位；不需要填写开发者电脑路径。配置和实验输出保存在解压目录下的 local.json、runs。保持启动窗口开启；停止接收机后可用 Ctrl+C 关闭本地服务。移动程序时先关闭服务，再移动整个目录。

没有附带用户信号文件。支持实数和 IQ 的 int8、int16、float32；int16/float32 使用小端序。实数输入在配置实验中选择格式，并设置实际采样率与中频。GPS L1 C/A 模板对应 signed int8 I/Q、18 MS/s、+20 kHz IF；其他数据需要匹配格式、采样率、中频和信号配置。当前验证主要为 GPS L1 C/A 文件回放，硬件并非免配置即用。

源码仓库的 Code → Download ZIP 是开发者源码；普通用户应在 Releases 下载带 `win-x64.zip` 的附件。

Extract the entire archive into a writable folder and run **Start-Workbench.cmd**. The included Python runtime and native receiver require no separate installation. Select your signal recording and sample format in Experiment Setup. The default GPS L1 C/A profile expects signed int8 I/Q at 18 MS/s and +20 kHz IF. This release does not redistribute IQ recordings.

This is an unofficial GNSS-SDR Windows build. Receiver source and dependency notices are included under receiver/. See LICENSE and THIRD-PARTY.md. No code-signing certificate is included.
