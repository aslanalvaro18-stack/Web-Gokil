from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AccessStatus = Literal['trusted', 'untrusted', 'unknown']


class TelemetryCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'uptime_seconds': 7250, 'status': 'running'}],
    })

    uptime_seconds: int = Field(ge=0)
    status: str = Field(default='unknown', min_length=1, max_length=40)


class TelemetryRecord(TelemetryCreate):
    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            'examples': [{
                'id': 1,
                'uptime_seconds': 7250,
                'status': 'running',
                'recorded_at': '2026-11-07T09:30:00+00:00',
            }],
        },
    )

    id: int
    recorded_at: str


class SensorReadingCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{
            'sensor_id': 'light-1',
            'sensor_type': 'light',
            'value': 360,
            'unit': 'lux',
        }],
    })

    sensor_id: str = Field(min_length=1, max_length=80)
    sensor_type: str = Field(min_length=1, max_length=80)
    value: float = Field(allow_inf_nan=False)
    unit: str | None = Field(default=None, max_length=24)


class SensorReadingRecord(SensorReadingCreate):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{
            'id': 1,
            'device_id': 'core-1',
            'sensor_id': 'light-1',
            'sensor_type': 'light',
            'value': 360,
            'unit': 'lux',
            'recorded_at': '2026-11-07T09:30:00+00:00',
        }],
    })

    id: int
    device_id: str
    recorded_at: str


class ScratchVariableCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'value': 42}],
    })

    value: str | int | float | bool | None


class ScratchVariableRecord(ScratchVariableCreate):
    name: str
    updated_at: str


class DeviceStatusUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'device_id': 'core-1', 'status': 'hidup'}],
    })

    device_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    status: Literal['hidup', 'mati']


class DeviceCoreStatusUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'status': 'hidup'}],
    })

    status: Literal['hidup', 'mati'] = Field(
        description='Kondisi Core Unit: hidup atau mati.'
    )


class DeviceCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'device_id': 'pompa-air', 'name': 'Pompa Air'}],
    })

    device_id: str = Field(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    name: str = Field(min_length=1, max_length=80)


class DeviceNameUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class DeviceComponentCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{
            'component_id': 'motor-elevator-1',
            'name': 'Motor elevator',
            'component_type': 'dc_motor',
            'estimated_count': None,
            'device_id': None,
            'confirmed': False,
            'enabled': False,
            'command_values': [],
            'safe_value': None,
        }],
    })

    component_id: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    name: str = Field(min_length=1, max_length=100)
    component_type: str = Field(min_length=1, max_length=60)
    estimated_count: str | None = Field(default=None, max_length=32)
    device_id: str | None = Field(default=None, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    confirmed: bool = False
    enabled: bool = False
    command_values: list[str] = Field(default_factory=list, max_length=32)
    safe_value: str | None = Field(default=None, max_length=40)


class DeviceComponentRecord(DeviceComponentCreate):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{
            'component_id': 'motor-elevator-1',
            'name': 'Motor elevator',
            'component_type': 'dc_motor',
            'estimated_count': None,
            'device_id': None,
            'confirmed': False,
            'enabled': False,
            'command_values': [],
            'safe_value': None,
            'current_value': None,
            'target_value': None,
            'updated_at': '2026-11-07T09:30:00+00:00',
            'reported_condition': None,
            'condition_reported_at': None,
        }],
    })

    current_value: str | None
    target_value: str | None
    updated_at: str
    reported_condition: str | None = None
    condition_reported_at: str | None = None


class ComponentConditionReport(BaseModel):
    id: int
    device_id: str
    component_id: str
    condition: str
    reported_at: str


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
    model_config = ConfigDict(json_schema_extra={'examples': [{'mode': 'manual'}]})

    mode: Literal['manual', 'auto']


class EmergencyUpdate(BaseModel):
    model_config = ConfigDict(json_schema_extra={'examples': [{'enabled': True}]})

    enabled: bool


class ActuatorCommandCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'position': 'closed'}],
    })

    position: str = Field(min_length=1, max_length=40)


class DryingStart(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'target_seconds': 3600}],
    })

    target_seconds: int = Field(ge=60, le=86400)


class CommandAcknowledgement(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{'actual_position': 'closed', 'success': True, 'detail': ''}],
    })

    actual_position: str = Field(min_length=1, max_length=40)
    success: bool = True
    detail: str = Field(default='', max_length=240)


class OperationEventCreate(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        'examples': [{
            'event_type': 'sensor_checked',
            'value': 'light-1',
            'duration_seconds': None,
            'detail': {},
        }],
    })

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


class EventFlagCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    mode: Literal['once', 'ack'] = 'once'


class EventFlagUpdate(BaseModel):
    active: bool | None = None
    mode: Literal['once', 'ack'] | None = None


class EventFlagRecord(BaseModel):
    name: str
    active: bool
    mode: Literal['once', 'ack']
    updated_at: str


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