# v0.3.1 — Windows portable distribution

- Bundles the Python runtime, NumPy/h5py, web resources and the unofficial native GNSS-SDR receiver with 103 DLLs.
- Locates the bundled receiver relative to the application directory; no developer drive paths or MSYS2 installation are required for running the package.
- Includes receiver corresponding source, component notices, package versions and SHA256 manifest.
- Personal settings, IQ, historical results and development caches are excluded.
- Retains the v0.3 live/replay clock, linked channel/acquisition/loop views and event clips.

Validated on the development Windows machine: frozen executable, real GPS L1 C/A input, successful receiver exit, UDP monitoring and position output. Relocation to a new Chinese-path directory with only Windows system directories on PATH also passed: 30-second GPS L1 C/A replay, 863 UDP packets, 3 position outputs, capture-grid and input-IQ reads. No Python or MSYS2 directory was present on the child process PATH. This is not a clean Windows virtual-machine certification. The package is unsigned.

Download the win-x64 ZIP from Releases, extract it completely and run Start-Workbench.cmd. Supply your own IQ file. See PORTABLE.md for the default input profile.
