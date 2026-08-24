ntsc-rs frei0r plugin (ntscrs), vendored for LocalCable CRT/VHS playback.

Plugin: https://github.com/rectalogic/ntsc  tag 0.3.0
Engine: https://github.com/ntsc-rs/ntsc-rs   rev bddab2d
Site:   https://ntsc.rs/

Binaries come from the 0.3.0 GitHub release of rectalogic/ntsc:
  ntscrs-Linux.tar.gz / ntscrs-macOS.tar.gz / ntscrs-Windows.tar.gz

  linux-x86_64/ntscrs.so     — Linux x86_64
  macos-arm64/ntscrs.dylib   — macOS Apple Silicon
  windows-x86_64/ntscrs.dll  — Windows x86_64

The plugin is GPL-3.0-or-later (LICENSE-GPL-3.0.txt). The ntsc-rs crate it
links is MIT OR Apache-2.0 (LICENSE-ntsc-rs-*.txt). Wrapper sources used to
build the plugin are in source/. Full corresponding source for the crate is
https://github.com/ntsc-rs/ntsc-rs/tree/bddab2d

LocalCable looks here first, then FREI0R_PATH, then system frei0r dirs.
mpv/ffmpeg load it via FREI0R_PATH + frei0r=ntscrs:<preset.json>.
