import asyncio
import json
import logging
import math
import os
from importlib.util import find_spec
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Literal, Protocol

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, StreamingResponse

from app import database
from app.schemas import (
    ActuatorCommandCreate,
    AccessResponse,
    CommandAcknowledgement,
    ControlSnapshot,
    DashboardResponse,
    DeviceCreate,
    DeviceStatusRecord,
    DeviceStatusUpdate,
    DryingStart,
    EmergencyStatus,
    EmergencyUpdate,
    ModeUpdate,
    OperationEvent,
    OperationEventCreate,
    PredictionRecord,
    TelemetryCreate,
    TelemetryRecord,
)
from app.services.automation import run_automation_cycle
from app.services.local_camera import LocalCameraService
from app.services.teachable_machine import (
    InvalidImageError,
    ModelUnavailableError,
    TeachableMachineClassifier,
)
from app.services.weather import WeatherUnavailableError, get_pakem_weather

MAX_IMAGE_BYTES = 10 * 1024 * 1024
BACKEND_DIR = Path(__file__).resolve().parents[1]
LOGGER = logging.getLogger(__name__)


class Classifier(Protocol):
    def predict(self, image_bytes: bytes) -> tuple[str, float]: ...


def create_app(
    database_path: str | Path | None = None,
    predictor: Classifier | None = None,
    weather_provider: Callable[[], dict] | None = None,
    camera_autostart: bool | None = None,
) -> FastAPI:
    resolved_database_path = Path(
        database_path or os.getenv('AGRO_DATABASE_PATH', BACKEND_DIR / 'data/agro_sembada.db')
    )
    default_model_path = BACKEND_DIR / 'models/teachable_machine/keras_model.h5'
    default_labels_path = BACKEND_DIR / 'models/teachable_machine/labels.txt'
    project_model_path = BACKEND_DIR.parent / 'keras_model.h5'
    project_labels_path = BACKEND_DIR.parent / 'labels.txt'
    model_path = Path(os.getenv('AGRO_MODEL_PATH', default_model_path))
    labels_path = Path(os.getenv('AGRO_LABELS_PATH', default_labels_path))
    if not os.getenv('AGRO_MODEL_PATH') and not model_path.is_file() and project_model_path.is_file():
        model_path = project_model_path
    if not os.getenv('AGRO_LABELS_PATH') and not labels_path.is_file() and project_labels_path.is_file():
        labels_path = project_labels_path
    trusted_labels = {
        label.strip().casefold()
        for label in os.getenv('AGRO_TRUSTED_LABELS', 'owner,trusted,terpercaya').split(',')
        if label.strip()
    }
    minimum_confidence = float(os.getenv('AGRO_MIN_CONFIDENCE', '0.85'))
    access_max_age = int(os.getenv('AGRO_ACCESS_MAX_AGE_SECONDS', '15'))
    automation_interval = max(5, int(os.getenv('AGRO_AUTOMATION_INTERVAL_SECONDS', '15')))
    should_autostart_camera = camera_autostart if camera_autostart is not None else (
        os.getenv('AGRO_CAMERA_AUTOSTART', '0').strip().casefold() in {'1', 'true', 'yes', 'on'}
    )
    try:
        safe_positions = json.loads(os.getenv('AGRO_SAFE_POSITIONS', '{"roof":"closed"}'))
        configured_positions = json.loads(
            os.getenv('AGRO_ACTUATOR_POSITIONS', '{"roof":["open","closed"]}')
        )
    except json.JSONDecodeError as error:
        raise ValueError('Konfigurasi posisi aktuator harus berupa JSON valid.') from error
    if not isinstance(safe_positions, dict) or not safe_positions or any(
        not isinstance(name, str)
        or not name.strip()
        or not isinstance(position, str)
        or not position.strip()
        for name, position in safe_positions.items()
    ):
        raise ValueError('AGRO_SAFE_POSITIONS harus berisi nama aktuator dan posisi aman.')
    if not isinstance(configured_positions, dict) or any(
        not isinstance(name, str)
        or not isinstance(positions, list)
        or not positions
        or any(not isinstance(position, str) or not position.strip() for position in positions)
        for name, positions in configured_positions.items()
    ):
        raise ValueError('AGRO_ACTUATOR_POSITIONS harus memetakan nama aktuator ke daftar posisi.')
    actuator_positions = {
        name: set(positions) for name, positions in configured_positions.items()
    }
    camera_service = LocalCameraService()
    for name, safe_position in safe_positions.items():
        actuator_positions.setdefault(name, {safe_position})
        if safe_position not in actuator_positions[name]:
            raise ValueError(f'Posisi aman {safe_position} tidak diizinkan untuk aktuator {name}.')

    async def automation_loop() -> None:
        while True:
            await asyncio.sleep(automation_interval)
            try:
                await asyncio.to_thread(
                    run_automation_cycle,
                    resolved_database_path,
                    app.state.weather_provider,
                )
            except Exception:
                LOGGER.exception('Automation cycle failed')

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database.initialize_database(resolved_database_path)
        database.configure_safe_positions(resolved_database_path, safe_positions)
        if isinstance(app.state.predictor, TeachableMachineClassifier) and app.state.prediction_model_ready:
            try:
                await asyncio.to_thread(app.state.predictor.load)
            except ModelUnavailableError as error:
                app.state.prediction_model_ready = False
                app.state.prediction_model_error = str(error)
                LOGGER.error('Prediction model unavailable: %s', error)
        if should_autostart_camera:
            camera_service.start()
        automation_task = asyncio.create_task(automation_loop())
        try:
            yield
        finally:
            camera_service.stop()
            automation_task.cancel()
            with suppress(asyncio.CancelledError):
                await automation_task

    app = FastAPI(
        title='AGRO-SEMBADA API',
        description='API telemetri dan prediksi visual untuk dashboard AGRO-SEMBADA.',
        version='1.0.0',
        lifespan=lifespan,
    )
    app.state.database_path = resolved_database_path
    app.state.predictor = predictor or TeachableMachineClassifier(model_path, labels_path)
    app.state.weather_provider = weather_provider or get_pakem_weather
    app.state.camera_service = camera_service
    app.state.prediction_model_ready = predictor is not None or (
        model_path.is_file()
        and labels_path.is_file()
        and find_spec('tensorflow') is not None
        and find_spec('tf_keras') is not None
    )
    app.state.prediction_model_error = (
        None if app.state.prediction_model_ready else 'Model, labels, atau TensorFlow belum tersedia.'
    )

    def camera_status_response() -> dict:
        return {
            **camera_service.get_status(),
            'prediction_ready': app.state.prediction_model_ready,
            'prediction_message': app.state.prediction_model_error,
        }

    def access_response(prediction: dict | None) -> dict:
        if prediction is None:
            return {
                'prediction_id': None,
                'identity': None,
                'access_status': 'unknown',
                'is_trusted': False,
                'confidence': None,
                'captured_at': None,
                'expires_at': None,
                'message': 'Belum ada hasil identifikasi.',
            }

        captured_at = datetime.fromisoformat(prediction['captured_at'])
        if captured_at.tzinfo is None:
            captured_at = captured_at.replace(tzinfo=timezone.utc)
        expires_at = captured_at + timedelta(seconds=access_max_age)
        is_expired = datetime.now(timezone.utc) >= expires_at
        status = 'unknown' if is_expired else prediction['access_status']
        messages = {
            'trusted': 'Identitas cocok dengan daftar yang diizinkan.',
            'untrusted': 'Identitas tidak termasuk daftar yang diizinkan.',
            'unknown': 'Keyakinan model rendah atau hasil sudah kedaluwarsa.',
        }
        return {
            'prediction_id': prediction['id'],
            'identity': prediction['class_name'],
            'access_status': status,
            'is_trusted': status == 'trusted',
            'confidence': prediction['confidence'],
            'captured_at': prediction['captured_at'],
            'expires_at': expires_at.isoformat(timespec='seconds'),
            'message': messages[status],
        }

    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            'AGRO_CORS_ORIGINS', 'http://localhost:5173,http://127.0.0.1:5173'
        ).split(',')
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=['GET', 'POST'],
        allow_headers=['Content-Type'],
    )

    @app.get('/api/health', response_class=PlainTextResponse)
    def health() -> str:
        return 'ok'

    @app.get('/api/camera/status')
    def camera_status() -> dict:
        return camera_status_response()

    @app.post('/api/camera/rescan')
    def rescan_cameras() -> dict:
        camera_service.rescan()
        return camera_status_response()

    @app.post('/api/camera/stop')
    def stop_camera() -> dict:
        camera_service.stop()
        return camera_status_response()

    @app.get('/api/camera/stream')
    async def camera_stream() -> StreamingResponse:
        async def frames():
            while True:
                frame = camera_service.latest_frame()
                if frame is not None:
                    yield b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n'
                await asyncio.sleep(0.05)

        return StreamingResponse(
            frames(),
            media_type='multipart/x-mixed-replace; boundary=frame',
            headers={'Cache-Control': 'no-cache'},
        )

    @app.post('/api/telemetry', response_model=TelemetryRecord)
    def create_telemetry(
        payload: TelemetryCreate | None = None,
        uptime_seconds: int | None = Query(default=None, ge=0),
        status: str = Query(default='unknown', min_length=1, max_length=40),
    ) -> dict:
        if payload is None and uptime_seconds is None:
            raise HTTPException(
                status_code=422,
                detail='Kirim JSON telemetry atau parameter uptime_seconds di URL.',
            )
        uptime = payload.uptime_seconds if payload else uptime_seconds
        device_status = payload.status if payload else status
        record = database.save_telemetry(
            app.state.database_path, uptime, device_status
        )
        database.add_operation_event(
            app.state.database_path,
            'telemetry_received',
            'device',
            value=device_status,
            detail={'uptime_seconds': uptime},
        )
        return record

    @app.get('/api/telemetry', response_model=list[TelemetryRecord])
    def read_telemetry(limit: int = Query(default=20, ge=1, le=100)) -> list[dict]:
        return database.list_telemetry(app.state.database_path, limit)

    @app.get('/api/devices', response_model=list[DeviceStatusRecord])
    def read_device_status() -> list[dict]:
        return database.list_device_status(app.state.database_path)

    @app.post('/api/devices', response_model=DeviceStatusRecord, status_code=201)
    def create_device(payload: DeviceCreate) -> dict:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail='Nama alat tidak boleh kosong.')
        record = database.create_device(app.state.database_path, payload.device_id, name)
        if record is None:
            raise HTTPException(status_code=409, detail='ID alat sudah terdaftar.')
        return record

    @app.post('/api/devices/status', response_model=DeviceStatusRecord)
    def update_device_status(
        payload: DeviceStatusUpdate | None = None,
        device_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=40,
            pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
        ),
        status: Literal['hidup', 'mati'] | None = Query(default=None),
    ) -> dict:
        if payload is not None:
            resolved_device_id = payload.device_id
            resolved_status = payload.status
        elif device_id is not None and status is not None:
            resolved_device_id = device_id
            resolved_status = status
        else:
            raise HTTPException(
                status_code=422,
                detail='Kirim device_id dan status melalui query URL atau JSON body.',
            )

        record = database.update_device_status(
            app.state.database_path, resolved_device_id, resolved_status
        )
        if record is None:
            raise HTTPException(
                status_code=404, detail='ID alat belum terdaftar.'
            )
        database.add_operation_event(
            app.state.database_path,
            'device_status_updated',
            resolved_device_id,
            value=resolved_status,
        )
        return record

    @app.post('/api/predictions', response_model=PredictionRecord)
    async def create_prediction(
        image: UploadFile = File(...),
    ) -> dict:
        if image.content_type and not image.content_type.startswith('image/'):
            raise HTTPException(status_code=415, detail='File harus berupa gambar.')
        image_bytes = await image.read(MAX_IMAGE_BYTES + 1)
        if len(image_bytes) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail='Ukuran gambar maksimal 10 MB.')
        if not image_bytes:
            raise HTTPException(status_code=422, detail='File gambar kosong.')

        try:
            class_name, confidence = app.state.predictor.predict(image_bytes)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ModelUnavailableError('Model menghasilkan nilai confidence yang tidak valid.')
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ModelUnavailableError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error

        if confidence < minimum_confidence:
            access_status = 'unknown'
        elif class_name.strip().casefold() in trusted_labels:
            access_status = 'trusted'
        else:
            access_status = 'untrusted'

        prediction = database.save_prediction(
            app.state.database_path, class_name, confidence, access_status
        )
        database.add_operation_event(
            app.state.database_path,
            'face_identified',
            'keras',
            value=access_status,
            detail={'class_name': class_name, 'confidence': confidence},
        )
        return prediction

    @app.get('/api/predictions/latest', response_model=PredictionRecord | None)
    def read_latest_prediction() -> dict | None:
        return database.latest_prediction(app.state.database_path)

    @app.get('/api/predictions', response_class=PlainTextResponse)
    def read_prediction_name() -> str:
        prediction = database.latest_prediction(app.state.database_path)
        if prediction is None or access_response(prediction)['access_status'] == 'unknown':
            return 'unknown'
        return prediction['class_name']

    @app.get('/api/access/latest', response_model=AccessResponse)
    def read_latest_access() -> dict:
        return access_response(database.latest_prediction(app.state.database_path))

    @app.get('/api/dashboard', response_model=DashboardResponse)
    def read_dashboard() -> dict:
        data = database.get_dashboard_data(app.state.database_path)
        data['access'] = access_response(data['prediction'])
        data['control'] = database.get_control_snapshot(app.state.database_path)
        data['events'] = database.list_operation_events(app.state.database_path, 20)
        return data

    @app.get('/api/control/state', response_model=ControlSnapshot)
    def read_control_state() -> dict:
        return database.get_control_snapshot(app.state.database_path)

    @app.post('/api/control/mode', response_model=ControlSnapshot)
    def update_control_mode(
        payload: ModeUpdate | None = None,
        mode: Literal['manual', 'auto'] | None = Query(default=None),
    ) -> dict:
        selected_mode = payload.mode if payload else mode
        if selected_mode is None:
            raise HTTPException(status_code=422, detail='Tentukan mode=manual atau mode=auto.')
        try:
            state = database.set_control_mode(
                app.state.database_path, selected_mode
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if selected_mode == 'auto':
            run_automation_cycle(app.state.database_path, app.state.weather_provider)
            state = database.get_control_snapshot(app.state.database_path)
        return state

    @app.post('/api/control/actuators/{actuator}', response_model=dict)
    def command_actuator(
        actuator: str,
        payload: ActuatorCommandCreate | None = None,
        position: str | None = Query(default=None, min_length=1, max_length=40),
    ) -> dict:
        selected_position = payload.position if payload else position
        if selected_position is None:
            raise HTTPException(status_code=422, detail='Tentukan position di URL atau JSON body.')
        state = database.get_control_snapshot(app.state.database_path)
        if state['emergency_mode']:
            raise HTTPException(status_code=409, detail='Emergency aktif; command manual ditolak.')
        if state['mode'] != 'manual':
            raise HTTPException(status_code=409, detail='Pilih mode manual sebelum mengubah aktuator.')
        if actuator not in actuator_positions or selected_position not in actuator_positions[actuator]:
            raise HTTPException(status_code=422, detail='Posisi aktuator tidak dikonfigurasi.')
        try:
            return database.queue_actuator_command(
                app.state.database_path, actuator, selected_position, 'manual'
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error

    @app.post('/api/drying/start', response_model=ControlSnapshot)
    def start_drying(
        payload: DryingStart | None = None,
        target_seconds: int | None = Query(default=None, ge=60, le=86400),
    ) -> dict:
        duration = payload.target_seconds if payload else target_seconds
        if duration is None:
            raise HTTPException(status_code=422, detail='Tentukan target_seconds di URL atau JSON body.')
        state = database.get_control_snapshot(app.state.database_path)
        if state['emergency_mode']:
            raise HTTPException(status_code=409, detail='Emergency aktif; sesi jemur tidak dapat dimulai.')
        try:
            state = database.start_drying_session(
                app.state.database_path, duration, 'dashboard'
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if state['mode'] == 'auto':
            run_automation_cycle(app.state.database_path, app.state.weather_provider)
            state = database.get_control_snapshot(app.state.database_path)
        return state

    @app.post('/api/drying/stop', response_model=ControlSnapshot)
    def stop_drying() -> dict:
        state = database.stop_drying_session(app.state.database_path, 'dashboard')
        if state is None:
            raise HTTPException(status_code=409, detail='Tidak ada sesi jemur yang berjalan.')
        if state['mode'] == 'auto' and not state['emergency_mode']:
            run_automation_cycle(app.state.database_path, app.state.weather_provider)
            state = database.get_control_snapshot(app.state.database_path)
        return state

    @app.get('/api/events', response_model=list[OperationEvent])
    def read_events(limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return database.list_operation_events(app.state.database_path, limit)

    @app.post('/api/events', response_model=OperationEvent)
    def create_event(
        payload: OperationEventCreate | None = None,
        event_type: str | None = Query(default=None, min_length=1, max_length=80),
        value: str | None = Query(default=None, max_length=160),
        duration_seconds: int | None = Query(default=None, ge=0),
        detail: str | None = Query(default=None),
    ) -> dict:
        if payload is not None:
            event = payload
        else:
            if event_type is None:
                raise HTTPException(status_code=422, detail='Tentukan event_type di URL atau JSON body.')
            try:
                detail_value = json.loads(detail) if detail else {}
            except json.JSONDecodeError as error:
                raise HTTPException(status_code=422, detail='Parameter detail harus JSON object.') from error
            if not isinstance(detail_value, dict):
                raise HTTPException(status_code=422, detail='Parameter detail harus JSON object.')
            event = OperationEventCreate(
                event_type=event_type,
                value=value,
                duration_seconds=duration_seconds,
                detail=detail_value,
            )
        return database.add_operation_event(
            app.state.database_path,
            event.event_type,
            'device',
            value=event.value,
            duration_seconds=event.duration_seconds,
            detail=event.detail,
        )

    @app.get('/api/emergency', response_class=PlainTextResponse)
    def read_emergency_status(
        mode: Literal['on'] | None = Query(default=None),
    ) -> str:
        if mode == 'on':
            state = database.set_emergency_mode(app.state.database_path, True)
            database.stop_drying_session(app.state.database_path, 'emergency')
            return 'on' if state['emergency_mode'] else 'off'
        state = database.get_control_snapshot(app.state.database_path)
        return 'on' if state['emergency_mode'] else 'off'

    @app.post('/api/emergency', response_model=ControlSnapshot)
    def set_emergency(
        payload: EmergencyUpdate | None = None,
        mode: Literal['on', 'off'] | None = Query(default=None),
    ) -> dict:
        enabled = payload.enabled if payload else (mode == 'on' if mode is not None else None)
        if enabled is None:
            raise HTTPException(status_code=422, detail='Tentukan mode=on/off di URL atau enabled di JSON body.')
        state = database.set_emergency_mode(
            app.state.database_path, enabled
        )
        if enabled:
            database.stop_drying_session(app.state.database_path, 'emergency')
        if not enabled and state['mode'] == 'auto':
            run_automation_cycle(app.state.database_path, app.state.weather_provider)
            state = database.get_control_snapshot(app.state.database_path)
        return state

    @app.get('/api/device/commands', response_model=list[dict])
    def read_device_commands(
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        return database.list_pending_commands(app.state.database_path, limit)

    @app.post('/api/device/commands/{command_id}/ack', response_model=dict)
    def acknowledge_device_command(
        command_id: int,
        payload: CommandAcknowledgement | None = None,
        actual_position: str | None = Query(default=None, min_length=1, max_length=40),
        success: bool = Query(default=True),
        detail: str = Query(default='', max_length=240),
    ) -> dict:
        if payload is None and actual_position is None:
            raise HTTPException(status_code=422, detail='Tentukan actual_position di URL atau JSON body.')
        acknowledgement = payload or CommandAcknowledgement(
            actual_position=actual_position,
            success=success,
            detail=detail,
        )
        command = database.acknowledge_actuator_command(
            app.state.database_path,
            command_id,
            acknowledgement.actual_position,
            acknowledgement.success,
            acknowledgement.detail,
        )
        if command is None:
            raise HTTPException(status_code=404, detail='Command tidak ditemukan atau sudah diproses.')
        return command

    @app.get('/api/weather')
    def read_weather() -> dict:
        try:
            return app.state.weather_provider()
        except WeatherUnavailableError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    return app


app = create_app()