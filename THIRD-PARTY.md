# Components

The workbench is GPL-3.0-or-later. The separately executed receiver is an unofficial Windows build based on GNSS-SDR commit 3132713b88a1b5b2ee8291bff8076574749349de, with local Windows and receiver changes. It is not an official upstream Windows release.

The portable archive includes receiver/receiver-corresponding-source.zip, matching the archived portable receiver, its build metadata, THIRD-PARTY.json and the original per-package license files. The source ZIP retains upstream copyright and build instructions.

Bundled Python 3.12.7 uses the Python Software Foundation license. NumPy 1.26.4 and h5py 3.11.0 use BSD licenses; their wheel notices and the HDF5 notice are collected into licenses/. NumPy's license also describes bundled numerical libraries. PyInstaller 6.22.3 uses its bootloader exception; its notices are retained.

Receiver DLLs retain their original licenses. Exact package versions, upstream links and MSYS2 source recipes appear in receiver/THIRD-PARTY.json and receiver/WINDOWS-BUILD.json. MSYS2's package and matching source archives are available at https://repo.msys2.org/ and recipes at https://github.com/msys2/MINGW-packages . Preserve all notices and corresponding source access when redistributing.
