# MW2 Texture Manager

A GUI tool for extracting, editing, and repacking textures from **Call of Duty: Modern Warfare 2 (2009)**.

Built with Python + Tkinter. Bundles into a single portable `.exe` via PyInstaller — no Python install needed to run it.

---

## Features

- Extract IWI textures from IWD archives in bulk
- Convert IWI → DDS → PNG for editing in any image editor
- Repack edited PNGs back to IWI and bundle into a game-ready IWD
- Preserves original DDS format per-texture (DXT1 / DXT3 / DXT5) — no quality loss from unnecessary format changes
- Colour-coded activity log with per-file progress counters
- Single-file portable EXE — drop it next to the tools and run

---

## Requirements

### Running the EXE
Download the latest release from the [Releases](https://github.com/CFOD/MW2-Texture-Manager/releases) page.

You also need these two external tools placed in the **same folder** as the EXE:

| Tool | Purpose | Where to get it |
|------|---------|-----------------|
| `iwi2dds.exe` | Converts IWI → DDS | [Link your source here] |
| `imgXiwi.exe` | Converts PNG → IWI | [Link your source here] |

> `texconv.exe` and `libsquish.dll` are already bundled inside the EXE.

### Building from source
```
pip install pillow pyinstaller
```
Place all four tool binaries (`iwi2dds.exe`, `imgXiwi.exe`, `texconv.exe`, `libsquish.dll`) in the project folder, then run:
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

The workspace location can be changed at any time via the **Workspace** bar at the top of the tool.

---

## License

Source code: [MIT](LICENSE)

Bundled third-party binaries:
- `texconv.exe` — [Microsoft DirectXTex](https://github.com/microsoft/DirectXTex) (MIT)
- `libsquish.dll` — [libsquish](https://sourceforge.net/projects/libsquish/) (MIT)
