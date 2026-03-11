"""
F1 Pro Dashboard  v4.0  — FIXED v3
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIX ROOT CAUSE:
  FastF1 devuelve subclases de pd.DataFrame/Series con metaclases
  personalizadas. Cualquier operación de indexación booleana (incluso
  .apply()) puede triggear recursión infinita en pandas internamente
  al validar el tipo del índice.

SOLUCIÓN DEFINITIVA:
  · Al cachear datos, se extraen los arrays de tiempo a numpy float64
    puros y se almacenan FUERA del DataFrame en dicts separados.
  · Todo el filtrado se hace con np.where sobre numpy arrays puros —
    NUNCA bool indexing sobre columnas de DataFrame de FastF1.
  · Los DataFrames se convierten a pd.DataFrame() puro con
    reset_index(drop=True) para romper la herencia de FastF1.
  · series_to_float_array() convierte Timedelta element-by-element
    usando .value (nanoseconds int) — sin llamar a ninguna función
    vectorizada de pandas que pueda explotar.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import tkinter as tk
from tkinter import ttk, Canvas, messagebox
import threading
import time
import os
import math
import logging
import urllib.request
import json
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass

import fastf1
import pandas as pd
import numpy as np

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("F1v4")

# ─── CACHÉ ───────────────────────────────────────────────────────────────────
CACHE_DIR = os.path.join(os.path.expanduser("~"), ".f1_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(CACHE_DIR)

# ─── OPENF1 ──────────────────────────────────────────────────────────────────
OPENF1_BASE = "https://api.openf1.org/v1"

def openf1_get(endpoint: str, params: dict = None, timeout: int = 8) -> list:
    url = f"{OPENF1_BASE}/{endpoint}"
    if params:
        url += "?" + "&".join(f"{k}={v}" for k, v in params.items())
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        log.debug("OpenF1 %s: %s", endpoint, e)
        return []

# ─── PALETA ──────────────────────────────────────────────────────────────────
BG_DARK  = "#0d0d1a"
BG_PANEL = "#13131f"
BG_CARD  = "#1c1c2e"
BG_ROW   = "#1e1e30"
ACCENT   = "#e10600"
ACCENT2  = "#00a0e9"
TEXT_PRI = "#ffffff"
TEXT_SEC = "#9999bb"
GREEN    = "#00e676"
YELLOW   = "#ffd600"
ORANGE   = "#ff6d00"
PURPLE   = "#d500f9"
FONT     = "Segoe UI"

F1_WHITE  = "#ffffff"
F1_GREEN  = "#00e676"
F1_YELLOW = "#ffd600"
F1_PURPLE = "#d500f9"

TEAM_COLORS: Dict[str, str] = {
    "Mercedes":                         "#00d2be",
    "Ferrari":                          "#dc0000",
    "Red Bull Racing":                  "#3671c6",
    "McLaren":                          "#ff8700",
    "Aston Martin":                     "#358c75",
    "Aston Martin Aramco Cognizant":    "#358c75",
    "Alpine":                           "#0090ff",
    "Williams":                         "#37bedd",
    "RB":                               "#6692ff",
    "Kick Sauber":                      "#52e252",
    "Haas F1 Team":                     "#b6babd",
    "Haas":                             "#b6babd",
    "Alfa Romeo":                       "#c92d4b",
    "AlphaTauri":                       "#2b4562",
}

TRACK_STATUS: Dict[str, Tuple[str, str, str]] = {
    "1": ("🟢 GREEN FLAG",    GREEN,  "#003300"),
    "2": ("🟡 YELLOW FLAG",   YELLOW, "#333300"),
    "3": ("🟡 SECTOR YEL",    YELLOW, "#333300"),
    "4": ("🟠 SAFETY CAR",    ORANGE, "#331a00"),
    "5": ("🔴 RED FLAG",      ACCENT, "#330000"),
    "6": ("🟣 VIRTUAL SC",    PURPLE, "#1a0033"),
    "7": ("🟢 VSC END",       GREEN,  "#003300"),
}

SESSION_INFO: Dict[str, Tuple[str, str, str]] = {
    "FP1": ("FREE PRACTICE 1",   ACCENT2, "#001a2e"),
    "FP2": ("FREE PRACTICE 2",   ACCENT2, "#001a2e"),
    "FP3": ("FREE PRACTICE 3",   ACCENT2, "#001a2e"),
    "Q":   ("QUALIFYING",        YELLOW,  "#2e2b00"),
    "SQ":  ("SPRINT QUALIFYING", ORANGE,  "#2e1600"),
    "S":   ("SPRINT",            ORANGE,  "#2e1600"),
    "R":   ("RACE",              ACCENT,  "#2e0000"),
}

DRS_ACTIVE_VALUES = {10, 12, 14}
MAX_RPM = 13_500

# ─── HELPERS — 100% Python/numpy, sin pandas ─────────────────────────────────
def safe(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def fmt_lap(s) -> str:
    try:
        if s is None or math.isnan(float(s)) or float(s) <= 0:
            return "--:--.---"
        m, sec = divmod(float(s), 60)
        return f"{int(m)}:{sec:06.3f}"
    except Exception:
        return "--:--.---"

def hms(s: int) -> str:
    h, r = divmod(int(s), 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def is_2026_era(year: int) -> bool:
    return year >= 2026

def td_to_sec(v) -> Optional[float]:
    """
    Timedelta/NaT → float segundos, sin usar pd.isna() ni operadores
    vectorizados de pandas que puedan triggear RecursionError.
    """
    if v is None:
        return None
    # NaT se detecta por nombre de clase, no por pd.isna()
    if type(v).__name__ == "NaTType":
        return None
    try:
        ns = int(v.value)          # Timedelta.value = nanosegundos como int64
        # NaT.value es pd.NaT.value = INT64_MIN = -9223372036854775808
        if ns < -9_000_000_000_000_000_000:
            return None
        s = ns / 1_000_000_000.0
        return None if (math.isnan(s) or math.isinf(s)) else s
    except Exception:
        try:
            return float(v.total_seconds())
        except Exception:
            return None

def series_to_float_array(series) -> np.ndarray:
    """
    Convierte una Series de Timedelta/datetime de FastF1 a numpy float64.
    Itera en Python puro — evita cualquier operación vectorizada de pandas
    que pueda explotar con subclases FastF1.
    """
    out = np.empty(len(series), dtype=np.float64)
    for i, v in enumerate(series):
        s = td_to_sec(v)
        out[i] = s if s is not None else np.nan
    return out

def df_to_plain(df) -> pd.DataFrame:
    """
    Convierte subclase FastF1 de DataFrame a pd.DataFrame puro,
    eliminando la herencia que causa los RecursionError.
    """
    return pd.DataFrame(df).reset_index(drop=True)


# ─── SNAPSHOT ────────────────────────────────────────────────────────────────
@dataclass
class Snap:
    drv: str = ""; abbr: str = ""; name: str = ""
    number: str = ""; team: str = "Unknown"
    pos: int = 999; lap: int = 0
    gap: str = "–"; interval: str = "–"
    gap_num: float = 999.; int_num: float = 999.
    speed: float = 0.; rpm: float = 0.
    throttle: float = 0.; brake: float = 0.
    gear: int = 0; drs: float = 0.; tyre: str = "–"
    dist: float = -1.; is_out: bool = False
    x: float = float("nan"); y: float = float("nan")


# ════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ════════════════════════════════════════════════════════════════════════════
class F1Dashboard:

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("F1 Pro Dashboard  v4.0  •  Telemetría & Timing")
        self.root.geometry("1760x1040")
        self.root.minsize(1400, 800)
        self.root.configure(bg=BG_DARK)

        self.session           = None
        self.telemetry:        Dict[str, pd.DataFrame] = {}
        self.laps_data:        Optional[pd.DataFrame]  = None
        self.drivers:          List[str] = []
        self.total_laps:       int   = 0
        self.session_best_s:   Optional[float] = None
        self.session_start:    float = 0.
        self.max_time:         float = 0.
        self.session_type:     str   = "R"
        self.session_year:     int   = 2024
        self._current_ts:      str   = "1"

        # Laps: plain DataFrames + numpy time arrays externos
        self._laps_by_driver: Dict[str, pd.DataFrame] = {}
        self._laps_times:     Dict[str, np.ndarray]   = {}  # segundos float[]

        # Track status: numpy arrays puros — NUNCA se indexan con bool de pandas
        self._ts_times:  np.ndarray = np.array([], dtype=np.float64)
        self._ts_status: List[str]  = []

        # Weather: numpy time + lista de dicts Python
        self._wx_times: np.ndarray = np.array([], dtype=np.float64)
        self._wx_rows:  List[dict] = []

        self._sector_bests:        Dict[str, List[Optional[float]]] = {}
        self._overall_sector_best: List[Optional[float]] = [None, None, None]

        self.is_playing     = False
        self.current_time   = 0.
        self.playback_speed = tk.IntVar(value=1)
        self._play_thread:  Optional[threading.Thread] = None
        self._load_thread:  Optional[threading.Thread] = None

        self.track_scale = 1.; self.track_cx = 0.; self.track_cy = 0.
        self.map_w = 600; self.map_h = 340
        self._map_zoom = 1.0; self._map_pan_x = 0.; self._map_pan_y = 0.
        self._drag_start: Optional[Tuple[int,int]] = None
        self._last_snaps: List[Snap] = []
        self.selected_driver: Optional[str] = None

        self._setup_styles()
        self._build_ui()
        self._load_calendar(2024)

    # ── ESTILOS ──────────────────────────────────────────────────────────────
    def _setup_styles(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",           background=BG_DARK)
        s.configure("TLabel",           background=BG_DARK, foreground=TEXT_PRI, font=(FONT,10))
        s.configure("TCombobox",        fieldbackground=BG_CARD, background=BG_CARD,
                    foreground=TEXT_PRI, selectbackground=ACCENT, font=(FONT,10))
        s.configure("TRadiobutton",     background=BG_DARK, foreground=TEXT_SEC, font=(FONT,9,"bold"))
        s.map("TRadiobutton",           foreground=[("selected", TEXT_PRI)])
        s.configure("Treeview",         background=BG_ROW, foreground=TEXT_PRI,
                    fieldbackground=BG_ROW, rowheight=26, font=(FONT,9))
        s.map("Treeview",               background=[("selected", ACCENT)],
                                        foreground=[("selected", TEXT_PRI)])
        s.configure("Treeview.Heading", background=BG_CARD, foreground=TEXT_SEC,
                    font=(FONT,9,"bold"), relief="flat")
        s.map("Treeview.Heading",       background=[("active", BG_ROW)])
        s.configure("Vertical.TScrollbar", background=BG_PANEL,
                    troughcolor=BG_CARD, arrowcolor=TEXT_SEC)

    # ── UI BUILD ─────────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        self._build_header(); self._build_controls(); self._build_main_area()

    def _build_header(self) -> None:
        hdr = tk.Frame(self.root, bg=BG_PANEL, height=56)
        hdr.pack(fill=tk.X); hdr.pack_propagate(False)

        tk.Label(hdr, text=" F1", bg=BG_PANEL, fg=ACCENT,
                 font=(FONT,22,"bold")).pack(side=tk.LEFT, padx=(14,0))
        tk.Label(hdr, text="PRO DASHBOARD", bg=BG_PANEL, fg=TEXT_PRI,
                 font=(FONT,11,"bold")).pack(side=tk.LEFT, padx=(4,18))
        self._vsep(hdr)

        tk.Label(hdr, text="Year:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT,9,"bold")).pack(side=tk.LEFT, padx=(10,3))
        self.combo_year = ttk.Combobox(hdr, values=list(range(2018,2027)), width=6, state="readonly")
        self.combo_year.set(2024); self.combo_year.pack(side=tk.LEFT, padx=(0,12))
        self.combo_year.bind("<<ComboboxSelected>>",
                             lambda _: self._load_calendar(int(self.combo_year.get())))

        tk.Label(hdr, text="Race:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT,9,"bold")).pack(side=tk.LEFT, padx=(0,3))
        self.combo_race = ttk.Combobox(hdr, width=38, state="readonly")
        self.combo_race.pack(side=tk.LEFT, padx=(0,12))

        tk.Label(hdr, text="Session:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT,9,"bold")).pack(side=tk.LEFT, padx=(0,3))
        self.combo_session = ttk.Combobox(hdr, values=["FP1","FP2","FP3","Q","SQ","S","R"],
                                           width=5, state="readonly")
        self.combo_session.set("R"); self.combo_session.pack(side=tk.LEFT, padx=(0,7))
        self.combo_session.bind("<<ComboboxSelected>>", self._on_session_type_change)

        si = SESSION_INFO["R"]
        self.lbl_sess_badge = tk.Label(hdr, text=f"◉ {si[0]}",
            bg=si[2], fg=TEXT_PRI, font=(FONT,9,"bold"), padx=10, pady=3)
        self.lbl_sess_badge.pack(side=tk.LEFT, padx=(0,12))
        self._vsep(hdr)

        self.btn_load = tk.Button(hdr, text="LOAD SESSION",
            bg=ACCENT, fg=TEXT_PRI, activebackground="#b30000",
            font=(FONT,10,"bold"), relief="flat", padx=12, pady=4,
            cursor="hand2", command=self._start_load)
        self.btn_load.pack(side=tk.LEFT, padx=(0,12))

        self.lbl_status = tk.Label(hdr, text="Select race + session, then LOAD SESSION.",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT,9))
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_spin = tk.Label(hdr, text="", bg=BG_PANEL, fg=ACCENT, font=(FONT,15,"bold"))
        self.lbl_spin.pack(side=tk.RIGHT, padx=14)

    def _vsep(self, p):
        tk.Frame(p, bg="#333355", width=1).pack(side=tk.LEFT, fill=tk.Y, pady=10, padx=3)

    def _build_controls(self) -> None:
        ctrl = tk.Frame(self.root, bg=BG_DARK, pady=5)
        ctrl.pack(fill=tk.X, padx=10)

        self.btn_play = tk.Button(ctrl, text="▶  PLAY",
            bg=ACCENT2, fg=TEXT_PRI, activebackground="#007bbf",
            font=(FONT,10,"bold"), relief="flat", padx=12, pady=3,
            cursor="hand2", command=self._toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, padx=(0,8))

        for lbl, val in (("×1",1),("×4",4),("×16",16),("×64",64)):
            ttk.Radiobutton(ctrl, text=lbl, variable=self.playback_speed,
                            value=val).pack(side=tk.LEFT, padx=2)
        self._vsep(ctrl)

        self.btn_prev = tk.Button(ctrl, text="◀◀ -1 Lap", bg=BG_CARD, fg=TEXT_SEC,
            relief="flat", font=(FONT,9), padx=8, pady=3,
            cursor="hand2", command=lambda: self._jump(-90), state=tk.DISABLED)
        self.btn_prev.pack(side=tk.LEFT, padx=2)

        self.btn_next = tk.Button(ctrl, text="+1 Lap ▶▶", bg=BG_CARD, fg=TEXT_SEC,
            relief="flat", font=(FONT,9), padx=8, pady=3,
            cursor="hand2", command=lambda: self._jump(90), state=tk.DISABLED)
        self.btn_next.pack(side=tk.LEFT, padx=(2,6))
        self._vsep(ctrl)

        box = tk.Frame(ctrl, bg=BG_DARK)
        box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5,7))
        self.timeline_canvas = Canvas(box, height=8, bg=BG_CARD, highlightthickness=0)
        self.timeline_canvas.pack(fill=tk.X, pady=(0,2))
        self.time_slider = tk.Scale(box, from_=0, to=100, orient=tk.HORIZONTAL,
            bg=BG_DARK, fg=TEXT_PRI, troughcolor=GREEN,
            highlightthickness=0, showvalue=False,
            command=self._on_slider, state=tk.DISABLED)
        self.time_slider.pack(fill=tk.X)

        self.lbl_time = tk.Label(ctrl, text="00:00:00", bg=BG_DARK, fg=TEXT_PRI,
            font=("Courier New",13,"bold"), width=9)
        self.lbl_time.pack(side=tk.LEFT, padx=(0,6))

    def _build_main_area(self) -> None:
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,6))
        self._build_left_panel(main); self._build_right_panel(main)

    def _build_left_panel(self, parent) -> None:
        left = tk.Frame(parent, bg=BG_DARK)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0,8))

        sb = tk.Frame(left, bg=BG_PANEL, height=38)
        sb.pack(fill=tk.X, pady=(0,5)); sb.pack_propagate(False)
        self.lbl_race_status = tk.Label(sb, text="⬜ NO SESSION",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT,12,"bold"), anchor="w", width=22)
        self.lbl_race_status.pack(side=tk.LEFT, padx=8)
        self.lbl_laps = tk.Label(sb, text="LAP — / —", bg=BG_PANEL, fg=TEXT_PRI, font=(FONT,12,"bold"))
        self.lbl_laps.pack(side=tk.LEFT, padx=10)
        self.lbl_weather = tk.Label(sb, text="Air —°C | Track —°C | ☀ —",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT,9))
        self.lbl_weather.pack(side=tk.RIGHT, padx=8)

        cols = ("Pos","No","DRV","Team","Gap","Int","Speed","Tyre","Lap")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=25, selectmode="browse")
        widths = {"Pos":32,"No":30,"DRV":46,"Team":96,"Gap":68,"Int":62,"Speed":68,"Tyre":44,"Lap":36}
        for c in cols:
            self.tree.heading(c, text=c, anchor=tk.CENTER)
            self.tree.column(c, width=widths[c],
                             anchor=tk.W if c=="Team" else tk.CENTER, stretch=False)
        vsb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", self._on_driver_select)

    def _build_right_panel(self, parent) -> None:
        right = tk.Frame(parent, bg=BG_DARK)
        right.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        top_row = tk.Frame(right, bg=BG_DARK)
        top_row.pack(fill=tk.BOTH, expand=True, pady=(0,6))
        self._build_map_panel(top_row); self._build_hud_panel(top_row)
        self._build_telemetry_plot(right); self._build_analysis_panel(right)

    def _build_map_panel(self, parent) -> None:
        mf = tk.Frame(parent, bg=BG_CARD)
        mf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
        hdr = tk.Frame(mf, bg=BG_CARD); hdr.pack(fill=tk.X)
        self.lbl_track_name = tk.Label(hdr, text="NO SESSION LOADED",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT,10,"bold"), anchor="w", padx=8, pady=3)
        self.lbl_track_name.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.lbl_map_badge = tk.Label(hdr, text="", bg=BG_CARD, fg=TEXT_PRI,
            font=(FONT,9,"bold"), padx=8, pady=3)
        self.lbl_map_badge.pack(side=tk.RIGHT)
        zoom_bar = tk.Frame(mf, bg=BG_CARD); zoom_bar.pack(fill=tk.X)
        tk.Label(zoom_bar, text="Scroll=zoom  |  Drag=pan  |",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT,7)).pack(side=tk.LEFT, padx=6)
        tk.Button(zoom_bar, text="⟳ Reset", bg=BG_CARD, fg=TEXT_SEC, font=(FONT,8),
            relief="flat", padx=6, command=self._map_reset).pack(side=tk.LEFT)
        self.map_canvas = Canvas(mf, bg=BG_CARD, highlightthickness=0)
        self.map_canvas.pack(fill=tk.BOTH, expand=True)
        self.map_canvas.bind("<MouseWheel>",      self._map_zoom_wheel)
        self.map_canvas.bind("<Button-4>",        self._map_zoom_wheel)
        self.map_canvas.bind("<Button-5>",        self._map_zoom_wheel)
        self.map_canvas.bind("<ButtonPress-1>",   self._map_drag_start)
        self.map_canvas.bind("<B1-Motion>",       self._map_drag_move)
        self.map_canvas.bind("<ButtonRelease-1>", self._map_drag_end)

    def _build_hud_panel(self, parent) -> None:
        f = tk.Frame(parent, bg=BG_CARD, padx=8, pady=6, width=340)
        f.pack(side=tk.RIGHT, fill=tk.Y); f.pack_propagate(False)

        self.lbl_driver_name = tk.Label(f, text="—", bg=BG_CARD, fg=TEXT_PRI,
            font=(FONT,18,"bold"), anchor="w")
        self.lbl_driver_name.pack(fill=tk.X)
        self.lbl_team_name = tk.Label(f, text="—", bg=BG_CARD, fg=TEXT_SEC,
            font=(FONT,9), anchor="w")
        self.lbl_team_name.pack(fill=tk.X)

        gap_frame = tk.Frame(f, bg=BG_CARD); gap_frame.pack(fill=tk.X, pady=(6,4))
        self.frm_ahead = tk.Frame(gap_frame, bg="#0d2035", padx=6, pady=4)
        self.frm_ahead.pack(fill=tk.X, pady=(0,3))
        tk.Label(self.frm_ahead, text="▲ AHEAD", bg="#0d2035", fg=TEXT_SEC,
                 font=(FONT,8,"bold")).pack(side=tk.LEFT)
        self.lbl_gap_ahead = tk.Label(self.frm_ahead, text="— —",
            bg="#0d2035", fg=ACCENT2, font=(FONT,12,"bold"), anchor="e")
        self.lbl_gap_ahead.pack(side=tk.RIGHT)
        self.frm_behind = tk.Frame(gap_frame, bg="#1f0d0d", padx=6, pady=4)
        self.frm_behind.pack(fill=tk.X)
        tk.Label(self.frm_behind, text="▼ BEHIND", bg="#1f0d0d", fg=TEXT_SEC,
                 font=(FONT,8,"bold")).pack(side=tk.LEFT)
        self.lbl_gap_behind = tk.Label(self.frm_behind, text="— —",
            bg="#1f0d0d", fg=ORANGE, font=(FONT,12,"bold"), anchor="e")
        self.lbl_gap_behind.pack(side=tk.RIGHT)

        self.lbl_battle = tk.Label(f, text="TRACK: CLEAR", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT,10,"bold"), anchor="w")
        self.lbl_battle.pack(fill=tk.X)
        self.lbl_style = tk.Label(f, text="STYLE: —", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT,10,"bold"), anchor="w")
        self.lbl_style.pack(fill=tk.X, pady=(0,4))

        self.hud_canvas = Canvas(f, width=320, height=272, bg=BG_CARD, highlightthickness=0)
        self.hud_canvas.pack()
        self._build_gauge_arcs()

        self.frm_battery = tk.Frame(f, bg=BG_CARD)
        tk.Label(self.frm_battery, text="⚡ BATTERY (ERS)", bg=BG_CARD, fg=ACCENT2,
                 font=(FONT,9,"bold"), anchor="w").pack(fill=tk.X)
        self.cvs_battery = Canvas(self.frm_battery, height=18, bg="#0d1a2e",
                                   highlightthickness=1, highlightbackground="#1a3a5e")
        self.cvs_battery.pack(fill=tk.X, pady=(2,0))
        self.lbl_battery_val = tk.Label(self.frm_battery, text="ERS: — kJ / — kJ",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT,8), anchor="w")
        self.lbl_battery_val.pack(fill=tk.X)

    def _build_gauge_arcs(self) -> None:
        c = self.hud_canvas; W, H = 320, 272
        c.create_arc(26,16,W-26,H-16, start=180,extent=-180,
                     style=tk.ARC, outline="#1c2c3c", width=16, tags="rpm_bg")
        c.create_arc(26,16,W-26,H-16, start=180,extent=0,
                     style=tk.ARC, outline=ACCENT2, width=16, tags="rpm_arc")
        rx,ry = (W-52)/2,(H-32)/2; ox,oy = W/2,H/2
        for rpm_m in range(0, MAX_RPM+1, 2000):
            a  = math.radians(180.-(rpm_m/MAX_RPM)*180.)
            c.create_text(ox+(rx-20)*math.cos(a), oy-(ry-20)*math.sin(a),
                          text=f"{rpm_m//1000}k", fill="#2a2a50", font=(FONT,7))
        c.create_arc(44,34,W-44,H-34, start=180,extent=-135,
                     style=tk.ARC, outline="#0f2b0f", width=18, tags="thr_bg")
        c.create_arc(44,34,W-44,H-34, start=180,extent=0,
                     style=tk.ARC, outline=GREEN, width=18, tags="thr_arc")
        c.create_arc(44,34,W-44,H-34, start=0,extent=45,
                     style=tk.ARC, outline="#2b0f0f", width=18, tags="brk_bg")
        c.create_arc(44,34,W-44,H-34, start=0,extent=0,
                     style=tk.ARC, outline=ACCENT, width=18, tags="brk_arc")
        cx = W//2
        c.create_text(cx,124, text="0",      fill=TEXT_PRI, font=(FONT,50,"bold"), tags="speed_val")
        c.create_text(cx,172, text="km/h",   fill=TEXT_SEC, font=(FONT,11))
        c.create_text(cx, 72, text="0 RPM",  fill=TEXT_SEC, font=(FONT,12),        tags="rpm_val")
        c.create_text(cx,206, text="N",       fill=ACCENT2,  font=(FONT,22,"bold"), tags="gear_val")
        c.create_text(cx,244, text="DRS OFF", fill=TEXT_SEC, font=(FONT,10,"bold"), tags="drs_val")
        c.create_text(42,160, text="THR",     fill=GREEN,    font=(FONT,8,"bold"))
        c.create_text(W-42,160, text="BRK",   fill=ACCENT,   font=(FONT,8,"bold"))

    def _build_telemetry_plot(self, parent) -> None:
        pf = tk.Frame(parent, bg=BG_CARD); pf.pack(fill=tk.X, pady=(0,4))
        hdr = tk.Frame(pf, bg=BG_CARD); hdr.pack(fill=tk.X)
        tk.Label(hdr, text="TELEMETRY PLOT  — Current Lap", bg=BG_CARD,
                 fg=ACCENT, font=(FONT,10,"bold"), padx=8, pady=3).pack(side=tk.LEFT)
        for txt,col in (("Speed",TEXT_PRI),("Throttle",GREEN),("Brake",ACCENT)):
            tk.Label(hdr, text=f"█ {txt}", bg=BG_CARD, fg=col,
                     font=(FONT,8,"bold")).pack(side=tk.LEFT, padx=6)
        self.plot_canvas = Canvas(pf, height=110, bg="#080810", highlightthickness=0)
        self.plot_canvas.pack(fill=tk.X, padx=4, pady=(0,4))

    def _build_analysis_panel(self, parent) -> None:
        row = tk.Frame(parent, bg=BG_DARK); row.pack(fill=tk.X)

        sec_f = tk.Frame(row, bg=BG_CARD, padx=8, pady=6)
        sec_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
        tk.Label(sec_f, text="SECTORS  vs  PREVIOUS LAP", bg=BG_CARD,
                 fg=ACCENT, font=(FONT,10,"bold"), anchor="w").pack(fill=tk.X, pady=(0,3))
        sec_cols = ("S","Time","Δ","Verdict","Cond")
        self.tree_sec = ttk.Treeview(sec_f, columns=sec_cols, show="headings",
                                      height=3, selectmode="none")
        for c,w in zip(sec_cols,(22,72,72,110,72)):
            self.tree_sec.heading(c, text=c)
            self.tree_sec.column(c, width=w, anchor=tk.CENTER, stretch=False)
        for tag,fg,bg in [("f1_purple",F1_PURPLE,None),("f1_green",F1_GREEN,None),
                           ("f1_yellow",F1_YELLOW,None),("f1_white",F1_WHITE,None),
                           ("sc_active",ORANGE,"#1a0e00"),("vsc_active",PURPLE,"#110022"),
                           ("yellow_sec",YELLOW,"#1a1a00"),("red_flag",ACCENT,"#1a0000")]:
            kw = {"foreground": fg}
            if bg: kw["background"] = bg
            self.tree_sec.tag_configure(tag, **kw)
        self.tree_sec.pack(fill=tk.X, pady=(0,3))
        self.lbl_track_cond = tk.Label(sec_f, text="Track: —", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT,9,"bold"), anchor="w"); self.lbl_track_cond.pack(fill=tk.X)
        self.lbl_tyre = tk.Label(sec_f, text="Tyre: —  |  Age: — laps  |  Pits: —",
            bg=BG_CARD, fg=TEXT_PRI, font=(FONT,10), anchor="w")
        self.lbl_tyre.pack(fill=tk.X, pady=(3,0))

        pace_f = tk.Frame(row, bg=BG_CARD, padx=8, pady=6)
        pace_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0,6))
        tk.Label(pace_f, text="PACE & ANALYSIS", bg=BG_CARD,
                 fg=ACCENT, font=(FONT,10,"bold"), anchor="w").pack(fill=tk.X, pady=(0,3))
        self.lbl_pace = tk.Label(pace_f, text="Pace (5L avg): —", bg=BG_CARD,
            fg=TEXT_PRI, font=(FONT,10,"bold"), anchor="w"); self.lbl_pace.pack(fill=tk.X)
        self.lbl_last_lap = tk.Label(pace_f, text="Last: —  |  Best: —", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT,10), anchor="w"); self.lbl_last_lap.pack(fill=tk.X, pady=(1,4))
        self.lbl_diag = tk.Label(pace_f, text="Behaviour: —", bg=BG_CARD,
            fg=ACCENT2, font=(FONT,9,"bold"), anchor="w", wraplength=260, justify="left")
        self.lbl_diag.pack(fill=tk.X)

        style_f = tk.Frame(row, bg=BG_CARD, padx=8, pady=6)
        style_f.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        tk.Label(style_f, text="DRIVING STYLE HISTORY", bg=BG_CARD,
                 fg=ACCENT, font=(FONT,10,"bold"), anchor="w").pack(fill=tk.X, pady=(0,3))
        style_cols = ("Lap","LiCo%","Clip%","Push%","Brk%","Lap Time","Δ Best","Cond")
        self.tree_style = ttk.Treeview(style_f, columns=style_cols,
                                        show="headings", height=5, selectmode="none")
        for c,w in zip(style_cols,(34,52,52,52,48,72,64,58)):
            self.tree_style.heading(c, text=c)
            self.tree_style.column(c, width=w, anchor=tk.CENTER, stretch=False)
        for tag,fg,bg in [("f1_purple",F1_PURPLE,None),("f1_green",F1_GREEN,None),
                           ("f1_yellow",F1_YELLOW,None),("f1_white",F1_WHITE,None),
                           ("high_clip",PURPLE,None),("sc_lap",ORANGE,None),
                           ("vsc_lap","#cc88ff",None),("yellow_lap",YELLOW,None),
                           ("red_lap",ACCENT,None)]:
            kw = {"foreground": fg}
            if bg: kw["background"] = bg
            self.tree_style.tag_configure(tag, **kw)
        self.tree_style.pack(fill=tk.BOTH, expand=True)

    # ── ZOOM / PAN ────────────────────────────────────────────────────────────
    def _map_reset(self):
        self._map_zoom=1.0; self._map_pan_x=0.; self._map_pan_y=0.
        self._redraw_track(); self._update_map_dots(self._last_snaps)
    def _map_zoom_wheel(self, event):
        self._map_zoom = clamp(self._map_zoom*(1.15 if (event.num==4 or event.delta>0) else 1/1.15), 0.3, 8.0)
        self._redraw_track(); self._update_map_dots(self._last_snaps)
    def _map_drag_start(self, event): self._drag_start=(event.x,event.y)
    def _map_drag_end(self, event):   self._drag_start=None
    def _map_drag_move(self, event):
        if self._drag_start:
            self._map_pan_x+=event.x-self._drag_start[0]
            self._map_pan_y+=event.y-self._drag_start[1]
            self._drag_start=(event.x,event.y)
            self._redraw_track(); self._update_map_dots(self._last_snaps)
    def _world_to_canvas(self,x,y):
        cx=self.map_w/2+(x-self.track_cx)*self.track_scale*self._map_zoom+self._map_pan_x
        cy=self.map_h/2-(y-self.track_cy)*self.track_scale*self._map_zoom+self._map_pan_y
        return cx,cy

    # ════════════════════════════════════════════════════════════════════════
    #  CARGA
    # ════════════════════════════════════════════════════════════════════════
    def _load_calendar(self, year: int) -> None:
        self._set_status(f"Loading {year} calendar…")
        def fetch():
            try:
                sch   = fastf1.get_event_schedule(year, include_testing=False)
                races = sch["EventName"].tolist()
                self.root.after(0, lambda: self.combo_race.configure(values=races))
                if races: self.root.after(0, lambda: self.combo_race.set(races[0]))
                self.root.after(0, lambda: self._set_status("Calendar loaded. Select race and session."))
            except Exception as exc:
                self.root.after(0, lambda: self._set_status(f"Calendar error: {exc}"))
        threading.Thread(target=fetch, daemon=True).start()

    def _start_load(self) -> None:
        race = self.combo_race.get(); sess = self.combo_session.get()
        if not race: messagebox.showwarning("No Race", "Select a race first."); return
        if self._load_thread and self._load_thread.is_alive(): return
        year = int(self.combo_year.get())
        self.session_year = year
        self.btn_load.configure(state=tk.DISABLED)
        self._set_status(f"Downloading {sess} – {race} {year}…"); self._spin(True)
        self._load_thread = threading.Thread(
            target=self._fetch_session, args=(year, race, sess), daemon=True)
        self._load_thread.start()

    def _fetch_session(self, year: int, race: str, sess_type: str) -> None:
        try:
            session = fastf1.get_session(year, race, sess_type)
            session.load(telemetry=True, weather=True, messages=False)
            laps = session.laps

            total_laps = int(laps["LapNumber"].max()) if not laps.empty else 0
            best_s: Optional[float] = None
            try:
                fastest = laps.pick_fastest()
                s = td_to_sec(fastest.get("LapTime"))
                if s is not None: best_s = s
            except Exception:
                pass

            # ── Telemetría ────────────────────────────────────────────────
            telemetry: Dict[str, pd.DataFrame] = {}
            t_min, t_max = float("inf"), 0.

            for drv in session.drivers:
                try:
                    _dl = laps.pick_drivers(drv)
                    if _dl.empty: continue
                    tel = _dl.get_telemetry()
                    if tel.empty: continue
                    tel = df_to_plain(tel)              # romper subclase FastF1
                    tel["TimeSec"] = series_to_float_array(tel["SessionTime"])
                    ts = tel["TimeSec"].values
                    valid = ts[~np.isnan(ts)]
                    if len(valid) == 0: continue
                    if float(valid.min()) < t_min: t_min = float(valid.min())
                    if float(valid.max()) > t_max: t_max = float(valid.max())
                    info = session.get_driver(drv)
                    tel["Team"]   = info.get("TeamName",    "Unknown")
                    tel["Abbr"]   = info.get("Abbreviation", drv)
                    tel["Name"]   = info.get("FullName",     drv)
                    tel["Number"] = info.get("DriverNumber", drv)
                    telemetry[drv] = tel
                except Exception as exc:
                    log.warning("Driver %s: %s", drv, exc)

            if not telemetry:
                raise ValueError("No telemetry. Future or cancelled event?")

            # ── Laps por piloto ───────────────────────────────────────────
            laps_by_driver: Dict[str, pd.DataFrame]  = {}
            laps_times:     Dict[str, np.ndarray]     = {}
            sector_bests:   Dict[str, List[Optional[float]]] = {}
            overall = [None, None, None]

            for drv in telemetry:
                try:
                    dl    = df_to_plain(laps.pick_drivers(drv))
                    t_arr = series_to_float_array(dl["Time"])  # numpy float[], fuera del df
                    laps_by_driver[drv] = dl
                    laps_times[drv]     = t_arr

                    sb = [None, None, None]
                    for s_idx in range(1, 4):
                        col = f"Sector{s_idx}Time"
                        if col not in dl.columns: continue
                        sec_arr = series_to_float_array(dl[col])
                        valid   = sec_arr[~np.isnan(sec_arr)]
                        if len(valid):
                            best = float(valid.min())
                            sb[s_idx-1] = best
                            if overall[s_idx-1] is None or best < overall[s_idx-1]:
                                overall[s_idx-1] = best
                    sector_bests[drv] = sb
                except Exception as exc:
                    log.warning("Laps cache %s: %s", drv, exc)
                    laps_by_driver[drv] = pd.DataFrame()
                    laps_times[drv]     = np.array([], dtype=np.float64)
                    sector_bests[drv]   = [None, None, None]

            # ── Track status — extraer a numpy + lista Python ─────────────
            ts_df     = df_to_plain(session.track_status)
            ts_times  = series_to_float_array(ts_df["Time"])
            ts_status = [str(v) for v in ts_df["Status"].tolist()]

            # ── Weather — extraer a numpy + lista de dicts ────────────────
            wx_df    = df_to_plain(session.weather_data)
            wx_times = series_to_float_array(wx_df["Time"])
            wx_rows  = wx_df.to_dict("records")

            # ── Commit ────────────────────────────────────────────────────
            self.session              = session
            self.telemetry            = telemetry
            self.laps_data            = laps
            self._laps_by_driver      = laps_by_driver
            self._laps_times          = laps_times
            self._ts_times            = ts_times
            self._ts_status           = ts_status
            self._wx_times            = wx_times
            self._wx_rows             = wx_rows
            self.drivers              = list(telemetry.keys())
            self.total_laps           = total_laps
            self.session_best_s       = best_s
            self.session_start        = t_min
            self.max_time             = t_max - t_min
            self.session_type         = sess_type
            self._sector_bests        = sector_bests
            self._overall_sector_best = overall

            self.root.after(0, lambda: self._on_session_loaded(race, year, sess_type))

        except Exception as exc:
            log.exception("Session load failed")
            self.root.after(0, lambda: self._set_status(f"Error: {exc}"))
            self.root.after(0, lambda: self.btn_load.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._spin(False))

    def _on_session_loaded(self, race, year, sess_type) -> None:
        self._spin(False)
        self.time_slider.configure(state=tk.NORMAL, to=self.max_time)
        self.btn_play.configure(state=tk.NORMAL)
        self.btn_prev.configure(state=tk.NORMAL)
        self.btn_next.configure(state=tk.NORMAL)
        self.btn_load.configure(state=tk.NORMAL)
        self.root.update_idletasks()
        self._draw_timeline(); self._draw_track_map()

        si = SESSION_INFO.get(sess_type, (sess_type, TEXT_PRI, BG_CARD))
        self.lbl_track_name.configure(text=f"  {race}  •  {year}  •  {si[0]}")
        self.lbl_map_badge.configure(text=f" ◉ {si[0]} ", bg=si[2], fg=TEXT_PRI)
        self._refresh_badge(sess_type)

        if is_2026_era(year): self.frm_battery.pack(fill=tk.X, pady=(4,0))
        else:                 self.frm_battery.pack_forget()

        for row in self.tree.get_children(): self.tree.delete(row)
        for drv in self.drivers:
            ref  = self.telemetry[drv].iloc[0]
            team = str(ref.get("Team","Unknown"))
            tag  = f"t_{drv}"
            self.tree.tag_configure(tag, foreground=TEAM_COLORS.get(team, TEXT_PRI))
            self.tree.insert("","end", iid=drv,
                values=("–",ref.get("Number","–"),ref.get("Abbr","–"),
                        team,"–","–","–","–","–"), tags=(tag,))
        if self.drivers:
            self.selected_driver = self.drivers[0]
            self.tree.selection_set(self.selected_driver)

        self._set_status(f"Loaded  •  {len(self.drivers)} drivers  •  {self.total_laps} laps  •  {si[0]}")
        self._on_slider(0)

    # ════════════════════════════════════════════════════════════════════════
    #  NUMPY SEARCH HELPERS — NÚCLEO DEL FIX
    # ════════════════════════════════════════════════════════════════════════
    def _last_le(self, arr: np.ndarray, val: float) -> int:
        """Índice del último elemento <= val en arr (puede tener NaN). -1 si ninguno."""
        mask = (~np.isnan(arr)) & (arr <= val)
        idx  = np.where(mask)[0]
        return int(idx[-1]) if len(idx) else -1

    def _first_gt(self, arr: np.ndarray, val: float) -> int:
        """Índice del primer elemento > val en arr. -1 si ninguno."""
        mask = (~np.isnan(arr)) & (arr > val)
        idx  = np.where(mask)[0]
        return int(idx[0]) if len(idx) else -1

    def _ts_at(self, abs_t: float) -> str:
        """Track status en abs_t."""
        if len(self._ts_times) == 0: return "1"
        i = self._last_le(self._ts_times, abs_t)
        return self._ts_status[i] if i >= 0 else "1"

    # ════════════════════════════════════════════════════════════════════════
    #  MAPA
    # ════════════════════════════════════════════════════════════════════════
    def _draw_timeline(self) -> None:
        self.timeline_canvas.delete("all")
        self.timeline_canvas.update_idletasks()
        W = self.timeline_canvas.winfo_width() or 1200
        n = len(self._ts_times)
        if n == 0 or self.max_time <= 0: return
        for i in range(n):
            t0 = clamp(self._ts_times[i]-self.session_start, 0, self.max_time)
            t1 = clamp((self._ts_times[i+1]-self.session_start if i+1<n else self.max_time),
                       0, self.max_time)
            col = TRACK_STATUS.get(self._ts_status[i],("","",BG_CARD))[1]
            self.timeline_canvas.create_rectangle(
                t0/self.max_time*W, 0, t1/self.max_time*W, 8, fill=col, outline="")

    def _draw_track_map(self) -> None:
        self.map_canvas.delete("all")
        try:
            fastest = self.session.laps.pick_fastest()
            tel = fastest.get_telemetry()
            x_vals = np.array(tel["X"].values, dtype=float)
            y_vals = np.array(tel["Y"].values, dtype=float)
            if len(x_vals) < 10: return
            self.map_canvas.update()
            self.map_w = max(self.map_canvas.winfo_width(), 100)
            self.map_h = max(self.map_canvas.winfo_height(), 60)
            mn_x,mx_x = float(np.nanmin(x_vals)),float(np.nanmax(x_vals))
            mn_y,mx_y = float(np.nanmin(y_vals)),float(np.nanmax(y_vals))
            rx=mx_x-mn_x or 1; ry=mx_y-mn_y or 1
            self.track_scale = min(self.map_w/rx, self.map_h/ry)*0.86
            self.track_cx=(mx_x+mn_x)/2; self.track_cy=(mx_y+mn_y)/2
            self._track_x=x_vals; self._track_y=y_vals
            self._redraw_track()
        except Exception as exc:
            log.warning("Track map: %s", exc)

    def _redraw_track(self) -> None:
        if not hasattr(self,"_track_x"): return
        self.map_canvas.delete("track"); self.map_canvas.delete("car_dot")
        pts = []
        for x,y in zip(self._track_x, self._track_y):
            cx,cy = self._world_to_canvas(x,y); pts+=[cx,cy]
        self.map_canvas.create_polygon(pts, outline="#444466", fill="", width=4, tags="track")

    # ════════════════════════════════════════════════════════════════════════
    #  REPRODUCCIÓN
    # ════════════════════════════════════════════════════════════════════════
    def _toggle_play(self) -> None:
        if self.is_playing:
            self.is_playing=False; self.btn_play.configure(text="▶  PLAY")
        else:
            self.is_playing=True; self.btn_play.configure(text="⏸  PAUSE")
            threading.Thread(target=self._play_loop, daemon=True).start()

    def _play_loop(self) -> None:
        tick=0.05; last_ui=0.
        while self.is_playing and self.current_time < self.max_time:
            self.current_time = min(self.current_time+tick*self.playback_speed.get(), self.max_time)
            now = time.monotonic()
            if now-last_ui >= 0.05:
                last_ui=now; t=self.current_time
                self.root.after(0, lambda t=t: self.time_slider.set(t))
            if self.current_time >= self.max_time:
                self.root.after(0, self._toggle_play); break
            time.sleep(tick)

    def _jump(self, delta: float) -> None:
        self.time_slider.set(clamp(self.current_time+delta, 0, self.max_time))

    def _on_slider(self, val) -> None:
        self.current_time = float(val)
        self.lbl_time.configure(text=hms(int(self.current_time)))
        self._update_dashboard(self.current_time)

    def _on_driver_select(self, _event) -> None:
        sel = self.tree.selection()
        if sel: self.selected_driver=sel[0]; self._update_dashboard(self.current_time)

    def _on_session_type_change(self, _=None) -> None:
        self._refresh_badge(self.combo_session.get())

    def _refresh_badge(self, sess_type: str) -> None:
        si = SESSION_INFO.get(sess_type, (sess_type, TEXT_PRI, BG_CARD))
        self.lbl_sess_badge.configure(text=f"◉  {si[0]}", bg=si[2], fg=TEXT_PRI)

    # ════════════════════════════════════════════════════════════════════════
    #  ACTUALIZACIÓN CENTRAL
    # ════════════════════════════════════════════════════════════════════════
    def _update_dashboard(self, elapsed: float) -> None:
        if not self.telemetry: return
        abs_t = self.session_start + elapsed
        self._update_race_status(abs_t)
        self._update_weather(abs_t)
        snaps = self._build_snapshots(abs_t)
        self._compute_gaps(snaps)
        self._last_snaps = snaps
        self._update_leaderboard(snaps)
        self._update_map_dots(snaps)
        self._update_hud(snaps, abs_t)

    def _update_race_status(self, abs_t: float) -> None:
        key = self._ts_at(abs_t); self._current_ts = key
        text,color,bg = TRACK_STATUS.get(key, ("⬜ UNKNOWN", TEXT_SEC, BG_PANEL))
        self.lbl_race_status.configure(text=text, fg=color, bg=bg)
        self.time_slider.configure(troughcolor=color)

    def _update_weather(self, abs_t: float) -> None:
        if len(self._wx_times)==0: return
        i = self._last_le(self._wx_times, abs_t)
        if i < 0: return
        w = self._wx_rows[i]
        rain = "💧 Rain" if w.get("Rainfall") else "☀ Dry"
        self.lbl_weather.configure(
            text=f"Air {round(safe(w.get('AirTemp',0)),1)}°C | "
                 f"Track {round(safe(w.get('TrackTemp',0)),1)}°C | {rain}")

    # ── Snapshots ─────────────────────────────────────────────────────────────
    def _build_snapshots(self, abs_t: float) -> List[Snap]:
        snaps: List[Snap] = []
        for drv, df in self.telemetry.items():
            times  = df["TimeSec"].values
            is_out = bool(abs_t > times[-1])
            idx    = int(min(np.searchsorted(times, abs_t), len(times)-1))
            row    = df.iloc[idx]
            sn = Snap(
                drv=drv, abbr=str(row.get("Abbr",drv)),
                name=str(row.get("Name",drv)), number=str(row.get("Number",drv)),
                team=str(row.get("Team","Unknown")),
                speed=safe(row.get("Speed")), rpm=safe(row.get("RPM")),
                throttle=safe(row.get("Throttle")), brake=safe(row.get("Brake")),
                gear=int(safe(row.get("nGear"))), drs=safe(row.get("DRS")),
                x=safe(row.get("X"), float("nan")), y=safe(row.get("Y"), float("nan")),
                is_out=is_out,
            )
            try:
                t_arr = self._laps_times.get(drv, np.array([]))
                dl    = self._laps_by_driver.get(drv, pd.DataFrame())
                if len(t_arr)>0 and not dl.empty:
                    nxt_i = self._first_gt(t_arr, abs_t)
                    if nxt_i >= 0:
                        r = dl.iloc[nxt_i]
                        sn.pos  = int(safe(r.get("Position"), 999))
                        sn.lap  = int(safe(r.get("LapNumber"), 0))
                        cmpd    = r.get("Compound", None)
                        sn.tyre = (f"({str(cmpd)[0]})"
                                   if cmpd is not None and str(cmpd)!="nan" else "–")
                    sn.dist = sn.lap*5_000 + safe(row.get("Distance"))
            except Exception:
                pass
            if is_out: sn.dist = -1.
            snaps.append(sn)
        return snaps

    def _compute_gaps(self, snaps: List[Snap]) -> None:
        snaps.sort(key=lambda s: (s.pos if s.pos<900 else 999, -s.dist))
        leader = next((s.dist for s in snaps if s.dist>=0), 0.)
        for i,s in enumerate(snaps):
            if s.is_out or s.dist<0:
                s.gap,s.interval,s.gap_num,s.int_num = "OUT","OUT",999.,999.
            elif i==0:
                s.gap,s.interval,s.gap_num,s.int_num = "LEAD","LEAD",0.,0.
            else:
                ms=max(10.,s.speed/3.6)
                g =clamp((leader-s.dist)/ms, 0, 999)
                ip=clamp((snaps[i-1].dist-s.dist)/ms, 0, 999)
                s.gap      = f"+{g:.1f}s"  if g<120  else "+1 Lap"
                s.interval = f"+{ip:.1f}s" if ip<120 else "+1 Lap"
                s.gap_num,s.int_num = g,ip

    def _update_leaderboard(self, snaps: List[Snap]) -> None:
        max_lap = 0
        for i,s in enumerate(snaps):
            if s.lap>max_lap: max_lap=s.lap
            if not self.tree.exists(s.drv): continue
            self.tree.item(s.drv, values=(
                "–" if s.is_out else str(i+1),
                s.number,s.abbr,s.team,s.gap,s.interval,
                "OUT" if s.is_out else str(int(s.speed)),s.tyre,s.lap))
            self.tree.move(s.drv,"",i)
        self.lbl_laps.configure(text=f"LAP {max_lap} / {self.total_laps}")

    def _update_map_dots(self, snaps: List[Snap]) -> None:
        self.map_canvas.delete("car_dot")
        for s in snaps:
            if s.is_out or math.isnan(s.x) or math.isnan(s.y): continue
            cx,cy = self._world_to_canvas(s.x,s.y)
            col  = TEAM_COLORS.get(s.team, TEXT_PRI)
            sel  = s.drv==self.selected_driver; size=9 if sel else 5
            self.map_canvas.create_oval(cx-size,cy-size,cx+size,cy+size,
                fill=col, outline="#fff" if sel else col, width=2, tags="car_dot")
            if sel:
                self.map_canvas.create_text(cx,cy-size-8,text=s.abbr,
                    fill=col,font=(FONT,8,"bold"),tags="car_dot")

    # ════════════════════════════════════════════════════════════════════════
    #  HUD
    # ════════════════════════════════════════════════════════════════════════
    def _update_hud(self, snaps: List[Snap], abs_t: float) -> None:
        drv = self.selected_driver
        if drv is None: return
        snap = next((s for s in snaps if s.drv==drv), None)
        if snap is None: return

        col = TEAM_COLORS.get(snap.team, TEXT_PRI)
        self.lbl_driver_name.configure(text=f"{snap.name}  #{snap.number}", fg=col)
        self.lbl_team_name.configure(text=snap.team)
        self.hud_canvas.itemconfigure("rpm_arc",   extent=-clamp(snap.rpm/MAX_RPM,0,1)*180)
        self.hud_canvas.itemconfigure("thr_arc",   extent=-clamp(snap.throttle/100,0,1)*135)
        self.hud_canvas.itemconfigure("brk_arc",   extent=45 if snap.brake>0 else 0)
        self.hud_canvas.itemconfigure("speed_val", text=str(int(snap.speed)))
        self.hud_canvas.itemconfigure("rpm_val",   text=f"{int(snap.rpm):,} RPM")
        self.hud_canvas.itemconfigure("gear_val",  text="N" if snap.gear==0 else str(snap.gear))
        drs_on = int(safe(snap.drs)) in DRS_ACTIVE_VALUES
        self.hud_canvas.itemconfigure("drs_val",
            text="DRS  OPEN" if drs_on else "DRS  CLOSED",
            fill=GREEN if drs_on else TEXT_SEC)

        idx = next((i for i,s in enumerate(snaps) if s.drv==drv), -1)
        if idx>=0:
            ahead  = snaps[idx-1] if idx>0 else None
            behind = snaps[idx+1] if idx<len(snaps)-1 else None
            self.lbl_gap_ahead.configure(
                text=f"{ahead.abbr if ahead else 'LEADER'}  {snap.interval if idx>0 else ''}")
            self.lbl_gap_behind.configure(
                text=f"{behind.abbr if behind else '–'}  {behind.interval if behind else ''}")

        self._update_style_battle(snap,abs_t,drv,snaps,idx)
        self._update_analysis(snap,drv,abs_t)
        self._update_telemetry_plot(drv,abs_t)
        if is_2026_era(self.session_year):
            self._update_battery(snap,abs_t,drv)

    def _update_style_battle(self, snap, abs_t, drv, snaps, idx) -> None:
        df=self.telemetry[drv]; times=df["TimeSec"].values
        i_now=int(min(np.searchsorted(times,abs_t),len(times)-1))
        Δspd=snap.speed-safe(df.iloc[max(0,i_now-5)].get("Speed"))
        use_2026=is_2026_era(self.session_year)

        style,sc="NORMAL",TEXT_SEC
        if snap.throttle==0 and snap.brake==0 and snap.speed>180 and Δspd<0:
            style,sc="LIFT & COAST",ACCENT2
        elif use_2026 and snap.throttle>=95 and snap.brake==0 and snap.speed>250 \
                and snap.rpm>10_500 and Δspd<-1.5:
            style,sc="⚠ SUPERCLIPPING (ERS cut)",PURPLE
        elif not use_2026 and snap.throttle>=95 and snap.brake==0 \
                and snap.rpm>11_000 and Δspd<-1.2:
            style,sc="ENGINE LIMITER / ICE CLIP",ORANGE
        elif snap.throttle>=95 and snap.brake==0: style,sc="FULL THROTTLE",GREEN
        elif snap.brake>60:                       style,sc="HEAVY BRAKING",ACCENT
        elif snap.brake>0 and snap.throttle>0:    style,sc="TRAIL BRAKING",YELLOW
        elif 20<snap.throttle<95:                 style,sc="ROLLING THROTTLE",ORANGE
        self.lbl_style.configure(text=f"STYLE: {style}", fg=sc)

        battle,bc="CLEAR",TEXT_SEC
        if idx<len(snaps)-1:
            behind=snaps[idx+1]
            if behind.int_num<=3.:
                battle,bc=(f"🟦 YIELDING → {behind.abbr}",ACCENT2) \
                    if behind.lap>snap.lap else (f"🛡 DEFENDING ← {behind.abbr}",ORANGE)
        if idx>0:
            ahead=snaps[idx-1]
            if snap.int_num<=3.:
                if snap.lap>ahead.lap:    battle,bc=f"🟦 LAPPING {ahead.abbr}",ACCENT2
                elif snap.int_num<=1.:    battle,bc=f"⚔ OVERTAKING {ahead.abbr}",ACCENT
                else:                     battle,bc=f"⚔ BATTLING {ahead.abbr}",ORANGE
        self.lbl_battle.configure(text=f"TRACK: {battle}", fg=bc)

    def _update_battery(self, snap, abs_t, drv) -> None:
        df=self.telemetry[drv]; times=df["TimeSec"].values
        i_now=int(min(np.searchsorted(times,abs_t),len(times)-1))
        window=df.iloc[max(0,i_now-20):i_now+1]
        if len(window)<2: return
        dt=np.diff(window["TimeSec"].values)
        thr=window["Throttle"].values[1:]; brk=window["Brake"].values[1:]
        spd=window["Speed"].values[1:]
        deploy=float(np.sum(dt*(thr>=95)*(spd>200)*120))
        regen =float(np.sum(dt*(brk>0)*60))
        pct   =clamp(50+(clamp(regen-deploy,-4000,4000)/4000)*50, 0, 100)
        W=self.cvs_battery.winfo_width() or 200
        self.cvs_battery.delete("all")
        fill_w=int(W*pct/100)
        col=GREEN if pct>60 else YELLOW if pct>30 else ACCENT
        self.cvs_battery.create_rectangle(0,0,fill_w,18,fill=col,outline="")
        self.cvs_battery.create_text(W//2,9,text=f"{pct:.0f}%",fill=TEXT_PRI,font=(FONT,8,"bold"))
        self.lbl_battery_val.configure(text=f"ERS deploy: {deploy:.0f} kJ  |  regen: {regen:.0f} kJ")

    # ════════════════════════════════════════════════════════════════════════
    #  ANÁLISIS
    # ════════════════════════════════════════════════════════════════════════
    def _update_analysis(self, snap: Snap, drv: str, abs_t: float) -> None:
        df    = self.telemetry[drv]
        dl    = self._laps_by_driver.get(drv, pd.DataFrame())
        t_arr = self._laps_times.get(drv, np.array([]))
        if dl.empty or len(t_arr)==0: return

        # Índices con numpy puro — cero indexing booleano de pandas
        comp_idx = np.where((~np.isnan(t_arr)) & (t_arr <= abs_t))[0]
        next_idx = np.where((~np.isnan(t_arr)) & (t_arr >  abs_t))[0]

        ts_txt,ts_fg,_ = TRACK_STATUS.get(self._current_ts, ("GREEN",GREEN,""))
        self.lbl_track_cond.configure(text=f"Track: {ts_txt}", fg=ts_fg)
        for row in self.tree_sec.get_children(): self.tree_sec.delete(row)

        if len(next_idx)>0:
            cur = dl.iloc[int(next_idx[0])].to_dict()

            # Contar pits iterando en Python — sin bool indexing
            pits = 0
            if "PitOutTime" in dl.columns:
                for v in dl["PitOutTime"]:
                    if td_to_sec(v) is not None: pits+=1

            self.lbl_tyre.configure(
                text=f"Tyre: {cur.get('Compound','—')}  |  "
                     f"Age: {cur.get('TyreLife','—')} laps  |  Pits: {pits}")

            # Vuelta anterior: buscar por LapNumber en Python
            cur_lap_num = cur.get("LapNumber", 0)
            prev_row = None
            for i in range(len(dl)):
                if dl.iloc[i].get("LapNumber") == cur_lap_num-1:
                    prev_row = dl.iloc[i].to_dict(); break

            lt_s    = td_to_sec(cur.get("LapTime"))
            t_end_f = t_arr[int(next_idx[0])]
            lap_start_abs = None
            if lt_s is not None and not math.isnan(t_end_f):
                lap_start_abs = self.session_start + t_end_f - lt_s

            for s_idx in range(1,4):
                col    = f"Sector{s_idx}Time"
                cur_s  = td_to_sec(cur.get(col))   or 0.
                prev_s = (td_to_sec(prev_row.get(col)) if prev_row else None) or 0.
                diff   = cur_s-prev_s if cur_s and prev_s else 0.

                verdict="–"
                if cur_s and prev_s:
                    if diff<=-0.3:   verdict="FLYING LAP ↑"
                    elif diff<=-0.1: verdict="On it ▲"
                    elif diff<=0.1:  verdict="On Pace"
                    elif diff<=0.4:  verdict="Gap ▼"
                    else:            verdict="Dropping Back ↓"

                sec_cond = ("1" if lap_start_abs is None
                            else self._ts_at(lap_start_abs+cur_s*(s_idx-1)))
                cond_lbl = {"1":"GREEN","2":"YELLOW","3":"SC YEL","4":"SC",
                            "5":"RED","6":"VSC","7":"VSC END"}.get(sec_cond,"GREEN")

                if   sec_cond=="4":        row_tag="sc_active"
                elif sec_cond=="6":        row_tag="vsc_active"
                elif sec_cond in("2","3"): row_tag="yellow_sec"
                elif sec_cond=="5":        row_tag="red_flag"
                elif not cur_s:            row_tag="f1_white"
                elif (cur_s and self._overall_sector_best[s_idx-1] and
                      abs(cur_s-self._overall_sector_best[s_idx-1])<0.05):
                    row_tag="f1_purple"
                elif diff<-0.05:           row_tag="f1_green"
                elif diff>0.05:            row_tag="f1_yellow"
                else:                      row_tag="f1_white"

                self.tree_sec.insert("","end",
                    values=(f"S{s_idx}",
                            f"{cur_s:.3f}" if cur_s else "–",
                            f"{diff:+.3f}" if diff else "–",
                            verdict, cond_lbl),
                    tags=(row_tag,))

        # ── Pace ─────────────────────────────────────────────────────────────
        pace_txt,pace_col="–",TEXT_SEC; last_str,delta_str="–","–"
        diag_parts: List[str] = []

        if len(comp_idx)>0:
            last_row = dl.iloc[int(comp_idx[-1])].to_dict()
            ll_s     = td_to_sec(last_row.get("LapTime"))
            if ll_s is not None:
                last_str=fmt_lap(ll_s)
                if self.session_best_s:
                    delta_str=f"{ll_s-self.session_best_s:+.3f}s"
                prev5=comp_idx[max(0,len(comp_idx)-6):len(comp_idx)-1]
                if len(prev5)>0:
                    avgs=[td_to_sec(dl.iloc[int(i)].get("LapTime")) for i in prev5]
                    avgs=[v for v in avgs if v is not None]
                    if avgs:
                        avg=sum(avgs)/len(avgs); diff=ll_s-avg
                        pace_txt=(f"IMPROVING ({diff:+.2f}s)" if diff<0
                                  else f"DROPPING ({diff:+.2f}s)")
                        pace_col=GREEN if diff<0 else ACCENT

        self.lbl_pace.configure(text=f"Pace (5L avg): {pace_txt}", fg=pace_col)
        self.lbl_last_lap.configure(
            text=f"Last: {last_str}  ({delta_str})  |  Best: "
                 f"{fmt_lap(self.session_best_s) if self.session_best_s else '–'}")

        # ── Style history ─────────────────────────────────────────────────────
        for row in self.tree_style.get_children(): self.tree_style.delete(row)

        for ci in (comp_idx[-10:] if len(comp_idx)>0 else []):
            try:
                lr    = dl.iloc[int(ci)].to_dict()
                lap_s = td_to_sec(lr.get("LapTime"))
                if lap_s is None: continue
                t_end_f = t_arr[int(ci)]
                if math.isnan(t_end_f): continue
                l_start=t_end_f-lap_s; l_end=t_end_f

                ts_vals=df["TimeSec"].values
                # Filtro numpy puro sobre array nativo
                mask  = (ts_vals>=l_start)&(ts_vals<=l_end)
                chunk = df.iloc[np.where(mask)[0]].copy()
                n=len(chunk)
                if n<10: continue

                chunk["dSpd"]=chunk["Speed"].diff(3)
                lico=int(np.sum((chunk["Throttle"]==0)&(chunk["Brake"]==0)&
                                (chunk["Speed"]>180)&(chunk["dSpd"]<0)))
                push=int(np.sum((chunk["Throttle"]>=95)&(chunk["Brake"]==0)&
                                (chunk["dSpd"]>=-1.5)))
                brk =int(np.sum(chunk["Brake"]>60))

                if is_2026_era(self.session_year):
                    clip=int(np.sum((chunk["Throttle"]>=95)&(chunk["Brake"]==0)&
                                    (chunk["Speed"]>250)&(chunk["RPM"]>10_500)&
                                    (chunk["dSpd"]<-1.5)))
                    diag_parts.append(f"L{int(lr.get('LapNumber',0))}: clip={clip/n*100:.1f}%")
                else:
                    clip=int(np.sum((chunk["Throttle"]>=95)&(chunk["Brake"]==0)&
                                    (chunk["RPM"]>11_000)&(chunk["dSpd"]<-1.2)))

                p_lico=lico/n*100; p_clip=clip/n*100
                p_push=push/n*100; p_brk=brk/n*100
                lap_str=fmt_lap(lap_s)
                db=f"{lap_s-self.session_best_s:+.3f}" if self.session_best_s else ""
                cond_key=self._ts_at((l_start+l_end)/2)
                cond_lbl={"1":"GREEN","2":"YELLOW","3":"SC YEL","4":"SC",
                          "5":"RED","6":"VSC","7":"END"}.get(cond_key,"GREEN")

                if cond_key=="4":      tag="sc_lap"
                elif cond_key=="6":    tag="vsc_lap"
                elif cond_key in("2","3"): tag="yellow_lap"
                elif cond_key=="5":    tag="red_lap"
                elif p_clip>1.5:       tag="high_clip"
                elif self.session_best_s and abs(lap_s-self.session_best_s)<0.1: tag="f1_purple"
                elif db and float(db)<-0.3: tag="f1_green"
                elif db and float(db)>0.5:  tag="f1_yellow"
                else:                       tag="f1_white"

                self.tree_style.insert("",0,
                    values=(int(lr.get("LapNumber",0)),
                            f"{p_lico:.1f}%",f"{p_clip:.1f}%",
                            f"{p_push:.1f}%",f"{p_brk:.1f}%",
                            lap_str,db,cond_lbl), tags=(tag,))
            except Exception:
                pass

        self.lbl_diag.configure(
            text=("Clipping: "+"  ".join(diag_parts[-3:])) if diag_parts
            else "Behaviour: Normal — no anomalies detected")

    # ════════════════════════════════════════════════════════════════════════
    #  TELEMETRY PLOT
    # ════════════════════════════════════════════════════════════════════════
    def _update_telemetry_plot(self, drv: str, abs_t: float) -> None:
        c=self.plot_canvas; c.delete("all"); c.update_idletasks()
        W=c.winfo_width(); H=c.winfo_height()
        if W<50 or H<20: return
        try:
            df    = self.telemetry[drv]
            dl    = self._laps_by_driver.get(drv, pd.DataFrame())
            t_arr = self._laps_times.get(drv, np.array([]))
            if dl.empty or len(t_arr)==0: return

            nxt_i=self._first_gt(t_arr, abs_t)
            if nxt_i<0: return
            cur=dl.iloc[nxt_i].to_dict()
            lap_num=cur.get("LapNumber",0)
            t_end_f=t_arr[nxt_i]
            if math.isnan(t_end_f): return

            # Vuelta anterior por LapNumber
            prev_lt=None; prev_end=None
            for i in range(len(dl)):
                if dl.iloc[i].get("LapNumber")==lap_num-1:
                    prev_lt=td_to_sec(dl.iloc[i].get("LapTime")); prev_end=t_arr[i]; break

            if prev_lt is not None and prev_end is not None and not math.isnan(prev_end):
                l_start=prev_end-prev_lt; l_end=prev_end
            else:
                l_start=abs_t-90; l_end=abs_t

            ts_vals=df["TimeSec"].values
            idx_mask=np.where((ts_vals>=l_start)&(ts_vals<=l_end))[0]
            chunk=df.iloc[idx_mask]
            if len(chunk)<5: return

            times=chunk["TimeSec"].values
            speeds=np.nan_to_num(chunk["Speed"].values)
            throttle=np.nan_to_num(chunk["Throttle"].values)
            brake=np.nan_to_num(chunk["Brake"].values)
            t_span=l_end-l_start
            if t_span<=0: return

            cursor_rel=clamp((abs_t-l_start)/t_span, 0, 1)
            cursor_x=int(cursor_rel*W)

            prev_tx=0
            for i,(thr,brk) in enumerate(zip(throttle,brake)):
                tx=int((times[i]-l_start)/t_span*W)
                bg="#001a00" if (thr>=95 and brk==0) else "#1a0000" if brk>0 else "#080810"
                c.create_rectangle(prev_tx,0,tx,H,fill=bg,outline=""); prev_tx=tx

            for pct in (100,50,0):
                c.create_line(0,H-int(H*pct/300),W,H-int(H*pct/300),fill="#1a1a3a",width=1)

            spd_pts=[]
            for t,v in zip(times,speeds):
                spd_pts+=[int((t-l_start)/t_span*W), H-int(clamp(v/350,0,1)*H)]
            if len(spd_pts)>=4: c.create_line(spd_pts,fill=F1_WHITE,width=2,smooth=True)

            thr_pts=[]
            for t,v in zip(times,throttle):
                thr_pts+=[int((t-l_start)/t_span*W), H-int(clamp(v/100,0,1)*H)]
            if len(thr_pts)>=4: c.create_line(thr_pts,fill=GREEN,width=2,smooth=True)

            for t,v in zip(times,brake):
                if v>0:
                    x1=int((t-l_start)/t_span*W)
                    c.create_rectangle(x1,0,x1+2,8,fill=ACCENT,outline="")

            c.create_line(cursor_x,0,cursor_x,H,fill=YELLOW,width=2,dash=(4,3))

            ci=min(int(cursor_rel*(len(times)-1)),len(times)-1)
            thr_c=throttle[ci]; brk_c=brake[ci]; spd_c=speeds[ci]
            mode=("L&C"   if thr_c==0 and brk_c==0 and spd_c>180
                  else "WOT"   if thr_c>=95 and brk_c==0
                  else "BRK"   if brk_c>60
                  else "TRAIL" if brk_c>0 and thr_c>0 else "")
            if mode:
                c.create_text(min(cursor_x+4,W-40),14,text=mode,
                              fill=YELLOW,font=(FONT,8,"bold"),anchor="w")

            for sr in (100,200,300):
                c.create_text(4,H-int(sr/350*H),text=f"{sr}",
                              fill=TEXT_SEC,font=(FONT,7),anchor="w")
            c.create_text(W-4,6,text=f"LAP {int(lap_num)-1}",
                          fill=TEXT_SEC,font=(FONT,8,"bold"),anchor="ne")
        except Exception as exc:
            log.debug("Plot: %s", exc)

    # ── UTILS ─────────────────────────────────────────────────────────────────
    def _set_status(self, msg: str) -> None:
        self.lbl_status.configure(text=msg)

    def _spin(self, active: bool) -> None:
        frames=["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        self._sf=getattr(self,"_sf",0)
        if not active: self.lbl_spin.configure(text=""); return
        def tick():
            if self.btn_load["state"]==tk.DISABLED:
                self._sf=(self._sf+1)%len(frames)
                self.lbl_spin.configure(text=frames[self._sf])
                self.root.after(80,tick)
            else: self.lbl_spin.configure(text="")
        tick()


# ════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
def main() -> None:
    root = tk.Tk()
    try: root.iconbitmap("f1.ico")
    except Exception: pass
    app = F1Dashboard(root)
    root.protocol("WM_DELETE_WINDOW",
                  lambda: (setattr(app,"is_playing",False), root.destroy()))
    root.mainloop()

if __name__ == "__main__":
    main()