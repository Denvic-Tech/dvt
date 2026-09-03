from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src import enums

from ..domain import SettingsModel, SettingsRegistry, TypedAppSettings, setting


class OOMGuardConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: enums.OOMGuardMode = Field(default=enums.OOMGuardMode.DISABLED)
    host_threshold_percent: float | None = Field(default=None)
    worker_threshold_type: enums.OOMWorkerThresholdType | None = Field(default=None)
    worker_threshold_percent: float | None = Field(default=None)
    worker_threshold_mb: int | None = Field(default=None)

    @model_validator(mode="after")
    def validate_mode_settings(self) -> "OOMGuardConfig":
        if self.mode == enums.OOMGuardMode.DISABLED:
            return self
        if self.mode == enums.OOMGuardMode.HOST_PRESSURE:
            if self.host_threshold_percent is None:
                raise ValueError("host_threshold_percent is required for HOST_PRESSURE mode")
            if not 0 < self.host_threshold_percent <= 100:
                raise ValueError("host_threshold_percent must be within (0, 100]")
            return self
        if self.mode == enums.OOMGuardMode.WORKER_THRESHOLD:
            if self.worker_threshold_type is None:
                raise ValueError("worker_threshold_type is required for WORKER_THRESHOLD mode")
            if self.worker_threshold_type == enums.OOMWorkerThresholdType.PERCENT:
                if self.worker_threshold_percent is None:
                    raise ValueError(
                        "worker_threshold_percent is required for PERCENT threshold type"
                    )
                if not 0 < self.worker_threshold_percent <= 100:
                    raise ValueError("worker_threshold_percent must be within (0, 100]")
                if self.worker_threshold_mb is not None:
                    raise ValueError(
                        "worker_threshold_mb must not be set for PERCENT threshold type"
                    )
                return self
            if self.worker_threshold_type == enums.OOMWorkerThresholdType.ABSOLUTE_MB:
                if self.worker_threshold_mb is None:
                    raise ValueError(
                        "worker_threshold_mb is required for ABSOLUTE_MB threshold type"
                    )
                if self.worker_threshold_mb <= 0:
                    raise ValueError("worker_threshold_mb must be greater than zero")
                if self.worker_threshold_percent is not None:
                    raise ValueError(
                        "worker_threshold_percent must not be set for ABSOLUTE_MB threshold type"
                    )
                return self
        raise ValueError(f"Unsupported OOM guard mode: {self.mode}")


class DateTimePrecision(StrEnum):
    NANOSECONDS = "Nanoseconds"
    MICROSECONDS = "Microseconds"
    SECONDS = "Seconds"


class DccSettings(SettingsModel):
    connector_id: str | None = setting(
        default=None,
        description="Connector ID",
        setup_label="Connector ID",
        runtime_editable=False,
    )
    url: str | None = setting(
        default=None,
        description="DCC URL",
        setup_label="DCC URL",
    )
    username: str | None = setting(
        default=None,
        description="DCC User for auth",
        setup_label="DCC User",
    )
    password: str | None = setting(
        default=None,
        description="DCC Password for auth",
        secret=True,
        setup_label="DCC Password",
        setup_type="password",
    )


class RuntimeSettings(SettingsModel):
    datetime_precision: DateTimePrecision = setting(
        default_factory=lambda: DateTimePrecision.MICROSECONDS,
        description="DateTime precision in Dask",
    )
    oom_guard: OOMGuardConfig = setting(
        default_factory=OOMGuardConfig,
        description="OOM guard policy settings configurable from UI",
    )


class DVTAppSettings(TypedAppSettings):
    dcc: DccSettings
    runtime: RuntimeSettings


class DVTApplicationSettings(SettingsRegistry[DVTAppSettings]):
    settings_model = DVTAppSettings
