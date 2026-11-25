# Components

GNSS-SDR Workbench is GPL-3.0-or-later. The v0.5.0 Windows application runs GNSS-SDR as a separate GNU/Linux process in QEMU. Receiver source is the unmodified upstream commit `3132713b88a1b5b2ee8291bff8076574749349de`. The original source archive, upstream configuration files, CMake options, build package versions and binary digest are in `receiver/linux`. [Upstream tree](https://github.com/gnss-sdr/gnss-sdr/tree/3132713b88a1b5b2ee8291bff8076574749349de) · [Linux build](https://github.com/Doct0rLu/gnss-sdr-workbench/actions/runs/45528437081)

The runtime uses Ubuntu 24.04 amd64 packages. The Linux kernel, BusyBox, SSHFS, OpenSSH, GNU Radio and their dependencies retain their original licenses. See `package-notices.tar.gz`, `source-packages.tsv` and `build-packages.tsv` under `receiver/linux`. Package source is published per source package and version on Launchpad. [Ubuntu source archives](https://launchpad.net/ubuntu/+source)

QEMU, BIOS images and the Windows runtime libraries come from MSYS2 UCRT64 packages. See `receiver/qemu/packages.json`, `distribution.json` and the accompanying licenses. [MSYS2 packages](https://packages.msys2.org/) · [Build recipes](https://github.com/msys2/MINGW-packages)

The application includes CPython, PyInstaller, NumPy, h5py, Paramiko and their runtime dependencies. Their notices are collected in `licenses`. Workbench code includes the guest startup script and a UDP relay for original configurations that send monitors to guest loopback. These run outside the receiver.
