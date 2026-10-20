import tkinter as tk
from tkinter import filedialog, messagebox
import json
import os
import shutil
import zipfile
import threading
import subprocess
import sys
import uuid
from pathlib import Path

import customtkinter as ctk
from tkinterdnd2 import TkinterDnD, DND_FILES

# Check for Pillow
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

# --- Workspace layout ---
FOLDER_IWI = "01_IWI"
FOLDER_DDS = "02_DDS"
FOLDER_PNG = "03_PNG"
FOLDER_OUTPUT = "04_Output"
FOLDER_REPACK_TEMP = ".repack_temp"
FOLDER_ORIGINALS = ".originals"  # pre-upscale PNG backups, for the compare view

# --- External tool names ---
EXE_EXTRACTOR = "iwi2dds.exe"
EXE_REPACKER = "imgXiwi.exe"
EXE_COMPRESSOR = "texconv.exe"
DLL_LIBSQUISH = "libsquish.dll"
ICON_FILE = "icon.ico"

# --- Upscaler (Real-ESRGAN ncnn-vulkan, bundled under upscaler/) ---
UPSCALER_DIR = "upscaler"
EXE_UPSCALER = "realesrgan-ncnn-vulkan.exe"
UPSCALER_MODEL_DIR = "models"
UPSCALER_MODEL_NAME = "realesrgan-x4plus"
UPSCALER_TIMEOUT_SECONDS = 120

# --- Misc ---
OUTPUT_IWD_PREFIX = "z_"
CONVERTER_TIMEOUT_SECONDS = 15
REPACKER_TIMEOUT_SECONDS = 20
SETTINGS_FILE = "settings.json"


# --- Palette --------------------------------------------------------------
# Central source of truth for every color used in the UI. Swapping LIGHT/DARK
# values here is all that's needed to re-theme the app; nothing else should
# hardcode a hex color.
PALETTE = {
    "light": {
        "bg": "#f2f2f2",
        "surface": "#ffffff",
        "border": "#d0d0d0",
        "text": "#212121",
        "text_muted": "#757575",
        "accent": "#1565c0",
        "success": "#2e7d32",
        "error": "#c62828",
        "warning": "#e65100",
        "listbox_bg": "#ffffff",
        "listbox_fg": "#212121",
        "listbox_select": "#bbdefb",
        "log_bg": "#fafafa",
    },
    "dark": {
        "bg": "#1e1e1e",
        "surface": "#2b2b2b",
        "border": "#3c3c3c",
        "text": "#e0e0e0",
        "text_muted": "#9e9e9e",
        "accent": "#64b5f6",
        "success": "#81c784",
        "error": "#e57373",
        "warning": "#ffb74d",
        "listbox_bg": "#2b2b2b",
        "listbox_fg": "#e0e0e0",
        "listbox_select": "#37474f",
        "log_bg": "#252525",
    },
}


def get_palette():
    mode = ctk.get_appearance_mode().lower()  # "light" or "dark"
    return PALETTE[mode]


# --- Hybrid root window: CustomTkinter + drag-and-drop ---------------------
class CTkDnD(ctk.CTk, TkinterDnD.DnDWrapper):
    """CTk's root window with tkinterdnd2's drop-target support mixed in.

    Both CTk and TkinterDnD.Tk subclass tkinter.Tk directly, so multiple
    inheritance works, but TkinterDnD's Tcl package has to be loaded manually
    since we're not going through TkinterDnD.Tk.__init__.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)


class IwiUtils:
    @staticmethod
    def _safe_remove(path):
        """Best-effort delete of a temp file; a failure here is not fatal to the caller."""
        try:
            os.remove(path)
        except OSError as e:
            print(f"Warning: could not remove temp file {path}: {e}", file=sys.stderr)

    def run_external_converter(self, exe_path, iwi_path, dds_output_path):
        """Runs iwi2dds.exe (Extracts IWI -> DDS)"""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [exe_path, '-i', str(iwi_path), '-o', str(dds_output_path)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=CONVERTER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return False, f"Timed out ({CONVERTER_TIMEOUT_SECONDS}s)"

            if os.path.exists(dds_output_path): return True, "Success"

            # Fallback syntax check
            cmd_simple = [exe_path, str(iwi_path)]
            try:
                subprocess.run(cmd_simple, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, timeout=CONVERTER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                pass

            possible_output = iwi_path.with_suffix(".dds")
            if possible_output.exists():
                if possible_output != dds_output_path:
                    shutil.move(possible_output, dds_output_path)
                return True, "Success (Fallback)"

            return False, result.stderr or "Unknown Error - output file not created"
        except Exception as e:
            return False, str(e)

    def run_external_repacker(self, exe_path, input_path, iwi_output_path):
        """Runs imgXiwi (Repacks PNG -> IWI) using Sandbox Execution"""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            abs_exe = os.path.abspath(exe_path)
            exe_dir = os.path.dirname(abs_exe)

            # Sandbox: Copy input to tool folder with a unique name to prevent
            # WinError 1224 — imgXiwi memory-maps its input, so reusing the same
            # filename while a previous mapping is still alive causes a write failure.
            temp_stem = f"tmp_{uuid.uuid4().hex[:12]}"
            temp_name = temp_stem + Path(input_path).suffix
            local_input_path = os.path.join(exe_dir, temp_name)

            shutil.copy2(input_path, local_input_path)

            cmd = [abs_exe, temp_name]

            try:
                process = subprocess.run(
                    cmd,
                    capture_output=True,
                    startupinfo=startupinfo,
                    cwd=exe_dir,
                    text=True,
                    timeout=REPACKER_TIMEOUT_SECONDS
                )
            except subprocess.TimeoutExpired as e:
                self._safe_remove(local_input_path)
                return False, f"TIMEOUT ({REPACKER_TIMEOUT_SECONDS}s): Repacker hung on this file. Output: {e.stdout}"

            # Cleanup input
            self._safe_remove(local_input_path)

            # Find output (.iwi) — name matches the unique temp stem
            local_iwi_name = temp_stem + ".iwi"
            local_iwi_path = os.path.join(exe_dir, local_iwi_name)

            if os.path.exists(local_iwi_path):
                if os.path.exists(iwi_output_path): os.remove(iwi_output_path)
                shutil.move(local_iwi_path, iwi_output_path)

                log_msg = "Success"
                if process.stdout:
                    lines = process.stdout.splitlines()
                    clean_lines = []
                    for line in lines:
                        l = line.strip()
                        if l.startswith("Image format:") or l.startswith("Image dimension:") or l.startswith("Creating"):
                            clean_lines.append(l)
                    if clean_lines:
                        log_msg = ", ".join(clean_lines)

                return True, log_msg

            error_log = f"Exit Code {process.returncode}. STDERR: {process.stderr.strip()}. STDOUT: {process.stdout.strip()}"
            return False, error_log

        except Exception as e:
            return False, f"Exception: {str(e)}"

    def detect_dds_format(self, dds_path):
        """Read the DDS header fourcc to detect pixel format (DXT1, DXT3, DXT5)."""
        try:
            with open(dds_path, 'rb') as f:
                if f.read(4) != b'DDS ':
                    return 'DXT5'
                f.seek(84)  # offset of dwFourCC in DDS_PIXELFORMAT
                fourcc = f.read(4).rstrip(b'\x00')
                if fourcc in (b'DXT1', b'DXT3', b'DXT5'):
                    return fourcc.decode('ascii')
        except Exception:
            pass
        return 'DXT5'

    def run_texconv(self, exe_path, png_path, dds_path, fmt='DXT5'):
        """Runs texconv.exe (PNG -> DDS)"""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [exe_path, '-f', fmt, '-y', '-o', os.path.dirname(dds_path), str(png_path)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=CONVERTER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return False, f"Texconv Timed Out ({CONVERTER_TIMEOUT_SECONDS}s)"

            actual_out = Path(dds_path).with_name(Path(png_path).stem + ".dds")
            if actual_out.exists():
                if actual_out != Path(dds_path):
                    shutil.move(actual_out, dds_path)
                return True, "Success"
            return False, result.stderr or "Texconv failed to produce output"
        except Exception as e:
            return False, str(e)

    def run_upscaler(self, exe_path, model_dir, model_name, png_path, out_path, scale=2):
        """
        Runs realesrgan-ncnn-vulkan (PNG -> larger PNG).

        Verifies the result before accepting it: the upscaler must preserve the
        input's alpha channel (its presence or absence) and must land on an
        exact integer multiple of the original dimensions. Silent alpha loss or
        an off-size output is exactly what corrupts a texture at repack time —
        the failure is invisible until the game renders it, so we catch it here
        instead of trusting the subprocess's exit code alone.
        """
        try:
            with Image.open(png_path) as src_img:
                src_mode = src_img.mode
                src_w, src_h = src_img.size
                had_alpha = src_mode in ("RGBA", "LA") or (src_mode == "P" and "transparency" in src_img.info)

            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [exe_path, '-i', str(png_path), '-o', str(out_path),
                   '-n', model_name, '-m', str(model_dir), '-s', str(scale)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True,
                                         startupinfo=startupinfo, timeout=UPSCALER_TIMEOUT_SECONDS)
            except subprocess.TimeoutExpired:
                return False, f"Upscaler timed out ({UPSCALER_TIMEOUT_SECONDS}s)"

            if not os.path.exists(out_path):
                return False, result.stderr.strip() or "Upscaler failed to produce output"

            with Image.open(out_path) as out_img:
                out_mode = out_img.mode
                out_w, out_h = out_img.size
                out_has_alpha = out_mode in ("RGBA", "LA")

            if (out_w, out_h) != (src_w * scale, src_h * scale):
                self._safe_remove(out_path)
                return False, (f"Output size {out_w}x{out_h} does not match expected "
                                f"{src_w * scale}x{src_h * scale} — rejected to avoid a broken repack")

            if had_alpha and not out_has_alpha:
                self._safe_remove(out_path)
                return False, "Upscaler dropped the alpha channel — rejected to avoid transparency corruption"

            return True, f"Success ({src_w}x{src_h} -> {out_w}x{out_h})"
        except Exception as e:
            return False, str(e)


class OperationCancelled(Exception):
    """Raised internally to unwind a running pipeline step when the user hits Cancel."""


class CompareWindow(ctk.CTkToplevel):
    """Side-by-side original-vs-current viewer for a project's upscaled/edited PNGs.

    The two images are frequently different resolutions (upscaling changes pixel
    dimensions), so a pixel-aligned slider-overlay isn't meaningful here; each pane
    is independently fit to a common display size with its real dimensions captioned
    underneath instead.
    """
    PREVIEW_SIZE = (380, 380)

    def __init__(self, app, project_name, pairs):
        super().__init__(app.root)
        self.app = app
        self.pairs = pairs  # list of (rel_path_str, original_path, current_path)
        self._left_image = None
        self._right_image = None

        self.title(f"Compare — {project_name}")
        self.geometry("820x520")
        self.transient(app.root)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=12, pady=(12, 6))
        ctk.CTkLabel(top, text="File:").pack(side="left", padx=(0, 6))
        self.file_var = tk.StringVar(value=pairs[0][0])
        ctk.CTkOptionMenu(top, values=[p[0] for p in pairs], variable=self.file_var,
                          command=lambda _: self._render()).pack(side="left", fill="x", expand=True)

        panes = ctk.CTkFrame(self, fg_color="transparent")
        panes.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        panes.columnconfigure(0, weight=1)
        panes.columnconfigure(1, weight=1)
        panes.rowconfigure(0, weight=1)

        left = ctk.CTkFrame(panes)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        ctk.CTkLabel(left, text="Original", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 2))
        self.left_image_label = ctk.CTkLabel(left, text="")
        self.left_image_label.pack(expand=True)
        self.left_caption = ctk.CTkLabel(left, text="", font=ctk.CTkFont(size=11))
        self.left_caption.pack(pady=(2, 8))

        right = ctk.CTkFrame(panes)
        right.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        ctk.CTkLabel(right, text="Current", font=ctk.CTkFont(weight="bold")).pack(pady=(8, 2))
        self.right_image_label = ctk.CTkLabel(right, text="")
        self.right_image_label.pack(expand=True)
        self.right_caption = ctk.CTkLabel(right, text="", font=ctk.CTkFont(size=11))
        self.right_caption.pack(pady=(2, 8))

        self._render()

    def _load_preview(self, path):
        with Image.open(path) as img:
            real_size = img.size
            display_img = img.convert("RGB").copy()
        display_img.thumbnail(self.PREVIEW_SIZE)
        return ctk.CTkImage(light_image=display_img, dark_image=display_img, size=display_img.size), real_size

    def _render(self):
        rel = self.file_var.get()
        original_path, current_path = next((o, c) for r, o, c in self.pairs if r == rel)
        try:
            self._left_image, left_size = self._load_preview(original_path)
            self.left_image_label.configure(image=self._left_image, text="")
            self.left_caption.configure(text=f"{left_size[0]} x {left_size[1]}")
        except Exception as e:
            self.left_image_label.configure(image=None, text=f"Failed to load: {e}")
            self.left_caption.configure(text="")

        try:
            self._right_image, right_size = self._load_preview(current_path)
            self.right_image_label.configure(image=self._right_image, text="")
            self.right_caption.configure(text=f"{right_size[0]} x {right_size[1]}")
        except Exception as e:
            self.right_image_label.configure(image=None, text=f"Failed to load: {e}")
            self.right_caption.configure(text="")


# --- GUI Application ---
class MW2TextureManager:
    def __init__(self, root):
        self.root = root
        self.root.title("MW2 Texture Manager")

        if getattr(sys, 'frozen', False):
            app_path = os.path.dirname(sys.executable)
        else:
            app_path = os.path.dirname(os.path.abspath(__file__))
        self.app_path = Path(app_path)

        self.settings = self._load_settings()

        self.project_root = Path(self.settings.get("last_workspace") or (self.app_path / "MW2_Project"))
        self._set_workspace_dirs(self.project_root)

        geometry = self.settings.get("window_geometry", "900x900")
        self.root.geometry(geometry)
        self.root.minsize(760, 640)

        self.source_iwds = []
        self._busy = False
        self._cancel_requested = False
        self._async_buttons = []
        self.utils = IwiUtils()
        self._preview_ctk_image = None
        self._advanced_visible = False

        self.extractor_exe = tk.StringVar()
        self.repacker_exe = tk.StringVar()
        self.compressor_exe = tk.StringVar()
        self.upscaler_exe = tk.StringVar()
        self.upscaler_model_dir = ""
        self.workspace_var = tk.StringVar(value=str(self.project_root))

        self._refresh_tool_paths(log_result=False)

        self.setup_ui()
        self.ensure_workspace_structure()
        self.root.after(200, self.refresh_workspace_list)

        icon_path = self.find_tool(ICON_FILE)
        if icon_path:
            try:
                self.root.iconbitmap(icon_path)
            except tk.TclError as e:
                print(f"Warning: could not load icon {icon_path}: {e}", file=sys.stderr)

        if not HAS_PIL:
            messagebox.showwarning("Dependency Error", "Pillow library missing.\nImages cannot be processed.")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ settings

    def _settings_path(self):
        return self.app_path / SETTINGS_FILE

    def _load_settings(self):
        path = self._settings_path()
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (OSError, json.JSONDecodeError) as e:
                print(f"Warning: could not read {path}: {e}", file=sys.stderr)
        return {}

    def _save_settings(self):
        self.settings["last_workspace"] = str(self.project_root)
        self.settings["window_geometry"] = self.root.geometry()
        self.settings["appearance_mode"] = ctk.get_appearance_mode()
        try:
            self._settings_path().write_text(json.dumps(self.settings, indent=2))
        except OSError as e:
            print(f"Warning: could not write {self._settings_path()}: {e}", file=sys.stderr)

    def _on_close(self):
        self._save_settings()
        self.root.destroy()

    # ------------------------------------------------------------------ workspace / tools

    def _set_workspace_dirs(self, root):
        """Single source of truth for the workspace's fixed subfolder layout."""
        self.project_root = root
        self.dir_raw = root / FOLDER_IWI
        self.dir_dds = root / FOLDER_DDS
        self.dir_png = root / FOLDER_PNG
        self.dir_final = root / FOLDER_OUTPUT
        self.dir_temp_repack = root / FOLDER_REPACK_TEMP

    def find_tool(self, name):
        bundled = self.resource_path(name)
        if os.path.exists(bundled): return bundled
        beside_app = self.app_path / name
        if beside_app.exists(): return str(beside_app)
        return ""

    def find_upscaler(self):
        """The upscaler ships as a subfolder (exe + models/) rather than a flat file
        next to the app, so it needs its own resolution logic distinct from find_tool."""
        exe_rel = os.path.join(UPSCALER_DIR, EXE_UPSCALER)
        model_rel = os.path.join(UPSCALER_DIR, UPSCALER_MODEL_DIR)
        exe_path = self.resource_path(exe_rel)
        model_dir = self.resource_path(model_rel)
        if os.path.exists(exe_path) and os.path.isdir(model_dir):
            return exe_path, model_dir
        exe_beside = self.app_path / exe_rel
        model_beside = self.app_path / model_rel
        if exe_beside.exists() and model_beside.is_dir():
            return str(exe_beside), str(model_beside)
        return "", ""

    def resource_path(self, relative_path):
        # sys._MEIPASS is the PyInstaller onefile extraction dir (bundled data);
        # self.app_path is where the script/exe itself lives (external tools placed alongside it).
        try: base_path = sys._MEIPASS
        except AttributeError: base_path = str(self.app_path)
        return os.path.join(base_path, relative_path)

    def ensure_workspace_structure(self):
        for d in (self.project_root, self.dir_raw, self.dir_dds, self.dir_png, self.dir_final):
            d.mkdir(parents=True, exist_ok=True)

    def _refresh_tool_paths(self, log_result=True):
        self.extractor_exe.set(self.find_tool(EXE_EXTRACTOR))
        self.repacker_exe.set(self.find_tool(EXE_REPACKER))
        self.compressor_exe.set(self.find_tool(EXE_COMPRESSOR))
        upscaler_exe, upscaler_model_dir = self.find_upscaler()
        self.upscaler_exe.set(upscaler_exe)
        self.upscaler_model_dir = upscaler_model_dir
        if log_result:
            found = sum(bool(v) for v in (self.extractor_exe.get(), self.repacker_exe.get(),
                                           self.compressor_exe.get(), self.upscaler_exe.get()))
            self.log(f"Tool paths refreshed: {found}/4 found.")
            self._update_tool_status_labels()

    # ------------------------------------------------------------------ UI construction

    def setup_ui(self):
        self._async_buttons = []
        pal = get_palette()

        # Root uses grid (not pack) so vertical space can be distributed by
        # explicit weight: fixed-height sections (header/status/workspace/source
        # queue/progress) get weight 0, while Workspace Projects and the
        # Activity Log — the two sections that should grow/shrink with the
        # window — split the remaining space in a guaranteed ratio. With plain
        # pack(), the log (being last) was the first thing crushed when the
        # window got taller than expected instead of actually growing into it.
        self.root.columnconfigure(0, weight=1)
        for row in (0, 1, 2, 3, 5):
            self.root.rowconfigure(row, weight=0)
        self.root.rowconfigure(4, weight=2)  # Workspace Projects
        self.root.rowconfigure(6, weight=1)  # Activity Log

        # --- Header ---
        frame_top = ctk.CTkFrame(self.root, fg_color="transparent")
        frame_top.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ctk.CTkLabel(frame_top, text="MW2 Texture Manager", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")

        appearance_row = ctk.CTkFrame(frame_top, fg_color="transparent")
        appearance_row.pack(side="right")
        ctk.CTkLabel(appearance_row, text="Dark Mode", font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        initial_dark = ctk.get_appearance_mode() == "Dark"
        self.dark_mode_switch = ctk.CTkSwitch(appearance_row, text="", width=36, command=self._toggle_appearance)
        if initial_dark:
            self.dark_mode_switch.select()
        self.dark_mode_switch.pack(side="left")

        # --- Tool status row ---
        status_row = ctk.CTkFrame(self.root, fg_color="transparent")
        status_row.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 6))
        self.status_labels = {}
        for key, name, var in (
            ("extractor", "Extractor", self.extractor_exe),
            ("compressor", "Compressor", self.compressor_exe),
            ("repacker", "Repacker", self.repacker_exe),
            ("upscaler", "Upscaler", self.upscaler_exe),
        ):
            lbl = ctk.CTkLabel(status_row, text="", font=ctk.CTkFont(size=11, weight="bold"))
            lbl.pack(side="left", padx=(0, 12))
            self.status_labels[key] = (lbl, name, var)
        ctk.CTkButton(status_row, text="Refresh", width=70, height=22,
                      font=ctk.CTkFont(size=11), command=self._on_refresh_tools).pack(side="right")
        self._update_tool_status_labels()

        # --- Workspace row ---
        frame_proj = ctk.CTkFrame(self.root, fg_color="transparent")
        frame_proj.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))
        ctk.CTkLabel(frame_proj, text="Workspace:").pack(side="left")
        self.workspace_entry = ctk.CTkEntry(frame_proj, textvariable=self.workspace_var, state="readonly")
        self.workspace_entry.pack(side="left", fill="x", expand=True, padx=6)
        ctk.CTkButton(frame_proj, text="Change...", width=90, command=self.browse_workspace).pack(side="left")

        # --- Source Queue ---
        frame_source = ctk.CTkFrame(self.root)
        frame_source.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 8))
        ctk.CTkLabel(frame_source, text="1. Source Queue", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(6, 2))
        ctk.CTkLabel(frame_source, text="Drag && drop .iwd files here, or use Add Files...",
                     font=ctk.CTkFont(size=10), text_color=pal["text_muted"]).pack(anchor="w", padx=8)

        source_toolbar = ctk.CTkFrame(frame_source, fg_color="transparent")
        source_toolbar.pack(fill="x", padx=8, pady=(4, 4))
        ctk.CTkButton(source_toolbar, text="+ Add IWD Files...", command=self.add_source_files).pack(side="left")
        ctk.CTkButton(source_toolbar, text="- Remove Selected", fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.remove_source_files).pack(side="left", padx=6)
        b = ctk.CTkButton(source_toolbar, text="Extract Selected ->", fg_color=pal["success"],
                          hover_color=pal["success"], command=lambda: self.run_async(self.process_extract_queue))
        b.pack(side="right")
        self._async_buttons.append(b)

        list_container = tk.Frame(frame_source, bg=pal["surface"], highlightthickness=1, highlightbackground=pal["border"])
        list_container.pack(fill="x", padx=8, pady=(0, 8))
        self.source_listbox = tk.Listbox(list_container, selectmode=tk.MULTIPLE, height=5, activestyle="none",
                                          bd=0, highlightthickness=0)
        self.source_listbox.pack(fill="both", expand=True, padx=1, pady=1)
        self._register_drop_target(self.source_listbox, self._on_files_dropped)

        # --- Workspace Projects ---
        frame_work = ctk.CTkFrame(self.root)
        frame_work.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 8))
        ctk.CTkLabel(frame_work, text="2. Workspace Projects", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(6, 4))

        work_split = ctk.CTkFrame(frame_work, fg_color="transparent")
        work_split.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        work_split.columnconfigure(0, weight=3)
        work_split.columnconfigure(1, weight=2)
        work_split.rowconfigure(0, weight=1)

        # Project list + Select All / None + preview
        list_frame = ctk.CTkFrame(work_split, fg_color="transparent")
        list_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        list_body = tk.Frame(list_frame, bg=pal["surface"], highlightthickness=1, highlightbackground=pal["border"])
        list_body.pack(fill="both", expand=True)
        self.archive_listbox = tk.Listbox(list_body, selectmode=tk.MULTIPLE, exportselection=False,
                                           activestyle="none", bd=0, highlightthickness=0)
        self.archive_listbox.pack(fill="both", expand=True, padx=1, pady=1)
        self.archive_listbox.bind("<<ListboxSelect>>", self._on_project_selected)

        sel_frame = ctk.CTkFrame(list_frame, fg_color="transparent")
        sel_frame.pack(fill='x', pady=(4, 0))
        ctk.CTkButton(sel_frame, text="Select All", height=22, font=ctk.CTkFont(size=11),
                      command=self.select_all_projects).pack(side='left', fill='x', expand=True, padx=(0, 3))
        ctk.CTkButton(sel_frame, text="Select None", height=22, font=ctk.CTkFont(size=11),
                      command=self.deselect_all_projects).pack(side='left', fill='x', expand=True, padx=(3, 0))

        # Preview panel
        preview_frame = ctk.CTkFrame(list_frame)
        preview_frame.pack(fill="x", pady=(8, 0))
        ctk.CTkLabel(preview_frame, text="Preview", font=ctk.CTkFont(size=11, weight="bold")).pack(anchor="w", padx=6, pady=(4, 0))
        self.preview_label = ctk.CTkLabel(preview_frame, text="Select a project to preview a texture", height=120,
                                           font=ctk.CTkFont(size=10), text_color=pal["text_muted"])
        self.preview_label.pack(fill="x", padx=6, pady=6)

        # Operation buttons
        btn_frame = ctk.CTkFrame(work_split, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="nsew")

        def section_sep(label_text):
            ctk.CTkFrame(btn_frame, height=1, fg_color=pal["border"]).pack(fill='x', pady=(8, 0))
            ctk.CTkLabel(btn_frame, text=label_text, font=ctk.CTkFont(size=10, slant="italic"),
                         text_color=pal["text_muted"]).pack(pady=(2, 4))

        section_sep("Extract")
        b = ctk.CTkButton(btn_frame, text="Convert IWI -> DDS", command=lambda: self.run_async(self.step_convert_iwi_to_dds))
        b.pack(pady=2, fill="x"); self._async_buttons.append(b)
        b = ctk.CTkButton(btn_frame, text="Convert DDS -> PNG", command=lambda: self.run_async(self.step_convert_dds_to_png))
        b.pack(pady=2, fill="x"); self._async_buttons.append(b)

        section_sep("Enhance")
        upscale_row = ctk.CTkFrame(btn_frame, fg_color="transparent")
        upscale_row.pack(fill="x", pady=2)
        self.upscale_scale_var = tk.StringVar(value="2x")
        ctk.CTkOptionMenu(upscale_row, values=["2x", "4x"], variable=self.upscale_scale_var,
                          width=60, font=ctk.CTkFont(size=11)).pack(side="left", padx=(0, 6))
        b = ctk.CTkButton(upscale_row, text="Upscale PNGs", command=self._on_upscale_clicked)
        b.pack(side="left", fill="x", expand=True)
        self._async_buttons.append(b)
        ctk.CTkLabel(btn_frame, text="Run anytime on a project's current PNGs.\nOriginals are kept for Compare.",
                     font=ctk.CTkFont(size=10), text_color=pal["text_muted"], justify="left").pack(anchor="w", pady=(2, 2))
        b = ctk.CTkButton(btn_frame, text="Compare Original / Current", fg_color="transparent", border_width=1,
                          text_color=("gray10", "gray90"), command=self._open_compare_view)
        b.pack(pady=2, fill="x")

        section_sep("Repack")
        b = ctk.CTkButton(btn_frame, text="Convert PNG -> IWI", command=lambda: self.run_async(self.step_pack_png_to_iwi_only))
        b.pack(pady=2, fill="x"); self._async_buttons.append(b)

        open_frame = ctk.CTkFrame(btn_frame, fg_color="transparent")
        open_frame.pack(fill='x', pady=(8, 2))
        ctk.CTkButton(open_frame, text="PNG Folder", fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.open_edit_folder).pack(side='left', fill='x', expand=True, padx=(0, 3))
        ctk.CTkButton(open_frame, text="Output Folder", fg_color="transparent", border_width=1,
                      text_color=("gray10", "gray90"), command=self.open_output_folder).pack(side='left', fill='x', expand=True, padx=(3, 0))

        b = ctk.CTkButton(btn_frame, text="Repack to IWD", fg_color=pal["success"], hover_color=pal["success"],
                          font=ctk.CTkFont(weight="bold"), command=lambda: self.run_async(self.step_repack_png))
        b.pack(pady=(6, 2), fill="x"); self._async_buttons.append(b)

        self.cancel_button = ctk.CTkButton(btn_frame, text="Cancel", fg_color=pal["error"], hover_color=pal["error"],
                                            state="disabled", command=self._request_cancel)
        self.cancel_button.pack(pady=2, fill="x")

        # Advanced (collapsible) section — reverse PNG -> DDS conversion
        self.advanced_toggle_btn = ctk.CTkButton(btn_frame, text="Show Advanced ▾", fg_color="transparent",
                                                  border_width=1, text_color=("gray10", "gray90"),
                                                  font=ctk.CTkFont(size=11), command=self._toggle_advanced)
        self.advanced_toggle_btn.pack(pady=(10, 2), fill="x")
        self.advanced_frame = ctk.CTkFrame(btn_frame, fg_color="transparent")
        b = ctk.CTkButton(self.advanced_frame, text="Convert PNG -> DDS (reverse)",
                          command=lambda: self.run_async(self.step_convert_png_to_dds))
        b.pack(pady=2, fill="x"); self._async_buttons.append(b)
        ctk.CTkLabel(self.advanced_frame, text="Re-compresses edited PNGs back to DDS,\nmatching the original format when known.",
                     font=ctk.CTkFont(size=10), text_color=pal["text_muted"], justify="left").pack(anchor="w", pady=(2, 4))
        # advanced_frame is intentionally not packed yet — starts collapsed

        # --- Progress ---
        frame_bottom = ctk.CTkFrame(self.root, fg_color="transparent")
        frame_bottom.grid(row=5, column=0, sticky="ew", padx=12, pady=(0, 4))
        self.progress_bar = ctk.CTkProgressBar(frame_bottom)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=(0, 4))
        self.progress_label = ctk.CTkLabel(frame_bottom, text="Idle", font=ctk.CTkFont(size=11), anchor="w")
        self.progress_label.pack(fill="x")

        # --- Log ---
        frame_log = ctk.CTkFrame(self.root)
        frame_log.grid(row=6, column=0, sticky="nsew", padx=12, pady=(0, 10))
        log_toolbar = ctk.CTkFrame(frame_log, fg_color="transparent")
        log_toolbar.pack(fill='x', padx=6, pady=(6, 2))
        ctk.CTkLabel(log_toolbar, text="Activity Log", font=ctk.CTkFont(weight="bold")).pack(side="left")
        ctk.CTkButton(log_toolbar, text="Clear Log", width=80, height=22, font=ctk.CTkFont(size=11),
                      command=self.clear_log).pack(side='right')

        self.log_text = ctk.CTkTextbox(frame_log, state='disabled', font=ctk.CTkFont(family="Consolas", size=12))
        self.log_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))

        # Color tags for log entries (CTkTextbox wraps a tkinter.Text as ._textbox)
        self._configure_log_tags()

    def _configure_log_tags(self):
        pal = get_palette()
        text_widget = self.log_text._textbox
        text_widget.tag_config('error', foreground=pal["error"])
        text_widget.tag_config('success', foreground=pal["success"])
        text_widget.tag_config('action', foreground=pal["accent"])
        text_widget.tag_config('normal', foreground=pal["text"])

    def _update_tool_status_labels(self):
        pal = get_palette()
        for key, (lbl, name, var) in self.status_labels.items():
            found = bool(var.get())
            color = pal["success"] if found else pal["error"]
            txt = "OK" if found else "MISSING"
            lbl.configure(text=f"{name}: {txt}", text_color=color)

    def _restyle_tk_widgets(self):
        """CTk widgets re-theme themselves automatically; the plain tk.Listbox/Textbox
        widgets we kept for functionality (no CTk equivalent) need manual re-coloring."""
        pal = get_palette()
        for lb in (self.source_listbox, self.archive_listbox):
            lb.configure(bg=pal["listbox_bg"], fg=pal["listbox_fg"],
                         selectbackground=pal["listbox_select"], selectforeground=pal["listbox_fg"])
            lb.master.configure(bg=pal["surface"], highlightbackground=pal["border"])
        self.log_text.configure(fg_color=pal["log_bg"])
        self._configure_log_tags()
        self._update_tool_status_labels()

    def _toggle_appearance(self):
        mode = "Dark" if self.dark_mode_switch.get() else "Light"
        ctk.set_appearance_mode(mode)
        self.root.after(50, self._restyle_tk_widgets)

    def _toggle_advanced(self):
        self._advanced_visible = not self._advanced_visible
        if self._advanced_visible:
            self.advanced_frame.pack(fill="x")
            self.advanced_toggle_btn.configure(text="Hide Advanced ▴")
        else:
            self.advanced_frame.pack_forget()
            self.advanced_toggle_btn.configure(text="Show Advanced ▾")

    def _on_refresh_tools(self):
        self._refresh_tool_paths(log_result=True)

    def _on_upscale_clicked(self):
        scale = int(self.upscale_scale_var.get().rstrip("x"))
        self.run_async(lambda: self.step_upscale_png(scale=scale))

    # ------------------------------------------------------------------ drag & drop

    def _register_drop_target(self, widget, callback):
        widget.drop_target_register(DND_FILES)
        widget.dnd_bind("<<Drop>>", callback)

    def _on_files_dropped(self, event):
        paths = self.root.tk.splitlist(event.data)
        added = 0
        for p in paths:
            if p.lower().endswith(".iwd"):
                f_path = str(Path(p).resolve())
                if f_path not in self.source_iwds:
                    self.source_iwds.append(f_path)
                    self.source_listbox.insert(tk.END, f_path)
                    added += 1
        if added:
            self.log(f"Added {added} item(s) to queue via drag-and-drop.")
        else:
            self.log("Drop ignored: no .iwd files found in dropped items.")

    # ------------------------------------------------------------------ helpers

    def log(self, msg):
        self.root.after(0, self._log_safe, msg)

    def _log_safe(self, msg):
        text_widget = self.log_text._textbox
        self.log_text.configure(state='normal')
        # Strip leading whitespace only for the tag check so indented lines still match
        stripped = msg.lstrip().upper()
        if (stripped.startswith('ERROR') or stripped.startswith('FAILED') or
                stripped.startswith('ABORTED') or stripped.startswith('! FAILED')):
            tag = 'error'
        elif (stripped.startswith('FINISHED') or stripped.startswith('FINALIZED') or
              stripped.startswith('SUCCESS') or stripped.startswith('+ ')):
            tag = 'success'
        elif (stripped.startswith('CONVERTING') or stripped.startswith('EXTRACTING') or
              stripped.startswith('PACKING') or stripped.startswith('REPACKING') or
              stripped.startswith('COMPILING')):
            tag = 'action'
        else:
            tag = 'normal'
        text_widget.insert(tk.END, f"> {msg}\n", tag)
        text_widget.see(tk.END)
        self.log_text.configure(state='disabled')

    def clear_log(self):
        self.log_text.configure(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.configure(state='disabled')

    def set_progress(self, value, text=None):
        self.root.after(0, self._update_progress, value, text)

    def _update_progress(self, value, text):
        self.progress_bar.set(max(0.0, min(1.0, value / 100)))
        if text: self.progress_label.configure(text=text)

    def _set_buttons_state(self, state):
        for btn in self._async_buttons:
            try:
                btn.configure(state=state)
            except tk.TclError:
                pass  # widget was destroyed (e.g. window closing mid-operation)

    def _request_cancel(self):
        self._cancel_requested = True
        self.log("Cancel requested — finishing current file, then stopping...")

    def run_async(self, target):
        if self._busy:
            self.log("Error: An operation is already running. Please wait.")
            return
        self._cancel_requested = False
        self._set_buttons_state('disabled')
        self.cancel_button.configure(state='normal')

        def _wrapped():
            self._busy = True
            try:
                target()
            except OperationCancelled:
                self.log("ABORTED: Operation cancelled by user.")
            finally:
                self._busy = False
                self._cancel_requested = False
                self.root.after(0, self._set_buttons_state, 'normal')
                self.root.after(0, lambda: self.cancel_button.configure(state='disabled'))
                self.root.after(0, lambda: self.refresh_workspace_list(silent=True))
        threading.Thread(target=_wrapped, daemon=True).start()

    def _check_cancelled(self):
        if self._cancel_requested:
            raise OperationCancelled()

    def open_edit_folder(self):
        self.dir_png.mkdir(parents=True, exist_ok=True)
        os.startfile(self.dir_png)

    def open_output_folder(self):
        self.dir_final.mkdir(parents=True, exist_ok=True)
        os.startfile(self.dir_final)

    def select_all_projects(self):
        self.archive_listbox.select_set(0, tk.END)

    def deselect_all_projects(self):
        self.archive_listbox.selection_clear(0, tk.END)

    def browse_workspace(self):
        new_dir = filedialog.askdirectory(title="Select Output Workspace Folder")
        if new_dir:
            self._set_workspace_dirs(Path(new_dir))
            self.workspace_var.set(str(self.project_root))
            self.ensure_workspace_structure()
            self.log(f"Project Workspace: {self.project_root}")
            self._save_settings()
            self.refresh_workspace_list()

    def add_source_files(self):
        files = filedialog.askopenfilenames(title="Select IWD Files", filetypes=[("IWD Archives", "*.iwd")])
        if files:
            for f in files:
                f_path = str(Path(f).resolve())
                if f_path not in self.source_iwds:
                    self.source_iwds.append(f_path)
                    self.source_listbox.insert(tk.END, f_path)
            self.log(f"Added {len(files)} items to queue.")

    def remove_source_files(self):
        indices = list(self.source_listbox.curselection())
        indices.sort(reverse=True)
        for i in indices:
            path_val = self.source_listbox.get(i)
            self.source_listbox.delete(i)
            if path_val in self.source_iwds: self.source_iwds.remove(path_val)

    def refresh_workspace_list(self, silent=False):
        selected_names = {self.archive_listbox.get(i).split("  [")[0] for i in self.archive_listbox.curselection()}
        self.archive_listbox.delete(0, tk.END)
        count = 0
        if self.dir_raw.exists():
            folders = [d for d in os.listdir(self.dir_raw) if os.path.isdir(self.dir_raw / d)]
            folders.sort()
            for f in folders:
                iwi_n = len(self._collect_files(self.dir_raw / f, '.iwi'))
                dds_n = len(self._collect_files(self.dir_dds / f, '.dds'))
                png_n = len(self._collect_files(self.dir_png / f, '.png'))
                self.archive_listbox.insert(tk.END, f"{f}  [{iwi_n} IWI · {dds_n} DDS · {png_n} PNG]")
                if f in selected_names:
                    self.archive_listbox.select_set(tk.END)
                count += 1
        if not silent:
            self.log(f"Project view refreshed: {count} archives found.")

    @staticmethod
    def _project_name_from_entry(entry_text):
        """Strip the '  [N IWI · N DDS · N PNG]' status suffix added by refresh_workspace_list."""
        return entry_text.split("  [")[0]

    # ---------------------------------------------------------------- preview

    def _on_project_selected(self, event):
        if not HAS_PIL:
            return
        indices = self.archive_listbox.curselection()
        if not indices:
            return
        name = self._project_name_from_entry(self.archive_listbox.get(indices[-1]))
        candidates = self._collect_files(self.dir_png / name, '.png') or self._collect_files(self.dir_dds / name, '.dds')
        if not candidates:
            self.preview_label.configure(image=None, text="No PNG/DDS files to preview yet")
            self._preview_ctk_image = None
            return
        try:
            with Image.open(candidates[0]) as img:
                img = img.convert("RGB")
                img.thumbnail((160, 120))
                self._preview_ctk_image = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
            self.preview_label.configure(image=self._preview_ctk_image, text="")
        except Exception as e:
            self.preview_label.configure(image=None, text=f"Preview unavailable: {e}")
            self._preview_ctk_image = None

    # ---------------------------------------------------------------- compare view

    def _get_selected_project_name(self):
        indices = self.archive_listbox.curselection()
        if not indices:
            return None
        return self._project_name_from_entry(self.archive_listbox.get(indices[-1]))

    def _find_comparable_pngs(self, name):
        """Pairs of (relative_path, original_path, current_path) for every current PNG
        that has a pre-upscale backup under .originals/. Files never upscaled have no
        backup and are not comparable."""
        current_dir = self.dir_png / name
        originals_dir = self.dir_png / FOLDER_ORIGINALS / name
        pairs = []
        for current_path in self._collect_files(current_dir, '.png'):
            rel = current_path.relative_to(current_dir)
            original_path = originals_dir / rel
            if original_path.exists():
                pairs.append((str(rel), original_path, current_path))
        return pairs

    def _open_compare_view(self):
        if not HAS_PIL:
            return self.log("Error: Pillow library not installed. Cannot compare images.")
        name = self._get_selected_project_name()
        if not name:
            return self.log("Error: Select a project to compare.")

        pairs = self._find_comparable_pngs(name)
        if not pairs:
            return self.log(f"No comparable files for {name} — upscale a PNG first to create a backup to compare against.")

        CompareWindow(self, name, pairs)

    # ---------------------------------------------------------------- operations

    @staticmethod
    def _collect_files(folder, ext):
        """Recursively find all files under `folder` with the given extension (case-insensitive),
        skipping the .originals sidecar (pre-upscale backups aren't pipeline input)."""
        if not folder.exists():
            return []
        matches = []
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if d != FOLDER_ORIGINALS]
            for f in files:
                if f.lower().endswith(ext):
                    matches.append(Path(root) / f)
        return matches

    def _run_pipeline_step(self, indices, list_source, src_dir, ext, step_label, process_fn, require_src_exists=False):
        """
        Shared driver for the four per-project conversion steps.

        For each selected project: collects files matching `ext` under src_dir/<name>,
        reports progress, and calls process_fn(project_name, src_path, idx, total) -> (ok, message)
        for each file. Returns per-project (processed_count, total_count, failures) so callers
        (e.g. the batch summary) don't have to re-walk the filesystem themselves.
        """
        results = {}
        failures = []
        try:
            for i in indices:
                name = self._project_name_from_entry(list_source.get(i))
                folder = src_dir / name

                if require_src_exists and not folder.exists():
                    self.log(f"Error: {name} source folder missing.")
                    continue

                self.log(f"{step_label}: {name}...")
                files_to_proc = self._collect_files(folder, ext)
                total = len(files_to_proc)

                if total == 0:
                    self.log(f"  (nothing to do — no matching files found for {name})")
                    results[name] = (0, 0)
                    continue

                processed = 0
                for idx, src_path in enumerate(files_to_proc):
                    self._check_cancelled()
                    self.set_progress((idx / total) * 100, f"{step_label}: {src_path.name} ({idx + 1}/{total})")
                    ok, msg = process_fn(name, folder, src_path, idx, total)
                    if ok:
                        processed += 1
                        self.log(f"  + {src_path.name}" + (f": {msg}" if msg and msg != "Success" else ""))
                    else:
                        self.log(f"  FAILED {src_path.name}: {msg}")
                        failures.append((name, src_path.name, msg))
                self.log(f"FINISHED: {name} {step_label.lower()} complete ({processed}/{total}).")
                results[name] = (processed, total)
        finally:
            self.set_progress(100, f"{step_label} complete")
            self._show_batch_summary(step_label, results, failures)
        return results

    def _show_batch_summary(self, step_label, results, failures):
        if not results:
            return
        total_processed = sum(p for p, t in results.values())
        total_files = sum(t for p, t in results.values())
        lines = [f"{step_label} finished.", f"Processed {total_processed}/{total_files} files across {len(results)} project(s)."]
        if failures:
            lines.append(f"\n{len(failures)} failure(s):")
            for proj, fname, msg in failures[:10]:
                lines.append(f"  • [{proj}] {fname}: {msg}")
            if len(failures) > 10:
                lines.append(f"  ...and {len(failures) - 10} more (see Activity Log).")
        self.root.after(0, lambda: messagebox.showinfo(
            "Batch Summary", "\n".join(lines), icon="warning" if failures else "info"
        ))

    def process_extract_queue(self):
        indices = self.source_listbox.curselection()
        if not indices: return self.log("Error: No IWDs selected in queue.")

        total_tasks = len(indices)
        try:
            for idx, i in enumerate(indices):
                self._check_cancelled()
                iwd_path = self.source_listbox.get(i)
                iwd_obj = Path(iwd_path)
                name = iwd_obj.stem
                target = self.dir_raw / name
                target.mkdir(parents=True, exist_ok=True)

                self.set_progress((idx/total_tasks)*100, f"Extracting {iwd_obj.name} ({idx+1}/{total_tasks})...")
                self.log(f"EXTRACTING: {iwd_obj.name}...")
                try:
                    with zipfile.ZipFile(iwd_path, 'r') as z:
                        iwis = [n for n in z.namelist() if n.lower().endswith('.iwi')]
                        unsafe = [n for n in iwis if self._is_unsafe_zip_member(n, target)]
                        if unsafe:
                            self.log(f"ERROR: {name} contains unsafe paths and was skipped: {unsafe[:3]}")
                            continue
                        for f in iwis: z.extract(f, target)
                    self.log(f"SUCCESS: Extracted {len(iwis)} files from {name}.")
                except Exception as e:
                    self.log(f"ERROR: Failed to extract {name}: {e}")
        finally:
            self.set_progress(100, "Extraction complete")

    @staticmethod
    def _is_unsafe_zip_member(member_name, extract_root):
        """
        Guard against Zip Slip: reject entries that would resolve outside extract_root
        once extracted (e.g. '../../evil.iwi' or an absolute path).
        """
        resolved = (extract_root / member_name).resolve()
        try:
            resolved.relative_to(extract_root.resolve())
            return False
        except ValueError:
            return True

    def step_convert_iwi_to_dds(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        exe = self.extractor_exe.get()
        if not exe: return self.log("Error: Extractor exe missing.")

        def convert(name, folder, iwi_p, idx, total):
            out = self.dir_dds / name / iwi_p.relative_to(folder).with_suffix('.dds')
            out.parent.mkdir(parents=True, exist_ok=True)
            return self.utils.run_external_converter(exe, iwi_p, out)

        self._run_pipeline_step(indices, self.archive_listbox, self.dir_raw, '.iwi', "CONVERTING IWI -> DDS", convert)

    def step_convert_dds_to_png(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        if not HAS_PIL: return self.log("Error: Pillow library not installed. Cannot convert DDS -> PNG.")

        def convert(name, folder, dds_p, idx, total):
            out = self.dir_png / name / dds_p.relative_to(folder).with_suffix('.png')
            out.parent.mkdir(parents=True, exist_ok=True)
            try:
                with Image.open(dds_p) as img:
                    img.save(out)
                return True, "Success"
            except Exception as e:
                return False, str(e)

        self._run_pipeline_step(indices, self.archive_listbox, self.dir_dds, '.dds', "CONVERTING DDS -> PNG",
                                 convert, require_src_exists=True)

    def step_convert_png_to_dds(self):
        """Reverse Conversion: PNG -> DDS (Advanced section)"""
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        exe = self.compressor_exe.get()
        if not exe: return self.log("Error: Texconv exe missing.")

        def convert(name, folder, png_p, idx, total):
            out = self.dir_dds / name / png_p.relative_to(folder).with_suffix('.dds')
            out.parent.mkdir(parents=True, exist_ok=True)
            fmt = self.utils.detect_dds_format(out) if out.exists() else 'DXT5'
            ok, msg = self.utils.run_texconv(exe, png_p, out, fmt)
            return ok, f"{msg} [{fmt}]" if ok else msg

        self._run_pipeline_step(indices, self.archive_listbox, self.dir_png, '.png', "CONVERTING PNG -> DDS",
                                 convert, require_src_exists=True)

    def step_upscale_png(self, scale=2):
        """
        Upscale the current PNGs of the selected projects in place, using the
        bundled Real-ESRGAN model. Can be run at any point in the workflow —
        right after DDS -> PNG (upscale before hand-editing) or right before
        packing (upscale finished edits). Before each file is overwritten, the
        pre-upscale version is copied to .originals/<project>/ so the Compare
        view has something to diff against later.
        """
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        if not HAS_PIL: return self.log("Error: Pillow library not installed. Cannot upscale.")
        exe = self.upscaler_exe.get()
        if not exe or not self.upscaler_model_dir:
            return self.log("Error: Upscaler exe/model missing.")

        def upscale(name, folder, png_p, idx, total):
            originals_dir = self.dir_png / FOLDER_ORIGINALS / name / png_p.relative_to(folder).parent
            originals_dir.mkdir(parents=True, exist_ok=True)
            backup_path = originals_dir / png_p.name
            if not backup_path.exists():
                shutil.copy2(png_p, backup_path)

            tmp_out = png_p.with_name(png_p.stem + f".upscaled_tmp{png_p.suffix}")
            ok, msg = self.utils.run_upscaler(exe, self.upscaler_model_dir, UPSCALER_MODEL_NAME,
                                               png_p, tmp_out, scale=scale)
            if ok:
                shutil.move(tmp_out, png_p)
            else:
                self.utils._safe_remove(tmp_out)
            return ok, msg

        self._run_pipeline_step(indices, self.archive_listbox, self.dir_png, '.png',
                                 f"UPSCALING {scale}X", upscale, require_src_exists=True)

    def step_pack_png_to_iwi_only(self):
        """Convert PNG -> IWI directly into workspace without zipping"""
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        repacker = self.repacker_exe.get()
        if not repacker: return self.log("Error: Repacker exe missing.")

        def convert(name, folder, png_p, idx, total):
            out_iwi = self.dir_raw / name / png_p.relative_to(folder).with_suffix('.iwi')
            out_iwi.parent.mkdir(parents=True, exist_ok=True)
            return self.utils.run_external_repacker(repacker, png_p, out_iwi)

        self._run_pipeline_step(indices, self.archive_listbox, self.dir_png, '.png', "PACKING PNG -> IWI", convert)

    def step_repack_png(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        repacker = self.repacker_exe.get()
        if not repacker: return self.log("Error: Repacker exe missing.")

        if not self.find_tool(DLL_LIBSQUISH):
            return self.log(f"Error: {DLL_LIBSQUISH} missing. Repacking will fail.")

        results = {}
        failures = []
        try:
            for i in indices:
                self._check_cancelled()
                name = self._project_name_from_entry(self.archive_listbox.get(i))
                folder = self.dir_png / name
                if not folder.exists(): continue

                zip_path = self.dir_final / f"{OUTPUT_IWD_PREFIX}{name}.iwd"
                if zip_path.exists():
                    should_overwrite = messagebox.askyesno(
                        "Overwrite existing archive?",
                        f"{zip_path.name} already exists in the output folder.\nOverwrite it?"
                    )
                    if not should_overwrite:
                        self.log(f"SKIPPED: {name} (output archive already exists).")
                        continue

                self.log(f"REPACKING PROJECT: {name}...")
                stage = self.dir_temp_repack / name
                if stage.exists(): shutil.rmtree(stage)
                stage.mkdir(parents=True)

                files_to_proc = self._collect_files(folder, '.png')
                total = len(files_to_proc)
                if total == 0:
                    self.log(f"ABORTED: No PNG files found for {name}.")
                    continue

                processed_count = 0
                for idx, png_path in enumerate(files_to_proc):
                    self._check_cancelled()
                    self.set_progress((idx/total)*100, f"Packing: {png_path.name} ({idx+1}/{total})")
                    rel = png_path.relative_to(folder)
                    out_iwi = stage / rel.with_suffix('.iwi')
                    out_iwi.parent.mkdir(parents=True, exist_ok=True)

                    ok, msg = self.utils.run_external_repacker(repacker, png_path, out_iwi)
                    if ok:
                        processed_count += 1
                        self.log(f"  + Success: {msg} — {png_path.name}")
                    else:
                        self.log(f"    ! FAILED: {msg} — {png_path.name}")
                        failures.append((name, png_path.name, msg))

                if processed_count > 0:
                    self.log(f"COMPILING ARCHIVE: {zip_path.name}...")
                    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
                        for s_root, _, s_files in os.walk(stage):
                            for s_file in s_files:
                                p = Path(s_root) / s_file
                                z.write(p, p.relative_to(stage))
                    self.log(f"FINALIZED: {zip_path.name} ({processed_count}/{total} textures) — game ready.")
                else:
                    self.log(f"ABORTED: No files were successfully processed for {name}.")
                results[name] = (processed_count, total)
        finally:
            self.set_progress(100, "Repack process complete")
            self._show_batch_summary("Repack to IWD", results, failures)


if __name__ == "__main__":
    saved_settings = {}
    settings_path = Path(os.path.dirname(sys.executable if getattr(sys, 'frozen', False) else os.path.abspath(__file__))) / SETTINGS_FILE
    if settings_path.exists():
        try:
            saved_settings = json.loads(settings_path.read_text())
        except (OSError, json.JSONDecodeError):
            pass
    ctk.set_appearance_mode(saved_settings.get("appearance_mode", "Light"))
    ctk.set_default_color_theme("blue")

    root = CTkDnD()
    app = MW2TextureManager(root)
    root.mainloop()
