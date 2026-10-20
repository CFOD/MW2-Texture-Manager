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
Download the latest release from the [Releases](https://github.com/CFOD/MW2-Texture-Manager/releases) page and run it — no Python and no other files needed.

> Everything is bundled inside the EXE: `iwi2dds.exe`, `imgXiwi.exe`, `texconv.exe`, `libsquish.dll` and the Real-ESRGAN upscaler with its model.
> The upscaler uses your GPU via Vulkan, so you need a Vulkan-capable graphics card and up-to-date drivers.
> If a tool is ever flagged MISSING in the status row, place it next to the EXE.

### Building from source
```
pip install pillow pyinstaller customtkinter tkinterdnd2
```
Requires Windows and Python 3.10+. All tool binaries (`iwi2dds.exe`, `imgXiwi.exe`, `texconv.exe`, `libsquish.dll`, `upscaler/`) are included in the repo. To run from source: `python mw2_upscale_assistant.py`. To build the EXE:
```
build_executable.bat
```
Or use the spec file directly:
```
pyinstaller MW2_Tool.spec
```

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
- `iwi2dds.exe`, `imgXiwi.exe` — third-party MW2 modding tools by their respective authors, included for convenience
- `texconv.exe` — [Microsoft DirectXTex](https://github.com/microsoft/DirectXTex) (MIT)
- `libsquish.dll` — [libsquish](https://sourceforge.net/projects/libsquish/) (MIT)
- `upscaler/realesrgan-ncnn-vulkan.exe` and bundled model weights — [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD 3-Clause)
