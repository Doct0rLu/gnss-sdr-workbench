# v0.4.0 — All-signal workbench and multi-RF replay

- Added all 17 signal identities present in the bundled GNSS-SDR receiver: GPS L1 C/A, L1C, L2C and L5; Galileo E1, E5a, E5b and E6; GLONASS L1/L2; BeiDou B1I, B1C, B2a and B3I; QZSS L1/L5; SBAS L1.
- Added signal selection, native configuration generation, single-signal and mixed/multiband templates, and independent RF file/format settings.
- Preserved the receiver's fixed absolute channel order. Channel monitoring, tracking dump selection, satellite labels, input previews and original-byte slices now follow each channel's signal and RF.
- Kept native PVT and telemetry roles, including SBAS augmentation and Galileo E6 correction data.
- Preserved portable file selection and real/IQ int8/int16/float32 inputs.

Validation: 24 Python tests and JavaScript replay tests; 17 native signal-chain startup/run/exit checks with seeded noise at template rates; same-RF GPS/Galileo and dual-RF GPS L1/L5 startup checks. GPS recording and B3I simulation PVT regressions are run separately. Noise checks do not establish satellite decoding or position performance on the other frequencies. See SIGNALS.md for the capability and verification matrix.

Extract the complete win-x64 ZIP and run Start-Workbench.cmd. Source, matching receiver source, runtime and dependency notices are included.
