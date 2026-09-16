Portable ffmpeg/ffprobe for LocalCable transcode-in-place (and DASH as a fallback).

Layout after `localcable transcode --fetch-ffmpeg` or a manual drop-in:

  linux-x86_64/ffmpeg
  linux-arm64/ffmpeg
  macos-arm64/ffmpeg
  macos-x86_64/ffmpeg
  windows-x86_64/ffmpeg.exe

Lookup order: LOCALCABLE_FFMPEG, this vendor dir, then PATH.

Linux/Windows builds come from BtbN FFmpeg-Builds (GPL, includes libx264/libx265
and the NVIDIA/QSV/AMF encoder wrappers). macOS uses evermeet.cx snapshots.

Do not commit the binaries; they are large and platform-specific.
GPU encode is selected at runtime if a smoke test succeeds (nvenc, qsv, amf,
vaapi, videotoolbox), otherwise libx264.
