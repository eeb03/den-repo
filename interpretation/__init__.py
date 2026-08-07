"""
Subsurface anomaly interpretation layer: groups already-computed anomaly
evidence (from preprocessing/spatial_grid.py::preprocess_trace_local_anomaly)
into spatially/depth-coherent candidate regions and characterizes them with
neutral, evidence-traceable descriptors.

This package NEVER claims a candidate is a confirmed physical object (pipe,
void, cable, ...); it only describes geometry and statistics of the
underlying signal. See anomaly_candidates.py's module docstring for the
full scientific framing.
"""
