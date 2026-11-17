# v0.3.2 — File picker repair and real sample inputs

- Fixed the portable file chooser: the picker and ctypes.wintypes are now compiled into the executable. Previously the dynamically loaded picker failed before opening the Windows dialog.
- Build checks now require the picker dependencies in the frozen archive. Picker failures write details to logs/file-picker.log.
- Added real int8, int16 LE and float32 LE inputs, plus IQ int16 and float32 alongside IQ int8.
- The sample-format selector updates receiver adapters and filter input types. Real inputs use native frequency translation and filtering.
- File length validation, receiver sample counts, live/replayed input waveform and FFT, and original-byte slice downloads now follow the selected sample layout.
- Unified the 100 ms file tail in logical sample units so multi-byte recordings finish before EOF.
- Real inputs show a single waveform and mirrored two-sided spectrum. IQ inputs retain I/Q waveforms and scatter views.

Extract the complete win-x64 ZIP and run Start-Workbench.cmd. Choose your signal recording, sample format, sampling rate and IF in Experiment Setup. Runtime, receiver, corresponding receiver source and dependency notices are included.

Validation on Windows: 20 Python tests and JavaScript playback tests pass. All six sample layouts completed native GPS L1 C/A acquisition and exited normally; a 10-second real int8 recording produced 7 tracking channels and 88 UDP monitoring packets. The frozen file chooser opened and returned Chinese-path signal and configuration files; cancellation returned an empty path. The real-signal panel and timeline seeking were checked in the portable build. Relocation is checked with only Windows system directories on PATH; no clean Windows VM was used.
