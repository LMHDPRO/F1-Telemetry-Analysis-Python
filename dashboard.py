import tkinter as tk
from tkinter import ttk, Canvas
import fastf1
import threading
import pandas as pd
import math
import time
import os
import numpy as np

cache_dir = 'f1_cache'
os.makedirs(cache_dir, exist_ok=True) 
fastf1.Cache.enable_cache(cache_dir) 

TEAM_COLORS = {
    'Mercedes': '#00d2be', 'Ferrari': '#dc0000', 'Red Bull Racing': '#0600ef', 
    'McLaren': '#ff8700', 'Aston Martin': '#006f62', 'Alpine': '#0090ff', 
    'Williams': '#005aff', 'RB': '#6692ff', 'Kick Sauber': '#52e252', 'Haas F1 Team': '#ffffff',
    'Alfa Romeo': '#900000', 'AlphaTauri': '#2b4562', 'Aston Martin Aramco Cognizant': '#006f62'
}

def format_lap_time(seconds):
    if pd.isna(seconds) or seconds == 0: return "--:--"
    m, s = divmod(seconds, 60)
    return f"{int(m)}:{s:06.3f}"

class F1RealDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("F1 Live Telemetry & Timing (API Real)")
        self.root.geometry("1650x950") 
        self.root.configure(bg="#1e1e2d") 
        
        self.session = None
        self.drivers = []
        self.telemetry_data = {}
        self.laps_data = None
        self.weather_data = None
        self.track_status = None
        self.total_laps_session = 0
        self.session_best_lap_s = None
        
        self.max_time_total = 0 
        self.session_start_time = 0
        
        self.current_selected_driver = None
        self.is_playing = False
        self.current_time_total = 0 
        self.playback_speed = tk.IntVar(value=1) 
        
        self.track_scale = 1.0
        self.track_cx = 0
        self.track_cy = 0
        self.map_w = 500
        self.map_h = 250

        self.style_ui()
        self.build_ui()
        self.load_calendar(2022) 

    def style_ui(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background="#1e1e2d")
        style.configure("TLabel", background="#1e1e2d", foreground="white", font=("Segoe UI", 10))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"), foreground="#e10600")
        style.configure("Treeview", background="#2a2a3b", foreground="white", fieldbackground="#2a2a3b", rowheight=25, font=("Segoe UI", 9))
        style.map('Treeview', background=[('selected', '#e10600')])
        style.configure("Treeview.Heading", background="#38383f", foreground="white", font=("Segoe UI", 10, "bold"))
        style.configure("TRadiobutton", background="#1e1e2d", foreground="white", font=("Segoe UI", 9, "bold"))

    def build_ui(self):
        # --- HEADER ---
        top_frame = ttk.Frame(self.root, padding=(10, 5, 10, 0))
        top_frame.pack(fill=tk.X)
        
        selector_frame = ttk.Frame(top_frame)
        selector_frame.pack(fill=tk.X, pady=5)
        
        ttk.Label(selector_frame, text="Año:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        self.combo_year = ttk.Combobox(selector_frame, values=[2022, 2023, 2024, 2025, 2026], width=6, state="readonly")
        self.combo_year.set(2022)
        self.combo_year.pack(side=tk.LEFT, padx=(0, 15))
        self.combo_year.bind("<<ComboboxSelected>>", lambda e: self.load_calendar(int(self.combo_year.get())))
        
        ttk.Label(selector_frame, text="Carrera:", font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 5))
        self.combo_race = ttk.Combobox(selector_frame, width=35, state="readonly")
        self.combo_race.pack(side=tk.LEFT, padx=(0, 15))
        
        self.btn_load = tk.Button(selector_frame, text="CARGAR SESIÓN", bg="#e10600", fg="white", font=("Segoe UI", 10, "bold"), command=self.load_session_thread)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 15))
        self.lbl_status = ttk.Label(selector_frame, text="Selecciona una carrera.", foreground="#aaa")
        self.lbl_status.pack(side=tk.LEFT)

        # --- SLICER Y CONTROLES ---
        control_frame = ttk.Frame(top_frame)
        control_frame.pack(fill=tk.X, pady=10)
        
        self.btn_play = tk.Button(control_frame, text="▶ PLAY", bg="#00a0e9", fg="white", font=("Segoe UI", 10, "bold"), command=self.toggle_play, state=tk.DISABLED)
        self.btn_play.pack(side=tk.LEFT, padx=(0, 10))
        
        ttk.Radiobutton(control_frame, text="X1", variable=self.playback_speed, value=1).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(control_frame, text="X4", variable=self.playback_speed, value=4).pack(side=tk.LEFT, padx=2)
        ttk.Radiobutton(control_frame, text="X16", variable=self.playback_speed, value=16).pack(side=tk.LEFT, padx=(2, 15))
        
        self.btn_prev_lap = tk.Button(control_frame, text="<< -1 LAP", bg="#38383f", fg="white", font=("Segoe UI", 9), command=lambda: self.jump_time(-90), state=tk.DISABLED)
        self.btn_prev_lap.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_next_lap = tk.Button(control_frame, text="+1 LAP >>", bg="#38383f", fg="white", font=("Segoe UI", 9), command=lambda: self.jump_time(90), state=tk.DISABLED)
        self.btn_next_lap.pack(side=tk.LEFT, padx=(0, 15))
        
        slider_container = ttk.Frame(control_frame)
        slider_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(10, 0))
        
        self.timeline_canvas = Canvas(slider_container, height=12, bg="#2a2a3b", highlightthickness=0)
        self.timeline_canvas.pack(fill=tk.X, pady=(0, 2))
        
        self.time_slider = tk.Scale(slider_container, from_=0, to=100, orient=tk.HORIZONTAL, bg="#1e1e2d", fg="white", troughcolor="#00ff00", highlightthickness=0, command=self.on_slider_move, state=tk.DISABLED)
        self.time_slider.pack(fill=tk.X)
        
        self.lbl_time = ttk.Label(control_frame, text="00:00:00", font=("Courier", 12, "bold"))
        self.lbl_time.pack(side=tk.LEFT, padx=10)

        # --- MAIN CONTENT ---
        main_content = ttk.Frame(self.root, padding=10)
        main_content.pack(fill=tk.BOTH, expand=True)
        
        # IZQUIERDA: LEADERBOARD
        left_frame = ttk.Frame(main_content)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, expand=False, padx=(0, 10))
        
        status_weather_frame = ttk.Frame(left_frame)
        status_weather_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.lbl_race_status = tk.Label(status_weather_frame, text="🟢 GREEN FLAG", font=("Segoe UI", 16, "bold"), bg="#1e1e2d", fg="#00ff00", width=16, anchor="w")
        self.lbl_race_status.pack(side=tk.LEFT)
        
        self.lbl_laps = tk.Label(status_weather_frame, text="LAP -- / --", font=("Segoe UI", 16, "bold"), bg="#1e1e2d", fg="white")
        self.lbl_laps.pack(side=tk.LEFT, padx=(10, 0))
        
        self.lbl_weather = ttk.Label(status_weather_frame, text="Air: --°C | Track: --°C | Rain: --", font=("Segoe UI", 10, "bold"), foreground="#aaa")
        self.lbl_weather.pack(side=tk.RIGHT, pady=6)
        
        cols = ("Pos", "Driver", "Team", "Gap", "Int", "Speed", "Tyre", "Laps")
        self.tree = ttk.Treeview(left_frame, columns=cols, show="headings", height=23)
        
        col_configs = {"Pos": 35, "Driver": 50, "Team": 90, "Gap": 60, "Int": 55, "Speed": 60, "Tyre": 45, "Laps": 40}
        for c, w in col_configs.items():
            self.tree.heading(c, text=c)
            self.tree.column(c, width=w, anchor=tk.CENTER if c != "Team" else tk.W)
            
        self.tree.pack(fill=tk.BOTH, expand=True)
        self.tree.bind("<<TreeviewSelect>>", self.on_driver_select)

        # DERECHA: MAPA, HUD Y SECTORES
        right_content = ttk.Frame(main_content)
        right_content.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # MAPA REAL
        map_frame = ttk.Frame(right_content)
        map_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        self.map_canvas = Canvas(map_frame, bg="#1e1e2d", highlightthickness=0)
        self.map_canvas.pack(fill=tk.BOTH, expand=True) 

        # HUD Y SECTORES
        bottom_right = ttk.Frame(right_content)
        bottom_right.pack(fill=tk.X, expand=False)
        
        # HUD IZQUIERDA
        hud_frame = ttk.Frame(bottom_right)
        hud_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        self.lbl_sel_driver = ttk.Label(hud_frame, text="--", font=("Segoe UI", 24, "bold"), foreground="white")
        self.lbl_sel_driver.pack(anchor=tk.W)
        self.lbl_team_name = ttk.Label(hud_frame, text="--", font=("Segoe UI", 12), foreground="#aaa")
        self.lbl_team_name.pack(anchor=tk.W, pady=(0,2))
        
        # Etiquetas de estado independientes
        self.lbl_battle_state = tk.Label(hud_frame, text="TRACK: CLEAR", font=("Segoe UI", 12, "bold"), bg="#1e1e2d", fg="gray", width=40, anchor="w")
        self.lbl_battle_state.pack(anchor=tk.W)
        
        self.lbl_driving_style = tk.Label(hud_frame, text="STYLE: NORMAL", font=("Segoe UI", 12, "bold"), bg="#1e1e2d", fg="gray", width=40, anchor="w")
        self.lbl_driving_style.pack(anchor=tk.W, pady=(0, 5))

        self.hud_canvas = Canvas(hud_frame, width=300, height=260, bg="#1e1e2d", highlightthickness=0)
        self.hud_canvas.pack(pady=5, fill=tk.BOTH, expand=True)

        # NUEVO DISEÑO REDONDO (Todo mirando hacia arriba, concéntrico)
        rpm_box = (30, 20, 270, 260)
        pedal_box = (45, 35, 255, 245)
        
        # RPM (Mitad Superior Exterior, 180 a 0)
        self.hud_canvas.create_arc(*rpm_box, start=180, extent=-180, style=tk.ARC, outline="#38383f", width=14, tags="rpm_bg")
        self.hud_canvas.create_arc(*rpm_box, start=180, extent=0, style=tk.ARC, outline="#00a0e9", width=14, tags="rpm_fg")

        # Pedales (Mitad Superior Interior, paralelos a RPM, naciendo desde abajo hacia arriba)
        # Throttle: 3/4 (135 grados) empezando a la Izquierda -> Desde 180 hacia 45 (extent -135)
        self.hud_canvas.create_arc(*pedal_box, start=180, extent=-135, style=tk.ARC, outline="#1a331a", width=16, tags="thr_bg")
        self.hud_canvas.create_arc(*pedal_box, start=180, extent=0, style=tk.ARC, outline="#00ff00", width=16, tags="thr_fg")

        # Brake: 1/4 (45 grados) a la Derecha -> Naciendo desde 0 hacia 45 (extent 45)
        self.hud_canvas.create_arc(*pedal_box, start=0, extent=45, style=tk.ARC, outline="#331a1a", width=16, tags="brk_bg")
        self.hud_canvas.create_arc(*pedal_box, start=0, extent=0, style=tk.ARC, outline="#ff0000", width=16, tags="brk_fg")

        # Textos Centrales Ajustados
        self.hud_canvas.create_text(150, 120, text="0", fill="white", font=("Segoe UI", 56, "bold"), tags="speed_text")
        self.hud_canvas.create_text(150, 170, text="km/h", fill="#ccc", font=("Segoe UI", 12), tags="kmh_text")
        self.hud_canvas.create_text(150, 70, text="0 RPM", fill="#bbb", font=("Segoe UI", 14), tags="rpm_text")
        self.hud_canvas.create_text(150, 205, text="N", fill="#00a0e9", font=("Segoe UI", 24, "bold"), tags="gear_text")
        
        # Etiquetas laterales para los pedales concéntricos
        self.hud_canvas.create_text(55, 155, text="THR", fill="#00ff00", font=("Segoe UI", 8, "bold"))
        self.hud_canvas.create_text(245, 155, text="BRK", fill="#ff0000", font=("Segoe UI", 8, "bold"))
        
        self.hud_canvas.create_text(150, 240, text="STRAIGHT MODE: OFF", fill="gray", font=("Segoe UI", 11, "bold"), tags="drs_text")

        self.lbl_gap_ahead = ttk.Label(hud_frame, text="▲ Ahead: --", font=("Segoe UI", 11, "bold"), foreground="#ccc")
        self.lbl_gap_ahead.pack(anchor=tk.W)
        self.lbl_gap_behind = ttk.Label(hud_frame, text="▼ Behind: --", font=("Segoe UI", 11, "bold"), foreground="#ccc")
        self.lbl_gap_behind.pack(anchor=tk.W)

        # PANEL DE SECTORES Y PACE (DERECHA)
        sec_frame = ttk.Frame(bottom_right)
        sec_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=(10,0))
        ttk.Label(sec_frame, text="Current Lap Sectors vs Prev", style="Header.TLabel").pack(anchor=tk.W, pady=(0, 5))
        
        self.tree_sec = ttk.Treeview(sec_frame, columns=("Sector", "Time", "Diff"), show="headings", height=3)
        for c in ("Sector", "Time", "Diff"):
            self.tree_sec.heading(c, text=c)
            self.tree_sec.column(c, width=70, anchor=tk.CENTER)
        self.tree_sec.pack(fill=tk.X)
        self.tree_sec.tag_configure("green", foreground="#00ff00")
        self.tree_sec.tag_configure("red", foreground="#ff0000")
        
        self.lbl_tyre_info = ttk.Label(sec_frame, text="Tyre: -- | Age: -- laps | Pits: --", font=("Segoe UI", 11))
        self.lbl_tyre_info.pack(anchor=tk.W, pady=(10, 2))
        
        ttk.Label(sec_frame, text="Pace & Telemetry Analysis", style="Header.TLabel").pack(anchor=tk.W, pady=(5,0))
        self.lbl_pace = ttk.Label(sec_frame, text="Pace (Avg 5L): --", font=("Segoe UI", 11, "bold"), foreground="white")
        self.lbl_pace.pack(anchor=tk.W)
        
        self.lbl_fastest_lap = ttk.Label(sec_frame, text="Last Lap: -- | Session Best: --", font=("Segoe UI", 11), foreground="#ccc")
        self.lbl_fastest_lap.pack(anchor=tk.W, pady=(2, 2))

        # Reemplazamos el Label por una Treeview scrolleable para el historial de estilos
        self.tree_style = ttk.Treeview(sec_frame, columns=("Lap", "LiCo %", "Clip %"), show="headings", height=5)
        self.tree_style.heading("Lap", text="Lap")
        self.tree_style.heading("LiCo %", text="LiCo %")
        self.tree_style.heading("Clip %", text="Clip %")
        self.tree_style.column("Lap", width=50, anchor=tk.CENTER)
        self.tree_style.column("LiCo %", width=70, anchor=tk.CENTER)
        self.tree_style.column("Clip %", width=70, anchor=tk.CENTER)
        self.tree_style.pack(fill=tk.X, pady=(2, 5))

    def load_calendar(self, year):
        self.lbl_status.config(text=f"Cargando {year}...")
        self.combo_race.set("")
        def fetch():
            try:
                schedule = fastf1.get_event_schedule(year)
                races = schedule[schedule['EventFormat'] != 'testing']['EventName'].tolist()
                self.root.after(0, lambda: self.combo_race.config(values=races))
                if races: self.root.after(0, lambda: self.combo_race.set(races[0]))
                self.root.after(0, lambda: self.lbl_status.config(text="Calendario listo."))
            except Exception as e:
                self.root.after(0, lambda: self.lbl_status.config(text="Error cargando."))
        threading.Thread(target=fetch, daemon=True).start()

    def load_session_thread(self):
        year, race = int(self.combo_year.get()), self.combo_race.get()
        if not race: return
        self.btn_load.config(state=tk.DISABLED)
        self.lbl_status.config(text=f"Descargando datos (Paciencia, procesando múltiples capas)...")
        threading.Thread(target=self.fetch_fastf1_data, args=(year, race), daemon=True).start()

    def fetch_fastf1_data(self, year, race):
        try:
            self.session = fastf1.get_session(year, race, 'R')
            self.session.load(telemetry=True, weather=True, messages=False)
            
            self.telemetry_data.clear()
            self.laps_data = self.session.laps
            self.weather_data = self.session.weather_data
            self.track_status = self.session.track_status
            self.drivers = [d for d in self.session.drivers]
            
            self.total_laps_session = self.laps_data['LapNumber'].max() if not self.laps_data.empty else 0
            
            try:
                fastest_overall = self.laps_data.pick_fastest()
                self.session_best_lap_s = fastest_overall['LapTime'].total_seconds() if pd.notnull(fastest_overall.get('LapTime')) else None
            except:
                self.session_best_lap_s = None
            
            min_time, max_time = float('inf'), 0
            for drv in self.drivers:
                try:
                    laps = self.laps_data.pick_drivers(drv)
                    if laps.empty: continue
                    tel = laps.get_telemetry()
                    if tel.empty: continue
                    
                    tel['TimeSec'] = tel['SessionTime'].dt.total_seconds()
                    
                    t_min, t_max = tel['TimeSec'].min(), tel['TimeSec'].max()
                    if t_min < min_time: min_time = t_min
                    if t_max > max_time: max_time = t_max
                    
                    drv_info = self.session.get_driver(drv)
                    tel['Team'] = drv_info.get('TeamName', 'Unknown')
                    tel['FullName'] = drv_info.get('FullName', drv)
                    tel['Abbr'] = drv_info.get('Abbreviation', drv)
                    tel['DriverNumber'] = drv_info.get('DriverNumber', drv)
                    self.telemetry_data[drv] = tel
                except Exception as e:
                    print(f"Driver {drv} data error: {e}")

            if not self.telemetry_data:
                raise ValueError("No valid telemetry found. Is this a future race?")

            self.session_start_time = min_time
            self.max_time_total = max_time - min_time 
            self.root.after(0, self.setup_post_load)
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            self.root.after(0, lambda: self.lbl_status.config(text=f"Error Crítico: {str(e)}"))
            self.root.after(0, lambda: self.btn_load.config(state=tk.NORMAL))

    def setup_post_load(self):
        self.time_slider.config(state=tk.NORMAL, to=self.max_time_total)
        self.btn_play.config(state=tk.NORMAL)
        self.btn_prev_lap.config(state=tk.NORMAL)
        self.btn_next_lap.config(state=tk.NORMAL)
        
        self.root.update_idletasks() # Forzar cálculo de dimensiones ANTES de dibujar la pista
        
        self.draw_timeline()
        self.draw_real_track_map()
        
        for item in self.tree.get_children(): self.tree.delete(item)
        for drv in self.drivers:
            if drv in self.telemetry_data:
                tel_ref = self.telemetry_data[drv].iloc[0]
                team, abbr = tel_ref['Team'], tel_ref['Abbr']
                self.tree.insert("", "end", iid=drv, values=("0", abbr, team, "-", "-", "0", "-", "0"))
                self.tree.tag_configure(drv, foreground=TEAM_COLORS.get(team, 'white'), background="#2a2a3b")
        
        if self.drivers:
            self.current_selected_driver = self.drivers[0]
            self.tree.selection_set(self.current_selected_driver)

        self.lbl_status.config(text="Sesión lista.")
        self.btn_load.config(state=tk.NORMAL)
        self.on_slider_move(0)

    def draw_timeline(self):
        self.timeline_canvas.delete("all")
        self.timeline_canvas.update_idletasks()
        w = self.timeline_canvas.winfo_width()
        if w < 100: w = 1200 
        
        if self.track_status is not None and not self.track_status.empty:
            status_colors = {'1': "#00ff00", '2': "#ffff00", '3': "#ffff00", '4': "#ff8700", '5': "#ff0000", '6': "#d200d2", '7': "#00ff00"}
            for i in range(len(self.track_status)):
                row = self.track_status.iloc[i]
                start_sec = row['Time'].total_seconds() - self.session_start_time
                if start_sec < 0: start_sec = 0
                
                end_sec = self.max_time_total
                if i + 1 < len(self.track_status):
                    end_sec = self.track_status.iloc[i+1]['Time'].total_seconds() - self.session_start_time
                
                x1, x2 = (start_sec / self.max_time_total) * w, (end_sec / self.max_time_total) * w
                color = status_colors.get(str(row['Status']), "#1e1e2d")
                self.timeline_canvas.create_rectangle(x1, 0, x2, 12, fill=color, outline="")

    def draw_real_track_map(self):
        self.map_canvas.delete("all")
        try:
            fastest_lap = self.session.laps.pick_fastest()
            if pd.isna(fastest_lap.get('LapTime')): return
            tel = fastest_lap.get_telemetry()
        except: return
        
        x_vals, y_vals = tel['X'].values, tel['Y'].values
        min_x, max_x = np.min(x_vals), np.max(x_vals)
        min_y, max_y = np.min(y_vals), np.max(y_vals)
        
        self.map_canvas.update()
        self.map_w = self.map_canvas.winfo_width()
        self.map_h = self.map_canvas.winfo_height()
        if self.map_w < 100: self.map_w, self.map_h = 600, 350 
        
        range_x, range_y = max_x - min_x, max_y - min_y
        self.track_scale = min(self.map_w / range_x, self.map_h / range_y) * 0.90
        self.track_cx, self.track_cy = (max_x + min_x) / 2, (max_y + min_y) / 2
        
        track_points = []
        for x, y in zip(x_vals, y_vals):
            track_points.extend([(self.map_w / 2) + (x - self.track_cx) * self.track_scale, (self.map_h / 2) - (y - self.track_cy) * self.track_scale])
        self.map_canvas.create_polygon(track_points, outline="#555566", fill="", width=5, smooth=False, tags="track")

    def toggle_play(self):
        if self.is_playing:
            self.is_playing = False
            self.btn_play.config(text="▶ PLAY")
        else:
            self.is_playing = True
            self.btn_play.config(text="|| PAUSE")
            threading.Thread(target=self.play_replay_thread, daemon=True).start()

    def play_replay_thread(self):
        while self.is_playing and self.current_time_total < self.max_time_total:
            time_step = 0.05 * self.playback_speed.get()
            self.current_time_total += time_step 
            self.root.after(0, lambda t=self.current_time_total: self.time_slider.set(t))
            if self.current_time_total >= self.max_time_total: self.root.after(0, self.toggle_play)
            time.sleep(0.05)

    def jump_time(self, seconds):
        new_time = max(0, min(self.max_time_total, self.current_time_total + seconds))
        self.time_slider.set(new_time)

    def on_slider_move(self, val):
        self.current_time_total = float(val)
        m, s = divmod(int(self.current_time_total), 60)
        h, m = divmod(m, 60)
        self.lbl_time.config(text=f"{h:02d}:{m:02d}:{s:02d}")
        self.update_dashboard_at_time(self.current_time_total)

    def on_driver_select(self, event):
        selected = self.tree.selection()
        if selected:
            self.current_selected_driver = selected[0]
            self.update_dashboard_at_time(self.current_time_total)

    def update_dashboard_at_time(self, elapsed_sec):
        if not self.telemetry_data: return
        target_abs_time = self.session_start_time + elapsed_sec
        target_td = pd.Timedelta(seconds=target_abs_time)
        
        # --- RACE STATUS & SLICER COLOR ---
        if self.track_status is not None and not self.track_status.empty:
            past_status = self.track_status[self.track_status['Time'] <= target_td]
            if not past_status.empty:
                status_map = {'1': ("🟢 GREEN FLAG", "#00ff00"), '2': ("🟡 YELLOW FLAG", "#ffff00"), '3': ("🟡 SECTOR YELLOW", "#ffff00"),
                              '4': ("🟠 SAFETY CAR", "#ff8700"), '5': ("🔴 RED FLAG", "#ff0000"), '6': ("🟣 VIRTUAL SC", "#d200d2"), '7': ("🟢 VSC END", "#00ff00")}
                text, color = status_map.get(str(past_status.iloc[-1]['Status']), ("🟢 GREEN FLAG", "#00ff00"))
                self.lbl_race_status.config(text=text, fg=color)
                self.time_slider.config(troughcolor=color) 

        if self.weather_data is not None and not self.weather_data.empty:
            past_weather = self.weather_data[self.weather_data['Time'] <= target_td]
            if not past_weather.empty:
                w = past_weather.iloc[-1]
                self.lbl_weather.config(text=f"Air: {round(w.get('AirTemp', 0), 1)}°C | Track: {round(w.get('TrackTemp', 0), 1)}°C | Rain: {'Yes' if w.get('Rainfall') else 'No'}")

        # --- MAPA Y POSICIONES ---
        self.map_canvas.delete("car_dot")
        drv_selected_data, driver_status_list = None, []
        max_lap_current = 0

        for drv, df in self.telemetry_data.items():
            times = df['TimeSec'].values
            if target_abs_time > times[-1]:
                speed_str, row, is_out = "OUT", df.iloc[-1], True
            else:
                idx = min(np.searchsorted(times, target_abs_time), len(times) - 1)
                row, is_out = df.iloc[idx], False
                speed_str = f"{int(row['Speed'])} km/h" if not pd.isna(row['Speed']) else "PIT"
            
            x, y = row['X'], row['Y']
            if not pd.isna(x) and not pd.isna(y) and not is_out:
                cv_x = (self.map_w / 2) + (x - self.track_cx) * self.track_scale
                cv_y = (self.map_h / 2) - (y - self.track_cy) * self.track_scale
                
                team_color = TEAM_COLORS.get(row['Team'], 'white')
                size, outline = (8, "#ffffff") if drv == self.current_selected_driver else (4.5, team_color)
                self.map_canvas.create_oval(cv_x-size, cv_y-size, cv_x+size, cv_y+size, fill=team_color, outline=outline, width=2, tags="car_dot")
            
            if drv == self.current_selected_driver: drv_selected_data = row
            
            drv_laps = self.laps_data.pick_drivers(drv)
            current_lap = drv_laps[(drv_laps['Time'].dt.total_seconds() > target_abs_time) | pd.isna(drv_laps['Time'])].head(1)
            pos, lap_num, tyre = 999, 0, "—" 
            
            if not current_lap.empty:
                r = current_lap.iloc[0]
                pos = r['Position'] if not pd.isna(r['Position']) else 999
                lap_num = r['LapNumber']
                tyre = f"({str(r['Compound'])[0]})" if not pd.isna(r['Compound']) else "—"
                if not pd.isna(lap_num) and lap_num > max_lap_current: max_lap_current = lap_num
            
            total_dist = (lap_num * 5000) + (row.get('Distance', 0) if not pd.isna(row.get('Distance', 0)) else 0)
            
            driver_status_list.append({
                'pos': pos, 'drv': drv, 'num': row.get('DriverNumber', drv), 'abbr': row.get('Abbr', drv),
                'team': row['Team'], 'speed': speed_str, 'tyre': tyre, 'lap': lap_num, 
                'dist': total_dist if not is_out else -1, 'spd_val': row.get('Speed', 0)
            })

        self.lbl_laps.config(text=f"LAP {int(max_lap_current)} / {int(self.total_laps_session)}")

        driver_status_list.sort(key=lambda x: (x['pos'], -x['dist'])) 
        leader_dist = driver_status_list[0]['dist'] if driver_status_list else 0
        ordered_drivers_dict = {}

        for i, d in enumerate(driver_status_list):
            if d['dist'] == -1:
                gap_str, int_str, gap_num, int_num = "OUT", "OUT", 999, 999
            elif i == 0:
                gap_str, int_str, gap_num, int_num = "Leader", "Leader", 0, 0
            else:
                spd_ms = max(10, d['spd_val'] / 3.6) 
                gap_s = (leader_dist - d['dist']) / spd_ms
                int_s = (driver_status_list[i-1]['dist'] - d['dist']) / spd_ms
                gap_str = f"+{gap_s:.1f}s" if gap_s < 100 else "+1L"
                int_str = f"+{int_s:.1f}s" if int_s < 100 else "+1L"
                gap_num, int_num = gap_s, int_s
            
            d['gap'], d['int'] = gap_str, int_str
            d['gap_num'], d['int_num'] = gap_num, int_num
            ordered_drivers_dict[d['drv']] = d 
            
            if self.tree.exists(d['drv']):
                self.tree.item(d['drv'], values=(str(i+1) if d['dist'] != -1 else "-", d['abbr'], d['team'], gap_str, int_str, d['speed'], d['tyre'], d['lap']))
                self.tree.move(d['drv'], '', i) 

        # --- HUD DEL PILOTO ---
        if drv_selected_data is not None:
            r = drv_selected_data
            drv = self.current_selected_driver
            team_color = TEAM_COLORS.get(r['Team'], 'white')
            
            self.lbl_sel_driver.config(text=f"{r.get('FullName', drv)} ({r.get('DriverNumber', drv)})", foreground=team_color)
            self.lbl_team_name.config(text=f"{r['Team']}")
            
            my_stats = ordered_drivers_dict.get(drv)
            my_idx = driver_status_list.index(my_stats)
            
            ahead = f"{driver_status_list[my_idx-1]['num']} {driver_status_list[my_idx-1]['abbr']} ({my_stats['int']})" if my_idx > 0 else "NOBODY (LEADER)"
            behind = f"{driver_status_list[my_idx+1]['num']} {driver_status_list[my_idx+1]['abbr']} ({driver_status_list[my_idx+1]['int']})" if my_idx < len(driver_status_list)-1 else "NOBODY"
            self.lbl_gap_ahead.config(text=f"▲ Ahead: {ahead}")
            self.lbl_gap_behind.config(text=f"▼ Behind: {behind}")

            speed, rpm = (0 if pd.isna(r[k]) else float(r[k]) for k in ('Speed', 'RPM'))
            throttle, brake = (0 if pd.isna(r[k]) else float(r[k]) for k in ('Throttle', 'Brake'))
            gear = "N" if pd.isna(r['nGear']) or r['nGear'] == 0 else int(r['nGear'])
            
            # RPM Mitad Superior Exterior (180 a 0)
            self.hud_canvas.itemconfigure("rpm_fg", extent=-(rpm/13000)*180)
            
            # Throttle 3/4 Izquierdo (Top Half Interior, naciendo de 180 hacia 45, extent -135)
            self.hud_canvas.itemconfigure("thr_fg", extent=-(throttle/100)*135)
            
            # Brake 1/4 Derecho Digital (Top Half Interior, naciendo de 0 hacia 45, extent 45)
            brake_ext = 45 if brake > 0 else 0
            self.hud_canvas.itemconfigure("brk_fg", extent=brake_ext)
            
            self.hud_canvas.itemconfigure("speed_text", text=str(int(speed)))
            self.hud_canvas.itemconfigure("rpm_text", text=f"{int(rpm)} RPM")
            self.hud_canvas.itemconfigure("gear_text", text=str(gear))

            # HEURÍSTICAS INDEPENDIENTES: Style vs Battle
            style_text, style_color = "NORMAL", "gray"
            
            df_drv = self.telemetry_data[drv]
            times_drv = df_drv['TimeSec'].values
            idx = min(np.searchsorted(times_drv, target_abs_time), len(times_drv) - 1)
            prev_idx = max(0, idx - 5) 
            speed_diff = speed - df_drv.iloc[prev_idx]['Speed']

            # Calcular Estilo de Conducción Vuelta a Vuelta (Últimas 10 vueltas)
            drv_laps = self.laps_data.pick_drivers(drv)
            completed_laps = drv_laps[drv_laps['Time'].dt.total_seconds() <= target_abs_time]
            
            # Limpiamos la tabla antes de reescribir
            for item in self.tree_style.get_children(): self.tree_style.delete(item)
            
            if len(completed_laps) > 0:
                recent_laps = completed_laps.tail(10)
                for l_idx, lap_row in recent_laps.iterrows():
                    l_start = lap_row['Time'].total_seconds() - lap_row['LapTime'].total_seconds()
                    l_end = lap_row['Time'].total_seconds()
                    
                    df_lap = df_drv[(df_drv['TimeSec'] >= l_start) & (df_drv['TimeSec'] <= l_end)].copy()
                    tot_f = len(df_lap)
                    
                    if tot_f > 0:
                        # Vectorizado: comparamos con 3 frames atrás para medir la caída de velocidad real
                        df_lap['SpeedDiff'] = df_lap['Speed'].diff(periods=3)
                        
                        # LiCo: 0 acelerador, 0 freno, vel > 200, perdiendo velocidad por inercia
                        lico_frames = np.sum((df_lap['Throttle'] == 0) & (df_lap['Brake'] == 0) & (df_lap['Speed'] > 200) & (df_lap['SpeedDiff'] < 0))
                        
                        # Superclipping: Acelerador a fondo, 0 freno, vel alta, pero perdiendo velocidad abruptamente (-1.5 km/h) por corte de energía
                        clip_frames = np.sum((df_lap['Throttle'] >= 95) & (df_lap['Brake'] == 0) & (df_lap['Speed'] > 250) & (df_lap['RPM'] > 10500) & (df_lap['SpeedDiff'] < -1.5))
                        
                        p_lico = (lico_frames / tot_f) * 100
                        p_clip = (clip_frames / tot_f) * 100
                        
                        # Insertamos en el índice 0 para que la vuelta más nueva quede siempre hasta arriba
                        tag = "high_clip" if p_clip > 1.5 else "normal"
                        self.tree_style.insert("", 0, values=(int(lap_row['LapNumber']), f"{p_lico:.1f}%", f"{p_clip:.1f}%"), tags=(tag,))
                        
                # Pintamos de morado las vueltas donde el clipping fue muy agresivo
                self.tree_style.tag_configure("high_clip", foreground="#d200d2")

            # Indicadores Activos Visuales (HUD Tiempo Real)
            if throttle == 0 and brake == 0 and speed > 200 and speed_diff < 0: 
                style_text, style_color = "LiCo (Lift & Coast)", "#00a0e9"
            elif throttle >= 95 and brake == 0 and speed > 250 and rpm > 10500 and speed_diff < -1.5:
                style_text, style_color = "⚠️ SUPERCLIPPING", "#d200d2"
            elif throttle >= 95: 
                style_text, style_color = "PUSHING", "#00ff00"
            
            self.lbl_driving_style.config(text=f"STYLE: {style_text}", foreground=style_color)
                
            # BATTLE DETECTOR BASADO ESTRICTAMENTE EN INTERVALOS REALES (<3s y <1s)
            battle_text, battle_color = "CLEAR", "gray"
            
            if my_idx < len(driver_status_list) - 1:
                car_behind = driver_status_list[my_idx + 1]
                if car_behind['int_num'] <= 3.0:
                    if car_behind['lap'] > my_stats['lap']:
                        battle_text, battle_color = f"🟦 YIELDING TO {car_behind['num']} {car_behind['abbr']}", "#00a0e9"
                    else:
                        battle_text, battle_color = f"🛡️ DEFENDING {car_behind['num']} {car_behind['abbr']}", "#ff8700"

            if my_idx > 0:
                car_ahead = driver_status_list[my_idx - 1]
                if my_stats['int_num'] <= 3.0:
                    if my_stats['lap'] > car_ahead['lap']:
                        battle_text, battle_color = f"🟦 LAPPING {car_ahead['num']} {car_ahead['abbr']}", "#00a0e9"
                    else:
                        mode = "⚔️ OVERTAKING" if my_stats['int_num'] <= 1.0 else "⚔️ BATTLING"
                        b_col = "#ff0000" if my_stats['int_num'] <= 1.0 else "#ff8700"
                        battle_text, battle_color = f"{mode} {car_ahead['num']} {car_ahead['abbr']}", b_col

            self.lbl_battle_state.config(text=f"TRACK: {battle_text}", foreground=battle_color)
            
            drs_val = r.get('DRS', 0)
            self.hud_canvas.itemconfigure("drs_text", text="STRAIGHT MODE", fill="#00ff00") if not pd.isna(drs_val) and drs_val >= 10 else self.hud_canvas.itemconfigure("drs_text", text="STRAIGHT MODE: OFF", fill="gray")

            # INFO DE PACE & FASTEST LAP
            cur_lap_df = drv_laps[(drv_laps['Time'].dt.total_seconds() > target_abs_time)].head(1)
            
            pace_str, pace_col = "--", "gray"
            last_lap_str, delta_str = "--:--", "--"
            
            if len(completed_laps) > 0:
                last_lap_sec = completed_laps.iloc[-1]['LapTime'].total_seconds()
                if not pd.isna(last_lap_sec):
                    last_lap_str = format_lap_time(last_lap_sec)
                    if self.session_best_lap_s:
                        delta_best = last_lap_sec - self.session_best_lap_s
                        delta_str = f"+{delta_best:.3f}s"
                        
                    if len(completed_laps) >= 2:
                        prev_laps = completed_laps.iloc[-6:-1] 
                        if not prev_laps.empty:
                            avg_pace = prev_laps['LapTime'].dt.total_seconds().mean()
                            pace_diff = last_lap_sec - avg_pace
                            if not pd.isna(pace_diff):
                                pace_str = f"IMPROVING ({pace_diff:+.2f}s)" if pace_diff < 0 else f"DROPPING ({pace_diff:+.2f}s)"
                                pace_col = "#00ff00" if pace_diff < 0 else "#ff0000"
            
            self.lbl_pace.config(text=f"Pace (Avg 5L): {pace_str}", foreground=pace_col)
            sess_best_str = format_lap_time(self.session_best_lap_s) if self.session_best_lap_s else "--:--"
            self.lbl_fastest_lap.config(text=f"Last Lap: {last_lap_str} ({delta_str}) | Session Best: {sess_best_str}")

            for item in self.tree_sec.get_children(): self.tree_sec.delete(item)
            if not cur_lap_df.empty:
                cur_lap_row = cur_lap_df.iloc[0]
                lap_num = cur_lap_row['LapNumber']
                
                pits = len(drv_laps.dropna(subset=['PitOutTime']))
                self.lbl_tyre_info.config(text=f"Tyre: {cur_lap_row['Compound']} | Age: {cur_lap_row['TyreLife']} laps | Pits: {pits}")
                
                prev_lap_df = drv_laps[drv_laps['LapNumber'] == lap_num - 1]
                for s_idx in range(1, 4):
                    s_col = f'Sector{s_idx}Time'
                    cur_s = cur_lap_row[s_col].total_seconds() if not pd.isna(cur_lap_row[s_col]) else 0
                    prev_s = prev_lap_df.iloc[0][s_col].total_seconds() if not prev_lap_df.empty and not pd.isna(prev_lap_df.iloc[0][s_col]) else 0
                    
                    diff = cur_s - prev_s if prev_s > 0 and cur_s > 0 else 0
                    tag = "green" if diff < 0 else "red" if diff > 0 else ""
                    self.tree_sec.insert("", "end", values=(f"S{s_idx}", f"{cur_s:.3f}" if cur_s else "-", f"{diff:+.3f}" if diff else "-"), tags=(tag,))

if __name__ == "__main__":
    root = tk.Tk()
    app = F1RealDashboard(root)
    root.mainloop()