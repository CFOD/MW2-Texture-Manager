import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
import os
import shutil
import zipfile
import struct
import threading
import subprocess
import sys
import uuid
from pathlib import Path

# Check for Pillow
try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

class IwiUtils:
    def run_external_converter(self, exe_path, iwi_path, dds_output_path):
        """Runs iwi2dds.exe (Extracts IWI -> DDS)"""
        try:
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

            cmd = [exe_path, '-i', str(iwi_path), '-o', str(dds_output_path)]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=15)
            except subprocess.TimeoutExpired:
                return False, "Timed out (15s)"

            if os.path.exists(dds_output_path): return True, "Success"

            # Fallback syntax check
            cmd_simple = [exe_path, str(iwi_path)]
            try:
                subprocess.run(cmd_simple, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, startupinfo=startupinfo, timeout=15)
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
                    timeout=20
                )
            except subprocess.TimeoutExpired as e:
                if os.path.exists(local_input_path):
                    try: os.remove(local_input_path)
                    except: pass
                return False, f"TIMEOUT (20s): Repacker hung on this file. Output: {e.stdout}"

            # Cleanup input
            if os.path.exists(local_input_path):
                try: os.remove(local_input_path)
                except: pass

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
                result = subprocess.run(cmd, capture_output=True, text=True, startupinfo=startupinfo, timeout=15)
            except subprocess.TimeoutExpired:
                return False, "Texconv Timed Out (15s)"

            actual_out = Path(dds_path).with_name(Path(png_path).stem + ".dds")
            if actual_out.exists():
                if actual_out != Path(dds_path):
                    shutil.move(actual_out, dds_path)
                return True, "Success"
            return False, result.stderr or "Texconv failed to produce output"
        except Exception as e:
            return False, str(e)


# --- GUI Application ---
class MW2TextureManager:
    def __init__(self, root):
        self.root = root
        self.root.title("MW2 Texture Manager")
        self.root.geometry("820x860")

        if getattr(sys, 'frozen', False):
            app_path = os.path.dirname(sys.executable)
        else:
            app_path = os.path.dirname(os.path.abspath(__file__))

        self.project_root = Path(app_path) / "MW2_Project"

        self.dir_raw = self.project_root / "01_IWI"
        self.dir_dds = self.project_root / "02_DDS"
        self.dir_png = self.project_root / "03_PNG"
        self.dir_final = self.project_root / "04_Output"
        self.dir_temp_repack = self.project_root / ".repack_temp"

        self.source_iwds = []
        self._busy = False
        self._async_buttons = []
        self.utils = IwiUtils()

        self.extractor_exe = tk.StringVar()
        self.repacker_exe = tk.StringVar()
        self.compressor_exe = tk.StringVar()
        self.workspace_var = tk.StringVar(value=str(self.project_root))

        self.extractor_exe.set(self.find_tool("iwi2dds.exe"))
        self.repacker_exe.set(self.find_tool("imgXiwi.exe"))
        self.compressor_exe.set(self.find_tool("texconv.exe"))

        self.setup_ui()
        self.ensure_workspace_structure()
        self.root.after(200, self.refresh_workspace_list)

        icon_path = self.find_tool("icon.ico")
        if icon_path:
            try: self.root.iconbitmap(icon_path)
            except: pass

        if not HAS_PIL:
            messagebox.showwarning("Dependency Error", "Pillow library missing.\nImages cannot be processed.")

    def find_tool(self, name):
        bundled = self.resource_path(name)
        if os.path.exists(bundled): return bundled
        if os.path.exists(name): return os.path.abspath(name)
        return ""

    def resource_path(self, relative_path):
        try: base_path = sys._MEIPASS
        except Exception: base_path = os.path.abspath(".")
        return os.path.join(base_path, relative_path)

    def ensure_workspace_structure(self):
        if not self.project_root.exists(): self.project_root.mkdir(parents=True)
        if not self.dir_raw.exists(): self.dir_raw.mkdir(parents=True)
        if not self.dir_dds.exists(): self.dir_dds.mkdir(parents=True)
        if not self.dir_png.exists(): self.dir_png.mkdir(parents=True)
        if not self.dir_final.exists(): self.dir_final.mkdir(parents=True)

    def setup_ui(self):
        self._async_buttons = []
        self.root.columnconfigure(0, weight=1)

        # --- Header ---
        frame_top = tk.Frame(self.root, pady=5)
        frame_top.pack(fill="x", padx=10)
        tk.Label(frame_top, text="MW2 Texture Manager", font=("Segoe UI", 12, "bold")).pack(side="left")

        status_frame = tk.Frame(frame_top)
        status_frame.pack(side="right")

        def status_lbl(name, var):
            found = bool(var.get())
            color = "#2e7d32" if found else "#c62828"
            txt = "✓" if found else "MISSING"
            tk.Label(status_frame, text=f"{name}: {txt}", fg=color, font=("Segoe UI", 9, "bold"), padx=5).pack(side="left")

        status_lbl("Extractor", self.extractor_exe)
        status_lbl("Compressor", self.compressor_exe)
        status_lbl("Repacker", self.repacker_exe)

        # --- Workspace row ---
        frame_proj = tk.Frame(self.root)
        frame_proj.pack(fill="x", padx=10, pady=(0, 5))
        tk.Label(frame_proj, text="Workspace:").pack(side="left")
        tk.Entry(frame_proj, textvariable=self.workspace_var, state='readonly').pack(side="left", fill="x", expand=True, padx=5)
        tk.Button(frame_proj, text="Change...", command=self.browse_workspace).pack(side="left")

        # --- Paned main ---
        paned_main = tk.PanedWindow(self.root, orient=tk.VERTICAL)
        paned_main.pack(fill="both", expand=True, padx=10, pady=5)

        # 1. SOURCE QUEUE
        frame_source = tk.LabelFrame(paned_main, text="1. Source Queue", padx=5, pady=5)
        paned_main.add(frame_source, height=160)
        source_toolbar = tk.Frame(frame_source)
        source_toolbar.pack(fill="x", pady=(0, 5))
        tk.Button(source_toolbar, text="+ Add IWD Files...", command=self.add_source_files, bg="#e1f5fe").pack(side="left")
        tk.Button(source_toolbar, text="- Remove Selected", command=self.remove_source_files).pack(side="left", padx=5)
        b = tk.Button(source_toolbar, text="Extract Selected ->",
                      command=lambda: self.run_async(self.process_extract_queue),
                      bg="#b2dfdb", font=("Segoe UI", 9, "bold"))
        b.pack(side="right")
        self._async_buttons.append(b)

        self.source_listbox = tk.Listbox(frame_source, selectmode=tk.MULTIPLE)
        self.source_listbox.pack(side="left", fill="both", expand=True)

        # 2. WORKSPACE MANAGER
        frame_work = tk.LabelFrame(paned_main, text="2. Workspace Projects", padx=5, pady=5)
        paned_main.add(frame_work, height=300)
        work_split = tk.PanedWindow(frame_work, orient=tk.HORIZONTAL)
        work_split.pack(fill="both", expand=True)

        # Project list + Select All / None
        list_frame = tk.Frame(work_split)
        self.archive_listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, exportselection=False)
        self.archive_listbox.pack(fill="both", expand=True)
        sel_frame = tk.Frame(list_frame)
        sel_frame.pack(fill='x', pady=(2, 0))
        tk.Button(sel_frame, text="Select All",  command=self.select_all_projects,  font=("Segoe UI", 8)).pack(side='left', fill='x', expand=True)
        tk.Button(sel_frame, text="Select None", command=self.deselect_all_projects, font=("Segoe UI", 8)).pack(side='left', fill='x', expand=True)
        work_split.add(list_frame, width=300)

        # Operation buttons
        btn_frame = tk.Frame(work_split, padx=4)
        b_width = 28

        def section_sep(label_text):
            tk.Frame(btn_frame, height=1, bg="#cccccc").pack(fill='x', pady=(10, 0))
            tk.Label(btn_frame, text=label_text, fg="#888888", font=("Segoe UI", 8, "italic")).pack(pady=(2, 4))

        section_sep("— Extract —")
        b = tk.Button(btn_frame, text="Convert IWI -> DDS", command=lambda: self.run_async(self.step_convert_iwi_to_dds), width=b_width)
        b.pack(pady=2); self._async_buttons.append(b)
        b = tk.Button(btn_frame, text="Convert DDS -> PNG", command=lambda: self.run_async(self.step_convert_dds_to_png), width=b_width)
        b.pack(pady=2); self._async_buttons.append(b)

        section_sep("— Repack —")
        b = tk.Button(btn_frame, text="Convert PNG -> IWI", command=lambda: self.run_async(self.step_pack_png_to_iwi_only), width=b_width)
        b.pack(pady=2); self._async_buttons.append(b)

        # Open folder shortcuts (side by side)
        open_frame = tk.Frame(btn_frame)
        open_frame.pack(fill='x', pady=(10, 2))
        tk.Button(open_frame, text="PNG Folder",    command=self.open_edit_folder,   bg="#fff9c4").pack(side='left', fill='x', expand=True, padx=(0, 2))
        tk.Button(open_frame, text="Output Folder", command=self.open_output_folder, bg="#fff9c4").pack(side='left', fill='x', expand=True, padx=(2, 0))

        b = tk.Button(btn_frame, text="Repack to IWD", command=lambda: self.run_async(self.step_repack_png), bg="#c8e6c9", width=b_width)
        b.pack(pady=2); self._async_buttons.append(b)

        work_split.add(btn_frame)

        # --- Progress ---
        frame_bottom = tk.Frame(self.root)
        frame_bottom.pack(fill="x", padx=10, pady=5)
        self.progress_var = tk.DoubleVar()
        self.progress_bar = ttk.Progressbar(frame_bottom, variable=self.progress_var, maximum=100)
        self.progress_bar.pack(fill="x", pady=(0, 5))
        self.progress_label = tk.Label(frame_bottom, text="Idle", font=("Segoe UI", 8))
        self.progress_label.pack(anchor="w")

        # --- Log ---
        frame_log = tk.LabelFrame(self.root, text="Activity Log", padx=5, pady=5)
        frame_log.pack(fill="both", expand=True, padx=10, pady=5)
        log_toolbar = tk.Frame(frame_log)
        log_toolbar.pack(fill='x', pady=(0, 3))
        tk.Button(log_toolbar, text="Clear Log", command=self.clear_log, font=("Segoe UI", 8)).pack(side='right')
        self.log_text = scrolledtext.ScrolledText(frame_log, state='disabled', font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

        # Color tags for log entries
        self.log_text.tag_config('error',   foreground='#c62828')
        self.log_text.tag_config('success', foreground='#2e7d32')
        self.log_text.tag_config('action',  foreground='#1565c0')
        self.log_text.tag_config('normal',  foreground='#212121')

    # ------------------------------------------------------------------ helpers

    def log(self, msg):
        self.root.after(0, self._log_safe, msg)

    def _log_safe(self, msg):
        self.log_text.config(state='normal')
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
        self.log_text.insert(tk.END, f"> {msg}\n", tag)
        self.log_text.see(tk.END)
        self.log_text.config(state='disabled')

    def clear_log(self):
        self.log_text.config(state='normal')
        self.log_text.delete('1.0', tk.END)
        self.log_text.config(state='disabled')

    def set_progress(self, value, text=None):
        self.root.after(0, self._update_progress, value, text)

    def _update_progress(self, value, text):
        self.progress_var.set(value)
        if text: self.progress_label.config(text=text)

    def _set_buttons_state(self, state):
        for btn in self._async_buttons:
            try: btn.config(state=state)
            except: pass

    def run_async(self, target):
        if self._busy:
            self.log("Error: An operation is already running. Please wait.")
            return
        self._set_buttons_state('disabled')
        def _wrapped():
            self._busy = True
            try:
                target()
            finally:
                self._busy = False
                self.root.after(0, self._set_buttons_state, 'normal')
                self.root.after(0, lambda: self.refresh_workspace_list(silent=True))
        threading.Thread(target=_wrapped, daemon=True).start()

    def open_edit_folder(self):
        if not self.dir_png.exists(): self.dir_png.mkdir(parents=True)
        os.startfile(self.dir_png)

    def open_output_folder(self):
        if not self.dir_final.exists(): self.dir_final.mkdir(parents=True)
        os.startfile(self.dir_final)

    def select_all_projects(self):
        self.archive_listbox.select_set(0, tk.END)

    def deselect_all_projects(self):
        self.archive_listbox.selection_clear(0, tk.END)

    def browse_workspace(self):
        new_dir = filedialog.askdirectory(title="Select Output Workspace Folder")
        if new_dir:
            self.project_root = Path(new_dir)
            self.dir_raw = self.project_root / "01_IWI"
            self.dir_dds = self.project_root / "02_DDS"
            self.dir_png = self.project_root / "03_PNG"
            self.dir_final = self.project_root / "04_Output"
            self.dir_temp_repack = self.project_root / ".repack_temp"
            self.workspace_var.set(str(self.project_root))
            self.ensure_workspace_structure()
            self.log(f"Project Workspace: {self.project_root}")
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
        self.archive_listbox.delete(0, tk.END)
        count = 0
        if self.dir_raw.exists():
            folders = [d for d in os.listdir(self.dir_raw) if os.path.isdir(self.dir_raw / d)]
            folders.sort()
            for f in folders:
                self.archive_listbox.insert(tk.END, f)
                count += 1
        if not silent:
            self.log(f"Project view refreshed: {count} archives found.")

    # ---------------------------------------------------------------- operations

    def process_extract_queue(self):
        indices = self.source_listbox.curselection()
        if not indices: return self.log("Error: No IWDs selected in queue.")

        total_tasks = len(indices)
        for idx, i in enumerate(indices):
            iwd_path = self.source_listbox.get(i)
            iwd_obj = Path(iwd_path)
            name = iwd_obj.stem
            target = self.dir_raw / name
            if not target.exists(): target.mkdir(parents=True)

            self.set_progress((idx/total_tasks)*100, f"Extracting {iwd_obj.name} ({idx+1}/{total_tasks})...")
            self.log(f"EXTRACTING: {iwd_obj.name}...")
            try:
                with zipfile.ZipFile(iwd_path, 'r') as z:
                    iwis = [n for n in z.namelist() if n.lower().endswith('.iwi')]
                    for f in iwis: z.extract(f, target)
                self.log(f"SUCCESS: Extracted {len(iwis)} files from {name}.")
            except Exception as e:
                self.log(f"ERROR: Failed to extract {name}: {e}")

        self.set_progress(100, "Extraction complete")

    def step_convert_iwi_to_dds(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        exe = self.extractor_exe.get()
        if not exe: return self.log("Error: Extractor exe missing.")

        for i in indices:
            name = self.archive_listbox.get(i)
            folder = self.dir_raw / name
            self.log(f"CONVERTING IWI -> DDS: {name}...")

            files_to_proc = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.iwi'): files_to_proc.append(Path(root) / f)
            total = len(files_to_proc)

            for idx, iwi_p in enumerate(files_to_proc):
                self.set_progress((idx/total)*100, f"IWI -> DDS: {iwi_p.name} ({idx+1}/{total})")
                out = self.dir_dds / name / iwi_p.relative_to(folder).with_suffix('.dds')
                out.parent.mkdir(parents=True, exist_ok=True)

                ok, msg = self.utils.run_external_converter(exe, iwi_p, out)
                if ok: self.log(f"  + {iwi_p.name}")
                else: self.log(f"  FAILED {iwi_p.name}: {msg}")
            self.log(f"FINISHED: {name} IWI -> DDS complete.")
        self.set_progress(100, "IWI to DDS conversion complete")

    def step_convert_dds_to_png(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        if not HAS_PIL: return self.log("Error: Pillow library not installed. Cannot convert DDS -> PNG.")

        for i in indices:
            name = self.archive_listbox.get(i)
            folder = self.dir_dds / name
            if not folder.exists():
                self.log(f"Error: {name} DDS folder missing.")
                continue

            self.log(f"CONVERTING DDS -> PNG: {name}...")
            files_to_proc = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.dds'): files_to_proc.append(Path(root) / f)

            total = len(files_to_proc)
            for idx, dds_p in enumerate(files_to_proc):
                self.set_progress((idx/total)*100, f"DDS -> PNG: {dds_p.name} ({idx+1}/{total})")
                out = self.dir_png / name / dds_p.relative_to(folder).with_suffix('.png')
                out.parent.mkdir(parents=True, exist_ok=True)
                try:
                    with Image.open(dds_p) as img: img.save(out)
                    self.log(f"  + {dds_p.name}")
                except Exception as e:
                    self.log(f"  FAILED {dds_p.name}: {e}")
            self.log(f"FINISHED: {name} DDS -> PNG complete.")
        self.set_progress(100, "DDS to PNG conversion complete")

    def step_convert_png_to_dds(self):
        """Reverse Conversion: PNG -> DDS (advanced / not exposed in main UI)"""
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        exe = self.compressor_exe.get()
        if not exe: return self.log("Error: Texconv exe missing.")

        for i in indices:
            name = self.archive_listbox.get(i)
            folder = self.dir_png / name
            if not folder.exists(): continue

            self.log(f"CONVERTING PNG -> DDS: {name}...")
            files_to_proc = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.png'): files_to_proc.append(Path(root) / f)

            total = len(files_to_proc)
            for idx, png_p in enumerate(files_to_proc):
                self.set_progress((idx/total)*100, f"PNG -> DDS: {png_p.name} ({idx+1}/{total})")
                out = self.dir_dds / name / png_p.relative_to(folder).with_suffix('.dds')
                out.parent.mkdir(parents=True, exist_ok=True)

                fmt = self.utils.detect_dds_format(out) if out.exists() else 'DXT5'
                ok, msg = self.utils.run_texconv(exe, png_p, out, fmt)
                if ok: self.log(f"  + {png_p.name} [{fmt}]")
                else: self.log(f"  FAILED {png_p.name}: {msg}")
            self.log(f"FINISHED: {name} PNG -> DDS complete.")
        self.set_progress(100, "PNG to DDS conversion complete")

    def step_pack_png_to_iwi_only(self):
        """Convert PNG -> IWI directly into workspace without zipping"""
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        repacker = self.repacker_exe.get()
        if not repacker: return self.log("Error: Repacker exe missing.")

        for i in indices:
            name = self.archive_listbox.get(i)
            folder = self.dir_png / name
            self.log(f"PACKING PNG -> IWI: {name}...")

            files_to_proc = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.png'): files_to_proc.append(Path(root) / f)

            total = len(files_to_proc)
            for idx, png_p in enumerate(files_to_proc):
                self.set_progress((idx/total)*100, f"PNG -> IWI: {png_p.name} ({idx+1}/{total})")
                out_iwi = self.dir_raw / name / png_p.relative_to(folder).with_suffix('.iwi')
                out_iwi.parent.mkdir(parents=True, exist_ok=True)

                ok, msg = self.utils.run_external_repacker(repacker, png_p, out_iwi)
                if ok:
                    self.log(f"  + Success: {msg} — {png_p.name}")
                else:
                    self.log(f"  ERROR {png_p.name}: {msg}")
            self.log(f"FINISHED: {name} IWI pack complete.")
        self.set_progress(100, "PNG to IWI pack complete")

    def step_repack_png(self):
        indices = self.archive_listbox.curselection()
        if not indices: return self.log("Error: No projects selected.")
        repacker = self.repacker_exe.get()
        if not repacker: return self.log("Error: Repacker exe missing.")

        if not os.path.exists("libsquish.dll") and not self.find_tool("libsquish.dll"):
            return self.log("Error: libsquish.dll missing. Repacking will fail.")

        for i in indices:
            name = self.archive_listbox.get(i)
            folder = self.dir_png / name
            if not folder.exists(): continue

            self.log(f"REPACKING PROJECT: {name}...")
            stage = self.dir_temp_repack / name
            if stage.exists(): shutil.rmtree(stage)
            stage.mkdir(parents=True)

            files_to_proc = []
            for root, _, files in os.walk(folder):
                for f in files:
                    if f.lower().endswith('.png'): files_to_proc.append(Path(root) / f)

            total = len(files_to_proc)
            processed_count = 0
            for idx, png_path in enumerate(files_to_proc):
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

            if processed_count > 0:
                zip_path = self.dir_final / f"z_{name}.iwd"
                self.log(f"COMPILING ARCHIVE: {zip_path.name}...")
                with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
                    for s_root, _, s_files in os.walk(stage):
                        for s_file in s_files:
                            p = Path(s_root) / s_file
                            z.write(p, p.relative_to(stage))
                self.log(f"FINALIZED: {zip_path.name} ({processed_count}/{total} textures) — game ready.")
            else:
                self.log(f"ABORTED: No files were successfully processed for {name}.")
        self.set_progress(100, "Repack process complete")


if __name__ == "__main__":
    root = tk.Tk()
    app = MW2TextureManager(root)
    root.mainloop()
