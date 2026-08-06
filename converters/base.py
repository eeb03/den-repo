from abc import ABC, abstractmethod
from pathlib import Path

from schemas.subterra_record import SubterraRecord, SensorType


class BaseConverter(ABC):
    """Every format converter takes a raw file and yields Universal Subterra Records."""

    format_name: str = "base"
    supported_extensions: tuple[str, ...] = ()

    @abstractmethod
    def convert(
        self, path: str | Path, dataset_id: str, sensor_type: SensorType
    ) -> list[SubterraRecord]:
        raise NotImplementedError

    def can_handle(self, path: str | Path) -> bool:
        return Path(path).suffix.lower() in self.supported_extensions


class MissingDependencyError(RuntimeError):
    """Raised when an optional format library (segyio, laspy, rasterio, obspy) isn't installed."""
    pass
