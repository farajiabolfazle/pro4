# -*- coding: utf-8 -*-
"""
VCam Injector - Advanced Windows Controller
Features: video preview player, seek bar, play/pause, speed 0.25x-4x,
mouse-wheel zoom, draggable always-on-top PiP window, USB/ADB management,
live sync of playback controls to the phone via control.json.

Requires: pip install opencv-python pillow ; adb (platform-tools) in PATH.
Phone: USB debugging enabled, connected by cable, rooted (Magisk).
"""
import json
import subprocess
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

import cv2
from PIL import Image, ImageTk

VCAM_DIR = "/sdcard/vcam"
VIDEO_PATH = VCAM_DIR + "/video.mp4"
CONFIG_PATH = VCAM_DIR + "/config.json"
CONTROL_PATH = VCAM_DIR + "/control.json"


def adb(*args, timeout=120):
    try:
        return subprocess.run(["adb"] + list(args), capture_output=True,
                              text=True, timeout=timeout)
    except Exception as e:
        r = subprocess.CompletedProcess(args, 1)
        r.stdout = ""
        r.stderr = str(e)
        return r


def fmt(sec):
    sec = max(int(sec), 0)
    return "%02d:%02d" % (sec // 60, sec % 60)


class Pip(tk.Toplevel):
    """Small draggable always-on-top preview window."""

    def __init__(self, master):
        super().__init__(master)
        self.attributes("-topmost", True)
        self.title("PiP")
        self.geometry("320x180+80+80")
        self.lbl = tk.Label(self, bg="black")
        self.lbl.pack(fill="both", expand=True)
        self._imgtk = None
        self._dx = self._dy = 0
        self.lbl.bind("<Button-1>", self._grab)
        self.lbl.bind("<B1-Motion>", self._drag)
        self.protocol("WM_DELETE_WINDOW", master.toggle_pip)

    def _grab(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag(self, e):
        self.geometry("+%d+%d" % (self.winfo_x() + e.x - self._dx,
                                  self.winfo_y() + e.y - self._dy))

    def show(self, pil_img):
        img = pil_img.copy()
        img.thumbnail((340, 340))
        self._imgtk = ImageTk.PhotoImage(img)
        self.lbl.config(image=self._imgtk)


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("VCam Injector - Advanced Controller")
        self.geometry("980x760")

        # --- player state ---
        self.cap = None
        self.video_file = None
        self.fps = 25.0
        self.frames = 0
        self.playing = False
        self.speed = 1.0
        self.zoom = 1.0
        self.pip = None
        self._seek_lock = False
        self._sync_job = None
        self._imgtk = None

        # --- preview ---
        self.preview = tk.Label(self, bg="black")
        self.preview.pack(fill="both", expand=True, padx=8, pady=(8, 2))
        self.preview.bind("<MouseWheel>", self.on_wheel)

        # --- transport controls ---
        tr = tk.Frame(self)
        tr.pack(fill="x", padx=8)
        tk.Button(tr, text="Select video", command=self.open_video).pack(side="left")
        self.btn_play = tk.Button(tr, text="Play", width=8,
                                  command=self.toggle_play)
        self.btn_play.pack(side="left", padx=4)
        self.time_lbl = tk.Label(tr, text="00:00 / 00:00")
        self.time_lbl.pack(side="left", padx=6)
        tk.Button(tr, text="PiP", command=self.toggle_pip).pack(side="left", padx=4)
        tk.Label(tr, text="Speed").pack(side="left", padx=(14, 2))
        self.speed_scale = tk.Scale(tr, from_=25, to=400, resolution=25,
                                    orient="horizontal", length=150,
                                    showvalue=True, command=self.on_speed)
        self.speed_scale.set(100)
        self.speed_scale.pack(side="left")
        tk.Label(tr, text="%").pack(side="left")
        tk.Label(tr, text="  zoom: mouse wheel", fg="gray").pack(side="left", padx=8)

        # --- seek bar ---
        self.seek_var = tk.IntVar(value=0)
        self.seek = tk.Scale(self, from_=0, to=1000, orient="horizontal",
                             showvalue=False, variable=self.seek_var,
                             command=self.on_seek)
        self.seek.pack(fill="x", padx=8)

        # --- phone / adb ---
        af = tk.LabelFrame(self, text="Phone over USB (ADB)")
        af.pack(fill="x", padx=8, pady=6)
        tk.Button(af, text="Check device + root",
                  command=self.check_device).pack(side="left", padx=4, pady=4)
        tk.Button(af, text="Push video", command=self.push_video).pack(side="left", padx=4)
        tk.Button(af, text="START injection", bg="#2e7d32", fg="white",
                  command=lambda: self.set_enabled(True)).pack(side="left", padx=4)
        tk.Button(af, text="STOP", bg="#c62828", fg="white",
                  command=lambda: self.set_enabled(False)).pack(side="left", padx=4)
        tk.Label(af, text="pkg:").pack(side="left")
        self.ent_pkg = tk.Entry(af, width=24)
        self.ent_pkg.insert(0, "com.android.camera")
        self.ent_pkg.pack(side="left", padx=2)
        tk.Button(af, text="Restart app",
                  command=self.restart_target).pack(side="left", padx=4)
        self.sync_var = tk.BooleanVar(value=True)
        tk.Checkbutton(af, text="Sync controls to phone",
                       variable=self.sync_var).pack(side="left", padx=8)

        # --- log ---
        self.log = scrolledtext.ScrolledText(self, height=8, state="disabled")
        self.log.pack(fill="both", padx=8, pady=(0, 8))

        self.after(100, self.tick)
        self.check_device()

    # ---------------- helpers ----------------

    def write_log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run_bg(self, fn):
        threading.Thread(target=fn, daemon=True).start()

    # ---------------- player ----------------

    def open_video(self):
        f = filedialog.askopenfilename(
            filetypes=[("Video", "*.mp4 *.mkv *.webm *.mov *.avi"),
                       ("All", "*.*")])
        if not f:
            return
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(f)
        if not self.cap.isOpened():
            messagebox.showerror("VCam", "Cannot open this video file.")
            self.cap = None
            return
        self.video_file = f
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        self.frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.seek.config(to=max(self.frames - 1, 1))
        self.playing = True
        self.btn_play.config(text="Pause")
        self.write_log("opened: " + f)
        self.schedule_sync()

    def toggle_play(self):
        if self.cap is None:
            return
        self.playing = not self.playing
        self.btn_play.config(text="Pause" if self.playing else "Play")
        self.schedule_sync()

    def on_seek(self, v):
        if self._seek_lock or self.cap is None:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, int(v))
        self.schedule_sync()

    def on_speed(self, v):
        self.speed = max(int(v) / 100.0, 0.05)
        self.schedule_sync()

    def on_wheel(self, e):
        self.zoom *= 1.15 if e.delta > 0 else 1 / 1.15
        self.zoom = min(max(self.zoom, 0.3), 5.0)
        self.render_current()

    def toggle_pip(self):
        if self.pip and self.pip.winfo_exists():
            self.pip.destroy()
            self.pip = None
        else:
            self.pip = Pip(self)

    def tick(self):
        try:
            if self.cap is not None and self.playing:
                ok, frame = self.cap.read()
                if not ok:
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = self.cap.read()
                if ok:
                    self.render_frame(frame)
                    pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
                    self._seek_lock = True
                    self.seek_var.set(pos)
                    self._seek_lock = False
                    self.time_lbl.config(text="%s / %s" % (
                        fmt(pos / self.fps), fmt(self.frames / self.fps)))
        except Exception as ex:
            self.write_log("player error: " + str(ex))
        delay = max(int(1000 / self.fps / self.speed), 10)
        self.after(delay, self.tick)

    def render_frame(self, frame):
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(img)
        w = min(int(pil.width * self.zoom), 1100)
        h = int(pil.height * w / pil.width)
        disp = pil.resize((max(w, 2), max(h, 2)))
        self._imgtk = ImageTk.PhotoImage(disp)
        self.preview.config(image=self._imgtk)
        if self.pip and self.pip.winfo_exists():
            self.pip.show(pil)

    def render_current(self):
        if self.cap is None:
            return
        pos = self.cap.get(cv2.CAP_PROP_POS_FRAMES)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, max(pos - 1, 0))
        ok, frame = self.cap.read()
        if ok:
            self.render_frame(frame)

    # ---------------- live sync to phone ----------------

    def schedule_sync(self):
        if not self.sync_var.get():
            return
        if self._sync_job:
            self.after_cancel(self._sync_job)
        self._sync_job = self.after(400, self.send_control)

    def send_control(self):
        self._sync_job = None
        if self.cap is None:
            return
        pos = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES) / self.fps * 1000)
        ctl = json.dumps({"playing": self.playing,
                          "position_ms": pos,
                          "speed": round(self.speed, 2),
                          "video": VIDEO_PATH})

        def work():
            adb("shell", "su", "-c",
                "echo '%s' > %s && chmod 644 %s" % (ctl, CONTROL_PATH,
                                                    CONTROL_PATH))
        self.run_bg(work)

    # ---------------- adb ----------------

    def check_device(self):
        def work():
            r = adb("devices")
            self.write_log(r.stdout.strip() or r.stderr.strip())
            root = adb("shell", "su", "-c", "id")
            self.write_log("root: " + (root.stdout.strip() or root.stderr.strip()))
        self.run_bg(work)

    def push_video(self):
        if not self.video_file:
            messagebox.showwarning("VCam", "Select a video first.")
            return

        def work():
            self.write_log("pushing video...")
            adb("shell", "mkdir", "-p", VCAM_DIR)
            r = adb("push", self.video_file, VIDEO_PATH, timeout=900)
            self.write_log((r.stdout + r.stderr).strip())
            adb("shell", "su", "-c", "chmod 644 " + VIDEO_PATH)
            self.write_log("done.")
        self.run_bg(work)

    def set_enabled(self, enabled):
        def work():
            cfg = json.dumps({"enabled": enabled, "video": VIDEO_PATH})
            adb("shell", "mkdir", "-p", VCAM_DIR)
            r = adb("shell", "su", "-c",
                    "echo '%s' > %s && chmod 644 %s" % (cfg, CONFIG_PATH,
                                                        CONFIG_PATH))
            self.write_log("injection " + ("ENABLED" if enabled else "DISABLED")
                           + ("" if r.returncode == 0
                              else " (error: " + r.stderr + ")"))
            self.write_log("Restart the target app to apply.")
        self.run_bg(work)

    def restart_target(self):
        pkg = self.ent_pkg.get().strip()

        def work():
            adb("shell", "am", "force-stop", pkg)
            r = adb("shell", "monkey", "-p", pkg, "-c",
                    "android.intent.category.LAUNCHER", "1")
            lines = r.stdout.strip().splitlines()
            self.write_log("restarted " + pkg + (" : " + lines[-1] if lines else ""))
        self.run_bg(work)


if __name__ == "__main__":
    App().mainloop()
