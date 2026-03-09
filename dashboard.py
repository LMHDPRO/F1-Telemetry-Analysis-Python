"""
F1 Pro Dashboard  v4.4  — ERS 2026 + Plot mejorado + PIT events
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FIXES v4.4.0:
  · BUG: "#ffffff55" → tkinter no soporta alfa en hex; reemplazado por blanco sólido.
  · FIX: Weather label redimensionado para caber correctamente.
  · FIX: Deploy/Regen en Race Administration ahora muestran kW instantáneo (no kJ acumulado).
  · FIX: Superclipping detectado por RPM sin bajar + velocidad bajando (no solo SOC).
  · NUEVO: Barra de desgaste de neumático en Race Administration (negro→color según laps).
  · NUEVO: Sectors vs Previous Lap fusionado con Pace & Analysis en panel único mejorado.
  · NUEVO: Tyre/Age/Pits movidos a Race Administration; columna Avg Sector en panel análisis.
  · NUEVO: Tabla de sectores ampliada: S/Time/Δ/Verdict/Cond + Tyre + AvgS.
FIXES v4.3.0:
  · BUG CRÍTICO: cur_lap_i se usaba ANTES de ser definido → tyre/compound
    nunca se asignaba, lo que rompía Interval, Gap y Compound display.
  · BUG: Fallback pit detection (speed<=82) causaba falsos positivos
    en chicanes. Ahora solo activa si PitInTime data confirma.
  · ERS 2026: Modelo físico corregido — regen en frenadas 350 kW (no 170).
    Superclipping: cuando SOC=0 en WOT el ICE intenta recargar → se detecta
    y muestra en telemetry plot con icono "⚡SC" en banda superior.
  · TELEMETRY PLOT: Banda superior con iconos SM/OM/SC/LC en lugar de
    solo colores. Marcador de superclipping en rojo pulsante.
  · PIT EVENTS: Notificación de cambio de compuesto arreglada (usaba
    tyre_prev con idx erróneo). Banner PIT LIMITER solo en Race Administration.
  · OUT LAP / IN LAP / PUSH LAP: lógica corregida en Qualy y FP.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import tkinter as tk
from tkinter import ttk, Canvas, messagebox
import threading
import queue
import time
import os
import math
import logging
import urllib.request
import json
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field

import fastf1
import pandas as pd
import numpy as np

# ─── LOGGING ─────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("F1v43")

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

def _drs_is_open(drs_val: float) -> bool:
    v = int(safe(drs_val, 0))
    return v in DRS_ACTIVE_VALUES or (v > 8 and v % 2 == 0)

def _norm_brake(brk_raw) -> float:
    v = float(safe(brk_raw, 0.0))
    return v * 100.0 if v <= 1.0 else v

MAX_RPM  = 13_500
PLOT_WIN = 300

# ─── ERS 2026 ────────────────────────────────────────────────────────────────
# Reglamento 2026: 50/50 ICE-ERS. Deploy máximo ~350 kW en rectas.
# Regen en frenadas: ~350 kW (MGU-K máximo bajo frenada pesada).
# Batería total ~4 MJ (≈1111 Wh).
ERS_CAPACITY_KJ    = 4000.0   # kJ (4 MJ total usable)
ERS_DEPLOY_KW      = 350.0    # kW deployment máximo en rectas WOT
ERS_REGEN_BRAKE_KW = 350.0    # kW recuperación bajo frenada intensa (2026: igual que deploy)
ERS_REGEN_COAST_KW =  40.0    # kW recuperación en L&C (MGU-H+K baja)
ERS_DEPLOY_SPD_MIN = 200.0    # km/h mínimo para deploy completo
# Superclipping 2026: cuando SOC → 0 en throttle>=95, el ICE recorta potencia
# para intentar recargar → velocidad cae aunque el piloto tenga WOT.
ERS_CLIP_SOC_THRESH = 5.0     # % por debajo del cual ocurre clipping


# ═══════════════════════════════════════════════════════════════════════
#  QUEUE DE UN SOLO SLOT — descarta frames viejos automáticamente
# ═══════════════════════════════════════════════════════════════════════
class DropQueue:
    """Queue que siempre contiene como máximo 1 item (el más reciente)."""
    def __init__(self):
        self._q: queue.Queue = queue.Queue(maxsize=1)

    def put_nowait(self, item):
        try:
            self._q.get_nowait()
        except queue.Empty:
            pass
        try:
            self._q.put_nowait(item)
        except queue.Full:
            pass

    def get(self, timeout=0.1):
        return self._q.get(timeout=timeout)

    def empty(self):
        return self._q.empty()


# ─── HELPERS ─────────────────────────────────────────────────────────────────
def safe(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
        return default if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return default

def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def fmt_lap(s: float) -> str:
    try:
        if pd.isna(s) or s <= 0: return "--:--.---"
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


# ─── FIX CRÍTICO: td_to_float SIN tocar .tz ────────────────────────────────
def td_to_float(td) -> float:
    if td is None:
        return float('nan')
    try:
        tn = type(td).__name__
        if tn == "NaTType":
            return float('nan')
    except Exception:
        pass
    try:
        s = td.total_seconds()
        if math.isnan(s) or math.isinf(s):
            return float('nan')
        return float(s)
    except AttributeError:
        pass
    try:
        return float(pd.Timedelta(td).total_seconds())
    except Exception:
        return float('nan')


# ─── FIX CRÍTICO: strip_fastf1 ────────────────────────────────────────────────
def strip_fastf1(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    result: Dict[str, np.ndarray] = {}
    for col in df.columns:
        arr = df[col]
        dtype = arr.dtype

        if pd.api.types.is_timedelta64_dtype(dtype):
            ns = arr.values.view(np.int64).astype(float)
            nat_mask = (ns == np.iinfo(np.int64).min)
            secs = ns / 1e9
            secs[nat_mask] = float('nan')
            result[col] = secs

        elif pd.api.types.is_datetime64_any_dtype(dtype):
            try:
                if hasattr(arr, 'dt'):
                    ns = arr.dt.view(np.int64).to_numpy().astype(float)
                else:
                    ns = np.array(arr.values.astype(np.int64), dtype=float)
                nat_mask = (ns == np.iinfo(np.int64).min)
                secs = ns / 1e9
                secs[nat_mask] = float('nan')
                result[col] = secs
            except Exception:
                result[col] = arr.to_numpy(dtype=object, na_value=float('nan'))

        else:
            try:
                result[col] = arr.to_numpy()
            except Exception:
                result[col] = arr.values

    return pd.DataFrame(result)


def add_timesec_col(df: pd.DataFrame, col: str = "Time") -> pd.DataFrame:
    df_pure = strip_fastf1(df)
    if not df_pure.empty and col in df_pure.columns:
        vals = df_pure[col].to_numpy(dtype=float)
        df_pure["TimeSec_f"] = vals
    return df_pure


def _simulate_ers_segment(soc_kj: float,
                           thr: np.ndarray, brk: np.ndarray,
                           spd: np.ndarray, rpm: np.ndarray,
                           dt: np.ndarray) -> tuple:
    """
    Simula el SOC de la batería ERS 2026 sobre un segmento de telemetría.

    Física 2026 (50/50 ICE-ERS):
    · Deploy: solo en WOT (thr>=95) + spd >= 200 km/h.
    · Regen frenada: hasta 350 kW bajo frenada intensa (igual que deploy).
    · Regen parcial: throttle parcial 20-80 + velocidad media.
    · Regen L&C: cuando thr=0, brk=0, spd>80.
    · Regen MGU-H (turbo): activo incluso en WOT en rectas (~40 kW a max RPM).

    Superclipping: cuando SOC <= CLIP_THRESH en WOT → ICE intenta recargar
    cortando el boost eléctrico (deploy=0). Velocidad cae en plena recta.

    Devuelve (soc_kj, deploy_acum_kj, regen_acum_kj, is_clipping).
    """
    deploy_acc = 0.0
    regen_acc  = 0.0
    clip_flag  = False
    n = len(dt)

    th = thr[1:n+1]; bk = brk[1:n+1]
    sp = spd[1:n+1]; rp = rpm[1:n+1]

    # ── Deploy ────────────────────────────────────────────────────────────
    on_straight = (th >= 95) & (bk == 0) & (sp >= ERS_DEPLOY_SPD_MIN)
    spd_factor  = np.clip((sp - ERS_DEPLOY_SPD_MIN) / (320.0 - ERS_DEPLOY_SPD_MIN), 0, 1)
    d_kw_arr    = ERS_DEPLOY_KW * (0.4 + 0.6 * spd_factor) * on_straight

    # ── Regen frenada (350 kW máximo = mismo que deploy en 2026) ─────────
    braking     = bk > 20
    r_brk_arr   = ERS_REGEN_BRAKE_KW * np.clip(bk / 100.0, 0, 1) * braking

    # ── Regen parcial (rolling throttle / curvas) ─────────────────────────
    partial_thr = (th >= 5) & (th < 80) & (bk == 0) & (sp > 80)
    r_part_arr  = 60.0 * (1.0 - th / 80.0) * partial_thr

    # ── Regen L&C ─────────────────────────────────────────────────────────
    coast       = (th == 0) & (bk == 0) & (sp > 80)
    r_coast_arr = ERS_REGEN_COAST_KW * coast

    # ── Regen MGU-H (turbo recovery) — activo incluso en WOT ─────────────
    mgu_h_mask  = rp > 6000
    r_mgu_h_arr = 40.0 * np.clip((rp - 6000.0) / (MAX_RPM - 6000.0), 0, 1) * mgu_h_mask

    # ── Simular paso a paso ────────────────────────────────────────────────
    for k in range(n):
        dk    = float(dt[k])
        d_kw  = float(d_kw_arr[k])
        r_kw  = float(r_brk_arr[k] + r_part_arr[k] + r_coast_arr[k] + r_mgu_h_arr[k])
        soc_pct = (soc_kj / ERS_CAPACITY_KJ) * 100.0

        if on_straight[k]:
            if soc_pct <= ERS_CLIP_SOC_THRESH:
                # Superclipping: ICE intenta recargar → no hay deploy eléctrico
                d_kw = 0.0
                clip_flag = True
                # En superclipping el MGU-H sigue regenerando desde turbo
                net = float(r_mgu_h_arr[k]) * dk
            else:
                clip_flag = False
                net = float(r_mgu_h_arr[k]) * dk - d_kw * dk
        else:
            clip_flag = False
            net = r_kw * dk

        soc_kj = float(np.clip(soc_kj + net, 0.0, ERS_CAPACITY_KJ))
        if on_straight[k] and d_kw > 0:
            deploy_acc += d_kw * dk
        if net > 0:
            regen_acc += net

    return soc_kj, deploy_acc, regen_acc, clip_flag


# ─── SNAPSHOT ────────────────────────────────────────────────────────────────
@dataclass
class Snap:
    drv:      str   = ""
    abbr:     str   = ""
    name:     str   = ""
    number:   str   = ""
    team:     str   = "Unknown"
    pos:      int   = 999
    lap:      int   = 0
    gap:      str   = "–"
    interval: str   = "–"
    gap_num:  float = 999.
    int_num:  float = 999.
    speed:    float = 0.
    rpm:      float = 0.
    throttle: float = 0.
    brake:    float = 0.
    gear:     int   = 0
    drs:      float = 0.
    straight_mode:  bool  = False
    overtake_mode:  bool  = False
    tyre:     str   = "–"
    tyre_prev:str   = "–"
    dist:     float = -1.
    is_out:   bool  = False
    x:        float = float("nan")
    y:        float = float("nan")
    # ERS 2026
    ers_soc:       float = 50.0
    ers_deploy_kw: float = 0.0
    ers_regen_kw:  float = 0.0
    is_clipping:   bool  = False
    # Pit status
    in_pit:       bool  = False
    pit_out_lap:  bool  = False
    lap_type:     str   = ""   # "PUSH", "OUT LAP", "IN LAP", ""


# ═══════════════════════════════════════════════════════════════════════════════
#  WORKER DE CÁLCULO — corre en hilo separado
# ═══════════════════════════════════════════════════════════════════════════════
class SnapshotWorker(threading.Thread):
    def __init__(self, dashboard: "F1Dashboard"):
        super().__init__(daemon=True, name="SnapshotWorker")
        self.dash   = dashboard
        self.inbox  = DropQueue()
        self._stop  = threading.Event()

    def stop(self):
        self._stop.set()

    def request(self, elapsed: float):
        self.inbox.put_nowait(elapsed)

    def run(self):
        while not self._stop.is_set():
            try:
                elapsed = self.inbox.get(timeout=0.15)
            except queue.Empty:
                continue
            try:
                result = self._compute(elapsed)
                self.dash.root.after(0, lambda r=result, e=elapsed: self.dash._apply_snapshot_result(r, e))
            except Exception as exc:
                log.debug("Worker error: %s", exc)

    def _compute(self, elapsed: float) -> dict:
        dash = self.dash
        abs_t = dash.session_start + elapsed

        # ── Track status ──────────────────────────────────────────────────
        ts_key = "1"
        ts_text, ts_color, ts_bg = TRACK_STATUS.get("1", ("GREEN", GREEN, BG_PANEL))
        if dash.track_status_df is not None and not dash.track_status_df.empty \
                and "TimeSec_f" in dash.track_status_df.columns:
            ts_arr = dash._ts_times
            idx = int(np.searchsorted(ts_arr, abs_t, side='right')) - 1
            if idx >= 0:
                ts_key = str(dash.track_status_df["Status"].iloc[idx])
                ts_text, ts_color, ts_bg = TRACK_STATUS.get(ts_key, ("UNKNOWN", TEXT_SEC, BG_PANEL))

        # ── Weather ───────────────────────────────────────────────────────
        weather_txt = None
        if dash.weather_data is not None and not dash.weather_data.empty \
                and "TimeSec_f" in dash.weather_data.columns:
            wx_arr = dash._wx_times
            idx = int(np.searchsorted(wx_arr, abs_t, side='right')) - 1
            if idx >= 0:
                w = dash.weather_data.iloc[idx]
                rain = "💧 Rain" if w.get("Rainfall") else "☀ Dry"
                weather_txt = (
                    f"Air {round(safe(w.get('AirTemp', 0)), 1)}°C | "
                    f"Track {round(safe(w.get('TrackTemp', 0)), 1)}°C | {rain}"
                )

        # ── Snapshots ─────────────────────────────────────────────────────
        snaps: List[Snap] = []
        for drv, df in dash.telemetry.items():
            times  = dash._tel_times[drv]
            is_out = abs_t > times[-1]
            idx    = int(min(np.searchsorted(times, abs_t), len(times) - 1))

            def gcol(col, default=0.0):
                try:
                    v = df[col].to_numpy()[idx]
                    return safe(v, default)
                except Exception:
                    return default

            def gstr(col, default=""):
                try:
                    return str(df[col].to_numpy()[idx])
                except Exception:
                    return default

            sn = Snap(
                drv      = drv,
                abbr     = gstr("Abbr", drv),
                name     = gstr("Name", drv),
                number   = gstr("Number", drv),
                team     = gstr("Team", "Unknown"),
                speed    = gcol("Speed"),
                rpm      = gcol("RPM"),
                throttle = gcol("Throttle"),
                brake    = _norm_brake(gcol("Brake")),
                gear     = int(gcol("nGear")),
                drs      = gcol("DRS"),
                x        = gcol("X", float("nan")),
                y        = gcol("Y", float("nan")),
                is_out   = is_out,
            )

            # 2026: StraightMode y OvertakeMode
            if "StraightMode" in df.columns:
                sm_raw = df["StraightMode"].to_numpy()[idx]
                sn.straight_mode = bool(sm_raw) if sm_raw == sm_raw else False
            if "OvertakeMode" in df.columns:
                om_raw = df["OvertakeMode"].to_numpy()[idx]
                sn.overtake_mode = bool(om_raw) if om_raw == om_raw else False

            # ── Datos de vuelta ───────────────────────────────────────────
            try:
                dl = dash._laps_by_driver.get(drv, pd.DataFrame())
                if not dl.empty and "TimeSec_f" in dl.columns:
                    lap_times = dash._lap_times[drv]
                    # idx_lap = índice de la SIGUIENTE vuelta (side='right')
                    # la vuelta ACTUAL es idx_lap - 1
                    idx_lap = int(np.searchsorted(lap_times, abs_t, side='right'))

                    # ── FIX: definir cur_lap_i ANTES de usarlo ─────────────
                    cur_lap_i = max(0, idx_lap - 1)

                    if idx_lap < len(lap_times):
                        pos_arr = dl["Position"].to_numpy() if "Position" in dl.columns else None
                        lap_arr = dl["LapNumber"].to_numpy() if "LapNumber" in dl.columns else None
                        cmp_arr = dl["Compound"].to_numpy()  if "Compound"  in dl.columns else None

                        if pos_arr is not None and cur_lap_i < len(pos_arr):
                            sn.pos = int(safe(pos_arr[cur_lap_i], 999))
                        if lap_arr is not None and cur_lap_i < len(lap_arr):
                            sn.lap = int(safe(lap_arr[cur_lap_i], 0))

                        # ── Compound / Tyre ───────────────────────────────
                        if cmp_arr is not None and cur_lap_i < len(cmp_arr):
                            c_raw = str(cmp_arr[cur_lap_i])
                            if c_raw not in ("nan", "None", ""):
                                sn.tyre = f"({c_raw[0].upper()})"
                            # Compuesto anterior (vuelta previa)
                            if cur_lap_i > 0:
                                cp_raw = str(cmp_arr[cur_lap_i - 1])
                                if cp_raw not in ("nan", "None", ""):
                                    sn.tyre_prev = f"({cp_raw[0].upper()})"

                        # ── Pit detection — PRIORIDAD a PitInTime/PitOutTime ──
                        pit_in_arr  = dl["PitInTime"].to_numpy(dtype=float)  if "PitInTime"  in dl.columns else None
                        pit_out_arr = dl["PitOutTime"].to_numpy(dtype=float) if "PitOutTime" in dl.columns else None

                        if pit_in_arr is not None:
                            for li in range(len(pit_in_arr)):
                                pi_t = pit_in_arr[li]
                                po_t = pit_out_arr[li] if pit_out_arr is not None and li < len(pit_out_arr) else float("nan")
                                if not math.isnan(pi_t):
                                    if not math.isnan(po_t):
                                        if pi_t - 2.0 <= abs_t <= po_t + 8.0:
                                            sn.in_pit = True
                                            break
                                    elif abs_t >= pi_t - 2.0 and abs_t <= pi_t + 60.0:
                                        sn.in_pit = True
                                        break

                        # Fallback solo si NO hay datos de pit (sesiones sin PitInTime)
                        # — se activa únicamente si la velocidad es muy baja Y hay datos
                        #   de que el piloto realmente estaba en boxes esa vuelta
                        if not sn.in_pit and pit_in_arr is None:
                            if sn.speed <= 82 and sn.speed > 5 and sn.gear <= 3 and not is_out:
                                sn.in_pit = True

                        # ── Lap type: OUT LAP / IN LAP / PUSH ─────────────
                        if not sn.in_pit:
                            # OUT LAP: pit_out en esta vuelta
                            if pit_out_arr is not None and cur_lap_i < len(pit_out_arr):
                                po_t = pit_out_arr[cur_lap_i]
                                if not math.isnan(po_t):
                                    sn.pit_out_lap = True
                                    sn.lap_type = "OUT LAP"
                            # IN LAP: pit_in en esta vuelta
                            if not sn.lap_type and pit_in_arr is not None and cur_lap_i < len(pit_in_arr):
                                pi_t = pit_in_arr[cur_lap_i]
                                if not math.isnan(pi_t):
                                    sn.lap_type = "IN LAP"
                            # Default PUSH
                            if not sn.lap_type:
                                sn.lap_type = "PUSH"

                    sn.dist = sn.lap * 5_000 + gcol("Distance")

            except Exception as exc:
                log.debug("Lap data drv %s: %s", drv, exc)

            # ── ERS SOC 2026 ──────────────────────────────────────────────
            if dash.session_year >= 2026 and not is_out:
                try:
                    t_arr = times
                    i_now_ers = int(min(np.searchsorted(t_arr, abs_t), len(t_arr)-1))
                    prev_state = dash._ers_state.get(drv)

                    if prev_state is None or abs_t < prev_state[0] - 0.1:
                        si_e = 0
                        ei_e = i_now_ers + 1
                        soc_e = ERS_CAPACITY_KJ * 0.90
                        dep_e = 0.0; reg_e = 0.0; clip_e = False
                        if ei_e - si_e >= 2:
                            thr_e = df["Throttle"].to_numpy()[si_e:ei_e].astype(float)
                            brk_e_raw = df["Brake"].to_numpy()[si_e:ei_e].astype(float)
                            brk_e = np.where(brk_e_raw <= 1.0, brk_e_raw * 100.0, brk_e_raw)
                            spd_e = df["Speed"].to_numpy()[si_e:ei_e].astype(float)
                            rpm_e = df["RPM"].to_numpy()[si_e:ei_e].astype(float) if "RPM" in df.columns else np.zeros(ei_e-si_e)
                            t_e   = t_arr[si_e:ei_e]
                            dt_e  = np.diff(t_e)
                            soc_e, dep_e, reg_e, clip_e = _simulate_ers_segment(
                                soc_e, thr_e, brk_e, spd_e, rpm_e, dt_e)
                    else:
                        prev_t, soc_e, dep_e, reg_e, clip_e = prev_state
                        i_prev_ers = int(np.searchsorted(t_arr, prev_t, side='left'))
                        i_prev_ers = max(0, min(i_prev_ers, len(t_arr)-1))
                        si_e = i_prev_ers
                        ei_e = i_now_ers + 1
                        if ei_e - si_e >= 2:
                            thr_e = df["Throttle"].to_numpy()[si_e:ei_e].astype(float)
                            brk_e_raw = df["Brake"].to_numpy()[si_e:ei_e].astype(float)
                            brk_e = np.where(brk_e_raw <= 1.0, brk_e_raw * 100.0, brk_e_raw)
                            spd_e = df["Speed"].to_numpy()[si_e:ei_e].astype(float)
                            rpm_e = df["RPM"].to_numpy()[si_e:ei_e].astype(float) if "RPM" in df.columns else np.zeros(ei_e-si_e)
                            t_e   = t_arr[si_e:ei_e]
                            dt_e  = np.diff(t_e)
                            soc_e_new, dep_add, reg_add, clip_new = _simulate_ers_segment(
                                soc_e, thr_e, brk_e, spd_e, rpm_e, dt_e)
                            soc_e  = soc_e_new
                            dep_e += dep_add
                            reg_e += reg_add
                            clip_e = clip_new

                    sn.ers_soc       = clamp((soc_e / ERS_CAPACITY_KJ) * 100.0, 0, 100)
                    sn.ers_deploy_kw = dep_e
                    sn.ers_regen_kw  = reg_e
                    sn.is_clipping   = clip_e
                    dash._ers_state[drv] = (abs_t, soc_e, dep_e, reg_e, clip_e)
                except Exception as exc:
                    log.debug("ERS drv %s: %s", drv, exc)

            if is_out:
                sn.dist = -1.
            snaps.append(sn)

        # ── Gaps ──────────────────────────────────────────────────────────
        snaps.sort(key=lambda s: (s.pos if s.pos < 900 else 999, -s.dist))
        leader = next((s.dist for s in snaps if s.dist >= 0), 0.)
        for i, s in enumerate(snaps):
            if s.is_out or s.dist < 0:
                s.gap, s.interval, s.gap_num, s.int_num = "OUT", "OUT", 999., 999.
            elif i == 0:
                s.gap, s.interval, s.gap_num, s.int_num = "LEAD", "LEAD", 0., 0.
            else:
                ms  = max(10., s.speed / 3.6)
                g   = clamp((leader - s.dist) / ms, 0, 999)
                ip  = clamp((snaps[i - 1].dist - s.dist) / ms, 0, 999)
                s.gap      = f"+{g:.1f}s"  if g  < 120 else "+1 Lap"
                s.interval = f"+{ip:.1f}s" if ip < 120 else "+1 Lap"
                s.gap_num, s.int_num = g, ip

        max_lap = max((s.lap for s in snaps), default=0)

        return {
            "elapsed":     elapsed,
            "abs_t":       abs_t,
            "snaps":       snaps,
            "ts_key":      ts_key,
            "ts_text":     ts_text,
            "ts_color":    ts_color,
            "ts_bg":       ts_bg,
            "weather_txt": weather_txt,
            "max_lap":     max_lap,
        }


# ════════════════════════════════════════════════════════════════════════════
#  DASHBOARD
# ════════════════════════════════════════════════════════════════════════════
class F1Dashboard:

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("F1 Pro Dashboard  v4.4  •  Telemetría & Timing")

        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        win_w = max(1280, int(sw * 0.95))
        win_h = max(720,  int(sh * 0.95))
        self.root.geometry(f"{win_w}x{win_h}+{(sw-win_w)//2}+{(sh-win_h)//2}")
        self.root.minsize(1280, 720)
        self._scale = clamp(win_w / 1760.0, 0.72, 1.2)
        self.root.configure(bg=BG_DARK)

        self.session            = None
        self.telemetry:         Dict[str, pd.DataFrame] = {}
        self.laps_data:         Optional[pd.DataFrame]  = None
        self.weather_data:      Optional[pd.DataFrame]  = None
        self.track_status_df:   Optional[pd.DataFrame]  = None
        self.drivers:           List[str] = []
        self.total_laps:        int   = 0
        self.session_best_s:    Optional[float] = None
        self.session_start:     float = 0.
        self.max_time:          float = 0.
        self.session_type:      str   = "R"
        self.session_year:      int   = 2024
        self._current_ts:       str   = "1"

        self._ts_times:  np.ndarray = np.array([])
        self._wx_times:  np.ndarray = np.array([])
        self._tel_times: Dict[str, np.ndarray] = {}
        self._lap_times: Dict[str, np.ndarray] = {}

        self._sector_bests:         Dict[str, List[Optional[float]]] = {}
        self._overall_sector_best:  List[Optional[float]] = [None, None, None]
        self._laps_by_driver:       Dict[str, pd.DataFrame] = {}

        self.is_playing     = False
        self.current_time   = 0.
        self.playback_speed = tk.IntVar(value=1)
        self._play_thread:  Optional[threading.Thread] = None
        self._load_thread:  Optional[threading.Thread] = None

        self._worker: Optional[SnapshotWorker] = None

        self.track_scale = 1.
        self.track_cx    = 0.
        self.track_cy    = 0.
        self.map_w       = 600
        self.map_h       = 340
        self._map_zoom   = 1.0
        self._map_pan_x  = 0.
        self._map_pan_y  = 0.
        self._drag_start: Optional[Tuple[int, int]] = None

        self.selected_driver: Optional[str] = None
        self._last_snaps: List[Snap] = []

        self._last_ana_lap: int  = -1
        self._last_ana_drv: str  = ""
        self._last_style_laps: int = -1

        self._ers_state: Dict[str, tuple] = {}

        self._map_pts_cache: Optional[list] = None
        self._map_zoom_pan_prev: Optional[tuple] = None

        self._setup_styles()
        self._build_ui()
        self._load_calendar(2024)

    # ════════════════════════════════════════════════════════════════════════
    #  ESTILOS
    # ════════════════════════════════════════════════════════════════════════
    def _setup_styles(self) -> None:
        s = ttk.Style()
        s.theme_use("clam")
        s.configure("TFrame",           background=BG_DARK)
        s.configure("TLabel",           background=BG_DARK, foreground=TEXT_PRI, font=(FONT, 10))
        s.configure("TCombobox",        fieldbackground="#ffffff", background="#ffffff",
                    foreground="#000000", selectbackground=ACCENT,
                    selectforeground="#ffffff", font=(FONT, 10))
        s.map("TCombobox",              fieldbackground=[("readonly","#ffffff")],
                    foreground=[("readonly","#000000"),("focus","#000000")])
        s.configure("TRadiobutton",     background=BG_DARK, foreground=TEXT_SEC, font=(FONT, 9, "bold"))
        s.map("TRadiobutton",           foreground=[("selected", TEXT_PRI)])
        s.configure("Treeview",         background=BG_ROW, foreground=TEXT_PRI,
                    fieldbackground=BG_ROW, rowheight=26, font=(FONT, 9))
        s.map("Treeview",               background=[("selected", ACCENT)], foreground=[("selected", TEXT_PRI)])
        s.configure("Treeview.Heading", background=BG_CARD, foreground=TEXT_SEC,
                    font=(FONT, 9, "bold"), relief="flat")
        s.map("Treeview.Heading",       background=[("active", BG_ROW)])
        s.configure("Vertical.TScrollbar", background=BG_PANEL, troughcolor=BG_CARD, arrowcolor=TEXT_SEC)

    # ════════════════════════════════════════════════════════════════════════
    #  UI
    # ════════════════════════════════════════════════════════════════════════
    def _build_ui(self) -> None:
        self._build_header()
        self._build_controls()
        self._build_main_area()

    def _build_header(self) -> None:
        hdr = tk.Frame(self.root, bg=BG_PANEL, height=56)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        tk.Label(hdr, text=" F1", bg=BG_PANEL, fg=ACCENT,
                 font=(FONT, 22, "bold")).pack(side=tk.LEFT, padx=(14, 0))
        tk.Label(hdr, text="PRO DASHBOARD", bg=BG_PANEL, fg=TEXT_PRI,
                 font=(FONT, 11, "bold")).pack(side=tk.LEFT, padx=(4, 18))
        self._vsep(hdr)

        tk.Label(hdr, text="Year:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT, 9, "bold")).pack(side=tk.LEFT, padx=(10, 3))
        self.combo_year = ttk.Combobox(hdr, values=list(range(2018, 2027)),
                                       width=6, state="readonly")
        self.combo_year.set(2024)
        self.combo_year.pack(side=tk.LEFT, padx=(0, 12))
        self.combo_year.bind("<<ComboboxSelected>>",
                             lambda _: self._load_calendar(int(self.combo_year.get())))

        tk.Label(hdr, text="Race:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT, 9, "bold")).pack(side=tk.LEFT, padx=(0, 3))
        self.combo_race = ttk.Combobox(hdr, width=38, state="readonly")
        self.combo_race.pack(side=tk.LEFT, padx=(0, 12))

        tk.Label(hdr, text="Session:", bg=BG_PANEL, fg=TEXT_SEC,
                 font=(FONT, 9, "bold")).pack(side=tk.LEFT, padx=(0, 3))
        self.combo_session = ttk.Combobox(
            hdr, values=["FP1", "FP2", "FP3", "Q", "SQ", "S", "R"],
            width=5, state="readonly")
        self.combo_session.set("R")
        self.combo_session.pack(side=tk.LEFT, padx=(0, 7))
        self.combo_session.bind("<<ComboboxSelected>>", self._on_session_type_change)

        si = SESSION_INFO["R"]
        self.lbl_sess_badge = tk.Label(hdr, text=f"◉ {si[0]}",
            bg=si[2], fg=TEXT_PRI, font=(FONT, 9, "bold"), padx=10, pady=3)
        self.lbl_sess_badge.pack(side=tk.LEFT, padx=(0, 12))
        self._vsep(hdr)

        self.btn_load = tk.Button(hdr, text="LOAD SESSION",
            bg=ACCENT, fg=TEXT_PRI, activebackground="#b30000",
            font=(FONT, 10, "bold"), relief="flat", padx=12, pady=4,
            cursor="hand2", command=self._start_load)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 12))

        self.lbl_status = tk.Label(hdr,
            text="Select race + session, then LOAD SESSION.",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT, 9))
        self.lbl_status.pack(side=tk.LEFT)

        self.lbl_spin = tk.Label(hdr, text="", bg=BG_PANEL, fg=ACCENT,
                                 font=(FONT, 15, "bold"))
        self.lbl_spin.pack(side=tk.RIGHT, padx=14)

    def _vsep(self, p):
        tk.Frame(p, bg="#333355", width=1).pack(side=tk.LEFT, fill=tk.Y, pady=10, padx=3)

    def _build_controls(self) -> None:
        ctrl = tk.Frame(self.root, bg=BG_DARK, pady=5)
        ctrl.pack(fill=tk.X, padx=10)

        self.btn_play = tk.Button(ctrl, text="▶  PLAY",
            bg=ACCENT2, fg=TEXT_PRI, activebackground="#007bbf",
            font=(FONT, 10, "bold"), relief="flat", padx=12, pady=3,
            cursor="hand2", command=self._toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, padx=(0, 8))

        for lbl, val in (("×1", 1), ("×4", 4), ("×16", 16), ("×64", 64)):
            ttk.Radiobutton(ctrl, text=lbl, variable=self.playback_speed,
                            value=val).pack(side=tk.LEFT, padx=2)

        self._vsep(ctrl)

        self.btn_prev = tk.Button(ctrl, text="◀◀ -1 Lap", bg=BG_CARD,
            fg=TEXT_SEC, relief="flat", font=(FONT, 9), padx=8, pady=3,
            cursor="hand2", command=lambda: self._jump(-90), state=tk.DISABLED)
        self.btn_prev.pack(side=tk.LEFT, padx=2)

        self.btn_next = tk.Button(ctrl, text="+1 Lap ▶▶", bg=BG_CARD,
            fg=TEXT_SEC, relief="flat", font=(FONT, 9), padx=8, pady=3,
            cursor="hand2", command=lambda: self._jump(90), state=tk.DISABLED)
        self.btn_next.pack(side=tk.LEFT, padx=(2, 6))

        self._vsep(ctrl)

        box = tk.Frame(ctrl, bg=BG_DARK)
        box.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 7))

        self.timeline_canvas = Canvas(box, height=8, bg=BG_CARD, highlightthickness=0)
        self.timeline_canvas.pack(fill=tk.X, pady=(0, 2))

        self.time_slider = tk.Scale(box, from_=0, to=100, orient=tk.HORIZONTAL,
            bg=BG_DARK, fg=TEXT_PRI, troughcolor=GREEN,
            highlightthickness=0, showvalue=False,
            command=self._on_slider, state=tk.DISABLED)
        self.time_slider.pack(fill=tk.X)

        self.lbl_time = tk.Label(ctrl, text="00:00:00", bg=BG_DARK, fg=TEXT_PRI,
            font=("Courier New", 13, "bold"), width=9)
        self.lbl_time.pack(side=tk.LEFT, padx=(0, 6))

    def _build_main_area(self) -> None:
        main = tk.Frame(self.root, bg=BG_DARK)
        main.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))
        main.columnconfigure(0, weight=0)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(0, weight=1)
        self._build_left_panel(main)
        self._build_right_panel(main)

    def _build_left_panel(self, parent) -> None:
        left = tk.Frame(parent, bg=BG_DARK)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        sb = tk.Frame(left, bg=BG_PANEL, height=38)
        sb.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        sb.pack_propagate(False)
        self.lbl_race_status = tk.Label(sb, text="⬜ NO SESSION",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT, 12, "bold"), anchor="w", width=22)
        self.lbl_race_status.pack(side=tk.LEFT, padx=8)
        self.lbl_laps = tk.Label(sb, text="LAP — / —",
            bg=BG_PANEL, fg=TEXT_PRI, font=(FONT, 12, "bold"))
        self.lbl_laps.pack(side=tk.LEFT, padx=10)
        self.lbl_weather = tk.Label(sb, text="Air —°C | Track —°C | ☀ —",
            bg=BG_PANEL, fg=TEXT_SEC, font=(FONT, 9), anchor="e")
        self.lbl_weather.pack(side=tk.RIGHT, padx=8)

        tf = tk.Frame(left, bg=BG_DARK)
        tf.grid(row=1, column=0, sticky="nsew")
        tf.rowconfigure(0, weight=1)
        tf.columnconfigure(0, weight=1)
        tf.columnconfigure(1, weight=0)

        cols = ("Pos", "No", "DRV", "Team", "Gap", "Int", "Speed", "Tyre", "Lap")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings",
                                 height=22, selectmode="browse")
        widths = {"Pos": 32, "No": 30, "DRV": 46, "Team": 96,
                  "Gap": 68, "Int": 62, "Speed": 68, "Tyre": 44, "Lap": 36}
        for c in cols:
            self.tree.heading(c, text=c, anchor=tk.CENTER)
            self.tree.column(c, width=widths[c],
                             anchor=tk.W if c == "Team" else tk.CENTER,
                             stretch=False)
        vsb = ttk.Scrollbar(tf, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<<TreeviewSelect>>", self._on_driver_select)

        self._build_left_bottom_panel(left)

    def _build_left_bottom_panel(self, parent) -> None:
        """Race Administration — panel inferior izquierdo."""
        frm = tk.Frame(parent, bg=BG_CARD, padx=7, pady=5)
        frm.grid(row=2, column=0, sticky="ew", pady=(4, 0))

        tk.Label(frm, text="RACE ADMINISTRATION", bg=BG_CARD, fg=ACCENT,
                 font=(FONT, 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 3))

        # ── Pit Status ────────────────────────────────────────────────────────
        pit_row = tk.Frame(frm, bg=BG_CARD)
        pit_row.pack(fill=tk.X)
        tk.Label(pit_row, text="PIT:", bg=BG_CARD, fg=TEXT_SEC,
                 font=(FONT, 8, "bold"), anchor="w").pack(side=tk.LEFT)
        self.lbl_lb_pit = tk.Label(pit_row, text="ON TRACK",
            bg=BG_CARD, fg=GREEN, font=(FONT, 9, "bold"), anchor="e")
        self.lbl_lb_pit.pack(side=tk.RIGHT)

        # ── Neumático: nombre + cambio ────────────────────────────────────────
        tyre_row = tk.Frame(frm, bg=BG_CARD)
        tyre_row.pack(fill=tk.X, pady=(2, 0))
        tk.Label(tyre_row, text="TYRE:", bg=BG_CARD, fg=TEXT_SEC,
                 font=(FONT, 8, "bold"), anchor="w").pack(side=tk.LEFT)
        self.lbl_lb_tyre = tk.Label(tyre_row, text="—",
            bg=BG_CARD, fg=TEXT_PRI, font=(FONT, 9, "bold"), anchor="e")
        self.lbl_lb_tyre.pack(side=tk.RIGHT)

        # Fila: Age + Pits
        age_row = tk.Frame(frm, bg=BG_CARD)
        age_row.pack(fill=tk.X)
        self.lbl_lb_tyre_age = tk.Label(age_row, text="Age: — laps  |  Pits: —",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 8), anchor="w")
        self.lbl_lb_tyre_age.pack(side=tk.LEFT)
        self.lbl_lb_tyre_change = tk.Label(age_row, text="",
            bg=BG_CARD, fg=ORANGE, font=(FONT, 8, "bold"), anchor="e")
        self.lbl_lb_tyre_change.pack(side=tk.RIGHT)

        # ── Barra de desgaste del neumático ──────────────────────────────────
        # Empieza en negro, se llena de izq a der según las laps en este stint.
        # Color: verde (0-10L) → amarillo (10-25L) → naranja (25-35L) → rojo (35+L)
        tk.Label(frm, text="TYRE WEAR", bg=BG_CARD, fg=TEXT_SEC,
                 font=(FONT, 7, "bold"), anchor="w").pack(fill=tk.X)
        self.cvs_lb_tyre_wear = tk.Canvas(frm, height=14, bg="#050505",
                                           highlightthickness=1,
                                           highlightbackground="#333355")
        self.cvs_lb_tyre_wear.pack(fill=tk.X, pady=(1, 4))

        tk.Frame(frm, bg="#2a2a4a", height=1).pack(fill=tk.X, pady=(0, 3))

        # ── ERS Battery ───────────────────────────────────────────────────────
        ers_hdr = tk.Frame(frm, bg=BG_CARD)
        ers_hdr.pack(fill=tk.X)
        tk.Label(ers_hdr, text="⚡ ERS BATTERY", bg=BG_CARD, fg=ACCENT2,
                 font=(FONT, 8, "bold"), anchor="w").pack(side=tk.LEFT)
        self.lbl_lb_ers_pct = tk.Label(ers_hdr, text="0%",
            bg=BG_CARD, fg=GREEN, font=(FONT, 9, "bold"), anchor="e")
        self.lbl_lb_ers_pct.pack(side=tk.RIGHT)

        self.cvs_lb_ers = tk.Canvas(frm, height=16, bg="#050510",
                                    highlightthickness=1,
                                    highlightbackground="#1a3a5e")
        self.cvs_lb_ers.pack(fill=tk.X, pady=(2, 2))

        # Deploy / Regen en kW instantáneo (no kJ acumulado)
        dep_reg = tk.Frame(frm, bg=BG_CARD)
        dep_reg.pack(fill=tk.X)
        self.lbl_lb_deploy = tk.Label(dep_reg, text="↓ Deploy:  — kW",
            bg=BG_CARD, fg=ORANGE, font=(FONT, 8, "bold"), anchor="w")
        self.lbl_lb_deploy.pack(side=tk.LEFT)
        self.lbl_lb_regen = tk.Label(dep_reg, text="↑ Regen:  — kW",
            bg=BG_CARD, fg=GREEN, font=(FONT, 8, "bold"), anchor="e")
        self.lbl_lb_regen.pack(side=tk.RIGHT)

        self.lbl_lb_ers_status = tk.Label(frm, text="",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 8, "bold"), anchor="w")
        self.lbl_lb_ers_status.pack(fill=tk.X)

    def _build_right_panel(self, parent) -> None:
        right = tk.Frame(parent, bg=BG_DARK)
        right.grid(row=0, column=1, sticky="nsew")

        top_row = tk.Frame(right, bg=BG_DARK)
        top_row.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        self._build_map_panel(top_row)
        self._build_hud_panel(top_row)
        self._build_telemetry_plot(right)
        self._build_analysis_panel(right)

    def _build_map_panel(self, parent) -> None:
        mf = tk.Frame(parent, bg=BG_CARD)
        mf.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        hdr = tk.Frame(mf, bg=BG_CARD)
        hdr.pack(fill=tk.X)

        self.lbl_track_name = tk.Label(hdr, text="NO SESSION LOADED",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 10, "bold"), anchor="w", padx=8, pady=3)
        self.lbl_track_name.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self.lbl_map_badge = tk.Label(hdr, text="", bg=BG_CARD, fg=TEXT_PRI,
            font=(FONT, 9, "bold"), padx=8, pady=3)
        self.lbl_map_badge.pack(side=tk.RIGHT)

        zoom_bar = tk.Frame(mf, bg=BG_CARD)
        zoom_bar.pack(fill=tk.X)
        tk.Label(zoom_bar, text="Scroll=zoom  |  Drag=pan  |",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 7)).pack(side=tk.LEFT, padx=6)
        tk.Button(zoom_bar, text="⟳ Reset", bg=BG_CARD, fg=TEXT_SEC,
            font=(FONT, 8), relief="flat", padx=6,
            command=self._map_reset).pack(side=tk.LEFT)

        self.map_canvas = Canvas(mf, bg=BG_CARD, highlightthickness=0)
        self.map_canvas.pack(fill=tk.BOTH, expand=True)

        self.map_canvas.bind("<MouseWheel>",      self._map_zoom_wheel)
        self.map_canvas.bind("<Button-4>",        self._map_zoom_wheel)
        self.map_canvas.bind("<Button-5>",        self._map_zoom_wheel)
        self.map_canvas.bind("<ButtonPress-1>",   self._map_drag_start)
        self.map_canvas.bind("<B1-Motion>",       self._map_drag_move)
        self.map_canvas.bind("<ButtonRelease-1>", self._map_drag_end)

    def _build_hud_panel(self, parent) -> None:
        hud_w   = max(280, min(380, int(340 * self._scale)))
        gauge_w = max(240, min(320, int(320 * self._scale)))
        gauge_h = max(220, min(272, int(272 * self._scale)))
        f = tk.Frame(parent, bg=BG_CARD, padx=8, pady=6, width=hud_w)
        f.pack(side=tk.RIGHT, fill=tk.Y)
        f.pack_propagate(False)

        self.lbl_driver_name = tk.Label(f, text="—", bg=BG_CARD, fg=TEXT_PRI,
            font=(FONT, 18, "bold"), anchor="w")
        self.lbl_driver_name.pack(fill=tk.X)

        self.lbl_team_name = tk.Label(f, text="—", bg=BG_CARD, fg=TEXT_SEC,
            font=(FONT, 9), anchor="w")
        self.lbl_team_name.pack(fill=tk.X)

        gap_frame = tk.Frame(f, bg=BG_CARD)
        gap_frame.pack(fill=tk.X, pady=(6, 4))

        self.frm_ahead = tk.Frame(gap_frame, bg="#0d2035", padx=6, pady=4)
        self.frm_ahead.pack(fill=tk.X, pady=(0, 3))
        tk.Label(self.frm_ahead, text="▲ AHEAD", bg="#0d2035", fg=TEXT_SEC,
                 font=(FONT, 8, "bold")).pack(side=tk.LEFT)
        self.lbl_gap_ahead = tk.Label(self.frm_ahead, text="— —",
            bg="#0d2035", fg=ACCENT2, font=(FONT, 12, "bold"), anchor="e")
        self.lbl_gap_ahead.pack(side=tk.RIGHT)

        self.frm_behind = tk.Frame(gap_frame, bg="#1f0d0d", padx=6, pady=4)
        self.frm_behind.pack(fill=tk.X)
        tk.Label(self.frm_behind, text="▼ BEHIND", bg="#1f0d0d", fg=TEXT_SEC,
                 font=(FONT, 8, "bold")).pack(side=tk.LEFT)
        self.lbl_gap_behind = tk.Label(self.frm_behind, text="— —",
            bg="#1f0d0d", fg=ORANGE, font=(FONT, 12, "bold"), anchor="e")
        self.lbl_gap_behind.pack(side=tk.RIGHT)

        self.lbl_battle = tk.Label(f, text="TRACK: CLEAR", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT, 10, "bold"), anchor="w")
        self.lbl_battle.pack(fill=tk.X)

        self.lbl_style = tk.Label(f, text="STYLE: —", bg=BG_CARD,
            fg=TEXT_SEC, font=(FONT, 10, "bold"), anchor="w")
        self.lbl_style.pack(fill=tk.X, pady=(0, 4))

        # Lap type badge
        self.lbl_lap_type = tk.Label(f, text="",
            bg=BG_CARD, fg=ACCENT2, font=(FONT, 9, "bold"), anchor="w")
        self.lbl_lap_type.pack(fill=tk.X, pady=(0, 2))

        self.hud_canvas = Canvas(f, width=gauge_w, height=gauge_h, bg=BG_CARD,
                                 highlightthickness=0)
        self.hud_canvas.pack()
        self._build_gauge_arcs()

        # Refs de compatibilidad para _update_battery (no se muestran — ERS está en panel izquierdo)
        self.frm_battery   = tk.Frame(f, bg=BG_CARD)
        self.lbl_battery_pct = tk.Label(self.frm_battery, text="—%", bg=BG_CARD, fg=GREEN,
                                        font=(FONT, 9, "bold"))
        self.cvs_battery     = tk.Canvas(self.frm_battery, height=20, bg="#050510",
                                         highlightthickness=0)
        self.lbl_deploy_val  = tk.Label(self.frm_battery, text="", bg=BG_CARD, fg=ORANGE,
                                        font=(FONT, 8))
        self.lbl_regen_val   = tk.Label(self.frm_battery, text="", bg=BG_CARD, fg=GREEN,
                                        font=(FONT, 8))
        self.lbl_battery_val = tk.Label(self.frm_battery, text="", bg=BG_CARD, fg=ACCENT,
                                        font=(FONT, 8))

    def _build_gauge_arcs(self) -> None:
        c = self.hud_canvas
        c.update_idletasks()
        W = c.winfo_reqwidth()  or 320
        H = c.winfo_reqheight() or 272
        c.create_arc(26, 16, W-26, H-16, start=180, extent=-180,
                     style=tk.ARC, outline="#1c2c3c", width=16, tags="rpm_bg")
        c.create_arc(26, 16, W-26, H-16, start=180, extent=0,
                     style=tk.ARC, outline=ACCENT2, width=16, tags="rpm_arc")
        rx, ry = (W-52)/2, (H-32)/2
        ox, oy = W/2, H/2
        for rpm_m in range(0, MAX_RPM+1, 2000):
            a = math.radians(180. - (rpm_m/MAX_RPM)*180.)
            tx = ox + (rx-20)*math.cos(a)
            ty = oy - (ry-20)*math.sin(a)
            c.create_text(tx, ty, text=f"{rpm_m//1000}k",
                          fill="#2a2a50", font=(FONT, 7))
        c.create_arc(44, 34, W-44, H-34, start=180, extent=-135,
                     style=tk.ARC, outline="#0f2b0f", width=18, tags="thr_bg")
        c.create_arc(44, 34, W-44, H-34, start=180, extent=0,
                     style=tk.ARC, outline=GREEN, width=18, tags="thr_arc")
        c.create_arc(44, 34, W-44, H-34, start=0, extent=45,
                     style=tk.ARC, outline="#2b0f0f", width=18, tags="brk_bg")
        c.create_arc(44, 34, W-44, H-34, start=0, extent=0,
                     style=tk.ARC, outline=ACCENT, width=18, tags="brk_arc")
        spd_fs = max(28, int(50 * (W/320)))
        cx = W//2
        c.create_text(cx, int(H*0.46), text="0",       fill=TEXT_PRI, font=(FONT, spd_fs, "bold"), tags="speed_val")
        c.create_text(cx, int(H*0.63), text="km/h",    fill=TEXT_SEC, font=(FONT, 11))
        c.create_text(cx, int(H*0.26), text="0 RPM",   fill=TEXT_SEC, font=(FONT, 12),         tags="rpm_val")
        c.create_text(cx, int(H*0.76), text="N",        fill=ACCENT2,  font=(FONT, 22, "bold"), tags="gear_val")
        c.create_text(cx, int(H*0.90), text="STRAIGHT MODE: OFF", fill=TEXT_SEC, font=(FONT, 9, "bold"), tags="drs_val")
        c.create_text(cx, int(H*0.97), text="OVERTAKE MODE: OFF", fill=TEXT_SEC, font=(FONT, 8, "bold"), tags="om_val")
        c.create_text(42, int(H*0.59), text="THR",     fill=GREEN,    font=(FONT, 8, "bold"))
        c.create_text(W-42, int(H*0.59), text="BRK",   fill=ACCENT,   font=(FONT, 8, "bold"))

    def _build_telemetry_plot(self, parent) -> None:
        pf = tk.Frame(parent, bg=BG_CARD)
        pf.pack(fill=tk.X, pady=(0, 4))

        hdr = tk.Frame(pf, bg=BG_CARD)
        hdr.pack(fill=tk.X)
        tk.Label(hdr,
            text="TELEMETRY PLOT  — Current Lap  |  Sector guides  |  SM/OM/⚡SC/L&C markers",
            bg=BG_CARD, fg=ACCENT, font=(FONT, 10, "bold"), padx=8, pady=3).pack(side=tk.LEFT)
        for txt, col in (("Speed", TEXT_PRI), ("Throttle", GREEN), ("Brake", ACCENT), ("ERS", ACCENT2)):
            tk.Label(hdr, text=f"█ {txt}", bg=BG_CARD, fg=col,
                     font=(FONT, 8, "bold")).pack(side=tk.LEFT, padx=6)

        self.plot_canvas = Canvas(pf, height=160, bg="#080810", highlightthickness=0)
        self.plot_canvas.pack(fill=tk.BOTH, expand=False, padx=4, pady=(0, 4))

    def _build_analysis_panel(self, parent) -> None:
        """Panel de análisis fusionado: Sectors vs Prev Lap + Pace & Style History."""
        row = tk.Frame(parent, bg=BG_DARK)
        row.pack(fill=tk.X)

        # ── Panel izquierdo: Sectors vs Previous Lap (ampliado) ──────────────
        sec_f = tk.Frame(row, bg=BG_CARD, padx=8, pady=6)
        sec_f.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        sec_hdr = tk.Frame(sec_f, bg=BG_CARD)
        sec_hdr.pack(fill=tk.X, pady=(0, 3))
        tk.Label(sec_hdr, text="SECTORS  vs  PREVIOUS LAP", bg=BG_CARD,
                 fg=ACCENT, font=(FONT, 10, "bold"), anchor="w").pack(side=tk.LEFT)
        self.lbl_track_cond = tk.Label(sec_hdr, text="Track: —",
            bg=BG_CARD, fg=GREEN, font=(FONT, 9, "bold"), anchor="e")
        self.lbl_track_cond.pack(side=tk.RIGHT)

        # Tabla de sectores — sin Tyre/Age/Pits (movidos a Race Admin)
        sec_cols = ("S", "Time", "Δ", "Verdict", "Cond")
        self.tree_sec = ttk.Treeview(sec_f, columns=sec_cols, show="headings",
                                     height=3, selectmode="none")
        sec_w = {"S": 22, "Time": 78, "Δ": 72, "Verdict": 120, "Cond": 72}
        for c in sec_cols:
            self.tree_sec.heading(c, text=c)
            self.tree_sec.column(c, width=sec_w[c], anchor=tk.CENTER, stretch=False)
        for tag, fg in (("f1_purple", F1_PURPLE), ("f1_green", F1_GREEN),
                        ("f1_yellow", F1_YELLOW), ("f1_white", F1_WHITE)):
            self.tree_sec.tag_configure(tag, foreground=fg)
        self.tree_sec.tag_configure("sc_active",  foreground=ORANGE,  background="#1a0e00")
        self.tree_sec.tag_configure("vsc_active", foreground=PURPLE,  background="#110022")
        self.tree_sec.tag_configure("yellow_sec", foreground=YELLOW,  background="#1a1a00")
        self.tree_sec.tag_configure("red_flag",   foreground=ACCENT,  background="#1a0000")
        self.tree_sec.pack(fill=tk.X, pady=(0, 3))

        # Avg sector time label
        self.lbl_sec_avg = tk.Label(sec_f, text="Avg S1/S2/S3: — / — / —",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 8), anchor="w")
        self.lbl_sec_avg.pack(fill=tk.X)

        # Separador y Pace block dentro del mismo panel
        tk.Frame(sec_f, bg="#2a2a4a", height=1).pack(fill=tk.X, pady=(4, 3))
        tk.Label(sec_f, text="PACE & ANALYSIS", bg=BG_CARD,
                 fg=ACCENT, font=(FONT, 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 2))

        self.lbl_pace = tk.Label(sec_f, text="Pace (5L avg): —",
            bg=BG_CARD, fg=TEXT_PRI, font=(FONT, 10, "bold"), anchor="w")
        self.lbl_pace.pack(fill=tk.X)

        self.lbl_last_lap = tk.Label(sec_f, text="Last: —  |  Best: —",
            bg=BG_CARD, fg=TEXT_SEC, font=(FONT, 10), anchor="w")
        self.lbl_last_lap.pack(fill=tk.X, pady=(1, 2))

        self.lbl_diag = tk.Label(sec_f, text="Behaviour: —",
            bg=BG_CARD, fg=ACCENT2, font=(FONT, 9, "bold"), anchor="w",
            wraplength=300, justify="left")
        self.lbl_diag.pack(fill=tk.X)

        # ── Panel derecho: Driving Style History ──────────────────────────────
        style_f = tk.Frame(row, bg=BG_CARD, padx=8, pady=6)
        style_f.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        tk.Label(style_f, text="DRIVING STYLE HISTORY", bg=BG_CARD,
                 fg=ACCENT, font=(FONT, 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 3))

        # Tabla invertida (última vuelta arriba → insert en pos 0) con columnas más legibles
        style_cols = ("Lap", "LiCo%", "Clip%", "Push%", "Brk%", "Lap Time", "Δ Best", "Cond")
        self.tree_style = ttk.Treeview(style_f, columns=style_cols,
                                       show="headings", height=8, selectmode="none")
        style_w = {"Lap": 34, "LiCo%": 52, "Clip%": 52, "Push%": 52, "Brk%": 48,
                   "Lap Time": 72, "Δ Best": 64, "Cond": 58}
        for c in style_cols:
            self.tree_style.heading(c, text=c)
            self.tree_style.column(c, width=style_w[c], anchor=tk.CENTER, stretch=False)
        for tag, fg in (("f1_purple", F1_PURPLE), ("f1_green", F1_GREEN),
                        ("f1_yellow", F1_YELLOW), ("f1_white", F1_WHITE)):
            self.tree_style.tag_configure(tag, foreground=fg)
        self.tree_style.tag_configure("high_clip",     foreground=PURPLE, background="#150030")
        self.tree_style.tag_configure("superclip",     foreground="#ffffff", background="#550000")
        self.tree_style.tag_configure("sc_lap",        foreground=ORANGE)
        self.tree_style.tag_configure("vsc_lap",       foreground="#cc88ff")
        self.tree_style.tag_configure("yellow_lap",    foreground=YELLOW)
        self.tree_style.tag_configure("red_lap",       foreground=ACCENT)
        self.tree_style.pack(fill=tk.BOTH, expand=True)

        # Leyenda de colores de clipping
        leg = tk.Frame(style_f, bg=BG_CARD)
        leg.pack(fill=tk.X, pady=(2, 0))
        tk.Label(leg, text="█ SUPERCLIP", bg=BG_CARD, fg="#ff4444",
                 font=(FONT, 7, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(leg, text="█ CLIP", bg=BG_CARD, fg=PURPLE,
                 font=(FONT, 7, "bold")).pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(leg, text="█ BEST", bg=BG_CARD, fg=F1_PURPLE,
                 font=(FONT, 7, "bold")).pack(side=tk.LEFT)

        # Referencia lbl_tyre — mantener para compatibilidad con _update_analysis
        self.lbl_tyre = tk.Label(style_f, text="", bg=BG_CARD, fg=BG_CARD,
                                  font=(FONT, 1))   # invisible, solo compatibilidad

    # ════════════════════════════════════════════════════════════════════════
    #  ZOOM / PAN MAPA
    # ════════════════════════════════════════════════════════════════════════
    def _map_reset(self):
        self._map_zoom = 1.0; self._map_pan_x = 0.; self._map_pan_y = 0.
        self._redraw_track()
        self._update_map_dots(self._last_snaps)

    def _map_zoom_wheel(self, event):
        factor = 1.15 if (event.num == 4 or event.delta > 0) else (1/1.15)
        self._map_zoom = clamp(self._map_zoom * factor, 0.3, 8.0)
        self._redraw_track()
        self._update_map_dots(self._last_snaps)

    def _map_drag_start(self, event):
        self._drag_start = (event.x, event.y)

    def _map_drag_move(self, event):
        if self._drag_start:
            self._map_pan_x += event.x - self._drag_start[0]
            self._map_pan_y += event.y - self._drag_start[1]
            self._drag_start = (event.x, event.y)
            self._redraw_track()
            self._update_map_dots(self._last_snaps)

    def _map_drag_end(self, event):
        self._drag_start = None

    def _world_to_canvas(self, x: float, y: float) -> Tuple[float, float]:
        cx = self.map_w/2 + (x - self.track_cx)*self.track_scale*self._map_zoom + self._map_pan_x
        cy = self.map_h/2 - (y - self.track_cy)*self.track_scale*self._map_zoom + self._map_pan_y
        return cx, cy

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
        race = self.combo_race.get()
        sess = self.combo_session.get()
        if not race:
            messagebox.showwarning("No Race", "Select a race first.")
            return
        if self._load_thread and self._load_thread.is_alive():
            return
        year = int(self.combo_year.get())
        self.session_year = year
        self.btn_load.configure(state=tk.DISABLED)
        self._set_status(f"Downloading {sess} – {race} {year}…")
        self._spin(True)
        self._load_thread = threading.Thread(
            target=self._fetch_session, args=(year, race, sess), daemon=True)
        self._load_thread.start()

    def _fetch_session(self, year: int, race: str, sess_type: str) -> None:
        try:
            session = fastf1.get_session(year, race, sess_type)
            session.load(telemetry=True, weather=True, messages=False)

            laps       = session.laps
            total_laps = int(laps["LapNumber"].max()) if not laps.empty else 0

            best_s: Optional[float] = None
            try:
                fastest = laps.pick_fastest()
                lt = fastest.get("LapTime")
                if lt is not None:
                    s = td_to_float(lt)
                    if not math.isnan(s):
                        best_s = s
            except Exception:
                pass

            telemetry: Dict[str, pd.DataFrame] = {}
            tel_times: Dict[str, np.ndarray]   = {}
            t_min, t_max = float("inf"), 0.

            for drv in session.drivers:
                try:
                    _dl = laps.pick_drivers(drv)
                    if _dl.empty: continue
                    tel = _dl.get_telemetry()
                    if tel.empty: continue
                    tel = tel.copy()

                    tel["TimeSec"] = tel["SessionTime"].dt.total_seconds()

                    info = session.get_driver(drv)
                    tel["Team"]   = info.get("TeamName",    "Unknown")
                    tel["Abbr"]   = info.get("Abbreviation", drv)
                    tel["Name"]   = info.get("FullName",     drv)
                    tel["Number"] = info.get("DriverNumber", drv)

                    tel_pure = strip_fastf1(tel)

                    ts_min = tel_pure["TimeSec"].min()
                    ts_max = tel_pure["TimeSec"].max()
                    if ts_min < t_min: t_min = ts_min
                    if ts_max > t_max: t_max = ts_max

                    telemetry[drv] = tel_pure
                    tel_times[drv] = tel_pure["TimeSec"].to_numpy(dtype=float)
                except Exception as exc:
                    log.warning("Driver %s: %s", drv, exc)

            if not telemetry:
                raise ValueError("No telemetry. Future or cancelled event?")

            laps_by_driver: Dict[str, pd.DataFrame] = {}
            lap_times_idx:  Dict[str, np.ndarray]   = {}
            sector_bests:   Dict[str, List[Optional[float]]] = {}
            overall = [None, None, None]

            for drv in telemetry:
                try:
                    dl = laps.pick_drivers(drv)
                    dl_pure = strip_fastf1(dl)

                    if "Time" in dl_pure.columns:
                        dl_pure["TimeSec_f"] = dl_pure["Time"]

                    laps_by_driver[drv] = dl_pure
                    if "TimeSec_f" in dl_pure.columns:
                        lap_times_idx[drv] = dl_pure["TimeSec_f"].to_numpy(dtype=float)
                    else:
                        lap_times_idx[drv] = np.array([])

                    sb = [None, None, None]
                    for s_idx in range(1, 4):
                        col = f"Sector{s_idx}Time"
                        if col not in dl_pure.columns: continue
                        vals_f = dl_pure[col].to_numpy(dtype=float)
                        vals_f = vals_f[~np.isnan(vals_f)]
                        if len(vals_f):
                            best = float(vals_f.min())
                            sb[s_idx-1] = best
                            if overall[s_idx-1] is None or best < overall[s_idx-1]:
                                overall[s_idx-1] = best
                    sector_bests[drv] = sb
                except Exception as exc:
                    log.warning("Laps cache drv %s: %s", drv, exc)
                    laps_by_driver[drv] = pd.DataFrame()
                    lap_times_idx[drv]  = np.array([])
                    sector_bests[drv]   = [None, None, None]

            ts_df = add_timesec_col(session.track_status, "Time")
            wx_df = add_timesec_col(session.weather_data, "Time")

            ts_times = ts_df["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in ts_df.columns else np.array([])
            wx_times = wx_df["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in wx_df.columns else np.array([])

            self.session              = session
            self.telemetry            = telemetry
            self.laps_data            = laps
            self._laps_by_driver      = laps_by_driver
            self.weather_data         = wx_df
            self.track_status_df      = ts_df
            self._ts_times            = ts_times
            self._wx_times            = wx_times
            self._tel_times           = tel_times
            self._lap_times           = lap_times_idx
            self.drivers              = list(telemetry.keys())
            self.total_laps           = total_laps
            self.session_best_s       = best_s
            self.session_start        = t_min
            self.max_time             = t_max - t_min
            self.session_type         = sess_type
            self._sector_bests        = sector_bests
            self._overall_sector_best = overall
            self._ers_state          = {}
            self._map_pts_cache      = None
            self._map_zoom_pan_prev  = None

            self.root.after(0, lambda: self._on_session_loaded(race, year, sess_type))

        except Exception as exc:
            log.exception("Session load failed")
            self.root.after(0, lambda: self._set_status(f"Error: {exc}"))
            self.root.after(0, lambda: self.btn_load.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self._spin(False))

    def _on_session_loaded(self, race: str, year: int, sess_type: str) -> None:
        self._spin(False)
        self.time_slider.configure(state=tk.NORMAL, to=self.max_time)
        self.btn_play.configure(state=tk.NORMAL)
        self.btn_prev.configure(state=tk.NORMAL)
        self.btn_next.configure(state=tk.NORMAL)
        self.btn_load.configure(state=tk.NORMAL)

        if self._worker:
            self._worker.stop()
        self._worker = SnapshotWorker(self)
        self._worker.start()

        self.root.update_idletasks()
        self._draw_timeline()
        self._draw_track_map()

        si = SESSION_INFO.get(sess_type, (sess_type, TEXT_PRI, BG_CARD))
        self.lbl_track_name.configure(text=f"  {race}  •  {year}  •  {si[0]}")
        self.lbl_map_badge.configure(text=f" ◉ {si[0]} ", bg=si[2], fg=TEXT_PRI)
        self._refresh_badge(sess_type)

        for row in self.tree.get_children(): self.tree.delete(row)
        for drv in self.drivers:
            ref  = self.telemetry[drv].iloc[0]
            team = str(ref.get("Team", "Unknown"))
            col  = TEAM_COLORS.get(team, TEXT_PRI)
            tag  = f"t_{drv}"
            self.tree.tag_configure(tag, foreground=col)
            self.tree.insert("", "end", iid=drv,
                values=("–", ref.get("Number","–"), ref.get("Abbr","–"),
                        team, "–", "–", "–", "–", "–"), tags=(tag,))

        if self.drivers:
            self.selected_driver = self.drivers[0]
            self.tree.selection_set(self.selected_driver)

        self._set_status(
            f"Loaded  •  {len(self.drivers)} drivers  •  {self.total_laps} laps  •  {si[0]}")
        self._request_update(0)

    # ════════════════════════════════════════════════════════════════════════
    #  MAPA
    # ════════════════════════════════════════════════════════════════════════
    def _draw_timeline(self) -> None:
        self.timeline_canvas.delete("all")
        self.timeline_canvas.update_idletasks()
        W = self.timeline_canvas.winfo_width() or 1200
        if self.track_status_df is None or self.track_status_df.empty: return
        n = len(self.track_status_df)
        for i in range(n):
            t0_raw = self._ts_times[i] if i < len(self._ts_times) else float('nan')
            if math.isnan(t0_raw): continue
            t0 = t0_raw - self.session_start
            if i+1 < n:
                t1_raw = self._ts_times[i+1]
                t1 = (t1_raw - self.session_start) if not math.isnan(t1_raw) else self.max_time
            else:
                t1 = self.max_time
            t0 = clamp(t0, 0, self.max_time)
            t1 = clamp(t1, 0, self.max_time)
            if self.max_time <= 0: continue
            x1 = t0/self.max_time*W
            x2 = t1/self.max_time*W
            color = TRACK_STATUS.get(str(self.track_status_df["Status"].iloc[i]), ("","",BG_CARD))[1]
            self.timeline_canvas.create_rectangle(x1, 0, x2, 8, fill=color, outline="")

    def _draw_track_map(self) -> None:
        self.map_canvas.delete("all")
        try:
            fastest = self.session.laps.pick_fastest()
            if pd.isna(fastest.get("LapTime")): return
            tel    = fastest.get_telemetry()
            x_vals = tel["X"].values
            y_vals = tel["Y"].values
            if len(x_vals) < 10: return

            self.map_canvas.update()
            self.map_w = max(self.map_canvas.winfo_width(),  100)
            self.map_h = max(self.map_canvas.winfo_height(), 60)

            mn_x, mx_x = x_vals.min(), x_vals.max()
            mn_y, mx_y = y_vals.min(), y_vals.max()
            rx = mx_x - mn_x or 1
            ry = mx_y - mn_y or 1
            self.track_scale = min(self.map_w/rx, self.map_h/ry) * 0.86
            self.track_cx = (mx_x + mn_x)/2
            self.track_cy = (mx_y + mn_y)/2

            self._track_x = x_vals
            self._track_y = y_vals
            self._redraw_track()
        except Exception as exc:
            log.warning("Track map: %s", exc)

    def _redraw_track(self) -> None:
        if not hasattr(self, "_track_x"): return
        zoom_pan = (self._map_zoom, self._map_pan_x, self._map_pan_y,
                    self.map_w, self.map_h)
        if self._map_pts_cache is None or zoom_pan != getattr(self, "_map_zoom_pan_prev", None):
            self._map_zoom_pan_prev = zoom_pan
            xs = self._track_x; ys = self._track_y
            cxs = (self.map_w/2
                   + (xs - self.track_cx) * self.track_scale * self._map_zoom
                   + self._map_pan_x)
            cys = (self.map_h/2
                   - (ys - self.track_cy) * self.track_scale * self._map_zoom
                   + self._map_pan_y)
            n = len(cxs)
            if n > 800:
                step = max(1, n // 800)
                cxs = cxs[::step]; cys = cys[::step]
            pts = []
            for cx, cy in zip(cxs, cys):
                pts += [float(cx), float(cy)]
            self._map_pts_cache = pts

        self.map_canvas.delete("track")
        self.map_canvas.delete("car_dot")
        self.map_canvas.create_polygon(
            self._map_pts_cache, outline="#444466", fill="", width=4, tags="track")

    # ════════════════════════════════════════════════════════════════════════
    #  REPRODUCCIÓN
    # ════════════════════════════════════════════════════════════════════════
    def _toggle_play(self) -> None:
        if self.is_playing:
            self.is_playing = False
            self.btn_play.configure(text="▶  PLAY")
        else:
            self.is_playing = True
            self.btn_play.configure(text="⏸  PAUSE")
            self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
            self._play_thread.start()

    def _play_loop(self) -> None:
        tick    = 0.05
        ui_rate = 0.12
        last_ui = 0.

        while self.is_playing and self.current_time < self.max_time:
            self.current_time = min(
                self.current_time + tick * self.playback_speed.get(),
                self.max_time)

            now = time.monotonic()
            if now - last_ui >= ui_rate:
                last_ui = now
                t = self.current_time
                self.root.after(0, lambda v=t: self._slider_tick(v))

            if self.current_time >= self.max_time:
                self.root.after(0, self._toggle_play)
                break
            time.sleep(tick)

    def _slider_tick(self, t: float) -> None:
        self.time_slider.set(t)
        self.lbl_time.configure(text=hms(int(t)))
        self._request_update(t)

    def _jump(self, delta: float) -> None:
        self.time_slider.set(clamp(self.current_time + delta, 0, self.max_time))

    def _on_slider(self, val) -> None:
        new_t = float(val)
        if new_t < self.current_time - 2.0:
            self._ers_state = {}
        self.current_time = new_t
        self.lbl_time.configure(text=hms(int(self.current_time)))
        self._request_update(self.current_time)

    def _on_driver_select(self, _event) -> None:
        sel = self.tree.selection()
        if sel:
            self.selected_driver = sel[0]
            self._request_update(self.current_time)

    def _on_session_type_change(self, _=None) -> None:
        self._refresh_badge(self.combo_session.get())

    def _refresh_badge(self, sess_type: str) -> None:
        si = SESSION_INFO.get(sess_type, (sess_type, TEXT_PRI, BG_CARD))
        self.lbl_sess_badge.configure(text=f"◉  {si[0]}", bg=si[2], fg=TEXT_PRI)

    # ════════════════════════════════════════════════════════════════════════
    #  PUNTO DE ENTRADA PARA ACTUALIZACIÓN
    # ════════════════════════════════════════════════════════════════════════
    def _request_update(self, elapsed: float) -> None:
        if self._worker and self._worker.is_alive():
            self._worker.request(elapsed)
        else:
            try:
                result = self._worker._compute(elapsed) if self._worker else None
                if result:
                    self._apply_snapshot_result(result, elapsed)
            except Exception:
                pass

    # ════════════════════════════════════════════════════════════════════════
    #  APLICAR RESULTADO
    # ════════════════════════════════════════════════════════════════════════
    def _apply_snapshot_result(self, result: dict, elapsed: float) -> None:
        snaps    = result["snaps"]
        abs_t    = result["abs_t"]
        ts_key   = result["ts_key"]
        ts_text  = result["ts_text"]
        ts_color = result["ts_color"]
        ts_bg    = result["ts_bg"]
        max_lap  = result["max_lap"]

        self._current_ts = ts_key
        self._last_snaps = snaps

        self.lbl_race_status.configure(text=ts_text, fg=ts_color, bg=ts_bg)
        self.time_slider.configure(troughcolor=ts_color)
        if result["weather_txt"]:
            self.lbl_weather.configure(text=result["weather_txt"])

        for i, s in enumerate(snaps):
            if not self.tree.exists(s.drv): continue
            self.tree.item(s.drv, values=(
                "–" if s.is_out else str(i+1),
                s.number, s.abbr, s.team,
                s.gap, s.interval,
                "OUT" if s.is_out else str(int(s.speed)),
                s.tyre, s.lap))
            self.tree.move(s.drv, "", i)
        self.lbl_laps.configure(text=f"LAP {max_lap} / {self.total_laps}")

        self._update_map_dots(snaps)
        self._update_hud(snaps, abs_t)

    def _update_map_dots(self, snaps: List[Snap]) -> None:
        self.map_canvas.delete("car_dot")
        for s in snaps:
            if s.is_out or math.isnan(s.x) or math.isnan(s.y): continue
            cx, cy = self._world_to_canvas(s.x, s.y)
            col  = TEAM_COLORS.get(s.team, TEXT_PRI)
            sel  = s.drv == self.selected_driver
            size = 9 if sel else 5
            self.map_canvas.create_oval(
                cx-size, cy-size, cx+size, cy+size,
                fill=col, outline="#ffffff" if sel else col,
                width=2 if sel else 1, tags="car_dot")
            if sel:
                self.map_canvas.create_text(
                    cx, cy-size-8, text=s.abbr,
                    fill=col, font=(FONT, 8, "bold"), tags="car_dot")

    # ════════════════════════════════════════════════════════════════════════
    #  HUD
    # ════════════════════════════════════════════════════════════════════════
    def _update_hud(self, snaps: List[Snap], abs_t: float) -> None:
        drv = self.selected_driver
        if drv is None: return
        snap = next((s for s in snaps if s.drv == drv), None)
        if snap is None: return

        col = TEAM_COLORS.get(snap.team, TEXT_PRI)
        self.lbl_driver_name.configure(text=f"{snap.name}  #{snap.number}", fg=col)
        self.lbl_team_name.configure(text=snap.team)

        self.hud_canvas.itemconfigure("rpm_arc",
            extent=-clamp(snap.rpm/MAX_RPM, 0, 1)*180)
        self.hud_canvas.itemconfigure("thr_arc",
            extent=-clamp(snap.throttle/100, 0, 1)*135)
        self.hud_canvas.itemconfigure("brk_arc",
            extent=45 if snap.brake > 0 else 0)
        self.hud_canvas.itemconfigure("speed_val", text=str(int(snap.speed)))
        self.hud_canvas.itemconfigure("rpm_val",   text=f"{int(snap.rpm):,} RPM")
        self.hud_canvas.itemconfigure("gear_val",
            text="N" if snap.gear == 0 else str(snap.gear))

        use_2026_hud = is_2026_era(self.session_year)
        if use_2026_hud:
            if snap.overtake_mode:
                drs_txt, drs_col = "STRAIGHT MODE: ON  ▶", GREEN
                om_txt,  om_col  = "OVERTAKE MODE: ON  ⚡", PURPLE
            elif snap.straight_mode or _drs_is_open(snap.drs):
                drs_txt, drs_col = "STRAIGHT MODE: ON  ▶", GREEN
                om_txt,  om_col  = "OVERTAKE MODE: OFF", TEXT_SEC
            else:
                drs_txt, drs_col = "STRAIGHT MODE: OFF", TEXT_SEC
                om_txt,  om_col  = "OVERTAKE MODE: OFF", TEXT_SEC
        else:
            drs_on  = _drs_is_open(snap.drs)
            drs_txt = "DRS: OPEN" if drs_on else "DRS: CLOSED"
            drs_col = GREEN if drs_on else TEXT_SEC
            om_txt  = ""
            om_col  = TEXT_SEC
        self.hud_canvas.itemconfigure("drs_val", text=drs_txt, fill=drs_col)
        self.hud_canvas.itemconfigure("om_val",  text=om_txt,  fill=om_col)

        idx = next((i for i, s in enumerate(snaps) if s.drv == drv), -1)
        if idx >= 0:
            ahead  = snaps[idx-1] if idx > 0 else None
            behind = snaps[idx+1] if idx < len(snaps)-1 else None

            if idx == 0:
                ahead_txt = "LEADER"
                ahead_gap = ""
            elif ahead is not None:
                ahead_txt = ahead.abbr
                if snap.is_out:
                    ahead_gap = "OUT"
                elif ahead.is_out:
                    ahead_gap = "+1 Lap"
                else:
                    ahead_gap = f"+{snap.int_num:.1f}s" if snap.int_num < 120 else "+1 Lap"
            else:
                ahead_txt = ""; ahead_gap = ""

            if behind is not None:
                behind_txt = behind.abbr
                if behind.is_out:
                    behind_gap = "OUT"
                elif snap.is_out:
                    behind_gap = "+1 Lap"
                else:
                    behind_gap = f"+{behind.int_num:.1f}s" if behind.int_num < 120 else "+1 Lap"
            else:
                behind_txt = ""; behind_gap = ""

            self.lbl_gap_ahead.configure(text=f"{ahead_txt}   {ahead_gap}")
            self.lbl_gap_behind.configure(text=f"{behind_txt}   {behind_gap}")

        # ── Lap type badge ─────────────────────────────────────────────────
        lt_colors = {"OUT LAP": ACCENT2, "IN LAP": ORANGE, "PUSH": GREEN, "": TEXT_SEC}
        self.lbl_lap_type.configure(
            text=snap.lap_type,
            fg=lt_colors.get(snap.lap_type, TEXT_SEC))

        self._update_style_battle(snap, abs_t, drv, snaps, idx)
        self._update_analysis(snap, drv, abs_t)
        self._update_telemetry_plot(drv, abs_t)

        if is_2026_era(self.session_year):
            self._update_battery(snap, abs_t, drv)

        self._update_left_bottom_panel(snap)

    def _update_style_battle(self, snap: Snap, abs_t: float, drv: str,
                              snaps: List[Snap], idx: int) -> None:
        df    = self.telemetry[drv]
        times = self._tel_times[drv]
        i_now  = int(min(np.searchsorted(times, abs_t), len(times)-1))
        i_prev = max(0, i_now-5)
        spd_arr = df["Speed"].to_numpy()
        rpm_arr = df["RPM"].to_numpy() if "RPM" in df.columns else np.zeros(len(times))
        Δspd    = snap.speed - safe(spd_arr[i_prev])
        Δrpm    = snap.rpm   - safe(float(rpm_arr[i_prev]))

        style, sc = "NORMAL", TEXT_SEC
        use_2026  = is_2026_era(self.session_year)

        # Superclipping 2026: WOT en recta, RPM no baja (motor a tope)
        # pero velocidad SÍ baja → el ERS no está desplegando (batería vacía)
        is_superclip = (use_2026 and snap.throttle >= 95 and snap.brake == 0
                        and snap.speed >= ERS_DEPLOY_SPD_MIN
                        and Δrpm >= -300         # RPM no cae significativamente
                        and Δspd < -0.5          # pero velocidad SÍ cae
                        and snap.rpm >= 10_000)
        is_clip_soft = (use_2026 and snap.throttle >= 95 and snap.brake == 0
                        and snap.speed >= 80 and Δspd <= 0
                        and snap.ers_soc < 10.0)

        if snap.throttle == 0 and snap.brake == 0 and snap.speed > 180 and Δspd < 0:
            style, sc = "LIFT & COAST", ACCENT2
        elif is_superclip or snap.is_clipping:
            style, sc = f"⚡ SUPERCLIPPING  {snap.ers_soc:.0f}%  RPM={snap.rpm/1000:.1f}k", PURPLE
        elif is_clip_soft:
            soc_str = f"{snap.ers_soc:.0f}%"
            style, sc = f"⚡ ERS CLIPPING  SOC={soc_str}", ORANGE
        elif use_2026 and snap.throttle >= 95 and snap.brake == 0 \
                and snap.speed > ERS_DEPLOY_SPD_MIN and snap.ers_soc < 20.0:
            style, sc = f"⚡ ERS LOW  {snap.ers_soc:.0f}%  —  DRAINING", ORANGE
        elif not use_2026 and snap.throttle >= 95 and snap.brake == 0 \
                and snap.rpm > 11_000 and Δspd < -1.2:
            style, sc = "ENGINE LIMITER / ICE CLIP", ORANGE
        elif snap.throttle >= 95 and snap.brake == 0:
            style, sc = "FULL THROTTLE", GREEN
        elif snap.brake > 50:
            style, sc = "HEAVY BRAKING", ACCENT
        elif snap.brake > 10 and snap.throttle > 0:
            style, sc = "TRAIL BRAKING", YELLOW
        elif 20 < snap.throttle < 95:
            style, sc = "ROLLING THROTTLE", ORANGE

        self.lbl_style.configure(text=f"STYLE: {style}", fg=sc)

        battle, bc = "CLEAR", TEXT_SEC
        if idx < len(snaps)-1:
            behind = snaps[idx+1]
            if behind.int_num <= 3.:
                battle, bc = (f"🟦 YIELDING → {behind.abbr}", ACCENT2) \
                    if behind.lap > snap.lap else (f"🛡 DEFENDING ← {behind.abbr}", ORANGE)
        if idx > 0:
            ahead = snaps[idx-1]
            if snap.int_num <= 3.:
                if snap.lap > ahead.lap:
                    battle, bc = f"🟦 LAPPING {ahead.abbr}", ACCENT2
                elif snap.int_num <= 1.:
                    battle, bc = f"⚔ OVERTAKING {ahead.abbr}", ACCENT
                else:
                    battle, bc = f"⚔ BATTLING {ahead.abbr}", ORANGE
        self.lbl_battle.configure(text=f"TRACK: {battle}", fg=bc)

    def _update_battery(self, snap: Snap, abs_t: float, drv: str) -> None:
        """Mantiene refs de compatibilidad — ERS ya se muestra en panel izquierdo."""
        pct = snap.ers_soc
        if pct > 60:    pct_col = GREEN
        elif pct > 30:  pct_col = YELLOW
        elif pct > ERS_CLIP_SOC_THRESH: pct_col = ORANGE
        else:           pct_col = ACCENT
        self.lbl_battery_pct.configure(text=f"{pct:.0f}%", fg=pct_col)
        self.lbl_deploy_val.configure(text=f"↓Deploy {snap.ers_deploy_kw:.0f} kJ")
        self.lbl_regen_val.configure(text=f"↑Regen {snap.ers_regen_kw:.0f} kJ")

    # ════════════════════════════════════════════════════════════════════════
    #  PANEL IZQUIERDO INFERIOR — Race Administration
    # ════════════════════════════════════════════════════════════════════════
    def _update_left_bottom_panel(self, snap: Snap) -> None:
        # ── Pit Status ────────────────────────────────────────────────────────
        if snap.in_pit:
            spd_lbl = "60 km/h PIT LIMITER" if snap.speed <= 62 else "80 km/h PIT LIMITER"
            pit_txt = f"🔧 IN PIT LANE  —  {spd_lbl}"
            pit_col = YELLOW
        elif snap.lap_type == "IN LAP":
            pit_txt = "⬇  IN LAP  (pitting this lap)"
            pit_col = ORANGE
        elif snap.lap_type == "OUT LAP":
            pit_txt = "⬆  OUT LAP  (warm-up)"
            pit_col = ACCENT2
        else:
            pit_txt = "ON TRACK"
            pit_col = GREEN
        self.lbl_lb_pit.configure(text=pit_txt, fg=pit_col)

        # ── Neumático ────────────────────────────────────────────────────────
        TYRE_FULL = {"M": "MEDIUM", "S": "SOFT", "H": "HARD",
                     "I": "INTER",  "W": "WET",  "U": "UNKNOWN"}
        TYRE_COL  = {"S": YELLOW, "M": TEXT_PRI, "H": "#dddddd",
                     "I": GREEN,  "W": ACCENT2}
        t_raw  = snap.tyre.strip("()")
        t_full = TYRE_FULL.get(t_raw.upper(), t_raw or "—")
        t_col  = TYRE_COL.get(t_raw.upper(), TEXT_SEC)
        self.lbl_lb_tyre.configure(text=t_full, fg=t_col)

        curr_compound = snap.tyre.strip("()").upper()
        prev_compound = snap.tyre_prev.strip("()").upper()
        if (curr_compound and prev_compound
                and curr_compound not in ("–", "", "N", "U")
                and prev_compound not in ("–", "", "N", "U")
                and curr_compound != prev_compound
                and (snap.pit_out_lap or snap.lap_type == "OUT LAP")):
            prev_full = TYRE_FULL.get(prev_compound, prev_compound)
            curr_full = TYRE_FULL.get(curr_compound, curr_compound)
            self.lbl_lb_tyre_change.configure(
                text=f"🔄 {prev_full}→{curr_full}", fg=ORANGE)
        else:
            self.lbl_lb_tyre_change.configure(text="", fg=TEXT_SEC)

        # ── Tyre age + pits ───────────────────────────────────────────────────
        tyre_age   = "—"
        pits_count = 0
        drv = self.selected_driver
        if drv:
            dl = self._laps_by_driver.get(drv, pd.DataFrame())
            if not dl.empty:
                if "TyreLife" in dl.columns and "TimeSec_f" in dl.columns:
                    lap_times_arr = self._lap_times.get(drv, np.array([]))
                    if len(lap_times_arr) > 0:
                        abs_t_now = self.session_start + self.current_time
                        idx_nxt = int(np.searchsorted(lap_times_arr, abs_t_now, side='right'))
                        idx_nxt = min(idx_nxt, len(lap_times_arr) - 1)
                        tl_arr = dl["TyreLife"].to_numpy()
                        if idx_nxt < len(tl_arr):
                            try:
                                tyre_age = str(int(float(tl_arr[idx_nxt])))
                            except Exception:
                                tyre_age = "—"
                if "PitOutTime" in dl.columns:
                    pot = dl["PitOutTime"].to_numpy()
                    pits_count = int(np.sum(~np.isnan(pot.astype(float))))
        self.lbl_lb_tyre_age.configure(
            text=f"Age: {tyre_age} laps  |  Pits: {pits_count}")

        # ── Barra de desgaste del neumático ──────────────────────────────────
        TYRE_MAX_LAPS = {"S": 20, "M": 35, "H": 50, "I": 30, "W": 40}
        max_laps_tyre = TYRE_MAX_LAPS.get(t_raw.upper(), 40)
        try:
            age_int = int(tyre_age)
        except Exception:
            age_int = 0
        wear_frac = clamp(age_int / max_laps_tyre, 0.0, 1.0)

        if wear_frac < 0.3:   wear_col = GREEN
        elif wear_frac < 0.6: wear_col = YELLOW
        elif wear_frac < 0.85: wear_col = ORANGE
        else:                  wear_col = ACCENT

        W_wear = self.cvs_lb_tyre_wear.winfo_width() or 200
        H_wear = 14
        self.cvs_lb_tyre_wear.delete("all")
        self.cvs_lb_tyre_wear.create_rectangle(0, 0, W_wear, H_wear,
            fill="#050505", outline="")
        for frac in (0.25, 0.50, 0.75):
            sx = int(W_wear * frac)
            self.cvs_lb_tyre_wear.create_line(sx, 2, sx, H_wear-2,
                fill="#333333", width=1)
        fw_wear = max(0, int(W_wear * wear_frac))
        if fw_wear > 0:
            self.cvs_lb_tyre_wear.create_rectangle(0, 1, fw_wear, H_wear-1,
                fill=wear_col, outline="")
        self.cvs_lb_tyre_wear.create_text(W_wear // 2, H_wear // 2,
            text=f"{int(wear_frac*100)}%  ({age_int}/{max_laps_tyre} L)",
            fill=TEXT_PRI, font=(FONT, 7, "bold"))

        # ── ERS Battery bar ───────────────────────────────────────────────────
        pct = snap.ers_soc
        if pct > 60:    ers_col = "#00cc88"; label_col = GREEN
        elif pct > 30:  ers_col = "#ccaa00"; label_col = YELLOW
        elif pct > ERS_CLIP_SOC_THRESH:
                        ers_col = "#cc5500"; label_col = ORANGE
        else:           ers_col = "#cc0000"; label_col = ACCENT

        self.lbl_lb_ers_pct.configure(text=f"{pct:.0f}%", fg=label_col)

        W_ers = self.cvs_lb_ers.winfo_width() or 200
        H_ers = 16
        self.cvs_lb_ers.delete("all")
        self.cvs_lb_ers.create_rectangle(0, 0, W_ers, H_ers,
            fill="#050510", outline="")
        fw = max(0, int(W_ers * pct / 100))
        if fw > 0:
            self.cvs_lb_ers.create_rectangle(0, 0, fw, H_ers,
                fill=ers_col, outline="")
            bright = "#aaffcc" if pct > 60 else ("#ffee88" if pct > 30 else "#ff9955")
            self.cvs_lb_ers.create_rectangle(0, 0, fw, 4, fill=bright, outline="")
        clip_x = int(W_ers * ERS_CLIP_SOC_THRESH / 100)
        self.cvs_lb_ers.create_line(clip_x, 0, clip_x, H_ers, fill=ACCENT, width=1)
        self.cvs_lb_ers.create_text(W_ers // 2, H_ers // 2,
            text=f"{pct:.0f}%", fill=TEXT_PRI, font=(FONT, 7, "bold"))

        # ── Deploy / Regen — kW instantáneo ──────────────────────────────────
        deploy_kw_now = 0.0
        regen_kw_now  = 0.0
        if snap.throttle >= 95 and snap.brake == 0 and snap.speed >= ERS_DEPLOY_SPD_MIN:
            spd_f = clamp((snap.speed - ERS_DEPLOY_SPD_MIN) / (320.0 - ERS_DEPLOY_SPD_MIN), 0, 1)
            deploy_kw_now = ERS_DEPLOY_KW * (0.4 + 0.6 * spd_f)
            if pct <= ERS_CLIP_SOC_THRESH:
                deploy_kw_now = 0.0
        elif snap.brake > 20:
            regen_kw_now = ERS_REGEN_BRAKE_KW * clamp(snap.brake / 100.0, 0, 1)
        elif snap.throttle == 0 and snap.brake == 0 and snap.speed > 80:
            regen_kw_now = ERS_REGEN_COAST_KW
        elif 5 <= snap.throttle < 80 and snap.brake == 0 and snap.speed > 80:
            regen_kw_now = 60.0 * (1.0 - snap.throttle / 80.0)

        dep_col = ORANGE if deploy_kw_now > 0 else TEXT_SEC
        reg_col = GREEN  if regen_kw_now > 0 else TEXT_SEC
        self.lbl_lb_deploy.configure(text=f"↓ Deploy: {deploy_kw_now:.0f} kW", fg=dep_col)
        self.lbl_lb_regen.configure( text=f"↑ Regen:  {regen_kw_now:.0f} kW",  fg=reg_col)

        # ── ERS Status ────────────────────────────────────────────────────────
        if snap.is_clipping:
            self.lbl_lb_ers_status.configure(
                text="⚠ SUPERCLIPPING — ERS CUT  ICE recharging", fg=PURPLE)
        elif pct < 20:
            self.lbl_lb_ers_status.configure(text="⚡ LOW BATTERY", fg=ORANGE)
        else:
            self.lbl_lb_ers_status.configure(text="", fg=TEXT_SEC)


    # ════════════════════════════════════════════════════════════════════════
    #  ANÁLISIS
    # ════════════════════════════════════════════════════════════════════════
    def _update_analysis(self, snap: Snap, drv: str, abs_t: float) -> None:
        drv_laps = self._laps_by_driver.get(drv, pd.DataFrame())
        if drv_laps.empty or "TimeSec_f" not in drv_laps.columns: return

        lap_times_arr = self._lap_times.get(drv, np.array([]))
        if len(lap_times_arr) == 0: return

        idx_nxt = int(np.searchsorted(lap_times_arr, abs_t, side='right'))
        if idx_nxt >= len(lap_times_arr): return

        def get_val(row_dict, col, default=None):
            v = row_dict.get(col, default)
            return v if v is not None else default

        cur_dict  = {col: drv_laps[col].to_numpy()[idx_nxt]
                     for col in drv_laps.columns}
        prev_dict = ({col: drv_laps[col].to_numpy()[idx_nxt-1]
                      for col in drv_laps.columns}
                     if idx_nxt > 0 else {})
        completed = drv_laps.iloc[:idx_nxt]

        ts_txt, ts_fg, _ = TRACK_STATUS.get(self._current_ts, ("GREEN", GREEN, ""))
        self.lbl_track_cond.configure(text=f"Track: {ts_txt}", fg=ts_fg)

        lap_start_abs = None
        lt_s   = float(cur_dict.get("LapTime", float('nan'))) if cur_dict.get("LapTime") is not None else float('nan')
        t_end  = cur_dict.get("TimeSec_f")
        if not math.isnan(lt_s) and t_end is not None and not math.isnan(float(t_end)):
            lap_start_abs = self.session_start + float(t_end) - lt_s

        cur_lap_num = cur_dict.get("LapNumber")
        lap_changed = self._last_ana_lap != cur_lap_num
        drv_changed = self._last_ana_drv != drv

        if lap_changed or drv_changed:
            self._last_ana_lap = cur_lap_num
            self._last_ana_drv = drv
            for row in self.tree_sec.get_children(): self.tree_sec.delete(row)

            for s_idx in range(1, 4):
                col  = f"Sector{s_idx}Time"
                cur_s  = 0.; prev_s = 0.
                if col in drv_laps.columns:
                    v = cur_dict.get(col, float('nan'))
                    if v is not None and not math.isnan(float(v)):
                        cur_s = float(v)
                    if prev_dict:
                        pv = prev_dict.get(col, float('nan'))
                        if pv is not None and not math.isnan(float(pv)):
                            prev_s = float(pv)

                diff = cur_s - prev_s if cur_s and prev_s else 0.
                verdict = "–"
                if cur_s and prev_s:
                    if diff <= -0.3:   verdict = "FLYING LAP ↑"
                    elif diff <= -0.1: verdict = "On it ▲"
                    elif diff <= 0.1:  verdict = "On Pace"
                    elif diff <= 0.4:  verdict = "Gap ▼"
                    else:              verdict = "Dropping Back ↓"

                sec_cond = "1"
                if lap_start_abs is not None and \
                   self.track_status_df is not None and \
                   not self.track_status_df.empty and \
                   len(self._ts_times) > 0:
                    sec_abs  = lap_start_abs + cur_s*(s_idx-1)
                    past_idx = int(np.searchsorted(self._ts_times, sec_abs, side='right')) - 1
                    if past_idx >= 0:
                        sec_cond = str(self.track_status_df["Status"].iloc[past_idx])

                cond_map = {"1":"GREEN","2":"YELLOW","3":"SC YEL",
                            "4":"SC","5":"RED","6":"VSC","7":"VSC END"}
                cond_lbl = cond_map.get(sec_cond, "GREEN")

                if   sec_cond == "4":         row_tag = "sc_active"
                elif sec_cond == "6":         row_tag = "vsc_active"
                elif sec_cond in ("2","3"):   row_tag = "yellow_sec"
                elif sec_cond == "5":         row_tag = "red_flag"
                elif not cur_s:               row_tag = "f1_white"
                elif cur_s and self._overall_sector_best[s_idx-1] and \
                     abs(cur_s - self._overall_sector_best[s_idx-1]) < 0.05:
                    row_tag = "f1_purple"
                elif diff < -0.05:            row_tag = "f1_green"
                elif diff >  0.05:            row_tag = "f1_yellow"
                else:                         row_tag = "f1_white"

                self.tree_sec.insert("", "end",
                    values=(f"S{s_idx}",
                            f"{cur_s:.3f}" if cur_s else "–",
                            f"{diff:+.3f}" if diff else "–",
                            verdict, cond_lbl),
                    tags=(row_tag,))

            # ── Avg sector times desde vueltas completadas ────────────────────
            avg_vals = []
            for s_idx2 in range(1, 4):
                col2 = f"Sector{s_idx2}Time"
                if col2 in drv_laps.columns and not completed.empty:
                    arr2 = completed[col2].to_numpy(dtype=float)
                    valid2 = arr2[~np.isnan(arr2)]
                    avg_vals.append(f"{float(np.mean(valid2[-5:])):.3f}" if len(valid2) else "–")
                else:
                    avg_vals.append("–")
            self.lbl_sec_avg.configure(
                text=f"Avg S1/S2/S3: {avg_vals[0]} / {avg_vals[1]} / {avg_vals[2]}")

        pace_txt, pace_col = "–", TEXT_SEC
        last_str, delta_str = "–", "–"
        diag_parts: List[str] = []

        if not completed.empty:
            lt_arr = completed["LapTime"].to_numpy(dtype=float)
            valid  = lt_arr[~np.isnan(lt_arr)]
            if len(valid):
                ll_s = float(valid[-1])
                last_str = fmt_lap(ll_s)
                if self.session_best_s:
                    delta_str = f"{ll_s - self.session_best_s:+.3f}s"
                if len(valid) >= 2:
                    avg  = float(np.mean(valid[-6:-1]))
                    diff = ll_s - avg
                    pace_txt = (f"IMPROVING ({diff:+.2f}s)" if diff < 0
                                else f"DROPPING ({diff:+.2f}s)")
                    pace_col = GREEN if diff < 0 else ACCENT

        self.lbl_pace.configure(text=f"Pace (5L avg): {pace_txt}", fg=pace_col)
        best_s = fmt_lap(self.session_best_s) if self.session_best_s else "–"
        self.lbl_last_lap.configure(
            text=f"Last: {last_str}  ({delta_str})  |  Best: {best_s}")

        num_completed = len(completed)
        if getattr(self, '_last_style_laps', -1) != num_completed or drv_changed:
            self._last_style_laps = num_completed
            df = self.telemetry[drv]
            tel_times = self._tel_times[drv]
            for row in self.tree_style.get_children(): self.tree_style.delete(row)

            lt_col  = completed["LapTime"].to_numpy(dtype=float)  if "LapTime"  in completed.columns else None
            tsf_col = completed["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in completed.columns else None
            lapn_col = completed["LapNumber"].to_numpy() if "LapNumber" in completed.columns else None

            if lt_col is None or tsf_col is None: return

            n_rows = len(completed)
            for ri in range(max(0, n_rows-10), n_rows):
                try:
                    lap_s = float(lt_col[ri])
                    if math.isnan(lap_s): continue
                    t_end_v = float(tsf_col[ri])
                    if math.isnan(t_end_v): continue
                    l_start = t_end_v - lap_s - self.session_start
                    l_end   = t_end_v - self.session_start

                    si = int(np.searchsorted(tel_times, self.session_start + l_start))
                    ei = int(np.searchsorted(tel_times, self.session_start + l_end))
                    n  = ei - si
                    if n < 10: continue

                    thr_c = df["Throttle"].to_numpy()[si:ei].astype(float)
                    brk_raw = df["Brake"].to_numpy()[si:ei].astype(float)
                    brk_c = np.where(brk_raw <= 1.0, brk_raw * 100.0, brk_raw)
                    spd_c = df["Speed"].to_numpy()[si:ei].astype(float)
                    rpm_c = df["RPM"].to_numpy()[si:ei] if "RPM" in df.columns else np.zeros(n)

                    dspd  = np.concatenate([[0,0,0], spd_c[3:] - spd_c[:-3]])

                    lico  = int(np.sum((thr_c==0)&(brk_c==0)&(spd_c>180)&(dspd<0)))
                    push  = int(np.sum((thr_c>=95)&(brk_c==0)&(dspd>=-1.5)))
                    brk_n = int(np.sum(brk_c > 50))

                    if is_2026_era(self.session_year):
                        clip = int(np.sum((thr_c>=95)&(brk_c==0)&(spd_c>250)&(rpm_c>10_500)&(dspd<-1.5)))
                        diag_parts.append(f"L{int(lapn_col[ri]) if lapn_col is not None else '?'}: clip={clip/n*100:.1f}%")
                    else:
                        clip = int(np.sum((thr_c>=95)&(brk_c==0)&(rpm_c>11_000)&(dspd<-1.2)))

                    p_lico = lico/n*100; p_clip = clip/n*100
                    p_push = push/n*100; p_brk  = brk_n/n*100
                    lap_str = fmt_lap(lap_s)
                    db = ""
                    if self.session_best_s:
                        db = f"{lap_s - self.session_best_s:+.3f}"

                    cond_key = "1"
                    if len(self._ts_times) > 0:
                        lap_mid = self.session_start + (l_start + l_end)/2
                        past_i  = int(np.searchsorted(self._ts_times, lap_mid, side='right')) - 1
                        if past_i >= 0:
                            cond_key = str(self.track_status_df["Status"].iloc[past_i])

                    cond_lbl = {"1":"GREEN","2":"YELLOW","3":"SC YEL","4":"SC",
                                "5":"RED","6":"VSC","7":"END"}.get(cond_key,"GREEN")

                    if   cond_key == "4":           tag = "sc_lap"
                    elif cond_key == "6":           tag = "vsc_lap"
                    elif cond_key in ("2","3"):     tag = "yellow_lap"
                    elif cond_key == "5":           tag = "red_lap"
                    elif p_clip > 3.0:              tag = "superclip"
                    elif p_clip > 1.0:              tag = "high_clip"
                    elif self.session_best_s and abs(lap_s - self.session_best_s) < 0.1:
                        tag = "f1_purple"
                    elif db and float(db) < -0.3:   tag = "f1_green"
                    elif db and float(db) > 0.5:    tag = "f1_yellow"
                    else:                           tag = "f1_white"

                    lap_num_display = int(lapn_col[ri]) if lapn_col is not None else "?"
                    self.tree_style.insert("", 0,
                        values=(lap_num_display,
                                f"{p_lico:.1f}%", f"{p_clip:.1f}%",
                                f"{p_push:.1f}%", f"{p_brk:.1f}%",
                                lap_str, db, cond_lbl),
                        tags=(tag,))
                except Exception:
                    pass

        if diag_parts:
            # Si hay vueltas con clipping alto, destacar
            high_clip_laps = [p for p in diag_parts if float(p.split("=")[1].rstrip("%")) > 3.0]
            if high_clip_laps:
                self.lbl_diag.configure(
                    text="⚡⚡ SUPERCLIPPING: " + "  ".join(high_clip_laps[-3:]), fg=PURPLE)
            else:
                self.lbl_diag.configure(
                    text="⚡ Clipping: " + "  ".join(diag_parts[-3:]), fg=ACCENT2)
        else:
            self.lbl_diag.configure(text="Behaviour: Normal — no anomalies detected", fg=ACCENT2)

    # ════════════════════════════════════════════════════════════════════════
    #  GRÁFICA DE TELEMETRÍA — Reescrita con marcadores SM/OM/⚡SC/L&C
    # ════════════════════════════════════════════════════════════════════════
    def _update_telemetry_plot(self, drv: str, abs_t: float) -> None:
        c = self.plot_canvas
        c.update_idletasks()
        W = c.winfo_width()
        H = c.winfo_height()
        if W < 50 or H < 30:
            return

        # ── Zonas de altura ───────────────────────────────────────────────────
        # LABEL_H: banda superior con iconos SM / OM / ⚡SC / L&C
        LABEL_H = 18                                      # aumentado para texto
        ERS_H   = 24 if is_2026_era(self.session_year) else 0
        TEL_TOP = LABEL_H + ERS_H
        TEL_H   = H - TEL_TOP - 4
        if TEL_H < 20:
            TEL_H = H - LABEL_H - 4
            ERS_H = 0
            TEL_TOP = LABEL_H

        try:
            df       = self.telemetry[drv]
            drv_laps = self._laps_by_driver.get(drv, pd.DataFrame())
            if "TimeSec_f" not in drv_laps.columns:
                return

            lap_times_arr = self._lap_times.get(drv, np.array([]))
            if len(lap_times_arr) == 0:
                return

            t_vals   = self._tel_times[drv]
            tsf_arr  = drv_laps["TimeSec_f"].to_numpy(dtype=float)
            lt_arr   = drv_laps["LapTime"].to_numpy(dtype=float) \
                       if "LapTime" in drv_laps.columns else None
            lapnum_arr = drv_laps["LapNumber"].to_numpy(dtype=float) \
                         if "LapNumber" in drv_laps.columns else None

            # ── Determinar inicio de la vuelta actual ──────────────────────
            idx_cur = int(np.searchsorted(lap_times_arr, abs_t, side='right'))
            idx_cur = min(idx_cur, len(lap_times_arr) - 1)

            if idx_cur > 0 and lt_arr is not None:
                prev_end = float(tsf_arr[idx_cur - 1])
                prev_lt  = float(lt_arr[idx_cur - 1])
                if not math.isnan(prev_end) and not math.isnan(prev_lt):
                    lap_abs_start = prev_end
                else:
                    lap_abs_start = abs_t - 90.0
            else:
                lap_abs_start = float(tsf_arr[0]) if len(tsf_arr) > 0 else abs_t - 90.0

            lap_abs_end = abs_t

            if lt_arr is not None and idx_cur > 0:
                ref_laptime = float(lt_arr[idx_cur - 1])
                if math.isnan(ref_laptime) or ref_laptime <= 0:
                    ref_laptime = 120.0
            else:
                ref_laptime = 120.0

            si = int(np.searchsorted(t_vals, lap_abs_start, side='left'))
            ei = int(np.searchsorted(t_vals, lap_abs_end,   side='right'))
            n  = ei - si
            if n < 3:
                return

            times     = t_vals[si:ei]
            speeds    = df["Speed"].to_numpy()[si:ei].astype(float)
            throttle  = df["Throttle"].to_numpy()[si:ei].astype(float)
            brake_raw = df["Brake"].to_numpy()[si:ei].astype(float)
            brake     = np.where(brake_raw <= 1.0, brake_raw * 100.0, brake_raw)
            rpm_arr   = df["RPM"].to_numpy()[si:ei].astype(float) if "RPM" in df.columns else np.zeros(n)

            t_span = ref_laptime
            if t_span <= 0:
                return

            xs = ((times - lap_abs_start) / t_span * W).astype(int)
            xs = np.clip(xs, 0, W - 1)

            cursor_prog = clamp((abs_t - lap_abs_start) / t_span, 0.0, 1.0)
            cursor_x    = int(cursor_prog * W)
            lap_num = int(lapnum_arr[idx_cur]) if lapnum_arr is not None else 0

            # ── Obtener arrays de modos DRS/SM/OM ─────────────────────────────
            drs_arr  = df["DRS"].to_numpy()[si:ei] if "DRS" in df.columns else None
            sm_arr   = df["StraightMode"].to_numpy()[si:ei] \
                       if "StraightMode" in df.columns else None
            om_arr   = df["OvertakeMode"].to_numpy()[si:ei] \
                       if "OvertakeMode" in df.columns else None

            # ── BORRAR y redibujar ────────────────────────────────────────
            for tag in ("_plot_bg", "_plot_ers", "_plot_lines",
                        "_plot_sec", "_plot_overlay", "_plot_labels", "_plot_icons"):
                c.delete(tag)

            # Fondo base
            c.create_rectangle(0, 0, W, H, fill="#080810", outline="", tags="_plot_bg")
            c.create_rectangle(0, 0, W, TEL_TOP, fill="#04040c", outline="", tags="_plot_bg")

            # Rejilla horizontal de velocidad
            for spd_ref, lbl in ((300, "300"), (200, "200"), (100, "100")):
                y = TEL_TOP + int((1.0 - spd_ref / 350.0) * TEL_H)
                c.create_line(0, y, W, y, fill="#15152a", width=1, tags="_plot_bg")
                c.create_text(2, y - 1, text=lbl, fill="#33336a",
                    font=(FONT, 7), anchor="sw", tags="_plot_labels")

            # ── ERS SOC band ──────────────────────────────────────────────────
            if ERS_H > 0:
                SOC_Y_TOP = LABEL_H
                SOC_Y_BOT = LABEL_H + ERS_H
                c.create_rectangle(0, SOC_Y_TOP, W, SOC_Y_BOT,
                    fill="#03030a", outline="", tags="_plot_ers")
                c.create_text(3, SOC_Y_TOP + 1, text="ERS SOC",
                    fill="#2255aa", font=(FONT, 7, "bold"), anchor="nw", tags="_plot_ers")

                ers_cached = self._ers_state.get(drv)
                soc_start = float(ers_cached[1]) if ers_cached is not None \
                            else ERS_CAPACITY_KJ * 0.90

                dt_arr2 = np.diff(times)

                soc_pcts: list = []
                if len(dt_arr2) >= 2:
                    soc_p = soc_start
                    thr2  = throttle[1:]; brk2 = brake[1:]
                    spd2  = speeds[1:];   rpm2 = rpm_arr[1:]
                    for k in range(len(dt_arr2)):
                        dt2 = float(dt_arr2[k])
                        sp_pct = (soc_p / ERS_CAPACITY_KJ) * 100.0
                        th = thr2[k]; bk = brk2[k]; sp = spd2[k]; rp = rpm2[k]
                        if th >= 95 and bk == 0 and sp >= ERS_DEPLOY_SPD_MIN:
                            spd_f = clamp((sp - ERS_DEPLOY_SPD_MIN) / (320. - ERS_DEPLOY_SPD_MIN), 0, 1)
                            d_kw  = ERS_DEPLOY_KW * (0.4 + 0.6 * spd_f)
                            if sp_pct <= ERS_CLIP_SOC_THRESH:
                                d_kw = 0.0
                            mgu_h = 40.0 * clamp((rp - 6000.) / (MAX_RPM - 6000.), 0, 1)
                            soc_p = float(np.clip(soc_p + (mgu_h - d_kw) * dt2,
                                                  0.0, ERS_CAPACITY_KJ))
                        elif bk > 20:
                            r2 = ERS_REGEN_BRAKE_KW * clamp(bk / 100., 0, 1)
                            soc_p = float(np.clip(soc_p + r2 * dt2, 0.0, ERS_CAPACITY_KJ))
                        elif th < 80 and bk == 0 and sp > 80:
                            r2 = 60.0 * (1. - th / 80.) if th >= 5 else ERS_REGEN_COAST_KW
                            soc_p = float(np.clip(soc_p + r2 * dt2, 0.0, ERS_CAPACITY_KJ))
                        soc_pcts.append(clamp((soc_p / ERS_CAPACITY_KJ) * 100., 0, 100))

                if soc_pcts:
                    poly = [0, SOC_Y_BOT]
                    for k, pct2 in enumerate(soc_pcts):
                        poly += [int(xs[min(k + 1, len(xs)-1)]),
                                 SOC_Y_BOT - int((pct2 / 100.) * ERS_H)]
                    poly += [cursor_x, SOC_Y_BOT]
                    if len(poly) >= 6:
                        c.create_polygon(poly, fill="#003366", outline="", tags="_plot_ers")
                    line = []
                    for k, pct2 in enumerate(soc_pcts):
                        line += [int(xs[min(k + 1, len(xs)-1)]),
                                 SOC_Y_BOT - int((pct2 / 100.) * ERS_H)]
                    if len(line) >= 4:
                        c.create_line(line, fill=ACCENT2, width=1,
                            smooth=True, tags="_plot_ers")

                clip_y = SOC_Y_BOT - int((ERS_CLIP_SOC_THRESH / 100.) * ERS_H)
                c.create_line(0, clip_y, W, clip_y,
                    fill=ACCENT, width=1, dash=(4, 3), tags="_plot_ers")
                c.create_text(W - 2, clip_y - 1, text="CLIP", fill=ACCENT,
                    font=(FONT, 6, "bold"), anchor="se", tags="_plot_ers")

            # ── Guías de sector ────────────────────────────────────────────────
            SEC_FILLS = ["#0d0900", "#1a1500", "#110022", "#001a1a"]
            sec_bounds = [0]
            try:
                dl_s = drv_laps
                row_i = idx_cur
                for scol in ["Sector1SessionTime", "Sector2SessionTime"]:
                    if scol in dl_s.columns:
                        sv = float(dl_s[scol].to_numpy(dtype=float)[row_i])
                        if not math.isnan(sv):
                            sx = int(clamp((sv - lap_abs_start) / t_span, 0, 1) * W)
                            sec_bounds.append(sx)
            except Exception:
                pass

            if len(sec_bounds) == 1:
                sec_bounds = [0, W // 3, 2 * W // 3, W]
            elif len(sec_bounds) == 2:
                sec_bounds.append(W)
            elif len(sec_bounds) == 3:
                sec_bounds.append(W)

            sec_labels = ["S1", "S2", "S3"]
            sec_line_cols = ["#776600", "#6600aa", "#006666"]
            for si_n in range(3):
                x0 = sec_bounds[si_n]
                x1 = min(sec_bounds[si_n + 1], W)
                if x1 > x0:
                    c.create_rectangle(x0, TEL_TOP, x1, TEL_TOP + TEL_H,
                        fill=SEC_FILLS[si_n + 1], outline="", tags="_plot_sec")
                if si_n > 0:
                    c.create_line(x0, TEL_TOP, x0, TEL_TOP + TEL_H,
                        fill=sec_line_cols[si_n], width=1, dash=(5, 3), tags="_plot_sec")
                lx = x0 + 3
                c.create_text(lx, TEL_TOP + TEL_H - 2, text=sec_labels[si_n],
                    fill=sec_line_cols[si_n], font=(FONT, 7, "bold"),
                    anchor="sw", tags="_plot_sec")

            # ══════════════════════════════════════════════════════════════════
            # BANDA SUPERIOR — Marcadores con ICONOS de texto
            # ══════════════════════════════════════════════════════════════════
            # En lugar de solo colorear el fondo, ahora dibujamos iconos
            # encima de cada zona activa: SM (verde), OM (púrpura), ⚡SC (rojo),
            # y también marcamos L&C (azul) en la zona de telemetría.
            # Para evitar superposición, agrupamos runs contiguos del mismo modo.

            step2 = max(1, n // 300)

            # Construir arrays de modos por sample
            mode_arr = np.zeros(n, dtype=np.uint8)
            # 1=SM, 2=OM, 3=SC (superclipping), 4=L&C
            prev_spd_arr = np.concatenate([[speeds[0]], speeds[:-1]])
            dspd_arr = speeds - prev_spd_arr

            for k in range(n):
                thr_k = throttle[k]; brk_k = brake[k]; spd_k = speeds[k]
                rpm_k = rpm_arr[k]

                om_on = bool(om_arr[k]) if om_arr is not None else False
                sm_on = (bool(sm_arr[k]) if sm_arr is not None
                         else (_drs_is_open(float(drs_arr[k]))
                               if drs_arr is not None else False))

                # Superclipping: WOT + RPM alto + velocidad NO aumenta + ERS bajo
                # Usamos snap.ers_soc como proxy (snapshot del frame actual)
                is_sc = (thr_k >= 95 and brk_k == 0 and spd_k >= ERS_DEPLOY_SPD_MIN
                         and rpm_k >= 10_500 and dspd_arr[k] < -1.0)
                # L&C: throttle=0, sin freno, alta velocidad, velocidad bajando
                is_lc = (thr_k == 0 and brk_k == 0 and spd_k > 200 and dspd_arr[k] < -0.5)

                if om_on:
                    mode_arr[k] = 2
                elif sm_on:
                    mode_arr[k] = 1
                elif is_sc:
                    mode_arr[k] = 3
                elif is_lc:
                    mode_arr[k] = 4

            # Dibujar fondo de banda y luego iconos de texto en runs
            MODE_BG   = {1: "#002800", 2: "#1a0033", 3: "#330000", 4: "#00001a"}
            MODE_FG   = {1: "#00cc44", 2: PURPLE,    3: ACCENT,    4: ACCENT2}
            MODE_ICON = {1: "SM▶",     2: "OM⚡",    3: "⚡SC",    4: "L&C"}
            MIN_ICON_W = 24   # píxeles mínimos de un run para dibujar icono

            k = 0
            while k < n:
                m = mode_arr[k]
                if m == 0:
                    k += 1
                    continue
                # Extender run
                j = k + 1
                while j < n and mode_arr[j] == m:
                    j += 1
                # Rango de píxeles
                x0 = int(xs[k])
                x1 = int(xs[min(j - 1, len(xs)-1)])
                if x1 < x0:
                    x1 = x0 + 1
                # Fondo de la banda superior
                c.create_rectangle(x0, 0, x1, LABEL_H,
                    fill=MODE_BG[m], outline="", tags="_plot_overlay")
                # Icono centrado si el run es suficientemente ancho
                run_w = x1 - x0
                if run_w >= MIN_ICON_W:
                    cx_icon = (x0 + x1) // 2
                    c.create_text(cx_icon, LABEL_H // 2,
                        text=MODE_ICON[m], fill=MODE_FG[m],
                        font=(FONT, 7, "bold"), anchor="center",
                        tags="_plot_icons")
                k = j

            # ── Speed line (blanca) ────────────────────────────────────────────
            step = max(1, n // 500)
            spd_pts = []
            for k in range(0, n, step):
                y = TEL_TOP + int((1.0 - clamp(speeds[k] / 350.0, 0, 1)) * TEL_H)
                spd_pts += [int(xs[k]), y]
            if len(spd_pts) >= 4:
                c.create_line(spd_pts, fill=F1_WHITE, width=2,
                    smooth=True, tags="_plot_lines")

            # ── Throttle line (verde) ──────────────────────────────────────────
            thr_pts = []
            for k in range(0, n, step):
                y = TEL_TOP + int((1.0 - clamp(throttle[k] / 100.0, 0, 1)) * TEL_H)
                thr_pts += [int(xs[k]), y]
            if len(thr_pts) >= 4:
                c.create_line(thr_pts, fill=GREEN, width=1,
                    smooth=True, tags="_plot_lines")

            # ── Brake bars — franja roja en el 10% superior ────────────────────
            BRK_ZONE_H  = max(8, int(TEL_H * 0.10))
            BRK_ZONE_Y0 = TEL_TOP
            BRK_ZONE_Y1 = TEL_TOP + BRK_ZONE_H
            for k in range(0, n, step):
                if brake[k] > 50:
                    x1b = int(xs[k])
                    x2b = x1b + max(2, step)
                    c.create_rectangle(x1b, BRK_ZONE_Y0, x2b, BRK_ZONE_Y1,
                        fill=ACCENT, outline="", tags="_plot_lines")

            # ── L&C markers en la zona de telemetría (líneas verticales cian) ──
            # Adicional: cuando detectamos L&C, dibujamos una línea vertical suave
            in_lc = False
            lc_x0 = 0
            for k in range(0, n, step):
                is_lc_k = (mode_arr[k] == 4)
                if is_lc_k and not in_lc:
                    in_lc = True
                    lc_x0 = int(xs[k])
                elif not is_lc_k and in_lc:
                    in_lc = False
                    lc_x1 = int(xs[k])
                    if lc_x1 > lc_x0:
                        c.create_rectangle(lc_x0, TEL_TOP, lc_x1, TEL_TOP + TEL_H,
                            fill="#00001a", outline="", stipple="gray25",
                            tags="_plot_lines")

            # ── Cursor ────────────────────────────────────────────────────────
            PROG_Y = H - 4
            c.create_rectangle(0, PROG_Y, W, H,
                fill="#111122", outline="", tags="_plot_overlay")
            c.create_rectangle(0, PROG_Y, cursor_x, H,
                fill=YELLOW, outline="", tags="_plot_overlay")
            c.create_line(cursor_x, 0, cursor_x, PROG_Y,
                fill="#888800", width=5, tags="_plot_overlay")
            c.create_line(cursor_x, 0, cursor_x, PROG_Y,
                fill=YELLOW, width=2, tags="_plot_overlay")
            cx_tri = cursor_x
            tri = [cx_tri - 8, 0, cx_tri + 8, 0, cx_tri, 12]
            c.create_polygon(tri, fill=YELLOW, outline="#000000",
                width=1, tags="_plot_overlay")

            ci = min(max(int(cursor_prog * (n - 1)), 0), n - 1)
            thr_c = throttle[ci]; brk_c = brake[ci]; spd_c = speeds[ci]
            if   thr_c == 0 and brk_c == 0 and spd_c > 180: mode_txt = "L&C"
            elif thr_c >= 95 and brk_c == 0:                 mode_txt = "WOT"
            elif brk_c > 50:                                  mode_txt = "BRK"
            elif brk_c > 10 and thr_c > 0:                   mode_txt = "TRAIL"
            else:                                             mode_txt = ""
            if mode_txt:
                tx = min(cursor_x + 5, W - 40)
                c.create_text(tx, TEL_TOP + 8, text=mode_txt, fill=YELLOW,
                    font=(FONT, 8, "bold"), anchor="w", tags="_plot_overlay")

            # ── Leyendas ──────────────────────────────────────────────────────
            c.create_text(W - 4, TEL_TOP + 3, text=f"LAP {lap_num}",
                fill=TEXT_SEC, font=(FONT, 8, "bold"), anchor="ne",
                tags="_plot_labels")
            for i, (txt, clr) in enumerate(
                    (("SPD", F1_WHITE), ("THR", GREEN), ("BRK", ACCENT))):
                c.create_text(4 + i * 36, PROG_Y - 2, text=f"▬{txt}", fill=clr,
                    font=(FONT, 7, "bold"), anchor="sw", tags="_plot_labels")
            if ERS_H > 0:
                c.create_text(W - 4, PROG_Y - 2, text="▬ERS", fill=ACCENT2,
                    font=(FONT, 7, "bold"), anchor="se", tags="_plot_labels")

            # Leyenda de iconos de la banda superior
            icon_x = 4
            for m_id, icon, fg_c in ((1, "SM", "#00cc44"), (2, "OM⚡", PURPLE),
                                      (3, "⚡SC", ACCENT), (4, "L&C", ACCENT2)):
                c.create_text(icon_x, LABEL_H // 2, text=icon, fill=fg_c,
                    font=(FONT, 6, "bold"), anchor="w", tags="_plot_labels")
                icon_x += len(icon) * 6 + 8

        except Exception as exc:
            log.debug("Telemetry plot: %s", exc, exc_info=True)

    # ════════════════════════════════════════════════════════════════════════
    #  UTILIDADES
    # ════════════════════════════════════════════════════════════════════════
    def _set_status(self, msg: str) -> None:
        self.lbl_status.configure(text=msg)

    def _spin(self, active: bool) -> None:
        frames = ["⠋","⠙","⠹","⠸","⠼","⠴","⠦","⠧","⠇","⠏"]
        self._sf = getattr(self, "_sf", 0)
        if not active:
            self.lbl_spin.configure(text=""); return
        def tick():
            if self.btn_load["state"] == tk.DISABLED:
                self._sf = (self._sf+1) % len(frames)
                self.lbl_spin.configure(text=frames[self._sf])
                self.root.after(80, tick)
            else:
                self.lbl_spin.configure(text="")
        tick()


# ════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ════════════════════════════════════════════════════════════════════════════
def main() -> None:
    root = tk.Tk()
    try: root.iconbitmap("f1.ico")
    except Exception: pass

    app = F1Dashboard(root)

    def on_close():
        app.is_playing = False
        if app._worker:
            app._worker.stop()
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
