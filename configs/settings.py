"""
Centralized configuration for the Subterra Data Platform.
Prefer configuration over hardcoded values, per PRD engineering principles.
"""
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str = "sqlite:///./subterra_dev.db"

    # Storage
    data_root: Path = Path("./datasets")
    storage_backend: str = "local"
    s3_bucket: str = ""
    s3_endpoint: str = ""
    s3_access_key: str = ""
    s3_secret_key: str = ""

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_env: str = "development"

    # Logging
    log_level: str = "INFO"

    # Sensor fusion
    fusion_spatial_tolerance_m: float = 25.0  # max distance to consider "same location"
    fusion_time_tolerance_days: int = 3650    # loose by default; geophysical data is slow-changing

    # External dataset sources
    opentopography_api_key: str = ""  # https://opentopography.org/blog/introducing-api-keys...
    zenodo_access_token: str = ""     # optional; raises anon rate limits (25->100 results/page)

    @property
    def raw_dir(self) -> Path:
        return self.data_root / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_root / "processed"

    @property
    def downloads_dir(self) -> Path:
        return self.data_root / "downloads"

    @property
    def metadata_dir(self) -> Path:
        return self.data_root / "metadata"

    @property
    def ground_truth_dir(self) -> Path:
        return self.data_root / "ground_truth"

    @property
    def benchmarks_dir(self) -> Path:
        return self.data_root / "benchmarks"


settings = Settings()

for _dir in [
    settings.raw_dir,
    settings.processed_dir,
    settings.downloads_dir,
    settings.metadata_dir,
    settings.ground_truth_dir,
    settings.benchmarks_dir,
]:
    _dir.mkdir(parents=True, exist_ok=True)
