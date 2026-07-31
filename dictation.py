# Dictation Reader v5.0 - Optimized
# Windows-only portable dictation assistant with TTS
import tkinter as tk
from tkinter import font as tkfont
import threading
import time
import os
import sys
import json
import logging
import atexit
import tempfile
import shutil
from enum import Enum, auto
from pathlib import Path
from ctypes import wintypes, windll, byref

import pyttsx3
import simpleaudio as sa

# ==================== Paths ====================
# Portable: all data stored next to the exe/script
if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).parent
else:
    APP_DIR = Path(__file__).resolve().parent
LOG_DIR = APP_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "dictation.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("dictation")


# ==================== Configuration ====================
DEFAULT_CONFIG = {
    "title": "听写",
    "font_family": "STKaiti",
    "font_size": 32,
    "tts_rate": 150,
    "tts_volume": 1.0,
    "char_interval": 0.5,
    "interval_min": 0.5,
    "interval_max": 10.0,
    "interval_step": 0.5,
    "settings_height": 120,
    "text_area_ratio": 0.6,
    "intro_text": "你好，同学，请认真听，现在开始",
    "outro_text": "日记完成，你很努力，加油！",
}

CONFIG_PATH = APP_DIR / "config.json"

PUNCT_MAP = {
    "，": "逗号", "。": "句号", "！": "感叹号", "？": "问号",
    "：": "冒号", "；": "分号", "、": "顿号",
    "\u201c": "引号", "\u201d": "引号",
    "\uff08": "左括号", "\uff09": "右括号",
    "\n": "另起一段，空两格",
}


class Config:
    """Persistent JSON configuration with defaults."""

    def __init__(self):
        self._data: dict = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                # Only merge known keys
                for k in DEFAULT_CONFIG:
                    if k in saved:
                        self._data[k] = saved[k]
                log.info("Config loaded from %s", CONFIG_PATH)
            except Exception as e:
                log.warning("Failed to load config, using defaults: %s", e)

    def save(self):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            log.info("Config saved to %s", CONFIG_PATH)
        except Exception as e:
            log.error("Failed to save config: %s", e)

    def __getattr__(self, name):
        if name.startswith("_"):
            return super().__getattribute__(name)
        try:
            return self._data[name]
        except KeyError:
            raise AttributeError(f"Config has no attribute '{name}'")

    def __setattr__(self, name, value):
        if name.startswith("_"):
            super().__setattr__(name, value)
        else:
            self._data[name] = value


# ==================== Playback State ====================
class PlayState(Enum):
    IDLE = auto()
    PLAYING = auto()
    PAUSED = auto()


# ==================== Audio Manager ====================
class AudioManager:
    """Manages TTS engine and audio playback with proper resource cleanup."""

    def __init__(self, config: Config):
        self._cfg = config
        self._temp_dir = LOG_DIR / "audio_cache"
        self._temp_dir.mkdir(exist_ok=True)
        self._current_play_obj = None
        self._lock = threading.Lock()
        log.info("Temp audio dir: %s", self._temp_dir)

    @property
    def temp_dir(self) -> Path:
        return self._temp_dir

    def _new_engine(self):
        """Create a fresh TTS engine (pyttsx3 SAPI5 is not reusable across runAndWait calls)."""
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", self._cfg.tts_rate)
            engine.setProperty("volume", self._cfg.tts_volume)
            return engine
        except Exception as e:
            log.error("Failed to init TTS engine: %s", e)
            return None

    def _speak_to_file(self, text: str, filepath: str) -> bool:
        """Generate a WAV file from text. Creates a fresh engine each call."""
        engine = self._new_engine()
        if engine is None:
            return False
        try:
            engine.save_to_file(text, filepath)
            engine.runAndWait()
            engine.stop()
            return os.path.exists(filepath) and os.path.getsize(filepath) > 0
        except Exception as e:
            log.error("TTS gen failed for '%s': %s", text[:20], e)
            return False

    def speak_text_sync(self, text: str):
        """Synchronous TTS for intro/outro prompts."""
        fd, filepath = tempfile.mkstemp(suffix=".wav", dir=str(self._temp_dir))
        os.close(fd)
        try:
            if self._speak_to_file(text, filepath):
                wave_obj = sa.WaveObject.from_wave_file(filepath)
                play_obj = wave_obj.play()
                play_obj.wait_done()
            else:
                log.warning("Skipping prompt, audio gen failed: %s", text[:20])
        except Exception as e:
            log.error("TTS speak failed for '%s': %s", text[:20], e)
        finally:
            self._safe_delete(filepath)

    def generate_char_audio(self, ch: str, index: int) -> str | None:
        """Generate WAV for a single character, return filepath or None."""
        ch_stripped = ch.strip()
        if ch_stripped == "" and ch != "\n":
            return None
        filepath = str(self._temp_dir / f"char_{index}.wav")
        speak_char = PUNCT_MAP.get(ch, ch)
        if self._speak_to_file(speak_char, filepath):
            return filepath
        return None

    def play_file(self, filepath: str) -> bool:
        """Play a WAV file. Returns True if started successfully."""
        try:
            wave_obj = sa.WaveObject.from_wave_file(filepath)
            with self._lock:
                self._current_play_obj = wave_obj.play()
            return True
        except Exception as e:
            log.error("Play failed for %s: %s", filepath, e)
            return False

    def is_playing(self) -> bool:
        with self._lock:
            return self._current_play_obj is not None and self._current_play_obj.is_playing()

    def stop_current(self):
        with self._lock:
            if self._current_play_obj:
                try:
                    self._current_play_obj.stop()
                except Exception:
                    pass
                self._current_play_obj = None

    def cleanup_file(self, filepath: str):
        """Delete a single temp file after use."""
        self._safe_delete(filepath)

    def _safe_delete(self, filepath: str):
        try:
            if filepath and os.path.exists(filepath):
                os.remove(filepath)
        except Exception as e:
            log.debug("Failed to delete %s: %s", filepath, e)

    def cleanup_all(self):
        """Remove entire temp directory."""
        self.stop_current()
        try:
            if self._temp_dir.exists():
                shutil.rmtree(self._temp_dir, ignore_errors=True)
                log.info("Temp dir cleaned: %s", self._temp_dir)
        except Exception as e:
            log.warning("Temp cleanup failed: %s", e)


# ==================== Dictation App ====================
class DictationApp:
    """Main application: UI + playback control with thread safety."""

    def __init__(self):
        self._cfg = Config()
        self._audio = AudioManager(self._cfg)
        self._state = PlayState.IDLE
        self._lock = threading.Lock()
        self._current_index = 0
        self._last_char = ""
        self._play_thread: threading.Thread | None = None
        self._play_text = ""

        # UI vars
        self._font_size_var = None
        self._interval_label_var = None
        self._word_count_var = None
        self._btn_start = None
        self._btn_cursor = None
        self._btn_stop = None
        self._btn_pause = None
        self._interval_scale = None

        self._build_ui()
        atexit.register(self._on_exit)

    # ---- UI Construction ----
    def _build_ui(self):
        self._root = tk.Tk()
        self._root.title(self._cfg.title + "_V5")
        self._root.protocol("WM_DELETE_WINDOW", self._on_exit)

        # Maximize to work area (Windows)
        try:
            work_area = wintypes.RECT()
            windll.user32.SystemParametersInfoW(0x0030, 0, byref(work_area), 0)
            w = work_area.right - work_area.left
            h = work_area.bottom - work_area.top
            self._root.geometry(f"{w}x{h}+{work_area.left}+{work_area.top}")
            self._root.state("zoomed")
        except Exception as e:
            log.warning("Failed to get work area, using default geometry: %s", e)
            self._root.geometry("1200x800")

        cfg = self._cfg
        self._text_box = tk.Text(
            self._root, wrap="word",
            font=(cfg.font_family, cfg.font_size),
        )
        self._canvas = tk.Canvas(
            self._root, bg="#ffffff",
            highlightthickness=2, highlightbackground="#888888",
        )
        self._settings_frame = tk.Frame(self._root)
        self._build_settings()

        # Bindings
        self._root.bind("<Configure>", self._on_resize)
        self._canvas.bind("<Configure>", self._on_canvas_resize)
        self._root.bind("<space>", lambda e: self._pause_resume())
        self._root.bind("<Escape>", lambda e: self._stop())

        self._on_resize()
        self._update_ui_state()
        log.info("UI built successfully")

    def _build_settings(self):
        cfg = self._cfg
        frame = self._settings_frame

        # Row 0: font size + interval
        tk.Label(frame, text="字体大小：", font=(cfg.font_family, 16)).grid(
            row=0, column=0, padx=8, pady=8)
        self._font_size_var = tk.StringVar(value=str(cfg.font_size))
        tk.Entry(frame, textvariable=self._font_size_var, width=5,
                 font=(cfg.font_family, 16)).grid(row=0, column=1)
        tk.Button(frame, text="更新", font=(cfg.font_family, 14),
                  command=self._apply_font_size).grid(row=0, column=2, padx=8)

        tk.Label(frame, text="字符间停顿(s)：",
                 font=(cfg.font_family, 16)).grid(row=0, column=3, padx=16)
        self._interval_label_var = tk.StringVar(
            value=f"字符间停顿: {cfg.char_interval:.1f}s")
        self._interval_scale = tk.Scale(
            frame, from_=cfg.interval_min, to=cfg.interval_max,
            resolution=cfg.interval_step, orient="horizontal", length=420,
            command=self._on_interval_change,
        )
        self._interval_scale.set(cfg.char_interval)
        self._interval_scale.grid(row=0, column=4)
        tk.Label(frame, textvariable=self._interval_label_var,
                 font=(cfg.font_family, 16)).grid(row=0, column=5, padx=16)

        # Row 1: buttons + word count
        btn_font = (cfg.font_family, 14)
        self._btn_start = tk.Button(frame, text="从开头朗读", command=self._speak_from_start,
                  bg="#4CAF50", fg="white", width=12, font=btn_font)
        self._btn_start.grid(row=1, column=0, padx=8, pady=12)
        self._btn_cursor = tk.Button(frame, text="从光标朗读", command=self._speak_from_cursor,
                  bg="#2196F3", fg="white", width=12, font=btn_font)
        self._btn_cursor.grid(row=1, column=1, padx=8)
        self._btn_stop = tk.Button(frame, text="停止朗读", command=self._stop,
                  bg="#F44336", fg="white", width=12, font=btn_font)
        self._btn_stop.grid(row=1, column=2, padx=8)
        self._btn_pause = tk.Button(frame, text="暂停朗读", command=self._pause_resume,
                  bg="#FFC107", fg="black", width=12, font=btn_font)
        self._btn_pause.grid(row=1, column=3, padx=8)

        self._word_count_var = tk.StringVar()
        tk.Label(frame, textvariable=self._word_count_var,
                 font=(cfg.font_family, 16)).grid(row=1, column=4, padx=20)

    # ---- Settings callbacks ----
    def _update_ui_state(self):
        """Enable/disable controls based on current PlayState."""
        with self._lock:
            state = self._state
        if state == PlayState.IDLE:
            self._text_box.config(state="normal")
            self._btn_start.config(state="normal")
            self._btn_cursor.config(state="normal")
            self._btn_stop.config(state="disabled")
            self._btn_pause.config(state="disabled", text="暂停朗读")
            self._interval_scale.config(state="normal")
        elif state == PlayState.PLAYING:
            self._text_box.config(state="disabled")
            self._btn_start.config(state="disabled")
            self._btn_cursor.config(state="disabled")
            self._btn_stop.config(state="normal")
            self._btn_pause.config(state="normal", text="暂停朗读")
            self._interval_scale.config(state="disabled")
        elif state == PlayState.PAUSED:
            self._text_box.config(state="disabled")
            self._btn_start.config(state="disabled")
            self._btn_cursor.config(state="disabled")
            self._btn_stop.config(state="normal")
            self._btn_pause.config(state="normal", text="继续朗读")
            self._interval_scale.config(state="normal")

    def _apply_font_size(self):
        try:
            size = int(self._font_size_var.get())
            if 8 <= size <= 120:
                self._text_box.config(font=(self._cfg.font_family, size))
                self._cfg.font_size = size
                self._cfg.save()
            else:
                log.warning("Font size out of range: %d", size)
        except ValueError:
            log.warning("Invalid font size input")

    def _on_interval_change(self, v):
        try:
            val = float(v)
            self._cfg.char_interval = val
            self._interval_label_var.set(f"字符间停顿: {val:.1f}s")
            self._cfg.save()
        except ValueError:
            pass

    # ---- Layout ----
    def _on_resize(self, event=None):
        win_w = self._root.winfo_width()
        win_h = self._root.winfo_height()
        if win_w <= 1 or win_h <= 1:
            return
        sh = self._cfg.settings_height
        left_w = int(win_w * self._cfg.text_area_ratio)
        right_w = win_w - left_w
        usable_h = max(win_h - sh, 0)

        self._text_box.place(x=0, y=0, width=left_w, height=usable_h)
        side = min(right_w, usable_h)
        self._canvas.place(x=left_w, y=(usable_h - side) // 2,
                           width=side, height=side)
        self._settings_frame.place(x=0, y=win_h - sh, width=win_w, height=sh)
        self._refresh_square()

    def _on_canvas_resize(self, event=None):
        self._refresh_square()

    # ---- Tianzi Grid ----
    def _refresh_square(self):
        side = min(self._canvas.winfo_width(), self._canvas.winfo_height())
        if side <= 0:
            return
        self._canvas.delete("grid")
        self._draw_tianzige(side)
        if self._last_char:
            self._update_canvas_char(self._last_char)

    def _draw_tianzige(self, side: int):
        c = self._canvas
        c.create_rectangle(2, 2, side - 2, side - 2, outline="gray", width=2, tags="grid")
        c.create_line(side / 2, 0, side / 2, side, fill="gray", width=1, tags="grid")
        c.create_line(0, side / 2, side, side / 2, fill="gray", width=1, tags="grid")
        c.create_line(0, 0, side, side, fill="lightgray", width=1, tags="grid")
        c.create_line(0, side, side, 0, fill="lightgray", width=1, tags="grid")

    def _update_canvas_char(self, ch: str):
        self._last_char = ch
        side = min(self._canvas.winfo_width(), self._canvas.winfo_height())
        self._canvas.delete("char")
        if ch and ch != "\n":
            margin = max(int(side * 0.06), 10)
            font_size = max(int((side - 2 * margin) / 1.2), 12)
            # Shift y up for Latin characters (compensate descender space)
            is_latin = '\u0020' <= ch <= '\u024F'
            y_offset = int(font_size * 0.08) if is_latin else 0
            tid = self._canvas.create_text(
                side / 2, side / 2 - y_offset, text=ch,
                font=(self._cfg.font_family, font_size),
                fill="black", tags="char",
            )
            self._canvas.tag_raise(tid)

    # ---- Text Highlight ----
    def _highlight_at(self, index: int):
        self._text_box.tag_remove("highlight", "1.0", tk.END)
        ch = self._text_box.get(f"1.0+{index}c", f"1.0+{index}c+1c")
        if ch != "\n":
            pos = f"1.0+{index}c"
            self._text_box.tag_add("highlight", pos, f"{pos}+1c")
            self._text_box.tag_config("highlight", background="yellow", foreground="red")

    def _clear_highlight(self):
        self._text_box.tag_remove("highlight", "1.0", tk.END)

    # ---- Word Count ----
    @staticmethod
    def _count_chars(text: str) -> int:
        return sum(1 for c in text if not c.isspace())

    def _update_word_count(self, text: str, index: int):
        total = self._count_chars(text)
        remaining = self._count_chars(text[index:])
        self._word_count_var.set(f"共计 {total} 字，剩余 {remaining} 字")

    # ---- Playback Control ----
    def _speak_from_start(self):
        self._stop()
        text = self._text_box.get("1.0", tk.END).rstrip()
        if not text:
            return
        with self._lock:
            self._state = PlayState.PLAYING
            self._current_index = 0
            self._play_text = text
        self._update_word_count(text, 0)
        self._root.after(0, self._update_ui_state)
        self._start_play_thread()

    def _speak_from_cursor(self):
        self._stop()
        text = self._text_box.get("1.0", tk.END).rstrip()
        if not text:
            return
        cursor = self._text_box.index("insert")
        idx = self._text_box.count("1.0", cursor, "chars")[0]
        with self._lock:
            self._state = PlayState.PLAYING
            self._current_index = idx
            self._play_text = text
        self._update_word_count(text, idx)
        self._root.after(0, self._update_ui_state)
        self._start_play_thread()

    def _start_play_thread(self):
        # Intro prompt (blocking) before thread
        try:
            self._audio.speak_text_sync(self._cfg.intro_text)
        except Exception as e:
            log.warning("Intro prompt failed: %s", e)
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._play_thread.start()

    def _stop(self):
        with self._lock:
            self._state = PlayState.IDLE
        self._audio.stop_current()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1)
        self._play_thread = None
        with self._lock:
            self._current_index = 0
            self._last_char = ""
        self._clear_highlight()
        self._update_canvas_char("")
        self._word_count_var.set("")
        self._root.after(0, self._update_ui_state)

    def _pause_resume(self):
        with self._lock:
            if self._state == PlayState.PLAYING:
                self._state = PlayState.PAUSED
                self._audio.stop_current()
            elif self._state == PlayState.PAUSED:
                self._state = PlayState.PLAYING
        self._root.after(0, self._update_ui_state)

    # ---- Play Loop (runs in thread) ----
    def _play_loop(self):
        interval = self._cfg.char_interval
        text = self._play_text
        idx = self._current_index
        highlight_dirty = False
        last_highlight_idx = -1

        while idx < len(text):
            # Check state
            with self._lock:
                state = self._state
            if state == PlayState.IDLE:
                break
            if state == PlayState.PAUSED:
                time.sleep(0.1)
                continue

            ch = text[idx]

            # Update UI (batched - only when index changed)
            if idx != last_highlight_idx:
                self._root.after(0, self._highlight_at, idx)
                self._root.after(0, self._update_canvas_char, ch)
                self._root.after(0, self._update_word_count, text, idx)
                last_highlight_idx = idx

            # Skip whitespace (no audio, just wait)
            if ch.strip() == "" and ch != "\n":
                if not self._sleep_check(interval):
                    break
                idx += 1
                with self._lock:
                    self._current_index = idx
                continue

            # Generate and play audio
            wav_path = self._audio.generate_char_audio(ch, idx)
            if wav_path:
                if self._audio.play_file(wav_path):
                    # Wait for playback to finish
                    while self._audio.is_playing():
                        with self._lock:
                            st = self._state
                        if st == PlayState.IDLE:
                            self._audio.stop_current()
                            break
                        if st == PlayState.PAUSED:
                            self._audio.stop_current()
                            # Wait until resumed
                            while True:
                                time.sleep(0.1)
                                with self._lock:
                                    st = self._state
                                if st != PlayState.PAUSED:
                                    break
                            break
                        time.sleep(0.05)
                # Clean up wav immediately
                self._audio.cleanup_file(wav_path)

            if not self._sleep_check(interval):
                break
            idx += 1
            with self._lock:
                self._current_index = idx

        # Finished
        with self._lock:
            self._state = PlayState.IDLE
        self._root.after(0, self._clear_highlight)
        self._root.after(0, self._update_canvas_char, "")
        self._root.after(0, self._update_word_count, text, len(text))
        self._root.after(0, self._update_ui_state)

        # Outro prompt
        try:
            self._audio.speak_text_sync(self._cfg.outro_text)
        except Exception as e:
            log.warning("Outro prompt failed: %s", e)

    def _sleep_check(self, seconds: float) -> bool:
        """Sleep for `seconds`, respecting pause/stop. Returns False if stopped."""
        ticks = max(int(seconds / 0.1), 1)
        for _ in range(ticks):
            with self._lock:
                state = self._state
            if state == PlayState.IDLE:
                return False
            while state == PlayState.PAUSED:
                time.sleep(0.1)
                with self._lock:
                    state = self._state
                if state == PlayState.IDLE:
                    return False
            time.sleep(0.1)
        return True

    # ---- Exit ----
    def _on_exit(self):
        log.info("Exiting...")
        self._stop()
        self._audio.cleanup_all()
        self._cfg.save()
        self._root.destroy()

    def run(self):
        self._root.mainloop()


# ==================== Entry Point ====================
if __name__ == "__main__":
    try:
        app = DictationApp()
        app.run()
    except Exception as e:
        log.critical("Fatal error: %s", e, exc_info=True)
        raise
