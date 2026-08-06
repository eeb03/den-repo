"""
SEG-Y converter for Subterra.

Converts SEG-Y files (GPR or seismic) into Universal Subterra Records.

For normal SEG-Y files, coordinates are taken from SourceX/SourceY when
they fall within valid WGS84 lon/lat range. For the INGV-UNISA GPR files,
SourceX/SourceY are projected (UTM-scale) values -- nowhere near +/-180/
+/-90 -- so they're left as an unset (0.0, 0.0) placeholder; the
acquisition-track mapping supplied separately by the ingestion layer
(ingestion/kmz_georeference.py, applied per-trace in
api/routes/datasets.py::ingest_zip_from_url) overwrites it.

GPR two-way travel time is commonly written into the SEG-Y binary header's
"microseconds" sample-interval field pre-scaled by 1000 so it round-trips
as the correct nanosecond value (confirmed on this dataset: header
Interval=293 -> segyio sample step 0.293, i.e. a 0.293 ns interval and a
~141 ns two-way window -- physically sane for a shallow GPR survey; taken
as literal microseconds it would imply an absurd multi-km penetration
depth). `depth` is derived from that time axis via a standard constant-
velocity conversion, not the raw time value itself.
"""

from pathlib import Path

from converters.base import BaseConverter, MissingDependencyError
from schemas.subterra_record import SubterraRecord, SensorType


# Typical near-surface soil GPR velocity (relative permittivity ~9);
# override with converter_kwargs={"velocity_m_per_ns": ...} when a
# site-specific velocity (e.g. from a CMP survey) is known.
DEFAULT_GPR_VELOCITY_M_PER_NS = 0.1


class SEGYConverter(BaseConverter):
    format_name = "segy"
    supported_extensions = (".sgy", ".segy")

    def can_convert(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_extensions

    def convert(
        self,
        path: Path,
        dataset_id: str,
        sensor_type: SensorType,
        velocity_m_per_ns: float = DEFAULT_GPR_VELOCITY_M_PER_NS,
        **kwargs,
    ) -> list[SubterraRecord]:

        try:
            import segyio
        except ImportError as e:
            raise MissingDependencyError(
                "segyio is required to convert SEG-Y files. "
                "Install with: pip install segyio"
            ) from e

        records = []

        with segyio.open(str(path), "r", ignore_geometry=True) as f:

            trace_count = f.tracecount
            samples = list(f.samples)

            for trace_idx in range(trace_count):

                trace = f.trace[trace_idx]
                header = f.header[trace_idx]

                # SEG-Y coordinate scalar.
                scalar = header.get(
                    segyio.TraceField.SourceGroupScalar,
                    1,
                ) or 1

                raw_x = header.get(
                    segyio.TraceField.SourceX,
                    0,
                )

                raw_y = header.get(
                    segyio.TraceField.SourceY,
                    0,
                )

                try:
                    scalar = float(scalar)

                    if scalar < 0:
                        scale = 1.0 / abs(scalar)
                    else:
                        scale = scalar

                    x = float(raw_x) * scale
                    y = float(raw_y) * scale

                except Exception:
                    x = 0.0
                    y = 0.0

                # Only trust these as real WGS84 lon/lat when they're
                # actually in range -- INGV-UNISA's SourceX/SourceY are
                # projected (UTM-scale) values. Out-of-range/zero coords
                # are left as a (0.0, 0.0) placeholder for the KMZ-based
                # georeferencing fallback (applied per-trace, downstream)
                # to overwrite.
                if -90.0 <= y <= 90.0 and -180.0 <= x <= 180.0:
                    latitude, longitude = y, x
                else:
                    latitude, longitude = 0.0, 0.0

                sample_interval = f.bin.get(segyio.BinField.Interval, None)

                # Store the complete trace as individual samples.
                #
                # This preserves the actual GPR waveform instead of
                # collapsing the entire trace into a single value.
                for sample_idx, value in enumerate(trace):

                    two_way_time_ns = float(samples[sample_idx])
                    depth = (two_way_time_ns * velocity_m_per_ns) / 2.0

                    record = SubterraRecord(
                        dataset_id=dataset_id,
                        latitude=latitude,
                        longitude=longitude,
                        elevation=None,
                        depth=depth,
                        signal=[float(value)],
                        sensor_type=sensor_type,
                        ground_truth="none",
                        metadata={
                            "source_file": path.name,
                            "trace_index": trace_idx,
                            "sample_index": sample_idx,
                            "two_way_time_ns": two_way_time_ns,
                            "velocity_m_per_ns": velocity_m_per_ns,
                            "sample_interval": sample_interval,
                            "segy_x": x,
                            "segy_y": y,
                            "trace_count": trace_count,
                            "sample_count": len(samples),
                        },
                    )

                    records.append(record)

        return records
