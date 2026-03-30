<div align="center">

# 🏎️ F1 Telemetry Analysis 26'

### Visualizador y analizador de telemetría de Fórmula 1 en tiempo real

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)
![DearPyGui](https://img.shields.io/badge/DearPyGui-UI-blueviolet?style=for-the-badge)
![FastF1](https://img.shields.io/badge/FastF1-Data-e10600?style=for-the-badge)
![Versión](https://img.shields.io/badge/Versión-v6.54-orange?style=for-the-badge)
![Temporadas](https://img.shields.io/badge/Temporadas-2018--2026-brightgreen?style=for-the-badge)

*Desarrollado por **Pardiñaz** · Reconstrucción completa de sesiones F1 usando telemetría real*

---

> Proyecto de análisis de datos desarrollado para entender cómo se procesa la información en pista y cómo la gestión de energía del power unit influye cada vez más en el rendimiento del monoplaza. Conceptos recientes como el **superclipping** —asociado a la generación eléctrica a partir de energía térmica en los motores de nueva generación— son analizados mediante telemetría disponible, identificando efectos de regeneración y despliegue que impactan la aceleración y el comportamiento general del vehículo.

</div>

---

## 📋 Índice

- [✨ Características](#-características)
- [🚀 Instalación](#-instalación)
- [🖥️ Interfaz](#️-interfaz)
- [⚡ Simulación ERS 2026](#-simulación-ers-2026)
- [📊 Sesiones soportadas](#-sesiones-soportadas)
- [🧰 Stack técnico](#-stack-técnico)
- [📄 Fuentes de datos](#-fuentes-de-datos)

---

## ✨ Características

<table>
<tr>
<td width="50%">

### 🏁 Live Timing Tower
- Tabla de posiciones en tiempo real durante la reproducción
- Gap al líder e intervalo al auto de adelante **con soporte de vueltas de diferencia** (`+N Laps`)
- Colores por equipo oficial (Mercedes, Ferrari, Red Bull, McLaren...)
- Click en cualquier fila para seleccionar el piloto y centrar el análisis

</td>
<td width="50%">

### 🗺️ Track Map
- Mapa del circuito generado automáticamente con la telemetría
- Puntos animados con los colores de cada equipo
- Zoom, paneo y botón de centrado en el piloto seleccionado
- Pilotos retirados o finalizados ocultos del mapa

</td>
</tr>
<tr>
<td width="50%">

### 🎛️ HUD Animado
- Gauge circular de RPM con zona roja y bicolor (azul/cian)
- Arco interior de throttle (verde) y freno (rojo)
- Velocidad en kph y mph, marcha actual y RPM exactos
- El color de la marcha cambia a rojo en zona roja

</td>
<td width="50%">

### 📈 Telemetría
- Gráfica continua de Velocidad, Throttle %, Freno y SOC de ERS
- Línea de cursor sincronizada con la posición actual de reproducción
- Fondos sombreados por sectores (S1/S2/S3)
- Ventana deslizante configurable de ~90s

</td>
</tr>
<tr>
<td width="50%">

### 🏎️ Análisis de Sectores
- Tiempo por sector vs mejor personal y promedio de 5 vueltas
- Veredicto automático: BEST / FAST / SLOW / DROP
- Estado de pista: GRN / SC / VSC / RED FLAG en tiempo real
- Métricas de degradación de neumático por vuelta

</td>
<td width="50%">

### 📋 Driving Style History
- Historial de todas las vueltas con clasificación por color:
  `BEST` · `FAST` · `OK` · `SLOW` · `DROP` · `SCLIP`
- Columnas: Throttle%, WOT%, Brake%, Lift&Coast, Superclipping, RPM alto
- Condición de pista (Cond) por vuelta
- Scroll automático hasta la vuelta actual

</td>
</tr>
<tr>
<td width="50%">

### ⚙️ Race Strategy
- Estado en pista: ON TRACK / PIT / OUT LAP / IN LAP
- Contador de paradas realizadas
- Compuesto actual, compuesto anterior y vida del neumático
- Barra visual del stint de neumático

</td>
<td width="50%">

### 📊 Pace & Metrics
- Gap al P1, promedio de stint, ventana de undercut
- Contador de adelantamientos y posiciones perdidas
- Velocidad máxima de sesión, mínima y promedio de vuelta
- Vueltas restantes y diagnóstico de ritmo

</td>
</tr>
</table>

---

## 🚀 Instalación

**Prerrequisitos:** Python 3.10 o superior

```bash
# 1. Clona el repositorio
git clone https://github.com/LMHDPRO/F1-Telemetry-Analysis-Python.git
cd F1-Telemetry-Analysis-Python

# 2. Instala las dependencias
pip install dearpygui fastf1 pandas numpy

# 3. Ejecuta el dashboard
python DashboardV5.py
```

> **Primera ejecución:** FastF1 descargará y cacheará los datos de la sesión seleccionada en `~/.f1_cache`. Las cargas posteriores de la misma sesión son casi instantáneas. El botón **CLR CACHE** limpia la caché desde la interfaz.

---

## 🖥️ Interfaz

El dashboard está dividido en cinco áreas principales:

```
┌─────────────────────────────────────────────────────────────────┐
│  Header: Año · Gran Premio · Tipo de sesión · LOAD · Status     │
├─────────────────────────────────────────────────────────────────┤
│  Controls: PLAY/PAUSE · Speed (x1/x4/x16/x64) · Timeline       │
├─────────────┬───────────────────────────┬───────────────────────┤
│             │                           │                       │
│  TIMING     │      TRACK MAP            │   HUD (Gauge)         │
│  TOWER      │   (circuito animado)      │   RPM · Gear · Speed  │
│             │                           │                       │
│  STRATEGY   ├───────────────────────────┴───────────────────────┤
│  ERS        │         TELEMETRY PLOT (Speed/Thr/Brk/ERS)        │
│             ├─────────────┬─────────────────┬───────────────────┤
│             │  SECTORS    │  PACE & METRICS │  STYLE HISTORY    │
└─────────────┴─────────────┴─────────────────┴───────────────────┘
```

**Velocidades de reproducción disponibles:** `x1` (tiempo real) · `x4` · `x16` · `x64`

---

## ⚡ Simulación ERS 2026

El proyecto incluye un **simulador heurístico de Energy Recovery System** diseñado para los reglamentos de 2026:

```
Despliegue MGU-K  →  350 kW cuando Throttle ≥ 95% y Velocidad ≥ 200 kph
Regeneración      →  Frenada (350 kW) + Térmico (40 kW) + Rolling + MGU-H
Capacidad batería →  4,000 kJ
```

**Superclipping detectado cuando:**
> SOC ≤ 5% con el piloto en pleno throttle → el MGU-K invierte dirección y carga a ~80% de regeneración máxima, sacrificando potencia de despliegue.

El indicador `SUPERCLIP` aparece en el HUD y queda registrado en el historial de estilo de conducción por vuelta.

---

## 📊 Sesiones soportadas

| Sesión | Modo | Tiempo / Countdown |
|--------|------|--------------------|
| FP1 / FP2 / FP3 | Práctica libre | 60 min, ordenado por mejor vuelta |
| Q | Clasificación | Q1 18' · Q2 15' · Q3 12' (15' en 2026) |
| SQ | Sprint Qualifying | Auto-detectado |
| S | Sprint | Distancia reducida |
| R | Carrera | Vueltas totales, gaps, estrategia |

La detección de fases Q1/Q2/Q3 es automática mediante análisis de gaps entre vueltas. La bandera roja pausa el countdown de clasificación correctamente.

---

## 🧰 Stack técnico

| Componente | Librería | Uso |
|---|---|---|
| UI / Rendering | `dearpygui` | Toda la interfaz gráfica, drawlists, tablas |
| Datos F1 | `fastf1` | Carga de sesiones, telemetría, vueltas |
| Procesamiento | `pandas` + `numpy` | Manipulación de DataFrames de telemetría |
| Threading | `threading` + `queue` | Worker de snapshots sin bloquear el render |
| Caché | FastF1 Cache | Persistencia local en `~/.f1_cache` |

---

## 📄 Fuentes de datos

- **FastF1** — API principal para telemetría, timing y datos de sesión
- **F1 Data Channel** — Referencia para validación de datos de broadcast
- **Telemetría de transmisión F1** — Fuente base de streams de datos

---

<div align="center">

Desarrollado con ❤️ y mucho café por **Pardiñaz**

*Para la comunidad de makers y fanáticos de los datos de F1*

⭐ Si el proyecto te pareció interesante, ¡dale una estrella!

</div>
