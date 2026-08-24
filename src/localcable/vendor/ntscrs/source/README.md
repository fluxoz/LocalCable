# NTSC frei0r plugin

[frei0r](https://dyne.org/software/frei0r/) filter plugin based on [ntsc-rs](https://ntsc.rs).
[ffmpeg](https://ffmpeg.org/ffmpeg-filters.html#frei0r-1) and [MLT](https://www.mltframework.org/features/)
both support frei0r plugins.

## Build

```sh-session
$ cargo build --release
$ cargo xtask package
# plugin now in target/release
```

## Usage

Copy the plugin to your frei0r plugins directory, or on macOS/Linux set `FREI0R_PATH` environment variable.
Create a preset using the [ntsc-rs application](https://ntsc.rs/docs/standalone-application/)
or download presets from the [ntsc-rs discussions](https://github.com/ntsc-rs/ntsc-rs/discussions).

frei0r parameter 0 is the preset pathname, parameter 1 is a time multiplier.
This defaults to 0 (no multiplier) which works for linear encoding.
For nonlinear usage (e.g. in a video editor), set the multiplier to the framerate for MLT based editors.

Scale `input.mp4` to 480p and apply the ntsc filter using a preset:
```sh-session
FREI0R_PATH=target/release ffmpeg -i input.mp4 \
  -vf scale=size=640x480:force_original_aspect_ratio=decrease:reset_sar=1:flags=lanczos,frei0r=ntscrs:data/Low-Power-NTSC.json \
  -y output.mp4
```

Apply ntsc filter to a testcard video:
```sh-session
FREI0R_PATH=target/release ffmpeg -f lavfi \
  -i testsrc2=duration=4:size=640x480:rate=30 \
  -vf frei0r=ntscrs:data/Low-Power-NTSC.json \
  -pix_fmt yuv422p \
  -y output.mp4
```

Result:

https://github.com/user-attachments/assets/1cd369f0-4218-4a78-9295-030933893e7f

## MLT

Use ntsc filter with [MLT](https://www.mltframework.org).
We set parameter `1=30`, this is the time multiplier to convert frei0r time to frame number.
MLT uses `frame / fps` as the time, so this parameter should be set to the fps for MLT.
This is only necessary if the video is being interactively seeked,
for linear encoding it can be left disabled (value 0).

```sh-session
FREI0R_PATH=target/release melt https://download.samplelib.com/mp4/sample-5s.mp4 \
  -filter frei0r.ntscrs 0=data/Low-Power-NTSC.json 1=30 \
  -consumer avformat:output.mp4 scale=0.4444
```

## kdenlive

Install the plugin in the kdenlive `lib/frei0r-1` plugin directory.
Install this [frei0r_ntscrs.xml](data/frei0r_ntscrs.xml) effect XML in the `kdenlive/effects` XML directory.

Make sure the preview window is <480p or it may not render.
