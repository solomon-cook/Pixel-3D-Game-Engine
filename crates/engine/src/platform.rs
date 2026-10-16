//! Platform-independent policy. Window lifecycle belongs to the host application.
pub fn backends() -> wgpu::Backends {
    if cfg!(target_os = "macos") {
        wgpu::Backends::METAL
    } else if cfg!(target_os = "windows") {
        wgpu::Backends::DX12
    } else {
        wgpu::Backends::VULKAN
    }
}

/// Integer viewport in physical framebuffer pixels. Undersized windows crop a
/// 1:1 image rather than silently changing the artist-selected pixel resolution.
pub fn presentation_rect(output: [u32; 2], scene: [u32; 2]) -> [u32; 4] {
    let scale = (output[0] / scene[0]).min(output[1] / scene[1]);
    if scale == 0 {
        return [0, 0, output[0].min(scene[0]), output[1].min(scene[1])];
    }
    let w = scene[0] * scale;
    let h = scene[1] * scale;
    [(output[0] - w) / 2, (output[1] - h) / 2, w, h]
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn integer_letterboxing() {
        assert_eq!(
            presentation_rect([1920, 1080], [480, 270]),
            [0, 0, 1920, 1080]
        );
        assert_eq!(
            presentation_rect([2000, 1200], [480, 270]),
            [40, 60, 1920, 1080]
        );
        assert_eq!(presentation_rect([960, 540], [480, 270]), [0, 0, 960, 540]);
    }
}
