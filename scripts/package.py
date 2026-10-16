#!/usr/bin/env python3
"""Package the host-native release build, editable assets and notices."""
import json
import argparse
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=["x86_64-pc-windows-gnu"])
    args = parser.parse_args()
    cargo = shutil.which("cargo") or str(Path.home() / ".cargo/bin/cargo")
    command=[cargo, "build", "--release", "--locked"]
    if args.target:
        command += ["--target", args.target]
    subprocess.run(command, cwd=ROOT, check=True)
    system = "Windows" if args.target else platform.system()
    build_dir=ROOT / "target"
    if args.target:
        build_dir /= args.target
    build_dir /= "release"
    name = "PixelEngine-macOS" if system == "Darwin" else "PixelEngine-Windows" if system == "Windows" else "PixelEngine-Linux-development"
    destination = ROOT / "dist" / name
    if destination.exists():
        shutil.rmtree(destination)
    if system == "Darwin":
        app = destination / "Pixel Engine Lab.app"
        binary_dir = app / "Contents/MacOS"
        resource_dir = app / "Contents/Resources"
        binary_dir.mkdir(parents=True)
        resource_dir.mkdir(parents=True)
        shutil.copy2(build_dir / "engine-lab", binary_dir)
        launcher = binary_dir / "PixelEngine"
        launcher.write_text('#!/bin/sh\nBASE="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\ncd "$BASE/../Resources"\nif [ "$#" -eq 0 ]; then exec "$BASE/engine-lab" run; else exec "$BASE/engine-lab" "$@"; fi\n')
        launcher.chmod(0o755)
        with (app / "Contents/Info.plist").open("wb") as file:
            plistlib.dump({"CFBundleName": "Pixel Engine Lab", "CFBundleDisplayName": "Pixel Engine Lab", "CFBundleExecutable": "PixelEngine", "CFBundleIdentifier": "local.pixelengine.lab", "CFBundleVersion": "1", "CFBundleShortVersionString": "0.1.0", "CFBundlePackageType": "APPL", "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "14.0"}, file)
    else:
        resource_dir = destination
        destination.mkdir(parents=True)
        executable = "engine-lab.exe" if system == "Windows" else "engine-lab"
        shutil.copy2(build_dir / executable, destination)
        if system == "Windows":
            (destination / "Launch Lab.cmd").write_text('@echo off\r\ncd /d "%~dp0"\r\nengine-lab.exe run\r\n')
    for source, target in [("assets", "assets"), ("crates/engine/src/render/shaders", "shaders"), ("docs", "docs")]:
        shutil.copytree(ROOT / source, resource_dir / target)
    for name_in in ["README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"]:
        shutil.copy2(ROOT / name_in, resource_dir)
    licenses = resource_dir / "dependency-licenses"
    licenses.mkdir()
    metadata = json.loads(subprocess.check_output([cargo, "metadata", "--locked", "--format-version", "1"], cwd=ROOT))
    inventory = []
    for package in metadata["packages"]:
        if package.get("source") is None:
            continue
        folder = Path(package["manifest_path"]).parent
        package_id = f'{package["name"]}-{package["version"]}'
        target = licenses / package_id
        target.mkdir()
        for pattern in ["LICENSE*", "LICENCE*", "COPYING*", "NOTICE*", "OFL*"]:
            for license_file in folder.rglob(pattern):
                if license_file.is_file():
                    license_target=target / license_file.relative_to(folder)
                    license_target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(license_file, license_target)
        inventory.append({"name": package["name"], "version": package["version"], "license": package.get("license"), "repository": package.get("repository")})
    (licenses / "inventory.json").write_text(json.dumps(inventory, indent=2) + "\n")
    if system == "Darwin":
        subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)], check=True)
        archive = ROOT / "dist" / "PixelEngine-macOS.zip"
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(app), str(archive)], check=True)
    else:
        archive = destination.with_suffix(".zip")
        # Cargo sources can retain reproducible pre-1980 timestamps. ZIP's
        # representable date range starts in 1980; clamp dates, not source files.
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, strict_timestamps=False) as bundle:
            for file in sorted(destination.rglob("*")):
                if file.is_file():
                    bundle.write(file, file.relative_to(destination))
    print(json.dumps({"bundle": str(destination), "archive": str(archive), "distribution": "development; not notarized or production signed"}))


if __name__ == "__main__":
    main()
