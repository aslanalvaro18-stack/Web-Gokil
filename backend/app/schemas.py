from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccessStatus = Literal['trusted', 'untrusted', 'unknown']


class TelemetryCreate(BaseModel):
    uptime_seconds: int = Field(ge=0)
    status: str = Field(default='unknown', min_length=1, max_length=40)


class TelemetryRecord(TelemetryCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    recorded_at: str


class SensorReadingCreate(BaseModel):
    sensor_id: str = Field(min_length=1, max_length=80)
    sensor_type: str = Field(min_length=1, max_length=80)
    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=24)


class SensorReadingRecord(SensorReadingCreate):
    id: int
    device_id: str
    recorded_at: str


class DeviceStatusUpdate(BaseModel):
    device_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    status: Literal['hidup', 'mati']


class DeviceCreate(BaseModel):
    device_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    name: str = Field(min_length=1, max_length=80)


class DeviceStatusRecord(BaseModel):
    device_id: str
    name: str
    status: Literal['belum_terhubung', 'hidup', 'mati']
    last_seen: str | None
    connection_status: Literal['never_seen', 'online', 'stale']
    age_seconds: int | None


class PredictionRecord(BaseModel):
    id: int
    class_name: str
    confidence: float = Field(ge=0, le=1)
    captured_at: str
    access_status: AccessStatus


class AccessResponse(BaseModel):
    prediction_id: int | None
    identity: str | None
    access_status: AccessStatus
    is_trusted: bool
    confidence: float | None = Field(default=None, ge=0, le=1)
    captured_at: str | None
    expires_at: str | None
    message: str


class ModeUpdate(BaseModel):
    mode: Literal['manual', 'auto']


class EmergencyUpdate(BaseModel):
    enabled: bool


class ActuatorCommandCreate(BaseModel):
    position: str = Field(min_length=1, max_length=40)


class DryingStart(BaseModel):
    target_seconds: int = Field(ge=60, le=86400)


class CommandAcknowledgement(BaseModel):
    actual_position: str = Field(min_length=1, max_length=40)
    success: bool = True
    detail: str = Field(default='', max_length=240)


class OperationEventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    value: str | None = Field(default=None, max_length=160)
    duration_seconds: int | None = Field(default=None, ge=0)
    detail: dict = Field(default_factory=dict)


class OperationEvent(BaseModel):
    id: int
    event_type: str
    source: str
    actuator: str | None
    value: str | None
    duration_seconds: int | None
    detail: dict
    occurred_at: str


class ControlSnapshot(BaseModel):
    mode: Literal['manual', 'auto']
    emergency_mode: bool
    drying_started_at: str | None
    drying_target_seconds: int | None
    drying_elapsed_seconds: int
    updated_at: str
    actuators: list[dict]
    pending_commands: list[dict]


class EmergencyStatus(BaseModel):
    emergency_mode: Literal['on', 'off']


class DashboardResponse(BaseModel):
    telemetry: TelemetryRecord | None
    prediction: PredictionRecord | None
    access: AccessResponse
    control: ControlSnapshot
    events: list[OperationEvent]