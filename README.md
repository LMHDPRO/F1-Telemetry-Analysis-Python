# F1-Telemetry-Analysis-Python
Telemetry visualization generated using a custom Python tool developed to analyze Formula 1 race data. The system reconstructs sessions using telemetry streams to display car position, speed, lap pace and energy-related driving patterns.

@Brief: Development of a Python application to visualize and analyze telemetry data from Formula 1 races. The project aims to better understand how on-track data is processed and how power unit energy management increasingly influences overall car performance.

Recent concepts such as superclipping, associated with electrical energy generation from thermal energy in the new generation of F1 engines, are still being analyzed even among commentators. Using available telemetry, the project explores ways to infer how energy is managed throughout a lap, identifying regeneration and deployment effects that influence acceleration and overall vehicle behavior.

The system allows full session replay on a circuit map, displaying car positions, speed, lap pace, and driver comparisons.

The system integrates:
– Telemetry processing in Python
– Car visualization over circuit maps
– Lap and sector comparison
– Heuristic analysis of energy deployment, lift & coast, and superclipping
– Data integration using FastF1
– Data processing with pandas and numpy
– Graphical interface developed with Tkinter

Data sources: Formula 1 broadcast / F1 Data Channel / FastF1
