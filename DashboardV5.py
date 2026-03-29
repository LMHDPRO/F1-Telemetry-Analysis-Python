"""
F1 Telemetry Analysis 26' by Pardiñaz  v6.54
pip install dearpygui fastf1 pandas numpy

Changes in v6.54:
  - DRS: only shows "DRS OPEN" (green), hidden otherwise
  - Race: FINISH label (not OUT) for drivers who completed total laps
  - Map: OUT/FINISH drivers dots are hidden
  - Gap/Interval: proper "+N Lap(s)" using lap-number delta
  - Driving Style: wider, friendlier colour legend, Cond → GRN/SC/VSC/RED
  - FP sessions: countdown timer MM:SS, sorted by best lap
  - Qualifying: Q1/Q2/Q3 auto-detected with countdowns, sorted by best lap
  - Red flag pauses Q countdown; Q3 2026 extended to 15 min
"""
from __future__ import annotations
import threading, queue, time, os, math, shutil, logging, faulthandler, signal
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
import dearpygui.dearpygui as dpg
import fastf1, pandas as pd, numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("F1v654")

faulthandler.enable()
try: faulthandler.register(signal.SIGUSR1)
except (AttributeError, OSError): pass

CACHE_DIR = os.path.join(os.path.expanduser("~"), ".f1_cache")
os.makedirs(CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(CACHE_DIR)

def _c(h: str, a: int = 255) -> Tuple[int, int, int, int]:
    h = h.lstrip("#")
    return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), a)

BG0=_c("050510"); BG1=_c("09091a"); BG2=_c("0d0d20"); BG3=_c("121226"); BG4=_c("181830")
RED=_c("e10600"); BLUE=_c("00a0e9"); GREEN=_c("00e676"); YLW=_c("ffd600")
ORG=_c("ff6d00"); PRP=_c("d500f9"); CYAN=_c("00e5ff"); PINK=_c("ff3d71")
TXT=_c("eaeaf8"); TMED=_c("8888aa"); TDIM=_c("484860"); BRD=_c("1c1c36"); BRDL=_c("262640")
NONE=(0,0,0,0)
F1_PRP=_c("d500f9"); F1_GRN=_c("00e676"); F1_YLW=_c("ffd600"); F1_WHT=_c("eaeaf8")

# Style-table row colour scheme (friendly traffic-light palette + legend)
STYLE_COL_BEST    = CYAN          # best/near-best lap in session
STYLE_COL_FAST    = GREEN         # fast vs recent average
STYLE_COL_NORMAL  = TXT           # normal lap
STYLE_COL_SLOW    = YLW           # slightly slow
STYLE_COL_VERY_SLOW = ORG         # notably slow
STYLE_COL_SUPERCLIP = PRP         # superclipping lap

TEAM_COLORS: Dict[str, Tuple] = {
    "Mercedes":_c("00d2be"), "Ferrari":_c("dc0000"),
    "Red Bull Racing":_c("3671c6"), "McLaren":_c("ff8700"),
    "Aston Martin":_c("358c75"), "Aston Martin Aramco Cognizant":_c("358c75"),
    "Alpine":_c("0090ff"), "Williams":_c("37bedd"), "RB":_c("6692ff"),
    "Kick Sauber":_c("52e252"), "Haas F1 Team":_c("b6babd"), "Haas":_c("b6babd"),
    "Alfa Romeo":_c("c92d4b"), "AlphaTauri":_c("2b4562"),
}
TYRE_COL   = {"S":YLW,"M":TXT,"H":_c("cccccc"),"I":GREEN,"W":BLUE,"U":TDIM}
TYRE_FULL  = {"S":"SOFT","M":"MEDIUM","H":"HARD","I":"INTER","W":"WET","U":"UNK"}
TYRE_SHORT = {"S":"S","M":"M","H":"H","I":"I","W":"W","U":"?"}
TRACK_STATUS = {
    "1":("GREEN FLAG",GREEN,_c("002200",180)), "2":("YELLOW FLAG",YLW,_c("222200",180)),
    "3":("SECTOR YEL",YLW,_c("222200",180)),  "4":("SAFETY CAR",ORG,_c("221100",180)),
    "5":("RED FLAG",RED,_c("220000",180)),     "6":("VIRTUAL SC",PRP,_c("110022",180)),
    "7":("VSC END",GREEN,_c("002200",180)),
}
# Short condition label for Style table Cond column
COND_SHORT = {
    "1":"GRN","2":"YEL","3":"SYEL","4":"SC","5":"RED","6":"VSC","7":"VSC"
}
SESSION_INFO = {
    "FP1":("FREE PRACTICE 1",BLUE),"FP2":("FREE PRACTICE 2",BLUE),"FP3":("FREE PRACTICE 3",BLUE),
    "Q":("QUALIFYING",YLW),"SQ":("SPRINT QUALIFYING",ORG),"S":("SPRINT",ORG),"R":("RACE",RED),
}
# Standard FP durations (seconds)
FP_DURATION_S = {"FP1": 3600, "FP2": 3600, "FP3": 3600}
# Standard Q phase durations (seconds); Q3 extended to 15 min from 2026
Q_PHASE_DUR_BASE = [1080, 900, 720]   # Q1=18min, Q2=15min, Q3=12min (pre-2026)
Q_PHASE_DUR_2026 = [1080, 900, 900]   # Q1=18min, Q2=15min, Q3=15min (2026+)
Q_PHASE_NAMES = ["Q1","Q2","Q3"]

DRS_ACTIVE = {10,12,14}; MAX_RPM = 13_500; ERS_CAP_KJ = 4000.0
ERS_DEP_KW = 350.0; ERS_RBK_KW = 350.0; ERS_RCS_KW = 40.0; ERS_SPD_MIN = 200.0; ERS_CLIP_TH = 5.0
VP_W,VP_H = 1760,992; LEFT_W = 530; HDR_H = 54; CTL_H = 52; HUD_W = 310
MAP_W = VP_W-LEFT_W-HUD_W-16
MAX_DRV = 22; MAX_STYLE_ROWS = 70
_RACE_COLS = [("P",30),("+/-",28),("DRV",40),("Team",86),("Gap",62),("Int",60),("Last",72),("Tyr",32),("L",24)]
_QUAL_COLS = [("P",30),("DRV",40),("Team",86),("Best",72),("Gap",72),("Tyr",32),("L",24)]
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/bahnschrift.ttf","C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/calibrib.ttf","C:/Windows/Fonts/arialbd.ttf","C:/Windows/Fonts/arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]

# ── Utility ─────────────────────────────────────────────────────────────
def _drs_open(v) -> bool:
    vi = int(safe(v,0)); return vi in DRS_ACTIVE or (vi > 8 and vi % 2 == 0)

def _norm_brk(b) -> float:
    v = float(safe(b,0.0)); return v*100.0 if v<=1.0 else v

def safe(v: Any, d: float = 0.0) -> float:
    try:
        f = float(v); return d if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError): return d

def clamp(v, lo, hi): return max(lo, min(hi, v))

def fmt_lap(s: float) -> str:
    try:
        if pd.isna(s) or s <= 0: return "--:--.---"
        m, sec = divmod(float(s), 60); return f"{int(m)}:{sec:06.3f}"
    except: return "--:--.---"

def fmt_countdown(s: float) -> str:
    """Format remaining seconds as MM:SS countdown."""
    if s <= 0: return "00:00"
    m, sec = divmod(int(s), 60); return f"{m:02d}:{sec:02d}"

def hms(s: int) -> str:
    h, r = divmod(max(0,int(s)),3600); m, s = divmod(r,60); return f"{h:02d}:{m:02d}:{s:02d}"

def is_2026(year: int) -> bool: return year >= 2026

def td_to_float(td) -> float:
    if td is None: return float("nan")
    try: return float(pd.Timedelta(td).total_seconds())
    except: return float("nan")


def strip_fastf1(df: pd.DataFrame) -> pd.DataFrame:
    """Convert FastF1 Timedelta/Datetime columns to plain float seconds."""
    if df is None or df.empty: return pd.DataFrame()
    res = {}
    for col in df.columns:
        arr = df[col]; dtype = arr.dtype
        if pd.api.types.is_timedelta64_dtype(dtype):
            ns = arr.values.view(np.int64).astype(float); secs = ns/1e9
            secs[ns == np.iinfo(np.int64).min] = float("nan"); res[col] = secs
        elif pd.api.types.is_datetime64_any_dtype(dtype):
            try:
                ns = (arr.dt.view(np.int64).to_numpy().astype(float)
                      if hasattr(arr,"dt") else arr.values.astype(np.int64).astype(float))
                secs = ns/1e9; secs[ns == np.iinfo(np.int64).min] = float("nan"); res[col] = secs
            except: res[col] = arr.to_numpy(dtype=object, na_value=float("nan"))
        else:
            try: res[col] = arr.to_numpy()
            except: res[col] = arr.values
    return pd.DataFrame(res)


def add_timesec_col(df: pd.DataFrame, col: str = "Time") -> pd.DataFrame:
    d = strip_fastf1(df)
    if not d.empty and col in d.columns: d["TimeSec_f"] = d[col].to_numpy(dtype=float)
    return d


def detect_q_phases(lbd: Dict[str, pd.DataFrame], t_min: float) -> List[float]:
    """
    Find Q1/Q2/Q3 phase start times (session-relative seconds) by looking
    for gaps > 5 minutes between consecutive laps across all drivers.
    Returns up to 3 phase-start times; first is always 0.0.
    """
    all_ends: List[float] = []
    for dl in lbd.values():
        if "TimeSec_f" not in dl.columns or "LapTime" not in dl.columns: continue
        tsf = dl["TimeSec_f"].to_numpy(dtype=float)
        lt  = dl["LapTime"].to_numpy(dtype=float) if "LapTime" in dl.columns else np.full(len(tsf), float("nan"))
        for t, l in zip(tsf, lt):
            if not math.isnan(t) and not math.isnan(l) and l > 10:
                all_ends.append(t - t_min)
    if not all_ends: return [0.0]
    all_ends.sort()
    bounds = [0.0]
    for i in range(1, len(all_ends)):
        if all_ends[i] - all_ends[i-1] > 360:   # 6-min gap → new phase
            bounds.append(all_ends[i])
    return bounds[:3]


def _simulate_ers(soc_kj, thr, brk, spd, rpm, dt):
    """
    Simplified ERS simulation.
    Superclipping: battery below threshold → MGU-K reverses, charges at ~80% max regen.
    """
    dep_acc = reg_acc = 0.0; clip = False; n = len(dt)
    if n == 0: return soc_kj, dep_acc, reg_acc, clip
    th = thr[1:n+1] if len(thr)>n else thr[:n]
    bk = brk[1:n+1] if len(brk)>n else brk[:n]
    sp = spd[1:n+1] if len(spd)>n else spd[:n]
    rp = rpm[1:n+1] if len(rpm)>n else rpm[:n]
    on = (th >= 95) & (bk == 0) & (sp >= ERS_SPD_MIN)
    sf = np.clip((sp-ERS_SPD_MIN)/120.0, 0, 1)
    dkw  = ERS_DEP_KW*(0.4+0.6*sf)*on
    r_b  = ERS_RBK_KW*np.clip(bk/100.0,0,1)*(bk>20)
    r_p  = 60.0*(1.0-th/80.0)*((th>=5)&(th<80)&(bk==0)&(sp>80))
    r_c  = ERS_RCS_KW*((th==0)&(bk==0)&(sp>80))
    r_m  = 40.0*np.clip((rp-6000.0)/(MAX_RPM-6000.0),0,1)*(rp>6000)
    for k in range(n):
        dk = float(dt[k]); d = float(dkw[k])
        r  = float(r_b[k]+r_p[k]+r_c[k]+r_m[k])
        p  = (soc_kj/ERS_CAP_KJ)*100.0
        if on[k]:
            if p <= ERS_CLIP_TH:
                d = 0.0; clip = True
                net = ERS_RBK_KW*0.80*dk     # MGU-K reversed: hard charge
            else:
                clip = False; net = float(r_m[k])*dk - d*dk
        else:
            clip = False; net = r*dk
        soc_kj = float(np.clip(soc_kj+net, 0.0, ERS_CAP_KJ))
        if on[k] and d > 0: dep_acc += d*dk
        if net > 0:          reg_acc += net
    return soc_kj, dep_acc, reg_acc, clip


class DropQueue:
    def __init__(self): self._q: queue.Queue = queue.Queue(maxsize=1)
    def put_nowait(self, item):
        try: self._q.get_nowait()
        except queue.Empty: pass
        try: self._q.put_nowait(item)
        except queue.Full: pass
    def get(self, timeout=0.15): return self._q.get(timeout=timeout)


@dataclass
class Snap:
    drv:str=""; abbr:str=""; name:str=""; number:str=""
    team:str="Unknown"; pos:int=999; lap:int=0
    gap:str="–"; interval:str="–"; gap_num:float=999.0; int_num:float=999.0
    speed:float=0.0; rpm:float=0.0; throttle:float=0.0; brake:float=0.0
    gear:int=0; drs:float=0.0
    tyre:str="–"; tyre_prev:str="–"; tyre_laps:int=0
    dist:float=-1.0; is_out:bool=False; is_finished:bool=False
    x:float=float("nan"); y:float=float("nan")
    ers_soc:float=50.0; is_clipping:bool=False
    in_pit:bool=False; pit_out_lap:bool=False
    lap_type:str=""; last_lap_str:str="–"; best_lap_str:str="–"
    best_lap_s:float=float("inf")   # for FP/Q sorting
    sector_times:Tuple=(0.0,0.0,0.0); pits_done:int=0; pos_change:int=0


# ═══════════════════════════════════════════════════════════════════════
#  WORKER
# ═══════════════════════════════════════════════════════════════════════
class SnapshotWorker(threading.Thread):
    def __init__(self, app:"F1App"):
        super().__init__(daemon=True, name="SnapWorker")
        self.app = app; self.inbox = DropQueue(); self._stop = threading.Event()

    def stop(self): self._stop.set()
    def request(self, elapsed:float): self.inbox.put_nowait(elapsed)

    def run(self):
        while not self._stop.is_set():
            elapsed = None
            try:
                elapsed = self.inbox.get(timeout=0.15)
                result = self._compute(elapsed)
                try: self.app._result_q.get_nowait()
                except queue.Empty: pass
                try: self.app._result_q.put_nowait(result)
                except queue.Full: pass
            except queue.Empty: continue
            except Exception as exc: log.exception("Worker unhandled elapsed=%s: %s", elapsed, exc)

    def _compute(self, elapsed:float) -> dict:
        app = self.app
        abs_t = app.session_start + elapsed
        is_race = app.session_type in ("R","S")
        is_fp   = app.session_type in ("FP1","FP2","FP3")
        is_q    = app.session_type in ("Q","SQ")

        # ── Track status ──────────────────────────────────────────────
        ts_key = "1"
        try:
            if (app.track_status_df is not None and not app.track_status_df.empty
                    and len(app._ts_times) > 0):
                idx = int(np.searchsorted(app._ts_times, abs_t, side="right")) - 1
                if idx >= 0: ts_key = str(app.track_status_df["Status"].iloc[idx])
        except Exception as exc: log.debug("ts_key: %s", exc)
        ts_txt, ts_col, _ = TRACK_STATUS.get(ts_key, TRACK_STATUS["1"])

        # ── Weather ───────────────────────────────────────────────────
        weather_txt = None
        try:
            if (app.weather_data is not None and not app.weather_data.empty
                    and len(app._wx_times) > 0):
                idx = int(np.searchsorted(app._wx_times, abs_t, side="right")) - 1
                if idx >= 0:
                    w = app.weather_data.iloc[idx]; rain = "Rain" if w.get("Rainfall") else "Dry"
                    weather_txt = (f"Air {round(safe(w.get('AirTemp',0)),1)}°C  "
                                   f"Track {round(safe(w.get('TrackTemp',0)),1)}°C  {rain}")
        except Exception as exc: log.debug("weather: %s", exc)

        snaps: List[Snap] = []
        prev_pos = dict(app._prev_positions)

        for drv, df in app.telemetry.items():
            try:
                times = app._tel_times[drv]
                if len(times) == 0: continue
                is_out = abs_t > times[-1]
                idx = int(min(np.searchsorted(times, abs_t), len(times)-1))

                col_cache: Dict[str,np.ndarray] = {}
                def g(c, d=0.0):
                    if c not in col_cache:
                        try: col_cache[c] = df[c].to_numpy()
                        except: col_cache[c] = None
                    a = col_cache[c]
                    if a is None or idx >= len(a): return d
                    try:
                        v = float(a[idx]); return d if (math.isnan(v) or math.isinf(v)) else v
                    except: return d
                def gs(c):
                    if c not in col_cache:
                        try: col_cache[c] = df[c].to_numpy()
                        except: col_cache[c] = None
                    a = col_cache[c]
                    if a is None or idx >= len(a): return ""
                    return str(a[idx])

                sn = Snap(
                    drv=drv, abbr=gs("Abbr") or drv, name=gs("Name") or drv,
                    number=gs("Number") or drv, team=gs("Team") or "Unknown",
                    speed=g("Speed"), rpm=g("RPM"), throttle=g("Throttle"),
                    brake=_norm_brk(g("Brake")), gear=int(g("nGear")), drs=g("DRS"),
                    x=g("X",float("nan")), y=g("Y",float("nan")), is_out=is_out,
                )

                # ── Lap data ─────────────────────────────────────────
                try:
                    dl  = app._laps_by_drv.get(drv, pd.DataFrame())
                    lta = app._lap_times.get(drv, np.array([]))
                    if not dl.empty and "TimeSec_f" in dl.columns and len(lta) > 0:
                        il  = int(np.searchsorted(lta, abs_t, side="right"))
                        cli = max(0, min(il, len(dl)-1))

                        lcc: Dict[str,np.ndarray] = {}
                        def lget(col, d=None):
                            if col not in lcc:
                                lcc[col] = dl[col].to_numpy() if col in dl.columns else None
                            a = lcc[col]
                            if a is None or cli >= len(a): return d
                            return a[cli]

                        pos_v = lget("Position")
                        if pos_v is not None:
                            try: sn.pos = int(safe(float(pos_v),999))
                            except: pass
                        lap_v = lget("LapNumber")
                        if lap_v is not None:
                            try: sn.lap = int(safe(float(lap_v),0))
                            except: pass

                        lt_arr = (lcc.get("LapTime") or
                                  (dl["LapTime"].to_numpy(dtype=float) if "LapTime" in dl.columns else None))
                        if lt_arr is not None:
                            lcc["LapTime"] = lt_arr
                            if cli < len(lt_arr) and not math.isnan(float(lt_arr[cli])):
                                sn.last_lap_str = fmt_lap(float(lt_arr[cli]))
                            valid = lt_arr[:cli+1]
                            vlt = valid[~np.isnan(valid.astype(float))] if len(valid) else np.array([])
                            if len(vlt):
                                sn.best_lap_s   = float(np.min(vlt))
                                sn.best_lap_str = fmt_lap(sn.best_lap_s)

                        comp = lget("Compound")
                        if comp is not None:
                            cr = str(comp)
                            if cr not in ("nan","None",""): sn.tyre = f"({cr[0].upper()})"
                        if cli > 0:
                            ca = dl["Compound"].to_numpy() if "Compound" in dl.columns else None
                            if ca is not None and cli-1 < len(ca):
                                cp = str(ca[cli-1])
                                if cp not in ("nan","None",""): sn.tyre_prev = f"({cp[0].upper()})"
                        tl_v = lget("TyreLife")
                        if tl_v is not None:
                            try: sn.tyre_laps = int(float(tl_v))
                            except: pass

                        # ── Pit detection (session-relative times, no session_start offset) ──
                        if "PitInTime" in dl.columns and "PitOutTime" in dl.columns:
                            pit_in  = dl["PitInTime"].to_numpy(dtype=float)
                            pit_out = dl["PitOutTime"].to_numpy(dtype=float)
                            for li in range(len(pit_in)):
                                pi_t = float(pit_in[li])
                                po_t = float(pit_out[li]) if li < len(pit_out) else float("nan")
                                if not math.isnan(pi_t):
                                    w_end = po_t+8 if not math.isnan(po_t) else pi_t+65
                                    if pi_t-2 <= abs_t <= w_end:
                                        sn.in_pit = True; break
                            if not sn.in_pit and "PitOutTime" in dl.columns:
                                pit_out2 = dl["PitOutTime"].to_numpy(dtype=float)
                                if cli < len(pit_out2):
                                    pov = float(pit_out2[cli])
                                    if not math.isnan(pov) and abs_t >= pov-5:
                                        sn.pit_out_lap = True; sn.lap_type = "OUT LAP"
                            if not sn.lap_type and "PitInTime" in dl.columns:
                                pit_in2 = dl["PitInTime"].to_numpy(dtype=float)
                                if cli < len(pit_in2) and not math.isnan(float(pit_in2[cli])):
                                    sn.lap_type = "IN LAP"
                            if not sn.lap_type: sn.lap_type = "PUSH"
                            pots = pit_out[~np.isnan(pit_out.astype(float))]
                            sn.pits_done = int(np.sum(np.array([float(p) for p in pots]) <= abs_t))

                        sec_vals = []
                        for si in range(1,4):
                            sc = f"Sector{si}Time"
                            if sc in dl.columns and cli < len(dl):
                                v = float(dl[sc].to_numpy(dtype=float)[cli])
                                sec_vals.append(0.0 if math.isnan(v) else v)
                            else: sec_vals.append(0.0)
                        sn.sector_times = tuple(sec_vals)

                        raw_dist  = g("Distance", 0.0)
                        track_len = app._track_lap_len
                        sn.dist   = sn.lap*track_len + raw_dist

                except Exception as exc: log.warning("Lap data drv=%s: %s", drv, exc)

                # ── ERS (2026) ────────────────────────────────────────
                if is_2026(app.session_year) and not is_out:
                    try:
                        i_now = int(min(np.searchsorted(times, abs_t), len(times)-1))
                        prev_ers = app._ers_state.get(drv)
                        ta = df["Throttle"].to_numpy().astype(float)
                        br = df["Brake"].to_numpy().astype(float)
                        ba = np.where(br<=1.0, br*100.0, br)
                        sa = df["Speed"].to_numpy().astype(float)
                        ra = (df["RPM"].to_numpy().astype(float) if "RPM" in df.columns
                              else np.zeros(len(times)))
                        if prev_ers is None or abs_t < prev_ers[0]-0.1:
                            soc,dep,reg,clip = _simulate_ers(ERS_CAP_KJ*0.90,
                                ta[:i_now+1], ba[:i_now+1], sa[:i_now+1], ra[:i_now+1],
                                np.diff(times[:i_now+1]))
                        else:
                            pr_t,soc,dep,reg,clip = prev_ers
                            i_pr = max(0, min(int(np.searchsorted(times,pr_t)), len(times)-1))
                            dts  = np.diff(times[i_pr:i_now+1])
                            if len(dts) > 0:
                                s_soc,s_dep,s_reg,clip = _simulate_ers(soc,
                                    ta[i_pr:i_now+1], ba[i_pr:i_now+1],
                                    sa[i_pr:i_now+1], ra[i_pr:i_now+1], dts)
                                soc = s_soc; dep += s_dep; reg += s_reg
                        sn.ers_soc    = clamp((soc/ERS_CAP_KJ)*100, 0, 100)
                        sn.is_clipping = clip
                        app._ers_state[drv] = (abs_t,soc,dep,reg,clip)
                    except Exception as exc: log.debug("ERS %s: %s", drv, exc)

                # ── is_finished: driver completed the full race distance ──
                if is_out:
                    sn.is_finished = (is_race and app.total_laps > 0
                                      and sn.lap >= app.total_laps)
                    sn.dist = -1.0
                snaps.append(sn)
            except Exception as exc: log.warning("_compute drv=%s outer: %s", drv, exc, exc_info=True)

        # ── Sort ──────────────────────────────────────────────────────
        if is_race:
            snaps.sort(key=lambda s: (s.pos if 0 < s.pos < 900 else 998, -max(s.dist,0.0)))
        else:
            # FP / Qualifying: order by best lap time ascending
            snaps.sort(key=lambda s: s.best_lap_s if math.isfinite(s.best_lap_s) else float("inf"))

        # ── Gap / Interval (laps-down aware) ──────────────────────────
        leader_dist = next((s.dist for s in snaps if not s.is_out and s.dist >= 0), 0.0)
        leader_lap  = snaps[0].lap if snaps else 0
        for i, s in enumerate(snaps):
            if s.is_out:
                label = "FINISH" if s.is_finished else "OUT"
                s.gap = s.interval = label; s.gap_num = s.int_num = 999.0
            elif i == 0:
                s.gap = s.interval = "LEAD"; s.gap_num = s.int_num = 0.0
            else:
                ms = max(10.0, s.speed/3.6)
                # ── gap to leader ─────────────────────────────────────
                laps_behind = max(0, leader_lap - s.lap)
                if laps_behind > 0:
                    s.gap     = f"+{laps_behind} Lap{'s' if laps_behind>1 else ''}"
                    s.gap_num = 900.0 + laps_behind
                else:
                    gv = clamp((leader_dist - s.dist) / ms, 0, 999)
                    s.gap     = f"+{gv:.1f}s"; s.gap_num = gv
                # ── interval to car directly ahead ────────────────────
                prev_snap = next((snaps[j] for j in range(i-1,-1,-1)
                                  if not snaps[j].is_out and snaps[j].dist >= 0), None)
                if prev_snap:
                    laps_iv = max(0, prev_snap.lap - s.lap)
                    if laps_iv > 0:
                        s.interval = f"+{laps_iv} Lap{'s' if laps_iv>1 else ''}"
                        s.int_num  = 900.0 + laps_iv
                    else:
                        iv = clamp((prev_snap.dist - s.dist) / ms, 0, 999)
                        s.interval = f"+{iv:.1f}s"; s.int_num = iv
                else:
                    s.interval = s.gap; s.int_num = s.gap_num

        for i, s in enumerate(snaps):
            s.pos_change = prev_pos.get(s.drv, i+1) - (i+1)
        new_positions = {s.drv: i+1 for i, s in enumerate(snaps)}
        max_lap = max((s.lap for s in snaps if s.lap > 0), default=0)
        return {
            "elapsed":elapsed, "abs_t":abs_t, "snaps":snaps,
            "ts_key":ts_key, "ts_txt":ts_txt, "ts_col":ts_col,
            "weather_txt":weather_txt, "max_lap":max_lap,
            "new_positions":new_positions,
        }


# ═══════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════
class F1App:
    def __init__(self):
        self.session = None; self.telemetry: Dict[str,pd.DataFrame] = {}
        self.laps_data = None; self.weather_data = None; self.track_status_df = None
        self.drivers: List[str] = []; self.total_laps: int = 0
        self.session_best_s: Optional[float] = None; self.session_start: float = 0.0
        self.max_time: float = 0.0; self.session_type: str = "R"; self.session_year: int = 2024
        self._current_ts: str = "1"; self._ts_times = np.array([]); self._wx_times = np.array([])
        self._tel_times: Dict[str,np.ndarray] = {}; self._lap_times: Dict[str,np.ndarray] = {}
        self._laps_by_drv: Dict[str,pd.DataFrame] = {}
        self._sector_bests: Dict[str,List] = {}; self._overall_sec_best: List = [None,None,None]
        self._ers_state: Dict[str,tuple] = {}; self._timing_mode: str = "race"
        self._track_x = None; self._track_y = None; self._map_dots: set = set()
        self._map_zoom: float = 1.0; self._map_pan_x: float = 0.0; self._map_pan_y: float = 0.0
        self.is_playing = False; self.current_time: float = 0.0; self.playback_speed: int = 1
        self._last_tick: float = 0.0; self._session_loaded = False
        self.selected_driver: Optional[str] = None; self._last_snaps: List[Snap] = []
        self._result_q: queue.Queue = queue.Queue(maxsize=1)
        self._session_q: queue.Queue = queue.Queue()
        self._worker: Optional[SnapshotWorker] = None
        self._plot_last_drv = ""; self._plot_last_lap = -1
        self._plot_current_t_span: float = 90.0
        self._ana_last_lap = object(); self._ana_last_drv = ""; self._ana_last_style_n = -1
        self._prev_positions: Dict[str,int] = {}; self._pit_entry_time: Dict[str,float] = {}
        self._track_lap_len: float = 5500.0
        self._overtake_count: Dict[str,int] = {}; self._pos_lost_count: Dict[str,int] = {}
        self._overtake_events: List[Tuple] = []; self._last_overtake_str: Dict[str,str] = {}
        self._session_max_speed: Dict[str,float] = {}
        self._strategy_last_hash = ""; self._ers_last_pct = -1.0
        self._spin_i = 0; self._loading = False; self._frame_n = 0
        self._hud_W = 0; self._hud_H = 0; self._hud_cx = 0; self._hud_cy = 0
        self._hud_r_rpm = 0; self._hud_r_inner = 0; self._hud_gear_str = "N"
        self._hud_spd_val = 0; self._hud_rpm_val = 0; self._hud_font: Optional[int] = None
        # ── FP / Q timing ─────────────────────────────────────────────
        self._fp_duration_s: int = 3600              # overwritten on load
        self._q_phase_bounds: List[float] = []       # session-relative seconds
        self._q_phase_durations: List[int] = []      # per-phase max seconds
        self._red_flag_intervals: List[Tuple[float,float]] = []  # (start_abs, end_abs)

    # ── Entry point ──────────────────────────────────────────────────────
    def run(self):
        dpg.create_context()
        self._apply_theme(); self._load_hud_font(); self._build_ui()
        dpg.create_viewport(title="F1 Telemetry Analysis 26' by Pardinaz  v6.54",
                            width=VP_W, height=VP_H, min_width=1400, min_height=800,
                            clear_color=list(BG0)+[255])
        dpg.setup_dearpygui(); dpg.show_viewport()
        dpg.set_primary_window("w_main", True)
        if self._hud_font is not None:
            try: dpg.bind_item_font("cw_hud", self._hud_font)
            except Exception as e: log.warning("HUD font bind: %s", e)
        self._load_calendar(2024)
        while dpg.is_dearpygui_running():
            self._frame(); dpg.render_dearpygui_frame()
        if self._worker: self._worker.stop()
        dpg.destroy_context()

    def _load_hud_font(self):
        with dpg.font_registry():
            for path in _FONT_CANDIDATES:
                if os.path.exists(path):
                    try: self._hud_font = dpg.add_font(path,16); return
                    except: pass
        self._hud_font = None

    # ── Theme ─────────────────────────────────────────────────────────────
    def _apply_theme(self):
        with dpg.theme() as gt:
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg,          BG1)
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg,           BG2)
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg,           BG3)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg,           BG3)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered,    BG4)
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive,     BG4)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg,           BG2)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive,     BG2)
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgCollapsed,  BG1)
                dpg.add_theme_color(dpg.mvThemeCol_Border,            BRD)
                dpg.add_theme_color(dpg.mvThemeCol_BorderShadow,      BG1)
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarBg,       BG1)
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrab,     BG3)
                dpg.add_theme_color(dpg.mvThemeCol_ScrollbarGrabHovered,BG4)
                dpg.add_theme_color(dpg.mvThemeCol_Header,            _c("e10600",120))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,     _c("e10600",55))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive,      _c("e10600",120))
                dpg.add_theme_color(dpg.mvThemeCol_Button,            BG3)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,     BG4)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,      RED)
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrab,        GREEN)
                dpg.add_theme_color(dpg.mvThemeCol_SliderGrabActive,  CYAN)
                dpg.add_theme_color(dpg.mvThemeCol_CheckMark,         GREEN)
                dpg.add_theme_color(dpg.mvThemeCol_Separator,         BRD)
                dpg.add_theme_color(dpg.mvThemeCol_SeparatorHovered,  BRDL)
                dpg.add_theme_color(dpg.mvThemeCol_Text,              TXT)
                dpg.add_theme_color(dpg.mvThemeCol_Tab,               BG3)
                dpg.add_theme_color(dpg.mvThemeCol_TabHovered,        BG4)
                dpg.add_theme_color(dpg.mvThemeCol_TabActive,         _c("e10600",160))
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding,    4.0)
                dpg.add_theme_style(dpg.mvStyleVar_ChildRounding,     4.0)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding,     3.0)
                dpg.add_theme_style(dpg.mvStyleVar_GrabRounding,      3.0)
                dpg.add_theme_style(dpg.mvStyleVar_PopupRounding,     4.0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding,     10.0,6.0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding,      6.0,3.0)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing,       6.0,4.0)
                dpg.add_theme_style(dpg.mvStyleVar_CellPadding,       5.0,3.0)
                dpg.add_theme_style(dpg.mvStyleVar_ScrollbarSize,     7.0)
        dpg.bind_theme(gt)
        def _sth(col,w=2.0):
            with dpg.theme() as th:
                with dpg.theme_component(dpg.mvLineSeries):
                    try:
                        dpg.add_theme_color(dpg.mvPlotCol_Line,col,category=dpg.mvThemeCat_Plots)
                        dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight,float(w),category=dpg.mvThemeCat_Plots)
                    except:
                        try: dpg.add_theme_color(dpg.mvPlotCol_Line,col)
                        except: pass
            return th
        self._th_spd=_sth(TXT,2.0); self._th_thr=_sth(GREEN,1.5)
        self._th_brk=_sth(RED,1.5);  self._th_ers=_sth(BLUE,1.0); self._th_cur=_sth(YLW,2.0)

    # ── UI build ─────────────────────────────────────────────────────────
    def _build_ui(self):
        with dpg.window(tag="w_main", no_title_bar=True, no_move=True,
                        no_resize=True, no_scrollbar=True):
            self._ui_header(); self._ui_controls()
            with dpg.group(horizontal=True):
                self._ui_left(); self._ui_right()

    def _ui_header(self):
        with dpg.child_window(height=HDR_H, no_scrollbar=True, border=False):
            with dpg.group(horizontal=True):
                dpg.add_text(" F1", color=RED); dpg.add_text("Telemetry Analysis 26'", color=TXT)
                dpg.add_text("by Pardiñaz", color=TMED); dpg.add_text("v6.54", color=TDIM)
                dpg.add_spacer(width=18); dpg.add_text("Year", color=TDIM)
                dpg.add_combo([str(y) for y in range(2018,2027)], default_value="2024",
                              width=72, tag="cb_year",
                              callback=lambda s,a: self._load_calendar(int(a)))
                dpg.add_spacer(width=8); dpg.add_text("Race", color=TDIM)
                dpg.add_combo([], width=280, tag="cb_race")
                dpg.add_spacer(width=8); dpg.add_text("Sess", color=TDIM)
                dpg.add_combo(["FP1","FP2","FP3","Q","SQ","S","R"], default_value="R",
                              width=60, tag="cb_sess",
                              callback=lambda s,a: self._refresh_badge(a))
                dpg.add_spacer(width=10)
                dpg.add_text("[ RACE ]", tag="txt_badge", color=RED)
                dpg.add_spacer(width=16)
                dpg.add_button(label="  LOAD SESSION", tag="btn_load",
                               callback=self._start_load, width=160, height=30)
                dpg.add_spacer(width=6)
                dpg.add_button(label=" CLR CACHE ", tag="btn_clrcache",
                               callback=self._clear_cache, width=100, height=30)
                dpg.add_spacer(width=6)
                dpg.add_text("Ready.", tag="txt_status", color=TDIM)
                dpg.add_spacer(width=6)
                dpg.add_text("", tag="txt_spin", color=RED)

    def _clear_cache(self):
        try:
            dpg.set_value("txt_status","Clearing cache…")
            if os.path.exists(CACHE_DIR): shutil.rmtree(CACHE_DIR)
            os.makedirs(CACHE_DIR, exist_ok=True)
            fastf1.Cache.enable_cache(CACHE_DIR)
            dpg.set_value("txt_status","Cache cleared.")
            self._load_calendar(int(dpg.get_value("cb_year")))
        except Exception as exc: dpg.set_value("txt_status",f"Cache error: {exc}")

    def _ui_controls(self):
        with dpg.child_window(height=CTL_H, no_scrollbar=True, border=False):
            with dpg.group(horizontal=True):
                dpg.add_button(label=" PLAY ", tag="btn_play",
                               callback=self._toggle_play, width=90, height=34)
                dpg.add_spacer(width=8); dpg.add_text("Speed:", color=TDIM)
                dpg.add_combo(["x1","x4","x16","x64"], default_value="x1", tag="cb_speed", width=62,
                              callback=lambda s,a: self._set_speed({"x1":1,"x4":4,"x16":16,"x64":64}.get(a,1)))
                dpg.add_spacer(width=12)
                dpg.add_button(label="-Lap", callback=lambda: self._jump(-90), width=72, height=34)
                dpg.add_button(label="+Lap", callback=lambda: self._jump(90),  width=72, height=34)
                dpg.add_spacer(width=12)
                with dpg.group():
                    dpg.add_drawlist(tag="dl_timeline", width=880, height=6)
                    dpg.add_slider_float(tag="sld_time", default_value=0,
                                         min_value=0, max_value=100, width=880,
                                         callback=self._on_slider, format="", no_input=True)
                dpg.add_spacer(width=10)
                dpg.add_text("00:00:00", tag="txt_time", color=TXT)

    def _ui_left(self):
        with dpg.child_window(width=LEFT_W, border=False, no_scrollbar=True):
            with dpg.child_window(height=52, border=False, no_scrollbar=True):
                dpg.add_text("NO SESSION", tag="txt_race_status", color=TDIM)
                with dpg.group(horizontal=True):
                    dpg.add_text("LAP — / —", tag="txt_lap_count", color=TXT)
                    dpg.add_spacer(width=12)
                    dpg.add_text("—", tag="txt_weather", color=TDIM)
            dpg.add_separator()
            self._ui_timing_table()
            dpg.add_separator()
            self._ui_race_admin()

    def _ui_timing_table(self):
        with dpg.group(horizontal=True):
            dpg.add_text("LIVE TIMING", color=RED); dpg.add_spacer(width=12)
            dpg.add_text("TOWER  — click row to select driver", color=TDIM)
        with dpg.child_window(height=560, border=False, tag="cw_timing"):
            with dpg.table(tag="tbl_timing", header_row=True,
                           borders_innerH=True, borders_outerH=True,
                           row_background=True, scrollY=True,
                           policy=dpg.mvTable_SizingFixedFit, height=546):
                for lbl,w in _RACE_COLS:
                    dpg.add_table_column(label=lbl, width_fixed=True, init_width_or_weight=w)
                for i in range(MAX_DRV):
                    with dpg.table_row(tag=f"trow_{i}"):
                        dpg.add_selectable(label="", tag=f"tc_{i}_0",
                                           span_columns=True, height=16,
                                           callback=self._on_timing_row, user_data="")
                        for ci in range(1, len(_RACE_COLS)):
                            dpg.add_text("", tag=f"tc_{i}_{ci}")

    def _ui_race_admin(self):
        with dpg.child_window(height=260, border=False, no_scrollbar=False):
            dpg.add_text("RACE STRATEGY", color=RED); dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_text("STATUS:", color=TDIM)
                dpg.add_text("ON TRACK", tag="txt_pit", color=GREEN)
                dpg.add_spacer(width=12); dpg.add_text("PITS:", color=TDIM)
                dpg.add_text("0", tag="txt_pits_done", color=TXT)
            with dpg.group(horizontal=True):
                dpg.add_text("TYRE:", color=TDIM)
                dpg.add_text("—", tag="txt_tyre", color=TXT)
                dpg.add_spacer(width=6); dpg.add_text("Age:", color=TDIM)
                dpg.add_text("—", tag="txt_tyre_age", color=TXT)
                dpg.add_text("L", color=TDIM)
                dpg.add_spacer(width=6)
                dpg.add_text("", tag="txt_tyre_change", color=ORG)
            dpg.add_drawlist(tag="dl_strategy", width=LEFT_W-28, height=36)
            dpg.add_separator()
            dpg.add_text("ENERGY STORE", color=BLUE)
            with dpg.group(horizontal=True):
                dpg.add_text("SOC:", color=TDIM)
                dpg.add_text("50%", tag="txt_ers_pct", color=GREEN)
                dpg.add_spacer(width=10)
                dpg.add_text("", tag="txt_ers_status", color=PRP)
            dpg.add_drawlist(tag="dl_ers_bar", width=LEFT_W-28, height=20)
            with dpg.group(horizontal=True):
                dpg.add_text("v", color=ORG); dpg.add_text("0 kW", tag="txt_deploy", color=TDIM)
                dpg.add_spacer(width=16)
                dpg.add_text("^", color=GREEN); dpg.add_text("0 kW", tag="txt_regen", color=TDIM)

    def _ui_right(self):
        with dpg.child_window(border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                self._ui_map(); self._ui_hud()
            dpg.add_separator(); self._ui_plot()
            dpg.add_separator(); self._ui_analysis()

    def _ui_map(self):
        with dpg.child_window(width=MAP_W, height=396, border=True):
            with dpg.group(horizontal=True):
                dpg.add_text("TRACK MAP", color=RED); dpg.add_spacer(width=8)
                dpg.add_text("—", tag="txt_track_name", color=TMED); dpg.add_spacer(width=10)
                dpg.add_button(label="+", callback=self._map_zoom_in,  width=22, height=18)
                dpg.add_button(label="-", callback=self._map_zoom_out, width=22, height=18)
                dpg.add_button(label="R", callback=self._map_reset,    width=22, height=18)
                dpg.add_button(label="@", callback=self._map_center_on_driver, width=22, height=18)
            dpg.add_drawlist(tag="dl_map", width=MAP_W-8, height=354)

    def _ui_hud(self):
        with dpg.child_window(width=HUD_W, height=396, border=True, tag="cw_hud"):
            dpg.add_text("—", tag="txt_hud_name")
            dpg.add_text("—", tag="txt_hud_team", color=TDIM)
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_text("AHD:", color=TDIM); dpg.add_text("—", tag="txt_hud_ahead", color=CYAN)
            with dpg.group(horizontal=True):
                dpg.add_text("BHD:", color=TDIM); dpg.add_text("—", tag="txt_hud_behind", color=ORG)
            dpg.add_text("—", tag="txt_hud_battle",  color=TDIM)
            dpg.add_text("—", tag="txt_hud_style",   color=TMED)
            dpg.add_text("",  tag="txt_hud_laptype",  color=BLUE)
            dpg.add_separator()
            dpg.add_text("",  tag="txt_hud_drs",      color=GREEN)   # only shown when DRS OPEN
            dpg.add_separator()
            DL_W = HUD_W-18
            dpg.add_drawlist(tag="dl_hud", width=DL_W, height=210)
            self._hud_init_arcs(DL_W, 210)

    @staticmethod
    def _arc_pts(cx,cy,r,a_start,a_end,segs=48):
        pts = []
        if a_start == a_end: return pts
        for i in range(segs+1):
            t = i/segs; deg = a_start+t*(a_end-a_start)
            rad = math.radians(180.0-deg)
            pts.append((cx+r*math.cos(rad), cy-r*math.sin(rad)))
        return pts

    def _hud_init_arcs(self,W,H):
        self._hud_W=W; self._hud_H=H; self._hud_cx=W*0.48; self._hud_cy=H*0.48
        margin=18; self._hud_r_rpm=min(W*0.5-margin,H*0.5-margin)
        self._hud_r_inner=self._hud_r_rpm-17
        self._hud_draw_static_bg()

    def _hud_draw_static_bg(self):
        cx,cy=self._hud_cx,self._hud_cy; r_rpm=self._hud_r_rpm; r_inner=self._hud_r_inner
        for pts,col,th in [
            (self._arc_pts(cx,cy,r_rpm,  0,240,80), _c("1a2a3a"),14),
            (self._arc_pts(cx,cy,r_rpm,204,240,24), _c("e10600",60),14),
            (self._arc_pts(cx,cy,r_inner,  0,200,80),_c("0a1a0a"),10),
            (self._arc_pts(cx,cy,r_inner,200,240,24),_c("1a0a0a"),10),
        ]:
            if pts: dpg.draw_polyline(pts,color=col,thickness=th,parent="dl_hud")
        for pct in (0,25,50,75,100):
            deg=pct/100*240; rad=math.radians(180.0-deg)
            x1=cx+(r_rpm-3)*math.cos(rad); y1=cy-(r_rpm-3)*math.sin(rad)
            x2=cx+(r_rpm+9)*math.cos(rad); y2=cy-(r_rpm+9)*math.sin(rad)
            dpg.draw_line((x1,y1),(x2,y2),color=_c("2a2a4a"),thickness=1,parent="dl_hud")
        cx_i,cy_i=int(cx),int(cy)
        dpg.draw_polyline([(cx_i,cy_i)],color=BLUE,  thickness=14,parent="dl_hud",tag="arc_rpm_lo")
        dpg.draw_polyline([(cx_i,cy_i)],color=CYAN,  thickness=14,parent="dl_hud",tag="arc_rpm_hi")
        dpg.draw_polyline([(cx_i,cy_i)],color=RED,   thickness=16,parent="dl_hud",tag="arc_rpm_red")
        dpg.draw_polyline([(cx_i,cy_i)],color=GREEN, thickness=10,parent="dl_hud",tag="arc_thr")
        dpg.draw_polyline([(cx_i,cy_i)],color=RED,   thickness=10,parent="dl_hud",tag="arc_brk")
        H_i=int(self._hud_H)
        dpg.draw_text(pos=(cx_i-12,cy_i-21),text="N",     color=TDIM,size=42,parent="dl_hud",tag="draw_gear")
        dpg.draw_text(pos=(cx_i-24,cy_i+20),text="0",     color=TXT, size=24,parent="dl_hud",tag="draw_spd")
        dpg.draw_text(pos=(cx_i+14,cy_i+24),text="kph",   color=TDIM,size=12,parent="dl_hud",tag="draw_kph")
        dpg.draw_text(pos=(cx_i-22,cy_i+44),text="0 mph", color=TDIM,size=11,parent="dl_hud",tag="draw_mph")
        dpg.draw_text(pos=(4,H_i-14),        text="0 rpm",color=TMED,size=11,parent="dl_hud",tag="draw_rpm")

    def _hud_redraw_dynamic(self,rpm_pct,thr_pct,brk_on,redline):
        cx,cy=self._hud_cx,self._hud_cy; r_rpm=self._hud_r_rpm; r_inner=self._hud_r_inner
        rpm_deg=rpm_pct*240.0
        if rpm_deg>1.0:
            segs=max(4,int(rpm_deg/4)); pts=self._arc_pts(cx,cy,r_rpm,0,rpm_deg,segs)
            if pts:
                mid=len(pts)//2
                col_lo=BLUE if not redline else _c("880000")
                col_hi=CYAN if not redline else RED
                dpg.configure_item("arc_rpm_lo",points=pts[:mid+1] if mid>1 else pts,color=col_lo,thickness=14)
                dpg.configure_item("arc_rpm_hi",points=pts[mid:]   if mid>1 else [(cx,cy)],color=col_hi,thickness=14)
            else:
                dpg.configure_item("arc_rpm_lo",points=[(cx,cy)]); dpg.configure_item("arc_rpm_hi",points=[(cx,cy)])
        else:
            dpg.configure_item("arc_rpm_lo",points=[(cx,cy)]); dpg.configure_item("arc_rpm_hi",points=[(cx,cy)])
        if redline:
            pts=self._arc_pts(cx,cy,r_rpm,204,240,20)
            dpg.configure_item("arc_rpm_red",points=pts if pts else [(cx,cy)],color=RED,thickness=16)
        else: dpg.configure_item("arc_rpm_red",points=[(cx,cy)])
        thr_deg=thr_pct*200.0
        if thr_deg>1.0:
            pts=self._arc_pts(cx,cy,r_inner,0,thr_deg,max(4,int(thr_deg/4)))
            dpg.configure_item("arc_thr",points=pts if pts else [(cx,cy)],
                               color=(GREEN if thr_pct>0.95 else _c("00bb55")),thickness=10)
        else: dpg.configure_item("arc_thr",points=[(cx,cy)])
        if brk_on:
            pts=self._arc_pts(cx,cy,r_inner,200,240,20)
            dpg.configure_item("arc_brk",points=pts if pts else [(cx,cy)],color=RED,thickness=10)
        else: dpg.configure_item("arc_brk",points=[(cx,cy)])
        gear=self._hud_gear_str; spd=self._hud_spd_val; rpm=self._hud_rpm_val
        gear_col=CYAN if gear not in ("N","0","") else TDIM
        if redline: gear_col=RED
        g_size=42; g_x=int(cx-(g_size*0.27 if len(gear)==1 else g_size*0.52)); g_y=int(cy-g_size//2+2)
        dpg.configure_item("draw_gear",pos=(g_x,g_y),text=gear,color=gear_col)
        spd_str=str(spd); s_cw=15; s_x=int(cx-len(spd_str)*s_cw//2); s_y=int(cy+r_inner*0.38)
        dpg.configure_item("draw_spd",pos=(s_x,s_y),text=spd_str)
        dpg.configure_item("draw_kph",pos=(s_x+len(spd_str)*s_cw+2,s_y+4))
        mph_str=f"{int(spd*0.621371)} mph"; m_x=int(cx-len(mph_str)*7//2)
        dpg.configure_item("draw_mph",pos=(m_x,s_y+26),text=mph_str)
        dpg.configure_item("draw_rpm",pos=(4,int(self._hud_H)-14),text=f"{rpm:,} rpm")

    def _ui_plot(self):
        with dpg.plot(tag="plot_tel",height=138,width=-1,no_title=True,no_menus=True,
                      no_box_select=True,no_mouse_pos=True,anti_aliased=True):
            dpg.add_plot_legend(show=False)
            dpg.add_plot_axis(dpg.mvXAxis,tag="ax_x",no_tick_marks=True,no_tick_labels=True)
            dpg.add_plot_axis(dpg.mvYAxis,tag="ax_y")
            dpg.set_axis_limits("ax_y",0,420)
            for tag in ("s_sec1","s_sec2","s_sec3"):
                dpg.add_shade_series([],[],tag=tag,parent="ax_y")
            dpg.add_line_series([],[],tag="s_spd",parent="ax_y")
            dpg.add_line_series([],[],tag="s_thr",parent="ax_y")
            dpg.add_line_series([],[],tag="s_brk",parent="ax_y")
            dpg.add_line_series([],[],tag="s_ers",parent="ax_y")
            dpg.add_line_series([0.0,0.0],[0.0,420.0],tag="s_cur",parent="ax_y")
        for tag,th in (("s_spd",self._th_spd),("s_thr",self._th_thr),
                       ("s_brk",self._th_brk),("s_ers",self._th_ers),("s_cur",self._th_cur)):
            try: dpg.bind_item_theme(tag,th)
            except: pass
        for stag,scol in zip(("s_sec1","s_sec2","s_sec3"),
                              [_c("e10600",28),_c("ffd600",22),_c("00e676",20)]):
            try:
                with dpg.theme() as _sth:
                    with dpg.theme_component(dpg.mvShadeSeries):
                        dpg.add_theme_color(dpg.mvPlotCol_Fill,scol,category=dpg.mvThemeCat_Plots)
                dpg.bind_item_theme(stag,_sth)
            except: pass

    def _ui_analysis(self):
        REM=VP_W-LEFT_W-18; SEC_W=268; PACE_W=358
        STY_W=REM-SEC_W-PACE_W-10   # fills to right edge of viewport
        PH=330
        with dpg.child_window(height=334, border=False, no_scrollbar=True):
            with dpg.group(horizontal=True):
                # ── Sectors ──────────────────────────────────────────
                with dpg.child_window(width=SEC_W, height=PH, border=True):
                    dpg.add_text("SECTORS", color=RED)
                    dpg.add_text("Track: —", tag="txt_track_cond", color=GREEN)
                    with dpg.table(tag="tbl_sectors", header_row=True,
                                   borders_innerH=True, policy=dpg.mvTable_SizingFixedFit):
                        for lbl,w in (("S",18),("Time",60),("Dlt",52),("Avg5",58),("Stat",76)):
                            dpg.add_table_column(label=lbl,width_fixed=True,init_width_or_weight=w)
                        for si in range(1,4):
                            with dpg.table_row():
                                dpg.add_text(f"S{si}",tag=f"sec_lbl_{si}",color=TDIM)
                                dpg.add_text("—",tag=f"sec_time_{si}")
                                dpg.add_text("—",tag=f"sec_delta_{si}")
                                dpg.add_text("—",tag=f"sec_avg5_{si}",color=TMED)
                                dpg.add_text("—",tag=f"sec_verd_{si}")
                    dpg.add_text("—",tag="txt_sec_avg",color=TDIM)

                # ── Pace & metrics ────────────────────────────────────
                with dpg.child_window(width=PACE_W, height=PH, border=True):
                    dpg.add_text("PACE & ANALYSIS", color=RED)
                    dpg.add_text("—", tag="txt_narrative", color=CYAN)
                    dpg.add_text("—", tag="txt_pace",      color=TXT)
                    dpg.add_text("—", tag="txt_last_lap",  color=TMED)
                    dpg.add_separator()
                    CW=(PACE_W-16)//4
                    with dpg.table(tag="tbl_pace_metrics", header_row=False,
                                   borders_innerV=True, policy=dpg.mvTable_SizingFixedFit):
                        for _ in range(4): dpg.add_table_column(width_fixed=True,init_width_or_weight=CW)
                        with dpg.table_row():
                            dpg.add_text("Deg/lap",color=TDIM); dpg.add_text("Gap P1",color=TDIM)
                            dpg.add_text("Stint avg",color=TDIM); dpg.add_text("Undercut",color=TDIM)
                        with dpg.table_row():
                            dpg.add_text("—",tag="pm_deg",color=TXT); dpg.add_text("—",tag="pm_gapp1",color=TXT)
                            dpg.add_text("—",tag="pm_savg",color=TXT); dpg.add_text("—",tag="pm_ucut",color=TXT)
                        with dpg.table_row():
                            dpg.add_text("Overtakes",color=TDIM); dpg.add_text("Pos lost",color=TDIM)
                            dpg.add_text("Last OVT",color=TDIM); dpg.add_text("MaxSpd",color=TDIM)
                        with dpg.table_row():
                            dpg.add_text("—",tag="pm_ovt",color=GREEN); dpg.add_text("—",tag="pm_poslost",color=RED)
                            dpg.add_text("—",tag="pm_lastovt",color=YLW); dpg.add_text("—",tag="pm_maxspd",color=TXT)
                        with dpg.table_row():
                            dpg.add_text("Pit wndw",color=TDIM); dpg.add_text("Laps left",color=TDIM)
                            dpg.add_text("Vs best",color=TDIM); dpg.add_text("Track",color=TDIM)
                        with dpg.table_row():
                            dpg.add_text("—",tag="pm_fc_win",color=TXT); dpg.add_text("—",tag="pm_fc_gap",color=TXT)
                            dpg.add_text("—",tag="pm_fc_dlt",color=TXT); dpg.add_text("—",tag="pm_cond",color=TXT)
                        with dpg.table_row():
                            dpg.add_text("Min spd",color=TDIM); dpg.add_text("Avg spd",color=TDIM)
                            dpg.add_text("DRS use",color=TDIM); dpg.add_text("Lap type",color=TDIM)
                        with dpg.table_row():
                            dpg.add_text("—",tag="pm_minspd",color=TXT); dpg.add_text("—",tag="pm_avgspd",color=TXT)
                            dpg.add_text("—",tag="pm_drslaps",color=TXT); dpg.add_text("—",tag="pm_laptype",color=TXT)
                    dpg.add_text("—", tag="txt_diag", color=BLUE)

                # ── Driving style history ─────────────────────────────
                with dpg.child_window(width=STY_W, height=PH, border=True):
                    dpg.add_text("DRIVING STYLE HISTORY", color=RED)
                    # Colour legend
                    with dpg.group(horizontal=True):
                        dpg.add_text("■",color=CYAN);  dpg.add_text("BEST",color=TMED)
                        dpg.add_spacer(width=4)
                        dpg.add_text("■",color=GREEN); dpg.add_text("FAST",color=TMED)
                        dpg.add_spacer(width=4)
                        dpg.add_text("■",color=TXT);   dpg.add_text("OK",color=TMED)
                        dpg.add_spacer(width=4)
                        dpg.add_text("■",color=YLW);   dpg.add_text("SLOW",color=TMED)
                        dpg.add_spacer(width=4)
                        dpg.add_text("■",color=ORG);   dpg.add_text("DROP",color=TMED)
                        dpg.add_spacer(width=4)
                        dpg.add_text("■",color=PRP);   dpg.add_text("SCLIP",color=TMED)
                    _base=[24,60,48,36,36,36,36,36,38,44]
                    _extra=max(0,STY_W-14-sum(_base)); _base[-1]+=_extra
                    _STYLE_COLS=("Lap","Time","DBst","Thr%","WOT%","BRK%","LiCo","Clip","RPMh","Cond")
                    with dpg.table(tag="tbl_style", header_row=True,
                                   borders_innerH=True, borders_innerV=True,
                                   policy=dpg.mvTable_SizingFixedFit,
                                   scrollY=True, height=PH-58):
                        for lbl,w in zip(_STYLE_COLS,_base):
                            dpg.add_table_column(label=lbl,width_fixed=True,init_width_or_weight=w)
                        for ri in range(MAX_STYLE_ROWS):
                            with dpg.table_row(tag=f"srow_{ri}"):
                                for ci in range(len(_STYLE_COLS)):
                                    dpg.add_text("",tag=f"sc_{ri}_{ci}")

    # ═════════════════════════════════════════════════════════════════
    #  FRAME LOOP
    # ═════════════════════════════════════════════════════════════════
    def _frame(self):
        try:
            sess_result = self._session_q.get_nowait()
            try:
                if "_calendar" in sess_result:
                    races = sess_result["_calendar"]
                    if races: dpg.configure_item("cb_race",items=races,default_value=races[0])
                    dpg.set_value("txt_status","Calendar loaded.")
                elif sess_result.get("ok"):
                    self._on_session_loaded(sess_result["race"],sess_result["year"],sess_result["sess_type"])
                elif sess_result.get("err"):
                    dpg.set_value("txt_status",f"Error: {sess_result['err']}")
                    self._loading = False
            except Exception as exc: log.warning("session_q: %s",exc,exc_info=True); self._loading=False
        except queue.Empty: pass

        try:
            result = self._result_q.get_nowait()
            try: self._apply_result(result)
            except Exception as exc: log.warning("_apply_result: %s",exc,exc_info=True)
        except queue.Empty: pass

        if self._loading:
            frames = ["|","/","-","\\",".","o"]
            self._spin_i=(self._spin_i+1)%len(frames)
            dpg.set_value("txt_spin",frames[self._spin_i])

        if self.is_playing and self._session_loaded:
            now=time.monotonic(); dt=(now-self._last_tick)*int(self.playback_speed or 1)
            self._last_tick=now
            self.current_time=min(self.current_time+dt,self.max_time)
            dpg.set_value("sld_time",self.current_time)
            dpg.set_value("txt_time",hms(int(self.current_time)))
            self._request_update(self.current_time)
            if self.current_time>=self.max_time: self._toggle_play()
        elif self._session_loaded:
            self._frame_n+=1
            if self._frame_n>=60: self._frame_n=0; self._request_update(self.current_time)

    # ═════════════════════════════════════════════════════════════════
    #  APPLY RESULT
    # ═════════════════════════════════════════════════════════════════
    def _apply_result(self, res:dict):
        snaps=res["snaps"]; abs_t=res["abs_t"]; ts_key=res["ts_key"]
        max_lap=res["max_lap"]; elapsed=res["elapsed"]
        try: self._detect_overtakes(snaps, elapsed)
        except Exception as exc: log.warning("detect_overtakes: %s", exc)
        if "new_positions" in res: self._prev_positions.update(res["new_positions"])
        self._current_ts=ts_key; self._last_snaps=snaps
        try:
            ts_txt,ts_col,_=TRACK_STATUS.get(ts_key,TRACK_STATUS["1"])
            dpg.set_value("txt_race_status",ts_txt)
            is_caution=ts_key in ("4","5","6")
            scol=(tuple(min(255,int(c*1.4)) if i<3 else c for i,c in enumerate(ts_col))
                  if is_caution else ts_col)
            dpg.configure_item("txt_race_status",color=scol)
            # ── Session-type header display ───────────────────────────
            if self.session_type in ("FP1","FP2","FP3"):
                rem = max(0.0, self._fp_duration_s - elapsed)
                dpg.set_value("txt_lap_count",
                              f"{self.session_type}  ⏱ {fmt_countdown(rem)}"
                              if rem > 0 else f"{self.session_type}  SESSION ENDED")
            elif self.session_type in ("Q","SQ"):
                phase_name, remaining = self._get_q_countdown(abs_t)
                if remaining > 0:
                    dpg.set_value("txt_lap_count",f"{phase_name}  ⏱ {fmt_countdown(remaining)}")
                else:
                    dpg.set_value("txt_lap_count",f"{phase_name}  ENDED")
            else:
                dpg.set_value("txt_lap_count",f"LAP {max_lap} / {self.total_laps}")
            if res["weather_txt"]: dpg.set_value("txt_weather",res["weather_txt"])
        except Exception as exc: log.warning("apply header: %s",exc)
        try:
            for s in snaps:
                if not s.is_out and s.speed > self._session_max_speed.get(s.drv,0):
                    self._session_max_speed[s.drv]=s.speed
        except: pass
        try: self._update_timing(snaps,abs_t)
        except Exception as exc: log.warning("update_timing: %s",exc,exc_info=True)
        try: self._update_map_dots(snaps)
        except Exception as exc: log.warning("update_map: %s",exc)
        drv=self.selected_driver
        if not drv: return
        snap=next((s for s in snaps if s.drv==drv),None)
        if snap is None: return
        try: self._update_hud(snap,snaps)
        except Exception as exc: log.warning("update_hud: %s",exc,exc_info=True)
        try: self._update_race_admin(snap)
        except Exception as exc: log.warning("update_race_admin: %s",exc,exc_info=True)
        try: self._update_plot(drv,abs_t,snap)
        except Exception as exc: log.warning("update_plot: %s",exc,exc_info=True)
        try: self._update_analysis(snap,drv,abs_t)
        except Exception as exc: log.warning("update_analysis: %s",exc,exc_info=True)

    def _get_q_countdown(self, abs_t:float) -> Tuple[str,float]:
        """Return (phase_name, seconds_remaining) for the current Q phase."""
        if not self._q_phase_bounds:
            return "Q", max(0.0, self.max_time - (abs_t - self.session_start))
        bounds_abs = [self.session_start + b for b in self._q_phase_bounds]
        phase_idx  = 0
        for i,ba in enumerate(bounds_abs):
            if abs_t >= ba: phase_idx = i
        name = Q_PHASE_NAMES[min(phase_idx, len(Q_PHASE_NAMES)-1)]
        # Phase end: use min(next_phase_start, phase_start + max_duration)
        phase_start_abs = bounds_abs[phase_idx]
        if phase_idx+1 < len(bounds_abs):
            phase_end = bounds_abs[phase_idx+1]
        else:
            phase_end = self.session_start + self.max_time
        # Cap to allowed phase duration (accounts for red flag extra time)
        if phase_idx < len(self._q_phase_durations):
            # Subtract red flag time in this phase to get effective running time
            red_in_phase = sum(
                min(e, abs_t) - max(s, phase_start_abs)
                for s,e in self._red_flag_intervals
                if s < abs_t and e > phase_start_abs
                if max(s, phase_start_abs) < min(e, abs_t)
            )
            elapsed_in_phase = (abs_t - phase_start_abs) - red_in_phase
            remaining = max(0.0, self._q_phase_durations[phase_idx] - elapsed_in_phase)
        else:
            remaining = max(0.0, phase_end - abs_t)
        return name, remaining

    def _detect_overtakes(self,snaps:List[Snap],elapsed:float):
        if not self._prev_positions: return
        for s in snaps:
            if s.is_out or s.in_pit or s.pit_out_lap: continue
            if s.lap<4: continue
            prev=self._prev_positions.get(s.drv,s.pos); curr=s.pos
            if prev<=0 or curr<=0: continue
            if prev>curr and s.int_num<=5.0:
                self._overtake_count[s.drv]=self._overtake_count.get(s.drv,0)+1
                behind=next((x for x in snaps if x.pos==curr+1 and not x.is_out),None)
                if behind: self._last_overtake_str[s.drv]=f"P{curr} vs {behind.abbr} L{s.lap}"
                self._overtake_events.append((elapsed,s.drv,s.lap))
            elif curr>prev and (s.int_num<=5.0 or s.gap_num<=5.0):
                self._pos_lost_count[s.drv]=self._pos_lost_count.get(s.drv,0)+1

    # ── Timing table ──────────────────────────────────────────────────────
    def _on_timing_row(self,sender,app_data,user_data):
        drv=None
        try:
            row_i=int(sender.split("_")[1])
            if 0<=row_i<len(self._last_snaps): drv=self._last_snaps[row_i].drv
        except: pass
        if not drv and user_data: drv=user_data
        if drv: self._select_driver(drv)
        try: dpg.set_value(sender,False)
        except: pass

    def _update_timing(self,snaps:List[Snap],abs_t:float):
        n=len(snaps)
        for i in range(MAX_DRV):
            if i>=n:
                try:
                    dpg.configure_item(f"tc_{i}_0",label="")
                    for ci in range(1,len(_RACE_COLS)):
                        dpg.set_value(f"tc_{i}_{ci}",""); dpg.configure_item(f"tc_{i}_{ci}",color=TDIM)
                except: pass
                continue
            try:
                s=snaps[i]; col=TEAM_COLORS.get(s.team,TXT)
                is_sel=s.drv==self.selected_driver; sel_col=(255,255,255,255) if is_sel else col
                tyre_raw=s.tyre.strip("()")
                if s.in_pit:
                    self._pit_entry_time[s.drv]=abs_t; tyre_disp,tyre_col="PITS",YLW
                elif s.drv in self._pit_entry_time:
                    if abs_t-self._pit_entry_time[s.drv]<22.0: tyre_disp,tyre_col="PITS",YLW
                    else:
                        del self._pit_entry_time[s.drv]
                        tyre_disp=TYRE_SHORT.get(tyre_raw.upper(),"-")
                        tyre_col=TYRE_COL.get(tyre_raw.upper(),TMED)
                else:
                    tyre_disp=TYRE_SHORT.get(tyre_raw.upper(),"-")
                    tyre_col=TYRE_COL.get(tyre_raw.upper(),TMED)
                pc=getattr(s,"pos_change",0)
                chg_str=f"+{pc}" if pc>0 else (str(pc) if pc<0 else "=")
                chg_col=GREEN if pc>0 else (RED if pc<0 else TDIM)
                # FINISH / OUT / position
                if s.is_out:
                    pos_str  = "FIN" if s.is_finished else "OUT"
                    gap_disp = "FINISH" if s.is_finished else "OUT"
                    int_disp = "FINISH" if s.is_finished else "OUT"
                else:
                    pos_str  = str(i+1)
                    gap_disp = "LEAD" if i==0 else s.gap
                    int_disp = "LEAD" if i==0 else s.interval
                if self._timing_mode=="race":
                    vals  =[pos_str,chg_str,s.abbr,s.team[:10],
                            gap_disp,int_disp,s.last_lap_str,tyre_disp,str(s.lap)]
                    v_cols=[col,chg_col,sel_col,col,
                            GREEN if i==0 else TMED,GREEN if i==0 else TMED,
                            col,tyre_col,TDIM]
                else:
                    gap_q="-"; gc=TMED
                    if self.session_best_s:
                        dl=self._laps_by_drv.get(s.drv,pd.DataFrame())
                        if not dl.empty and "LapTime" in dl.columns:
                            lta=dl["LapTime"].to_numpy(dtype=float); vld=lta[~np.isnan(lta)]
                            if len(vld):
                                d=float(np.min(vld))-self.session_best_s
                                gap_q="POLE" if abs(d)<0.01 else f"+{d:.3f}"
                                gc=F1_PRP if gap_q=="POLE" else TMED
                    vals  =[pos_str,s.abbr,s.team[:10],s.best_lap_str,gap_q,tyre_disp,str(s.lap)]
                    v_cols=[col,sel_col,col,col,gc,tyre_col,TDIM]
                try: dpg.configure_item(f"tc_{i}_0",label=str(vals[0]))
                except: pass
                for ci in range(1,len(vals)):
                    try:
                        dpg.set_value(f"tc_{i}_{ci}",str(vals[ci]))
                        dpg.configure_item(f"tc_{i}_{ci}",color=v_cols[ci])
                    except: pass
                for ci in range(len(vals),len(_RACE_COLS)):
                    try: dpg.set_value(f"tc_{i}_{ci}","")
                    except: pass
            except Exception as exc: log.debug("timing row %d: %s",i,exc)

    # ── Track map ────────────────────────────────────────────────────────
    def _update_map_dots(self,snaps:List[Snap]):
        """Move or create each driver's dot; hide dots for OUT/FINISH drivers."""
        if self._track_x is None: return
        W=max(200,dpg.get_item_width("dl_map") or 200)
        H=max(100,dpg.get_item_height("dl_map") or 100)
        for s in snaps:
            oval=f"dot_{s.drv}"; dtxt=f"dlab_{s.drv}"
            if s.is_out:
                # Hide the dot once the driver is out/finished
                if s.drv in self._map_dots:
                    try:
                        dpg.configure_item(oval, show=False)
                        dpg.configure_item(dtxt, show=False)
                    except: pass
                continue
            if math.isnan(s.x) or math.isnan(s.y): continue
            sx,sy=self._w2m(s.x,s.y,W,H); col=TEAM_COLORS.get(s.team,TXT)
            sel=s.drv==self.selected_driver; r=8.0 if sel else 4.5; otl=(255,255,255,220) if sel else col
            if s.drv not in self._map_dots:
                dpg.draw_circle(parent="dl_map",tag=oval,center=(sx,sy),radius=r,color=otl,fill=col)
                dpg.draw_text(parent="dl_map",tag=dtxt,pos=(sx,sy-r-10),text=s.abbr,color=col,size=10)
                self._map_dots.add(s.drv)
            else:
                try:
                    dpg.configure_item(oval,center=(sx,sy),radius=r,color=otl,fill=col,show=True)
                    dpg.configure_item(dtxt,pos=(sx,sy-r-10),show=sel)
                except: pass

    def _w2m(self,wx,wy,W,H):
        mn_x,mx_x=self._track_x.min(),self._track_x.max()
        mn_y,mx_y=self._track_y.min(),self._track_y.max()
        rx=mx_x-mn_x or 1; ry=mx_y-mn_y or 1
        sc=min(W/rx,H/ry)*0.84*self._map_zoom
        cx=(mx_x+mn_x)/2+self._map_pan_x; cy=(mx_y+mn_y)/2+self._map_pan_y
        return float(W/2+(wx-cx)*sc),float(H/2-(wy-cy)*sc)

    def _map_zoom_in(self):  self._map_zoom=min(self._map_zoom*1.3,8.0); self._draw_track()
    def _map_zoom_out(self): self._map_zoom=max(self._map_zoom/1.3,0.5); self._draw_track()
    def _map_reset(self):    self._map_zoom=1.0; self._map_pan_x=self._map_pan_y=0.0; self._draw_track()
    def _map_center_on_driver(self):
        if not self.selected_driver or self._track_x is None: return
        sn=next((s for s in self._last_snaps if s.drv==self.selected_driver),None)
        if sn and not math.isnan(sn.x):
            mn_x,mx_x=self._track_x.min(),self._track_x.max()
            mn_y,mx_y=self._track_y.min(),self._track_y.max()
            self._map_pan_x=sn.x-(mx_x+mn_x)/2; self._map_pan_y=sn.y-(mx_y+mn_y)/2
            self._draw_track()

    # ── HUD ───────────────────────────────────────────────────────────────
    def _update_hud(self,snap:Snap,snaps:List[Snap]):
        col=TEAM_COLORS.get(snap.team,TXT)
        dpg.set_value("txt_hud_name",f"{snap.name}  #{snap.number}")
        dpg.configure_item("txt_hud_name",color=col)
        dpg.set_value("txt_hud_team",snap.team)
        self._hud_gear_str="N" if snap.gear==0 else str(snap.gear)
        self._hud_spd_val=int(snap.speed); self._hud_rpm_val=int(snap.rpm)
        self._hud_redraw_dynamic(clamp(snap.rpm/MAX_RPM,0,1),
                                  clamp(snap.throttle/100.0,0,1),
                                  snap.brake>0, snap.rpm>MAX_RPM*0.88)
        # DRS: only show "DRS OPEN" label; hide otherwise
        if _drs_open(snap.drs):
            dpg.set_value("txt_hud_drs","DRS OPEN")
            dpg.configure_item("txt_hud_drs",color=GREEN,show=True)
        else:
            dpg.configure_item("txt_hud_drs",show=False)

        idx=next((i for i,s in enumerate(snaps) if s.drv==snap.drv),-1)
        if idx>=0:
            ah=snaps[idx-1] if idx>0 else None
            bh=snaps[idx+1] if idx<len(snaps)-1 else None
            dpg.set_value("txt_hud_ahead",
                          f"{ah.abbr}  +{snap.int_num:.1f}s" if ah and not ah.is_out else "LEADER")
            dpg.set_value("txt_hud_behind",
                          f"{bh.abbr}  +{bh.int_num:.1f}s"  if bh and not bh.is_out else "")
            self._update_battle_style(snap,snaps,idx)
        lt_map={"OUT LAP":BLUE,"IN LAP":ORG,"PUSH":GREEN,"":TDIM}
        dpg.set_value("txt_hud_laptype",snap.lap_type)
        dpg.configure_item("txt_hud_laptype",color=lt_map.get(snap.lap_type,TDIM))

    def _update_battle_style(self,snap:Snap,snaps:List[Snap],idx:int):
        df=self.telemetry.get(snap.drv)
        if df is None: return
        times=self._tel_times.get(snap.drv,np.array([]))
        if len(times)==0: return
        abs_t=self.session_start+self.current_time
        i_n=int(min(np.searchsorted(times,abs_t),len(times)-1))
        spd_arr=df["Speed"].to_numpy()
        prev_spd=float(spd_arr[max(0,i_n-5)]) if i_n>0 else snap.speed
        dspd=snap.speed-prev_spd
        style,sc="NORMAL DRIVING",TDIM
        if snap.throttle==0 and snap.brake==0 and snap.speed>180 and dspd<0:
            style,sc="LIFT & COAST",BLUE
        elif snap.is_clipping:
            style,sc=f"SUPERCLIPPING  {snap.ers_soc:.0f}%",PRP
        elif is_2026(self.session_year) and snap.throttle>=95 and snap.brake==0 and snap.speed>ERS_SPD_MIN and snap.ers_soc<20:
            style,sc=f"ERS CRITICAL  {snap.ers_soc:.0f}%",ORG
        elif snap.throttle>=95 and snap.brake==0:
            style,sc="FULL THROTTLE",GREEN
        elif snap.brake>50:
            style,sc="HEAVY BRAKING",RED
        elif snap.brake>10 and snap.throttle>0:
            style,sc="TRAIL BRAKING",YLW
        elif 20<snap.throttle<95:
            style,sc="ROLLING THROTTLE",ORG
        dpg.set_value("txt_hud_style",f"STYLE: {style}"); dpg.configure_item("txt_hud_style",color=sc)
        battle,bc="CLEAR",TDIM
        if idx<len(snaps)-1 and snaps[idx+1].int_num<=3.0: battle,bc=f"DEFEND ← {snaps[idx+1].abbr}",ORG
        if idx>0 and snap.int_num<=3.0:
            ah=snaps[idx-1]
            if snap.lap>ah.lap:     battle,bc=f"LAPPING {ah.abbr}",BLUE
            elif snap.int_num<=1.0: battle,bc=f"OVERTAKING {ah.abbr}",RED
            else:                   battle,bc=f"BATTLING {ah.abbr}",ORG
        dpg.set_value("txt_hud_battle",f"TRACK: {battle}"); dpg.configure_item("txt_hud_battle",color=bc)

    # ── Race admin / ERS ─────────────────────────────────────────────────
    def _update_race_admin(self,snap:Snap):
        try:
            if snap.in_pit and snap.speed<=90:
                lim="60 km/h" if snap.speed<=62 else "80 km/h"
                dpg.set_value("txt_pit",f"PIT LANE  {lim}"); dpg.configure_item("txt_pit",color=YLW)
            elif snap.lap_type=="OUT LAP": dpg.set_value("txt_pit","OUT LAP"); dpg.configure_item("txt_pit",color=BLUE)
            elif snap.lap_type=="IN LAP":  dpg.set_value("txt_pit","IN LAP");  dpg.configure_item("txt_pit",color=ORG)
            else: dpg.set_value("txt_pit","ON TRACK"); dpg.configure_item("txt_pit",color=GREEN)
            dpg.set_value("txt_pits_done",str(snap.pits_done))
            t_raw=snap.tyre.strip("()"); t_full=TYRE_FULL.get(t_raw.upper(),t_raw or "—")
            dpg.set_value("txt_tyre",t_full); dpg.configure_item("txt_tyre",color=TYRE_COL.get(t_raw.upper(),TDIM))
            dpg.set_value("txt_tyre_age",str(snap.tyre_laps) if snap.tyre_laps else "—")
            cp=snap.tyre_prev.strip("()").upper(); ct=t_raw.upper()
            if (cp and ct and cp not in ("–","","U") and ct not in ("–","","U") and cp!=ct
                    and (snap.pit_out_lap or snap.lap_type=="OUT LAP")):
                dpg.set_value("txt_tyre_change",f">> {TYRE_FULL.get(cp,cp)}→{TYRE_FULL.get(ct,ct)}")
            else: dpg.set_value("txt_tyre_change","")
            new_hash=f"{snap.drv}_{snap.tyre}_{snap.pits_done}_{snap.lap}"
            if new_hash!=self._strategy_last_hash:
                self._strategy_last_hash=new_hash
                try: self._draw_strategy_timeline(snap.drv,snap)
                except Exception as exc: log.warning("strategy: %s",exc)
        except Exception as exc: log.warning("race_admin: %s",exc,exc_info=True); return
        try:
            pct=snap.ers_soc; dep_kw=0.0; reg_kw=0.0
            if snap.is_clipping:
                reg_kw=ERS_RBK_KW*0.80
            elif snap.throttle>=95 and snap.brake==0 and snap.speed>=ERS_SPD_MIN and pct>ERS_CLIP_TH:
                dep_kw=ERS_DEP_KW*(0.4+0.6*clamp((snap.speed-ERS_SPD_MIN)/120,0,1))
            elif snap.brake>20: reg_kw=ERS_RBK_KW*clamp(snap.brake/100,0,1)
            elif snap.throttle==0 and snap.brake==0 and snap.speed>80: reg_kw=ERS_RCS_KW
            elif 5<=snap.throttle<80 and snap.brake==0 and snap.speed>80: reg_kw=60.0*(1-snap.throttle/80.0)
            pct_col=GREEN if pct>60 else YLW if pct>30 else ORG if pct>ERS_CLIP_TH else RED
            dpg.set_value("txt_ers_pct",f"{pct:.0f}%"); dpg.configure_item("txt_ers_pct",color=pct_col)
            if abs(pct-self._ers_last_pct)>0.5:
                self._ers_last_pct=pct
                try: self._draw_ers_bar(pct,dep_kw,reg_kw,snap.is_clipping)
                except Exception as exc: log.warning("ers bar: %s",exc)
            if snap.is_clipping:
                dpg.set_value("txt_ers_status",f"SUPERCLIP  +{reg_kw:.0f}kW"); dpg.configure_item("txt_ers_status",color=PRP)
            elif reg_kw>5:
                dpg.set_value("txt_ers_status",f"REGEN  {reg_kw:.0f}kW"); dpg.configure_item("txt_ers_status",color=GREEN)
            elif dep_kw>5:
                dpg.set_value("txt_ers_status",f"DEPLOY {dep_kw:.0f}kW"); dpg.configure_item("txt_ers_status",color=ORG)
            elif pct<20:
                dpg.set_value("txt_ers_status","LOW BATTERY"); dpg.configure_item("txt_ers_status",color=RED)
            else:
                dpg.set_value("txt_ers_status","")
            dpg.set_value("txt_deploy",f"{dep_kw:.0f} kW"); dpg.configure_item("txt_deploy",color=ORG  if dep_kw>0 else TDIM)
            dpg.set_value("txt_regen", f"{reg_kw:.0f} kW"); dpg.configure_item("txt_regen", color=GREEN if reg_kw>0 else TDIM)
        except Exception as exc: log.warning("race_admin ERS: %s",exc)

    def _draw_ers_bar(self,pct:float,dep_kw:float,reg_kw:float,superclipping:bool=False):
        """Purple+glow during superclipping (battery charging from reversed MGU-K)."""
        try:
            BW=LEFT_W-28
            dpg.delete_item("dl_ers_bar",children_only=True)
            dpg.draw_rectangle((0,0),(BW,18),fill=_c("04040f"),color=BRD,parent="dl_ers_bar")
            fw=max(0.0,BW*pct/100.0)
            if superclipping:
                dpg.draw_rectangle((0,0),(fw,18),fill=_c("8800cc"),color=NONE,parent="dl_ers_bar")
                glow_w=min(BW*0.07,BW-fw+1)
                if glow_w>0:
                    dpg.draw_rectangle((fw,0),(fw+glow_w,18),fill=_c("dd66ff",120),color=NONE,parent="dl_ers_bar")
                dpg.draw_rectangle((0,0),(fw,3),fill=_c("ee99ff"),color=NONE,parent="dl_ers_bar")
            else:
                ers_fill=(_c("00cc66") if pct>60 else _c("ccaa00") if pct>30
                          else _c("cc5500") if pct>ERS_CLIP_TH else _c("cc0000"))
                if fw>0:
                    dpg.draw_rectangle((0,0),(fw,18),fill=ers_fill,color=NONE,parent="dl_ers_bar")
                    dpg.draw_rectangle((0,0),(fw,3),
                                       fill=_c("ccffdd") if pct>60 else _c("ffeeaa"),
                                       color=NONE,parent="dl_ers_bar")
            cx_l=BW*ERS_CLIP_TH/100.0
            dpg.draw_line((cx_l,0),(cx_l,18),color=RED,thickness=2,parent="dl_ers_bar")
            dpg.draw_text((4,3),f"{pct:.0f}%",color=TXT,size=11,parent="dl_ers_bar")
        except Exception as exc: log.debug("ers_bar: %s",exc)

    def _draw_strategy_timeline(self,drv:str,snap:Snap):
        try:
            BW=LEFT_W-28; dl=self._laps_by_drv.get(drv,pd.DataFrame())
            cur=float(snap.lap); total=float(self.total_laps) if self.total_laps>0 else 1.0
            cx=cur/total*BW; stints:List[Tuple]=[]
            if not dl.empty and "Compound" in dl.columns:
                comp=dl["Compound"].to_numpy(); lapn=dl["LapNumber"].to_numpy(dtype=float)
                prev_c=None; stint_s=0
                for i,(ln,c) in enumerate(zip(lapn,comp)):
                    if str(c) in ("nan","None",""): continue
                    if prev_c is None: prev_c=c; stint_s=int(safe(ln,1))
                    if c!=prev_c:
                        stints.append((stint_s,int(safe(lapn[i-1],stint_s)),str(prev_c)))
                        prev_c=c; stint_s=int(safe(ln,1))
                if prev_c is not None: stints.append((stint_s,int(safe(lapn[-1],stint_s)),str(prev_c)))
            dpg.delete_item("dl_strategy",children_only=True)
            dpg.draw_rectangle((0,0),(BW,28),fill=_c("0a0a1a"),color=BRD,parent="dl_strategy")
            for s_lap,e_lap,comp_str in stints:
                x0=max(0.0,(s_lap-1)/total*BW); x1=min(BW,e_lap/total*BW)
                t_raw=comp_str[0].upper() if comp_str not in ("nan","None","") else "U"
                col=TYRE_COL.get(t_raw,TDIM)
                dpg.draw_rectangle((x0,2),(x1,26),fill=col,color=NONE,parent="dl_strategy")
                if x1-x0>14: dpg.draw_text((x0+3,8),t_raw,color=_c("000000"),size=12,parent="dl_strategy")
            dpg.draw_line((cx,0),(cx,28),color=TXT,thickness=2,parent="dl_strategy")
        except Exception as exc: log.debug("strategy_timeline: %s",exc)

    # ── Telemetry plot ────────────────────────────────────────────────────
    def _update_plot(self,drv:str,abs_t:float,snap:Snap):
        try:
            dl=self._laps_by_drv.get(drv,pd.DataFrame())
            lta=self._lap_times.get(drv,np.array([]))
            tval=self._tel_times.get(drv,np.array([]))
            if dl.empty or "TimeSec_f" not in dl.columns or len(lta)==0 or len(tval)<3: return
            idx_c=min(int(np.searchsorted(lta,abs_t,side="right")),len(lta)-1)
            tsf=dl["TimeSec_f"].to_numpy(dtype=float)
            lt_col=dl["LapTime"].to_numpy(dtype=float) if "LapTime" in dl.columns else None
            if idx_c>0 and lt_col is not None:
                pe=float(tsf[idx_c-1]) if idx_c-1<len(tsf) else float("nan")
                pl=float(lt_col[idx_c-1]) if idx_c-1<len(lt_col) else float("nan")
                lap_start=pe if (not math.isnan(pe) and not math.isnan(pl)) else float(tval[0])
                t_span=pl if (not math.isnan(pl) and pl>0) else 90.0
            else:
                lap_start=float(tval[0]) if len(tval)>0 else 0.0; t_span=90.0
            if not math.isfinite(t_span) or t_span<1.0: t_span=90.0
            if not math.isfinite(lap_start): lap_start=float(tval[0]) if len(tval)>0 else 0.0
            self._plot_current_t_span=t_span
            lap_changed=(drv!=self._plot_last_drv or snap.lap!=self._plot_last_lap)
            if lap_changed:
                self._plot_last_drv=drv; self._plot_last_lap=snap.lap
                try:
                    si=int(np.searchsorted(tval,lap_start))
                    ei=min(int(np.searchsorted(tval,lap_start+t_span))+5,len(tval))
                    n=ei-si
                    if n<3: return
                    df=self.telemetry[drv]
                    t_raw=tval[si:ei]-lap_start
                    spd=df["Speed"].to_numpy()[si:ei].astype(float)
                    thr=df["Throttle"].to_numpy()[si:ei].astype(float)
                    brk_r=df["Brake"].to_numpy()[si:ei].astype(float)
                    brk=np.where(brk_r<=1.0,brk_r*100.0,brk_r)
                    step=max(1,n//600)
                    def _clean(arr): return np.nan_to_num(arr[::step],nan=0.0,posinf=0.0,neginf=0.0).tolist()
                    t_clean=_clean(t_raw)
                    dpg.set_value("s_spd",[t_clean,_clean(spd)])
                    dpg.set_value("s_thr",[t_clean,_clean(thr)])
                    dpg.set_value("s_brk",[t_clean,_clean(np.clip(brk,0,100))])
                    dpg.set_value("s_ers",[[],[]])
                except Exception as exc: log.warning("plot data: %s",exc,exc_info=True)
                try:
                    st=snap.sector_times
                    if (st and len(st)==3
                            and all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in st)):
                        s1=float(st[0]); s2=s1+float(st[1]); s3=s2+float(st[2]); YMAX=430.0
                        if all(math.isfinite(v) for v in (s1,s2,s3)):
                            dpg.set_value("s_sec1",[[0,s1,s1,0],[YMAX,YMAX,0,0],[0,0,0,0]])
                            dpg.set_value("s_sec2",[[s1,s2,s2,s1],[YMAX,YMAX,0,0],[0,0,0,0]])
                            dpg.set_value("s_sec3",[[s2,s3,s3,s2],[YMAX,YMAX,0,0],[0,0,0,0]])
                        else:
                            for stag in ("s_sec1","s_sec2","s_sec3"): dpg.set_value(stag,[[],[],[]])
                    else:
                        for stag in ("s_sec1","s_sec2","s_sec3"): dpg.set_value(stag,[[],[],[]])
                except:
                    for stag in ("s_sec1","s_sec2","s_sec3"):
                        try: dpg.set_value(stag,[[],[],[]])
                        except: pass
            prog=clamp((abs_t-lap_start)/t_span,0.0,1.0)*t_span
            if math.isfinite(prog): dpg.set_value("s_cur",[[prog,prog],[0,420]])
            dpg.set_axis_limits("ax_x",0,t_span)
        except Exception as exc: log.warning("update_plot outer: %s",exc,exc_info=True)

    # ── Analysis ─────────────────────────────────────────────────────────
    def _update_analysis(self,snap:Snap,drv:str,abs_t:float):
        try:
            dl=self._laps_by_drv.get(drv,pd.DataFrame())
            lta=self._lap_times.get(drv,np.array([]))
            if dl.empty or "TimeSec_f" not in dl.columns or len(lta)==0: return
            idx_nxt=int(np.searchsorted(lta,abs_t,side="right"))
            cli=max(0,min(idx_nxt,len(dl)-1))
            ts_txt,ts_col,_=TRACK_STATUS.get(self._current_ts,TRACK_STATUS["1"])
            dpg.set_value("txt_track_cond",f"Track: {ts_txt}"); dpg.configure_item("txt_track_cond",color=ts_col)
            def col_val(col,default=float("nan")):
                try:
                    if col not in dl.columns: return default
                    v=dl[col].to_numpy(dtype=object)[cli]; f=float(v)
                    return default if math.isnan(f) else f
                except: return default
            def col_val_prev(col,default=float("nan")):
                if cli==0: return default
                try:
                    if col not in dl.columns: return default
                    v=dl[col].to_numpy(dtype=object)[cli-1]; f=float(v)
                    return default if math.isnan(f) else f
                except: return default
            cur_lap=col_val("LapNumber",None)
        except Exception as e: log.debug("analysis setup: %s",e); return

        try:
            if self._ana_last_lap!=cur_lap or self._ana_last_drv!=drv:
                self._ana_last_lap=cur_lap; self._ana_last_drv=drv
                avg_vals=[]
                for si in range(1,4):
                    col2=f"Sector{si}Time"; cs=col_val(col2,0.0); ps=col_val_prev(col2,0.0)
                    diff=cs-ps if cs and ps else 0.0
                    if not cs:       vrd,vc="—",TDIM
                    elif diff<=-0.3: vrd,vc="Improving ++",F1_PRP
                    elif diff<=-0.1: vrd,vc="Improving +",F1_GRN
                    elif diff<= 0.1: vrd,vc="On Pace",TXT
                    elif diff<= 0.4: vrd,vc="Losing -",F1_YLW
                    else:            vrd,vc="Dropping --",RED
                    sc2=TDIM
                    if cs and self._overall_sec_best[si-1] and abs(cs-self._overall_sec_best[si-1])<0.05: sc2=F1_PRP
                    elif diff<-0.05: sc2=F1_GRN
                    elif diff>0.05:  sc2=F1_YLW
                    dpg.set_value(f"sec_time_{si}",f"{cs:.3f}" if cs else "—"); dpg.configure_item(f"sec_time_{si}",color=sc2)
                    dpg.set_value(f"sec_delta_{si}",f"{diff:+.3f}" if diff else "—"); dpg.configure_item(f"sec_delta_{si}",color=sc2)
                    dpg.set_value(f"sec_verd_{si}",vrd); dpg.configure_item(f"sec_verd_{si}",color=vc)
                    try:
                        if col2 in dl.columns:
                            sarr=dl[col2].iloc[:cli+1].to_numpy(dtype=float); sval=sarr[~np.isnan(sarr)]
                            avg5=f"{float(np.mean(sval[-5:])):.3f}" if len(sval) else "—"
                        else: avg5="—"
                        dpg.set_value(f"sec_avg5_{si}",avg5); avg_vals.append(avg5)
                    except: avg_vals.append("—")
                dpg.set_value("txt_sec_avg",f"5L avg: {' / '.join(avg_vals)}")
        except Exception as e: log.debug("analysis sectors: %s",e)

        try:
            if "LapTime" not in dl.columns: return
            lt_arr=dl["LapTime"].iloc[:cli+1].to_numpy(dtype=float); valid=lt_arr[~np.isnan(lt_arr)]
            if len(valid)==0: return
            ll_s=float(valid[-1]); delta_str=f"{ll_s-self.session_best_s:+.3f}s" if self.session_best_s else "—"
            cur_snap=next((s for s in self._last_snaps if s.drv==drv),None)
            if cur_snap and not cur_snap.is_out:
                pos=cur_snap.pos; gap=cur_snap.gap_num
                narr=(f"P1 LEADER" if pos==1 else
                      f"P{pos}  IN BATTLE  +{gap:.1f}s" if gap<5 else
                      f"P{pos}  HUNTING  +{gap:.1f}s"   if gap<20 else
                      f"P{pos}  GAP +{gap:.1f}s")
                dpg.set_value("txt_narrative",narr)
            if len(valid)>=2:
                r5=valid[-min(6,len(valid)):-1]; avg=float(np.mean(r5)) if len(r5) else ll_s; diff=ll_s-avg
                if   diff<-0.5: pt,pc=f"FLYING ++ ({diff:+.2f}s)",F1_PRP
                elif diff<0:    pt,pc=f"IMPROVING + ({diff:+.2f}s)",GREEN
                elif diff<0.3:  pt,pc=f"CONSISTENT ({diff:+.2f}s)",TXT
                else:           pt,pc=f"DROPPING - ({diff:+.2f}s)",RED
                dpg.set_value("txt_pace",pt); dpg.configure_item("txt_pace",color=pc)
            dpg.set_value("txt_last_lap",f"Last: {fmt_lap(ll_s)}  {delta_str}")
            if len(valid)>=3:
                trend=float(np.polyfit(range(len(valid[-5:])),valid[-5:],1)[0])
                dpg.set_value("pm_deg",f"{trend:+.3f}s/L")
                dpg.configure_item("pm_deg",color=GREEN if trend<0.05 else YLW if trend<0.2 else RED)
            else: dpg.set_value("pm_deg","—"); dpg.configure_item("pm_deg",color=TDIM)
            if cur_snap and not cur_snap.is_out and cur_snap.gap_num<900:
                dpg.set_value("pm_gapp1",f"{cur_snap.gap_num:.1f}s")
                dpg.configure_item("pm_gapp1",color=GREEN if cur_snap.gap_num<5 else YLW if cur_snap.gap_num<30 else RED)
            else: dpg.set_value("pm_gapp1","—"); dpg.configure_item("pm_gapp1",color=TDIM)
            tl=snap.tyre_laps; stint=valid[-tl:] if 0<tl<=len(valid) else valid[-5:]
            dpg.set_value("pm_savg",fmt_lap(float(np.mean(stint))) if len(stint) else "—")
            if cur_snap:
                bidx=next((i for i,s in enumerate(self._last_snaps) if s.drv==drv),-1)
                if 0<=bidx<len(self._last_snaps)-1:
                    bs=self._last_snaps[bidx+1]
                    if not bs.is_out and bs.int_num<4.0:
                        dpg.set_value("pm_ucut",f"! {bs.abbr} {bs.int_num:.1f}s"); dpg.configure_item("pm_ucut",color=YLW)
                    else: dpg.set_value("pm_ucut","Safe"); dpg.configure_item("pm_ucut",color=GREEN)
                else: dpg.set_value("pm_ucut","—"); dpg.configure_item("pm_ucut",color=TDIM)
            ovt_n=self._overtake_count.get(drv,0)
            dpg.set_value("pm_ovt",str(ovt_n)); dpg.configure_item("pm_ovt",color=GREEN if ovt_n>0 else TDIM)
            pos_lost=self._pos_lost_count.get(drv,0)
            dpg.set_value("pm_poslost",str(pos_lost)); dpg.configure_item("pm_poslost",color=RED if pos_lost>0 else TDIM)
            last_ovt=self._last_overtake_str.get(drv,"—")
            dpg.set_value("pm_lastovt",last_ovt); dpg.configure_item("pm_lastovt",color=YLW if last_ovt!="—" else TDIM)
            max_spd=self._session_max_speed.get(drv,0.0)
            dpg.set_value("pm_maxspd",f"{int(max_spd)} kph" if max_spd>0 else "—"); dpg.configure_item("pm_maxspd",color=CYAN if max_spd>0 else TDIM)
            laps_rem=max(0,self.total_laps-snap.lap)
            if snap.tyre_laps>0 and len(valid)>=3:
                deg_rate=max(0.0,float(np.polyfit(range(len(valid[-5:])),valid[-5:],1)[0]))
                optimal_w=int(max(1,min(laps_rem,round(0.8/(deg_rate+0.001)))))
                dpg.set_value("pm_fc_win",f"{optimal_w} laps"); dpg.configure_item("pm_fc_win",color=TXT)
            else: dpg.set_value("pm_fc_win","—"); dpg.configure_item("pm_fc_win",color=TDIM)
            dpg.set_value("pm_fc_gap",f"{laps_rem}L left"); dpg.set_value("pm_fc_dlt",delta_str)
            dlt_val=float(delta_str.replace("+","").replace("s","")) if delta_str!="—" else 999.0
            dpg.configure_item("pm_fc_dlt",color=(GREEN if dlt_val<0 else YLW if dlt_val<2 else RED) if delta_str!="—" else TDIM)
            ts_n,ts_c,_=TRACK_STATUS.get(self._current_ts,TRACK_STATUS["1"])
            dpg.set_value("pm_cond",COND_SHORT.get(self._current_ts,"GRN")); dpg.configure_item("pm_cond",color=ts_c)
            dpg.set_value("pm_laptype",snap.lap_type or "—")
            dpg.configure_item("pm_laptype",{"OUT LAP":BLUE,"IN LAP":ORG}.get(snap.lap_type,GREEN if snap.lap_type else TDIM))
        except Exception as e: log.debug("analysis pace: %s",e)

        try:
            tel2=self.telemetry.get(drv); tval2=self._tel_times.get(drv,np.array([]))
            if tel2 is not None and len(tval2)>3 and "LapTime" in dl.columns:
                lt_arr2=dl["LapTime"].to_numpy(dtype=float); tsarr=dl["TimeSec_f"].to_numpy(dtype=float)
                inxt=int(np.searchsorted(lta,abs_t,"right"))
                if inxt>0:
                    irow=min(inxt-1,len(tsarr)-1); t_end=float(tsarr[irow])
                    lap_t=float(lt_arr2[irow]) if not math.isnan(float(lt_arr2[irow])) else 90.0
                    if not math.isnan(t_end):
                        le=t_end; si2=int(np.searchsorted(tval2,le-lap_t)); ei2=int(np.searchsorted(tval2,le))
                        sl2=tel2["Speed"].to_numpy()[si2:ei2].astype(float)
                        if len(sl2)>5:
                            dpg.set_value("pm_minspd",f"{int(sl2.min())} kph"); dpg.configure_item("pm_minspd",color=RED)
                            dpg.set_value("pm_avgspd",f"{int(sl2.mean())} kph"); dpg.configure_item("pm_avgspd",color=TXT)
                            if "DRS" in tel2.columns:
                                dv=tel2["DRS"].to_numpy()[si2:ei2]
                                drs_pct=sum(1 for v in dv if int(float(v)) in DRS_ACTIVE)*100//max(len(dv),1)
                                dpg.set_value("pm_drslaps",f"{drs_pct}%"); dpg.configure_item("pm_drslaps",color=BLUE)
        except Exception as e: log.debug("analysis speed: %s",e)

        try:
            completed=dl.iloc[:cli+1]; n_c=len(completed)
            if self._ana_last_style_n!=n_c or self._ana_last_drv!=drv:
                self._ana_last_style_n=n_c; self._rebuild_style_table(drv,completed)
        except Exception as e: log.debug("analysis style: %s",e)

    def _rebuild_style_table(self,drv:str,completed:pd.DataFrame):
        """
        Write one row per completed lap.  Colour scheme:
          CYAN  = best/near-best session lap
          GREEN = faster than recent average
          TXT   = normal
          YLW   = slightly slow
          ORG   = noticeably slow (>1 s off best)
          PRP   = superclipping lap detected
        Cond column shows: GRN / YEL / SC / VSC / RED (from COND_SHORT map).
        """
        for ri in range(MAX_STYLE_ROWS):
            try:
                for ci in range(10): dpg.set_value(f"sc_{ri}_{ci}","")
            except: pass
        if "LapTime" not in completed.columns or "TimeSec_f" not in completed.columns: return
        df=self.telemetry.get(drv)
        if df is None: return
        tel_t=self._tel_times.get(drv,np.array([]))
        if len(tel_t)==0: return
        lt_col=completed["LapTime"].to_numpy(dtype=float)
        tsf_col=completed["TimeSec_f"].to_numpy(dtype=float)
        lapn_col=completed["LapNumber"].to_numpy() if "LapNumber" in completed.columns else None
        n_rows=len(completed); slot=0
        for ri in range(n_rows):
            if slot>=MAX_STYLE_ROWS: break
            try:
                lap_s=float(lt_col[ri]); t_end=float(tsf_col[ri])
                if math.isnan(lap_s) or math.isnan(t_end): continue
                l_st=t_end-lap_s; l_en=t_end   # session-relative; no session_start offset
                si_=int(np.searchsorted(tel_t,l_st)); ei_=int(np.searchsorted(tel_t,l_en)); n=ei_-si_
                if n<5: continue
                thr_c=df["Throttle"].to_numpy()[si_:ei_].astype(float)
                brk_r=df["Brake"].to_numpy()[si_:ei_].astype(float)
                brk_c=np.where(brk_r<=1.0,brk_r*100.0,brk_r)
                spd_c=df["Speed"].to_numpy()[si_:ei_].astype(float)
                rpm_c=(df["RPM"].to_numpy()[si_:ei_].astype(float)
                       if "RPM" in df.columns else np.zeros(n))
                on_t=int(np.sum(thr_c>5)); wot=int(np.sum(thr_c>=98))
                brk_n=int(np.sum(brk_c>50))
                dspd=np.concatenate([[0,0,0],spd_c[3:]-spd_c[:-3]])
                lico=int(np.sum((thr_c==0)&(brk_c==0)&(spd_c>180)&(dspd<0)))
                clip=int(np.sum((thr_c>=95)&(brk_c==0)&(rpm_c>10_500)&(dspd<-1.5)))
                rpm_hi=int(np.sum(rpm_c>11_000))
                p_thr=on_t/n*100; p_wot=wot/n*100; p_brk=brk_n/n*100
                p_lico=lico/n*100; p_clip=clip/n*100; p_rpm=rpm_hi/n*100
                db=f"{lap_s-self.session_best_s:+.3f}" if self.session_best_s else ""
                ln=int(float(lapn_col[ri])) if lapn_col is not None else "?"
                # ── Row colour ───────────────────────────────────────────
                if p_clip>3.0:
                    row_col = STYLE_COL_SUPERCLIP
                elif self.session_best_s and abs(lap_s-self.session_best_s)<0.15:
                    row_col = STYLE_COL_BEST
                elif db and float(db)<-0.3:
                    row_col = STYLE_COL_FAST
                elif db and float(db)>1.5:
                    row_col = STYLE_COL_VERY_SLOW
                elif db and float(db)>0.5:
                    row_col = STYLE_COL_SLOW
                else:
                    row_col = STYLE_COL_NORMAL
                # ── Cond: use COND_SHORT map for readable label ──────────
                cond=COND_SHORT.get(self._current_ts,"GRN")
                vals=(str(ln),fmt_lap(lap_s),db or "—",
                      f"{p_thr:.0f}",f"{p_wot:.0f}",f"{p_brk:.0f}",
                      f"{p_lico:.0f}",f"{p_clip:.0f}",f"{p_rpm:.0f}",cond)
                for ci,v in enumerate(vals):
                    try:
                        dpg.set_value(f"sc_{slot}_{ci}",str(v))
                        dpg.configure_item(f"sc_{slot}_{ci}",color=row_col)
                    except: pass
                slot+=1
            except Exception as exc: log.debug("style row %d: %s",ri,exc)

    # ═════════════════════════════════════════════════════════════════
    #  DATA LOADING
    # ═════════════════════════════════════════════════════════════════
    def _load_calendar(self,year:int):
        dpg.set_value("txt_status",f"Loading {year} calendar…")
        def fetch():
            try:
                sch=fastf1.get_event_schedule(year,include_testing=False)
                races=sch["EventName"].tolist()
                self._session_q.put_nowait({"_calendar":races,"_year":year})
            except Exception as exc: log.warning("Calendar fetch: %s",exc)
        threading.Thread(target=fetch,daemon=True).start()

    def _start_load(self):
        race=dpg.get_value("cb_race"); sess=dpg.get_value("cb_sess")
        if not race: return
        year=int(dpg.get_value("cb_year")); self.session_year=year
        self._loading=True
        dpg.set_value("txt_status",f"Downloading {sess} – {race} {year}…")
        threading.Thread(target=self._fetch_session,args=(year,race,sess),daemon=True).start()

    def _fetch_session(self,year:int,race:str,sess_type:str):
        try:
            session=fastf1.get_session(year,race,sess_type)
            session.load(telemetry=True,weather=True,messages=False)
            laps=session.laps
            total_laps=int(laps["LapNumber"].max()) if not laps.empty else 0
            best_s=None
            try:
                lt=td_to_float(laps.pick_fastest().get("LapTime"))
                if not math.isnan(lt): best_s=lt
            except: pass

            telemetry={}; tel_times={}; t_min=float("inf"); t_max=0.0
            track_lap_len=5500.0
            for drv in session.drivers:
                try:
                    dl=laps.pick_drivers(drv)
                    if dl.empty: continue
                    tel=dl.get_telemetry()
                    if tel.empty: continue
                    tel=tel.copy(); tel["TimeSec"]=tel["SessionTime"].dt.total_seconds()
                    info=session.get_driver(drv)
                    tel["Team"]=info.get("TeamName","Unknown"); tel["Abbr"]=info.get("Abbreviation",drv)
                    tel["Name"]=info.get("FullName",drv);      tel["Number"]=info.get("DriverNumber",drv)
                    tp=strip_fastf1(tel)
                    if "Distance" in tp.columns:
                        md=float(tp["Distance"].max())
                        if math.isfinite(md) and md>track_lap_len: track_lap_len=md
                    t0=tp["TimeSec"].min(); t1=tp["TimeSec"].max()
                    if t0<t_min: t_min=t0
                    if t1>t_max: t_max=t1
                    telemetry[drv]=tp; tel_times[drv]=tp["TimeSec"].to_numpy(dtype=float)
                except Exception as exc: log.warning("Driver %s: %s",drv,exc)

            if not telemetry: raise ValueError("No telemetry found.")

            lbd={}; lti={}; sb={}; overall=[None,None,None]
            for drv in telemetry:
                try:
                    dp=strip_fastf1(laps.pick_drivers(drv))
                    if "Time" in dp.columns: dp["TimeSec_f"]=dp["Time"]
                    lbd[drv]=dp
                    lti[drv]=dp["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in dp.columns else np.array([])
                    s_b=[None,None,None]
                    for si in range(1,4):
                        col2=f"Sector{si}Time"
                        if col2 not in dp.columns: continue
                        vf=dp[col2].to_numpy(dtype=float); vf=vf[~np.isnan(vf)]
                        if len(vf):
                            b=float(vf.min()); s_b[si-1]=b
                            if overall[si-1] is None or b<overall[si-1]: overall[si-1]=b
                    sb[drv]=s_b
                except:
                    lbd[drv]=pd.DataFrame(); lti[drv]=np.array([]); sb[drv]=[None,None,None]

            ts_df=add_timesec_col(session.track_status,"Time")
            wx_df=add_timesec_col(session.weather_data,"Time")

            # ── FP / Q timing setup ───────────────────────────────────
            fp_duration=FP_DURATION_S.get(sess_type,3600)
            q_phase_bounds=[]; q_phase_durations=[]
            if sess_type in ("Q","SQ"):
                q_phase_bounds=detect_q_phases(lbd,t_min)
                durs=Q_PHASE_DUR_2026 if year>=2026 else Q_PHASE_DUR_BASE
                q_phase_durations=durs[:len(q_phase_bounds)]

            # ── Red flag intervals (for Q countdown pause) ────────────
            red_flag_intervals=[]
            try:
                if not ts_df.empty and "TimeSec_f" in ts_df.columns and "Status" in ts_df.columns:
                    times_ts=ts_df["TimeSec_f"].to_numpy(dtype=float)
                    status_ts=ts_df["Status"].to_numpy()
                    in_red=False; red_start=0.0
                    for idx in range(len(times_ts)):
                        t_abs=times_ts[idx]; st=str(status_ts[idx])
                        if st=="5" and not in_red:
                            in_red=True; red_start=t_abs
                        elif st!="5" and in_red:
                            in_red=False
                            red_flag_intervals.append((red_start,t_abs))
                    if in_red: red_flag_intervals.append((red_start,t_min+t_max))
            except: pass

            self.session=session; self.telemetry=telemetry; self.laps_data=laps
            self._laps_by_drv=lbd; self.weather_data=wx_df; self.track_status_df=ts_df
            self._ts_times=ts_df["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in ts_df.columns else np.array([])
            self._wx_times=wx_df["TimeSec_f"].to_numpy(dtype=float) if "TimeSec_f" in wx_df.columns else np.array([])
            self._tel_times=tel_times; self._lap_times=lti
            self.drivers=list(telemetry.keys()); self.total_laps=total_laps
            self.session_best_s=best_s; self.session_start=t_min; self.max_time=t_max-t_min
            self.session_type=sess_type; self._sector_bests=sb; self._overall_sec_best=overall
            self._ers_state={}; self._track_lap_len=track_lap_len
            self._plot_last_drv=""; self._plot_last_lap=-1
            self._strategy_last_hash=""; self._ers_last_pct=-1.0; self._prev_positions={}
            self._overtake_count={}; self._pos_lost_count={}
            self._overtake_events=[]; self._last_overtake_str={}; self._session_max_speed={}
            self._fp_duration_s=fp_duration
            self._q_phase_bounds=q_phase_bounds; self._q_phase_durations=q_phase_durations
            self._red_flag_intervals=red_flag_intervals

            self._session_q.put({"ok":True,"race":race,"year":year,"sess_type":sess_type})
        except Exception as exc:
            log.exception("Session load failed")
            self._session_q.put({"ok":False,"err":str(exc)})
            self._loading=False

    def _on_session_loaded(self,race:str,year:int,sess_type:str):
        self._loading=False; dpg.set_value("txt_spin","")
        si=SESSION_INFO.get(sess_type,(sess_type,TXT))
        dpg.set_value("txt_track_name",f"{race}  •  {year}")
        self._refresh_badge(sess_type)
        self._timing_mode="race" if sess_type in ("R","S") else "quali"
        self._rebuild_timeline()
        try:
            fastest=self.session.laps.pick_fastest()
            if fastest is not None and not pd.isna(fastest.get("LapTime")):
                tel=fastest.get_telemetry()
                self._track_x=tel["X"].values; self._track_y=tel["Y"].values; self._draw_track()
        except Exception as exc: log.warning("Track map: %s",exc)
        dpg.configure_item("sld_time",max_value=self.max_time)
        if self._worker: self._worker.stop()
        self._worker=SnapshotWorker(self); self._worker.start()
        if self.drivers: self.selected_driver=self.drivers[0]
        self._session_loaded=True
        phase_info=""
        if sess_type in ("Q","SQ") and self._q_phase_bounds:
            phase_info=f"  {len(self._q_phase_bounds)} phases detected"
        dpg.set_value("txt_status",
                      f"OK  {len(self.drivers)} drivers  {self.total_laps} laps  {si[0]}{phase_info}")
        self._request_update(0)

    def _rebuild_timeline(self):
        if self.track_status_df is None or self.track_status_df.empty: return
        dpg.delete_item("dl_timeline",children_only=True); W=880
        dpg.draw_rectangle((0,0),(W,6),fill=_c("1a1a2e"),color=NONE,parent="dl_timeline")
        for i in range(len(self.track_status_df)):
            t0r=self._ts_times[i] if i<len(self._ts_times) else float("nan")
            if math.isnan(t0r): continue
            t0=(t0r-self.session_start)/self.max_time if self.max_time>0 else 0
            t1=((self._ts_times[i+1]-self.session_start)/self.max_time
                if i+1<len(self._ts_times) else 1.0)
            t0,t1=clamp(t0,0,1),clamp(t1,0,1)
            col=TRACK_STATUS.get(str(self.track_status_df["Status"].iloc[i]),TRACK_STATUS["1"])[1]
            dpg.draw_rectangle((t0*W,0),(t1*W,6),fill=col,color=NONE,parent="dl_timeline")

    def _draw_track(self):
        dpg.delete_item("dl_map",children_only=True); self._map_dots=set()
        if self._track_x is None: return
        W=max(200,dpg.get_item_width("dl_map") or 200)
        H=max(100,dpg.get_item_height("dl_map") or 100)
        n=len(self._track_x); step=max(1,n//1200); pts=[]
        for i in range(0,n,step):
            sx,sy=self._w2m(self._track_x[i],self._track_y[i],W,H); pts.append((sx,sy))
        if pts: dpg.draw_polyline(pts,color=_c("40405e"),thickness=4,parent="dl_map",tag="track_poly")

    # ── Playback controls ─────────────────────────────────────────────────
    def _set_speed(self,val:int): self.playback_speed=int(val or 1)

    def _select_driver(self,drv:str):
        if not drv: return
        self.selected_driver=drv; self._plot_last_drv=""; self._plot_last_lap=-1
        self._ana_last_drv=""; self._ana_last_lap=object()
        self._ana_last_style_n=-1; self._strategy_last_hash=""; self._ers_last_pct=-1.0
        log.info("Selected driver: %s",drv)
        if self._session_loaded: self._request_update(self.current_time)

    def _toggle_play(self):
        self.is_playing=not self.is_playing; self._last_tick=time.monotonic()
        dpg.configure_item("btn_play",label=" PAUSE " if self.is_playing else " PLAY ")

    def _on_slider(self,sender,value):
        new_t=float(value)
        if new_t<self.current_time-2.0: self._ers_state={}
        self.current_time=new_t; dpg.set_value("txt_time",hms(int(new_t)))
        self._request_update(new_t)

    def _jump(self,delta:float):
        self.current_time=clamp(self.current_time+delta,0,self.max_time)
        dpg.set_value("sld_time",self.current_time); self._request_update(self.current_time)

    def _refresh_badge(self,sess_type:str):
        si=SESSION_INFO.get(sess_type,(sess_type,TXT))
        dpg.set_value("txt_badge",f"[ {si[0]} ]"); dpg.configure_item("txt_badge",color=si[1])

    def _request_update(self,elapsed:float):
        if self._worker: self._worker.request(elapsed)


def main():
    app = F1App()
    app.run()

if __name__ == "__main__":
    main()