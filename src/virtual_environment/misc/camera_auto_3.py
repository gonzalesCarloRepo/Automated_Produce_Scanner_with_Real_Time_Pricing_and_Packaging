#!/usr/bin/env python3
import os
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from picamera2 import Picamera2
from PIL import Image, ImageTk

# =========================
# EDIT THESE DEFAULTS
# =========================
DEFAULT_SAVE_DIR = "/home/jekaca/datasets/auto_capture"
DEFAULT_FILE_PREFIX = "vegetable"
DEFAULT_CAPTURE_SIZE = 720
DEFAULT_PREVIEW_SIZE = 520
DEFAULT_INTERVAL_SECONDS = 3
DEFAULT_JPEG_QUALITY = 95
DEFAULT_SAVE_FORMAT = "jpg"         # use "png" if you want lossless files
DEFAULT_ZOOM = 1.00

RESAMPLE = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS


class AutoCameraApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Camera_Ver_2 - Automatic Capture UI")
        self.root.geometry("1120x720")
        self.root.configure(bg="#1e1e1e")

        self.picam2 = None
        self.photo = None
        self.latest_frame = None
        self.base_crop = None
        self.preview_job = None
        self.auto_job = None
        self.auto_running = False
        self.capture_count = 0

        self.save_dir_var = tk.StringVar(value=DEFAULT_SAVE_DIR)
        self.prefix_var = tk.StringVar(value=DEFAULT_FILE_PREFIX)
        self.capture_size_var = tk.IntVar(value=DEFAULT_CAPTURE_SIZE)
        self.preview_size_var = tk.IntVar(value=DEFAULT_PREVIEW_SIZE)
        self.interval_var = tk.IntVar(value=DEFAULT_INTERVAL_SECONDS)
        self.quality_var = tk.IntVar(value=DEFAULT_JPEG_QUALITY)
        self.save_format_var = tk.StringVar(value=DEFAULT_SAVE_FORMAT)
        self.zoom_var = tk.DoubleVar(value=DEFAULT_ZOOM)
        self.status_var = tk.StringVar(value="Ready.")

        self._build_ui()
        self._start_camera(self.capture_size_var.get())
        self._update_preview()

        self.root.bind("<k>", self.start_auto_capture)
        self.root.bind("<s>", self.stop_auto_capture)
        self.root.bind("<q>", self.quit_app)
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)

    def _build_ui(self):
        main = tk.Frame(self.root, bg="#1e1e1e")
        main.pack(fill="both", expand=True, padx=12, pady=12)

        left = tk.Frame(main, bg="#1e1e1e")
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, bg="#2a2a2a", width=330)
        right.pack(side="right", fill="y")
        right.pack_propagate(False)

        self.preview_label = tk.Label(
            left,
            text="Starting camera...",
            bg="black",
            fg="white"
        )
        self.preview_label.pack(expand=True)

        info = tk.Label(
            left,
            text="Keys:  k = start auto capture   |   s = stop auto capture   |   q = quit",
            bg="#1e1e1e",
            fg="white",
            font=("Arial", 11)
        )
        info.pack(pady=(8, 0))

        title = tk.Label(
            right,
            text="Automatic Capture Controls",
            bg="#2a2a2a",
            fg="white",
            font=("Arial", 15, "bold")
        )
        title.pack(pady=(12, 10))

        self._add_labeled_entry(right, "Save folder", self.save_dir_var)
        ttk.Button(right, text="Browse Folder", command=self.browse_folder).pack(fill="x", padx=12, pady=(0, 10))

        self._add_labeled_entry(right, "File prefix", self.prefix_var)

        size_frame = tk.Frame(right, bg="#2a2a2a")
        size_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(size_frame, text="Capture size (square)", bg="#2a2a2a", fg="white").pack(anchor="w")
        ttk.Combobox(
            size_frame,
            textvariable=self.capture_size_var,
            values=[196, 320, 480, 640, 720, 960, 1080],
            state="readonly"
        ).pack(fill="x", pady=(4, 0))
        ttk.Button(size_frame, text="Apply Resolution", command=self.apply_resolution).pack(fill="x", pady=(6, 0))

        interval_frame = tk.Frame(right, bg="#2a2a2a")
        interval_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(interval_frame, text="Auto capture interval (seconds)", bg="#2a2a2a", fg="white").pack(anchor="w")
        tk.Spinbox(interval_frame, from_=1, to=3600, textvariable=self.interval_var, width=8).pack(anchor="w", pady=(4, 0))

        quality_frame = tk.Frame(right, bg="#2a2a2a")
        quality_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(quality_frame, text="JPEG quality", bg="#2a2a2a", fg="white").pack(anchor="w")
        tk.Scale(
            quality_frame,
            from_=50, to=100,
            orient="horizontal",
            variable=self.quality_var,
            bg="#2a2a2a",
            fg="white",
            highlightthickness=0
        ).pack(fill="x")

        fmt_frame = tk.Frame(right, bg="#2a2a2a")
        fmt_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(fmt_frame, text="Save format", bg="#2a2a2a", fg="white").pack(anchor="w")
        ttk.Combobox(
            fmt_frame,
            textvariable=self.save_format_var,
            values=["jpg", "png"],
            state="readonly"
        ).pack(fill="x", pady=(4, 0))

        preview_frame = tk.Frame(right, bg="#2a2a2a")
        preview_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(preview_frame, text="Live preview size in UI", bg="#2a2a2a", fg="white").pack(anchor="w")
        tk.Scale(
            preview_frame,
            from_=280, to=820,
            orient="horizontal",
            variable=self.preview_size_var,
            bg="#2a2a2a",
            fg="white",
            highlightthickness=0
        ).pack(fill="x")

        zoom_frame = tk.Frame(right, bg="#2a2a2a")
        zoom_frame.pack(fill="x", padx=12, pady=6)
        tk.Label(zoom_frame, text="Zoom", bg="#2a2a2a", fg="white").pack(anchor="w")

        btns = tk.Frame(zoom_frame, bg="#2a2a2a")
        btns.pack(fill="x", pady=(4, 4))
        ttk.Button(btns, text="-", command=lambda: self.adjust_zoom(-0.05)).pack(side="left", fill="x", expand=True, padx=(0, 4))
        ttk.Button(btns, text="+", command=lambda: self.adjust_zoom(0.05)).pack(side="left", fill="x", expand=True, padx=(4, 0))

        tk.Scale(
            zoom_frame,
            from_=1.00, to=4.00,
            resolution=0.05,
            orient="horizontal",
            variable=self.zoom_var,
            command=lambda _=None: self.apply_zoom(),
            bg="#2a2a2a",
            fg="white",
            highlightthickness=0
        ).pack(fill="x")

        ttk.Button(right, text="Reset Zoom", command=self.reset_zoom).pack(fill="x", padx=12, pady=(6, 12))

        ttk.Button(right, text="Start Auto Capture", command=self.start_auto_capture).pack(fill="x", padx=12, pady=6)
        ttk.Button(right, text="Stop Auto Capture", command=self.stop_auto_capture).pack(fill="x", padx=12, pady=6)
        ttk.Button(right, text="Quit", command=self.quit_app).pack(fill="x", padx=12, pady=6)

        status_title = tk.Label(right, text="Status", bg="#2a2a2a", fg="white", font=("Arial", 12, "bold"))
        status_title.pack(anchor="w", padx=12, pady=(10, 2))

        self.status_label = tk.Label(
            right,
            textvariable=self.status_var,
            bg="#2a2a2a",
            fg="#dddddd",
            justify="left",
            wraplength=290
        )
        self.status_label.pack(fill="x", padx=12, pady=(0, 12))

    def _add_labeled_entry(self, parent, label_text, text_var):
        frame = tk.Frame(parent, bg="#2a2a2a")
        frame.pack(fill="x", padx=12, pady=6)
        tk.Label(frame, text=label_text, bg="#2a2a2a", fg="white").pack(anchor="w")
        tk.Entry(frame, textvariable=text_var).pack(fill="x", pady=(4, 0))

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.save_dir_var.get() or "/home")
        if folder:
            self.save_dir_var.set(folder)

    def choose_largest_raw_size(self, picam2):
        try:
            modes = getattr(picam2, "sensor_modes", [])
            if not modes:
                return None
            best = max(
                [m for m in modes if "size" in m],
                key=lambda m: m["size"][0] * m["size"][1]
            )
            return best["size"]
        except Exception:
            return None

    def _start_camera(self, square_size):
        self._stop_camera()

        self.picam2 = Picamera2()
        raw_size = self.choose_largest_raw_size(self.picam2)

        config_kwargs = {
            "main": {"size": (square_size, square_size), "format": "RGB888"},
            "buffer_count": 4
        }

        if raw_size:
            config_kwargs["raw"] = {"size": raw_size}

        config = self.picam2.create_video_configuration(**config_kwargs)
        self.picam2.configure(config)
        self.picam2.start()

        time.sleep(0.4)
        self.base_crop = tuple(self.picam2.capture_metadata()["ScalerCrop"])
        self.apply_zoom()
        self.status_var.set(f"Camera started at {square_size}x{square_size}.")

    def _stop_camera(self):
        if self.picam2 is not None:
            try:
                self.picam2.stop()
            except Exception:
                pass
            try:
                self.picam2.close()
            except Exception:
                pass
            self.picam2 = None

    def apply_resolution(self):
        try:
            size = int(self.capture_size_var.get())
            if size < 64:
                raise ValueError
            self._start_camera(size)
        except Exception:
            messagebox.showerror("Invalid size", "Please enter a valid square size like 720.")

    def reset_zoom(self):
        self.zoom_var.set(1.00)
        self.apply_zoom()

    def adjust_zoom(self, delta):
        new_value = round(self.zoom_var.get() + delta, 2)
        new_value = min(4.00, max(1.00, new_value))
        self.zoom_var.set(new_value)
        self.apply_zoom()

    def apply_zoom(self):
        if self.picam2 is None or self.base_crop is None:
            return

        bx, by, bw, bh = self.base_crop
        zoom = max(1.00, float(self.zoom_var.get()))

        new_w = int(bw / zoom)
        new_h = int(bh / zoom)

        new_w -= (new_w % 2)
        new_h -= (new_h % 2)

        x = bx + (bw - new_w) // 2
        y = by + (bh - new_h) // 2

        x -= (x % 2)
        y -= (y % 2)

        self.picam2.set_controls({"ScalerCrop": (x, y, new_w, new_h)})
        self.status_var.set(f"Zoom set to {zoom:.2f}x.")

    def _update_preview(self):
        try:
            if self.picam2 is not None:
                frame = self.picam2.capture_array("main")
                self.latest_frame = frame.copy()

                image = Image.fromarray(frame)
                preview_side = int(self.preview_size_var.get())
                image = image.resize((preview_side, preview_side), RESAMPLE)

                self.photo = ImageTk.PhotoImage(image=image)
                self.preview_label.configure(image=self.photo, text="", width=preview_side, height=preview_side)
        except Exception as e:
            self.status_var.set(f"Preview error: {e}")

        self.preview_job = self.root.after(40, self._update_preview)

    def start_auto_capture(self, event=None):
        if self.auto_running:
            return
        self.auto_running = True
        self.capture_count = 0
        interval = max(1, int(self.interval_var.get()))
        self._run_auto_cycle(interval)

    def _run_auto_cycle(self, remaining):
        if not self.auto_running:
            return

        if remaining > 0:
            self.status_var.set(f"Auto mode ON. Next capture in {remaining} second(s)...")
            self.auto_job = self.root.after(1000, lambda: self._run_auto_cycle(remaining - 1))
        else:
            self.save_current_frame()
            next_interval = max(1, int(self.interval_var.get()))
            self.auto_job = self.root.after(10, lambda: self._run_auto_cycle(next_interval))

    def stop_auto_capture(self, event=None):
        self.auto_running = False
        try:
            if self.auto_job:
                self.root.after_cancel(self.auto_job)
        except Exception:
            pass
        self.auto_job = None
        self.status_var.set("Auto capture stopped.")

    def save_current_frame(self):
        if self.latest_frame is None:
            self.status_var.set("No frame available yet.")
            return

        save_dir = self.save_dir_var.get().strip()
        prefix = self.prefix_var.get().strip() or "image"
        fmt = self.save_format_var.get().strip().lower()
        quality = int(self.quality_var.get())

        if fmt not in ("jpg", "jpeg", "png"):
            fmt = "jpg"

        os.makedirs(save_dir, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        self.capture_count += 1
        filename = f"{prefix}_{timestamp}_{self.capture_count:04d}.{fmt}"
        path = os.path.join(save_dir, filename)

        image = Image.fromarray(self.latest_frame)

        if fmt in ("jpg", "jpeg"):
            image.save(path, quality=quality, subsampling=0)
        else:
            image.save(path)

        self.status_var.set(f"Saved #{self.capture_count}: {path}")

    def quit_app(self, event=None):
        self.stop_auto_capture()

        try:
            if self.preview_job:
                self.root.after_cancel(self.preview_job)
        except Exception:
            pass

        self._stop_camera()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = AutoCameraApp(root)
    root.mainloop()