# Third-party components

Original engine code and scene assets are proprietary. Dependencies keep their
own licenses; the proprietary notice does not replace them.

Principal dependencies: wgpu (MIT OR Apache-2.0), winit (Apache-2.0), egui and
its wgpu/winit integrations (MIT OR Apache-2.0), glam (MIT OR Apache-2.0),
serde/serde_json (MIT OR Apache-2.0), schemars (MIT), image (MIT OR Apache-2.0),
gltf (MIT OR Apache-2.0), clap (MIT OR Apache-2.0), anyhow (MIT OR Apache-2.0),
bytemuck (Zlib OR Apache-2.0 OR MIT), pollster (MIT OR Apache-2.0).

`scripts/package.py` collects dependency manifests and available license/notice
files from the locked Cargo sources into each bundle. Its inventory includes
transitive and target-specific dependencies. No third-party game art is used.
The egui default fonts are distributed with egui; their notices are included in
the dependency license directory, including nested font license files.

Development bundles are not production signing or distribution approval.
