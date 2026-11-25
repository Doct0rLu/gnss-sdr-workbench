# Components

GNSS-SDR Workbench and GNSS-SDR are GPL-3.0-or-later. The portable workbench launches the bundled native Windows x64 file receiver. The corresponding upstream source archive and Windows build scripts, including the complete platform patch, are included in `receiver`. The fixed baseline is `3132713b88a1b5b2ee8291bff8076574749349de`. [GNSS-SDR source](https://github.com/gnss-sdr/gnss-sdr/tree/3132713b88a1b5b2ee8291bff8076574749349de)

GNU Radio, VOLK, FFTW, OpenBLAS and the other native dependencies retain their original licenses. The exact MSYS2 package names and versions are listed in `receiver/THIRD-PARTY.json`. The binary hashes are in `receiver/WINDOWS-BUILD.json`. The VOLK_GNSSSDR source is part of the upstream archive. Package notices are collected under `receiver/licenses`. [MSYS2 UCRT64 packages](https://packages.msys2.org/) · [MSYS2 source recipes](https://github.com/msys2/MINGW-packages)

The workbench includes CPython, PyInstaller, NumPy, h5py and their bundled libraries. Their notices are included under `licenses`.
