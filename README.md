# MW2 Texture Manager

A GUI tool for extracting, editing, and repacking textures from **Call of Duty: Modern Warfare 2 (2009)**.

Built with Python + CustomTkinter. Bundles into a single portable `.exe` via PyInstaller — no Python install needed to run it.

---

## Features

- Extract IWI textures from IWD archives in bulk
- Convert IWI → DDS → PNG for editing in any image editor
- Repack edited PNGs back to IWI and bundle into a game-ready IWD
- Preserves original DDS format per-texture (DXT1 / DXT3 / DXT5) — no quality loss from unnecessary format changes
- **AI upscaling** of extracted textures with Real-ESRGAN (2x or 4x), with automatic backup of originals and a side-by-side **Compare Original / Current** viewer
- Drag-and-drop IWD files into the source queue; dark mode; remembers your workspace and window size
- Colour-coded activity log with per-file progress counters
- Single-file portable EXE — drop it next to the tools and run

---

## Requirements

### Running the EXE
Download the latest release from the [Releases](https://github.com/CFOD/MW2-Texture-Manager/releases) page.

You also need these two external tools placed in the **same folder** as the EXE:

| Tool | Purpose |
|------|---------|
| `iwi2dds.exe` | Converts IWI → DDS |
| `imgXiwi.exe` | Converts PNG → IWI |

> `texconv.exe`, `libsquish.dll` and the Real-ESRGAN upscaler (with its model) are already bundled inside the EXE.
> The upscaler uses your GPU via Vulkan, so you need a Vulkan-capable graphics card and up-to-date drivers.
> `iwi2dds.exe` and `imgXiwi.exe` are third-party tools that are not redistributed here — obtain them from the MW2 modding community and place them next to the EXE. The tool header shows OK/MISSING for each dependency.

### Building from source
```
pip install pillow pyinstaller customtkinter tkinterdnd2
```
Requires Windows and Python 3.10+. The repo already contains `texconv.exe`, `libsquish.dll` and the `upscaler/` folder. Place `iwi2dds.exe` and `imgXiwi.exe` in the project folder to run from source (`python mw2_upscale_assistant.py`) or to build with them embedded, then run:
```
build_executable.bat
```
Or use the spec file directly:
```
pyinstaller MW2_Tool.spec
```
By default the EXE does **not** embed `iwi2dds.exe` / `imgXiwi.exe`. For a private all-in-one build, set `MW2_BUNDLE_EXTERNAL=1` before building.

---

## Usage

### Full pipeline — extract → edit → repack

**1. Extract textures**
- Click **+ Add IWD Files** and select IWD files from your MW2 `main/` folder
- Select them in the queue, then click **Extract Selected →**
- They appear in the **Workspace Projects** list once extracted

**2. Convert to PNG for editing**
- Select a project in the workspace list
- Click **Convert IWI → DDS**, then **Convert DDS → PNG**
- Click **PNG Folder** to open the output folder — edit your textures here

> Textures must use **power-of-2 dimensions** (e.g. 512×512, 1024×512). Resize before repacking or the game will reject them.

**3. Repack into the game**
- Select your project in the workspace list
- Click **Repack to IWD** → outputs `z_<name>.iwd` in `04_Output/`
- Copy that file to your MW2 `main/` folder
- The `z_` prefix ensures it loads after base game files, overriding them

Click **Output Folder** to jump straight to the finished IWD.

### Optional: upscale before repacking
After **Convert DDS → PNG**, use the **Enhance** section:
- Pick **2x** or **4x**, then click **Upscale PNGs** (runs Real-ESRGAN on every PNG in the selected projects)
- The first time a PNG is upscaled, the original is backed up to `03_PNG/.originals/` — use **Compare Original / Current** to review the result
- Results that don't match the expected size, or that lose transparency, are rejected rather than written
- Upscaled textures must still be power-of-2 sizes, so a 2x/4x of a power-of-2 texture is fine

### IWI-only output
Use **Convert PNG → IWI** instead of Repack to get raw `.iwi` files placed back into `01_IWI/` for manual placement without zipping.

---

## Workspace structure

```
MW2_Project/
├── 01_IWI/      ← Extracted IWI files (source)
├── 02_DDS/      ← Intermediate DDS files
├── 03_PNG/      ← Editable PNGs — edit these
└── 04_Output/   ← Finished IWD files, ready for the game
```

Each folder holds one subfolder per project. The workspace location can be changed at any time via the **Workspace** bar at the top of the tool.

---

## License

Source code: [MIT](LICENSE)

Bundled third-party binaries:
- `texconv.exe` — [Microsoft DirectXTex](https://github.com/microsoft/DirectXTex) (MIT)
- `libsquish.dll` — [libsquish](https://sourceforge.net/projects/libsquish/) (MIT)
- `upscaler/realesrgan-ncnn-vulkan.exe` and bundled model weights — [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD 3-Clause)
