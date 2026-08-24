// Copyright (C) 2026 Andrew Wason
// SPDX-License-Identifier: GPL-3.0-or-later
use std::ffi::CString;

use anyhow::Context;
use frei0r_rs2::{slice_to_bytes, slice_to_bytes_mut};
use ntsc_rs::{
    NtscEffect, NtscEffectFullSettings,
    settings::SettingsList,
    yiq_fielding::{BlitInfo, DeinterlaceMode, Rgbx, YiqOwned, YiqView, pixel_bytes_for},
};

pub struct NtscPlugin {
    preset_path: CString,
    time_multiplier: f64,
    width: usize,
    height: usize,
    frame_num: usize,
    effect: Option<NtscEffect>,
    initialized: bool,
}

impl frei0r_rs2::Plugin for NtscPlugin {
    type Kind = frei0r_rs2::KindFilter;

    const PARAMS: &'static [frei0r_rs2::ParamInfo<Self>] = &[
        frei0r_rs2::ParamInfo::new_string(
            c"preset",
            c"Path to NTSC preset JSON file",
            |plugin| plugin.preset_path.as_c_str(),
            |plugin, value| plugin.preset_path = value.to_owned(),
        ),
        frei0r_rs2::ParamInfo::new_double(
            c"time_multiplier",
            c"Time multiplier to convert time to frame number. For linear encoding, set to 0 to ignore time and count frames.",
            |plugin| plugin.time_multiplier,
            |plugin, value| plugin.time_multiplier = value,
        ),
    ];

    fn info() -> frei0r_rs2::PluginInfo {
        frei0r_rs2::PluginInfo {
            name: c"ntsc",
            author: c"Andrew Wason",
            color_model: frei0r_rs2::ColorModel::RGBA8888,
            major_version: env!("CARGO_PKG_VERSION_MAJOR").parse().unwrap(),
            minor_version: env!("CARGO_PKG_VERSION_MINOR").parse().unwrap(),
            explanation: Some(c"NTSC filter"),
        }
    }

    fn new(width: usize, height: usize) -> Self {
        Self {
            preset_path: c"".into(),
            time_multiplier: 0.0,
            width,
            height,
            frame_num: 0,
            effect: None,
            initialized: false,
        }
    }
}

impl frei0r_rs2::FilterPlugin for NtscPlugin {
    fn update_filter(&mut self, time: f64, inframe: &[u32], outframe: &mut [u32]) {
        if !self.initialized
            && let Err(err) = self.initialize()
        {
            eprintln!("Failed to initialize plugin: {err:?}");
            return;
        }
        let Some(ref effect) = self.effect else {
            return;
        };
        let inframe = slice_to_bytes(inframe);
        let outframe = slice_to_bytes_mut(outframe);
        let frame_num = if self.time_multiplier > 0.0 {
            (time * self.time_multiplier).round() as usize
        } else {
            self.frame_num += 1;
            self.frame_num - 1
        };
        self.apply_effect(effect, frame_num, inframe, outframe);
    }
}

impl NtscPlugin {
    fn initialize(&mut self) -> anyhow::Result<()> {
        self.initialized = true;
        let preset_path = self
            .preset_path
            .to_str()
            .with_context(|| format!("Invalid preset path: {:?}", self.preset_path))?;
        let file_contents = std::fs::read_to_string(preset_path)?;
        let settings = SettingsList::<NtscEffectFullSettings>::new().from_json(&file_contents)?;
        self.effect = Some(settings.into());
        Ok(())
    }

    fn apply_effect(
        &self,
        effect: &NtscEffect,
        time: usize,
        input_frame: &[u8],
        output_frame: &mut [u8],
    ) {
        let field = effect.use_field.to_yiq_field(time);
        let row_bytes = self.width * pixel_bytes_for::<Rgbx, u8>();
        let mut yiq = YiqOwned::from_strided_buffer::<Rgbx, _>(
            input_frame,
            row_bytes,
            self.width,
            self.height,
            field,
        );
        let mut view = YiqView::from(&mut yiq);
        effect.apply_effect_to_yiq(&mut view, time, [1.0, 1.0]);
        view.write_to_strided_buffer::<Rgbx, _, _>(
            output_frame,
            BlitInfo::from_full_frame(self.width, self.height, row_bytes),
            DeinterlaceMode::Bob,
            (),
        );
    }
}

frei0r_rs2::plugin!(NtscPlugin);
