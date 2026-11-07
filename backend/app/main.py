import asyncio
import hmac
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
from fastapi.openapi.utils import get_openapi
from fastapi.responses import PlainTextResponse, StreamingResponse

from app import database
from app.schemas import (
    ActuatorCommandCreate,
    AccessResponse,
    CommandAcknowledgement,
    ControlSnapshot,
    ComponentConditionReport,
    DashboardResponse,
    DeviceCreate,
    DeviceComponentCreate,
    DeviceComponentRecord,
    DeviceCoreStatusUpdate,
    DeviceStatusRecord,
    DeviceStatusUpdate,
    DryingStart,
    EmergencyStatus,
    EmergencyUpdate,
    ModeUpdate,
    OperationEvent,
    OperationEventCreate,
    PredictionRecord,
    SensorReadingCreate,
    SensorReadingRecord,
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

DOCS_TAGS = [
    {
        'name': 'Sistem & kamera',
        'description': 'Cek backend dan kelola kamera lokal. `/api/health` adalah pemeriksaan paling sederhana.',
    },
    {
        'name': 'Devices & telemetri',
        'description': 'Enam Core Unit awal memakai ID `core-1` sampai `core-6`. Kirim heartbeat dan pembacaan sensor ke ID yang sudah terdaftar.',
    },
    {
        'name': 'Komponen & commands',
        'description': 'Komponen baru boleh disimpan sebagai placeholder. Command aktuator hanya tersedia setelah komponen, unit pemilik, nilai command, dan posisi aman diverifikasi.',
    },
    {
        'name': 'Identitas & prediksi',
        'description': 'Unggah gambar sebagai multipart field `image`; keputusan akses terakhir tersedia di endpoint access.',
    },
    {
        'name': 'Dashboard & kontrol',
        'description': 'Baca ringkasan dashboard, cuaca, event, dan kendali jemur/aktuator.',
    },
    {
        'name': 'ArtecRobo (teks)',
        'description': 'Endpoint `/api/artec/...` untuk blok ArtecRobo: parameter dikirim melalui query URL dan respons berupa teks sederhana.',
    },
]

DOCS_DESCRIPTION = '''
API backend AGRO-SEMBADA untuk dashboard, Core Unit, sensor, komponen, kontrol, dan integrasi ArtecRobo.

## Mulai mencoba

1. Pilih **Server ini** agar permintaan dikirim ke host yang sedang membuka `/docs` (lokal: `http://localhost:3000`).
2. Jalankan `GET /api/health` untuk memastikan backend membalas `ok`.
3. Buka `GET /api/devices` dan `GET /api/components` untuk melihat data yang sudah terdaftar. Enam Core Unit (`core-1` sampai `core-6`) dan inventaris awal komponen sudah tersedia.
4. Buka operasi `POST`, tekan **Try it out**, lalu ubah contoh body atau parameter sebelum menekan **Execute**.

## Contoh alur sensor

`POST /api/devices/core-1/readings` dengan body:

```json
{"sensor_id":"light-1","sensor_type":"light","value":360,"unit":"lux"}
```

Lalu cek datanya lewat `GET /api/readings?device_id=core-1`.

## Aturan penting

- ID alat dan komponen harus unik. Endpoint registrasi mengembalikan `409` jika ID sudah dipakai.
- Komponen baru sebaiknya dimulai dengan `confirmed: false`, `enabled: false`, dan `device_id: null`. Verifikasi wiring dan unit pemilik sebelum mengaktifkannya.
- Polling dan ACK per-unit memerlukan `device_token` pada query URL jika token unit dikonfigurasi. Gunakan HTTPS dan jangan expose URL bertoken di log atau layanan publik.
- Endpoint `/api/artec/...` menggunakan parameter URL dan umumnya membalas teks, sedangkan endpoint `/api/...` utama menggunakan JSON.
'''


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
    device_stale_seconds = int(os.getenv('AGRO_DEVICE_STALE_SECONDS', '10'))
    if device_stale_seconds < 1:
        raise ValueError('AGRO_DEVICE_STALE_SECONDS harus minimal 1 detik.')
    should_autostart_camera = camera_autostart if camera_autostart is not None else (
        os.getenv('AGRO_CAMERA_AUTOSTART', '0').strip().casefold() in {'1', 'true', 'yes', 'on'}
    )
    try:
        safe_positions = json.loads(os.getenv('AGRO_SAFE_POSITIONS', '{"roof":"closed"}'))
        configured_positions = json.loads(
            os.getenv('AGRO_ACTUATOR_POSITIONS', '{"roof":["open","closed"]}')
        )
        device_tokens = json.loads(os.getenv('AGRO_DEVICE_TOKENS', '{}'))
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
    if not isinstance(device_tokens, dict) or any(
        not isinstance(device_id, str)
        or not isinstance(token, str)
        or not token
        for device_id, token in device_tokens.items()
    ):
        raise ValueError('AGRO_DEVICE_TOKENS harus memetakan ID alat ke token non-kosong.')
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
        description=DOCS_DESCRIPTION,
        version='1.0.0',
        openapi_tags=DOCS_TAGS,
        lifespan=lifespan,
        servers=[
            {'url': '/', 'description': 'Server ini (host yang membuka /docs)'},
            {'url': 'http://localhost:3000', 'description': 'Backend lokal port 3000'},
            {'url': 'https://dev.pradnyasiwi.web.id', 'description': 'Production'},
            {'url': 'http://localhost:5173', 'description': 'Local frontend'},
        ],
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

    def authorize_device(device_id: str, supplied_token: str | None) -> None:
        expected_token = device_tokens.get(device_id)
        if expected_token is None:
            raise HTTPException(
                status_code=503,
                detail='Command unit belum diaktifkan; konfigurasikan token perangkat.',
            )
        if supplied_token is None or not hmac.compare_digest(supplied_token, expected_token):
            raise HTTPException(status_code=401, detail='Token perangkat tidak valid.')

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
            'AGRO_CORS_ORIGINS',
            'http://localhost:5173,http://127.0.0.1:5173,https://app.artec-kk.co.jp',
        ).split(',')
        if origin.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=False,
        allow_methods=['*'],
        allow_headers=['*'],
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

    @app.post(
        '/api/devices/{device_id}/readings',
        response_model=SensorReadingRecord,
        status_code=201,
    )
    def create_sensor_reading(
        device_id: str,
        payload: SensorReadingCreate | None = None,
        sensor_id: str | None = Query(default=None, min_length=1, max_length=80),
        sensor_type: str | None = Query(default=None, min_length=1, max_length=80),
        value: float | None = None,
        unit: str | None = Query(default=None, max_length=24),
    ) -> dict:
        if payload is None:
            if sensor_id is None or sensor_type is None or value is None:
                raise HTTPException(
                    status_code=422,
                    detail='Tentukan sensor_id, sensor_type, dan value di URL atau JSON body.',
                )
            payload = SensorReadingCreate(
                sensor_id=sensor_id,
                sensor_type=sensor_type,
                value=value,
                unit=unit,
            )
        reading = database.save_sensor_reading(
            app.state.database_path,
            device_id,
            payload.sensor_id,
            payload.sensor_type,
            payload.value,
            payload.unit,
        )
        if reading is None:
            raise HTTPException(status_code=404, detail='ID alat belum terdaftar.')
        return reading

    @app.get('/api/readings', response_model=list[SensorReadingRecord])
    def read_sensor_readings(
        limit: int = Query(default=100, ge=1, le=500),
        device_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=40,
            pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
        ),
    ) -> list[dict]:
        return database.list_sensor_readings(app.state.database_path, limit, device_id)

    @app.get('/api/devices', response_model=list[DeviceStatusRecord])
    def read_device_status() -> list[dict]:
        return database.list_device_status(app.state.database_path, device_stale_seconds)

    @app.get('/api/artec/health', response_class=PlainTextResponse)
    def artec_health() -> str:
        return 'ok'

    @app.get('/api/artec/devices/all-online', response_class=PlainTextResponse)
    def artec_all_devices_online() -> str:
        devices = database.list_device_status(app.state.database_path, device_stale_seconds)
        is_online = bool(devices) and all(
            device['status'] == 'hidup' and device['connection_status'] == 'online'
            for device in devices
        )
        return 'true' if is_online else 'false'

    @app.get(
        '/api/artec/devices/{device_id}/status',
        response_class=PlainTextResponse,
    )
    def artec_device_status(device_id: str) -> str:
        device = database.get_device_status(
            app.state.database_path,
            device_id,
            device_stale_seconds,
        )
        return device['status'] if device else 'tidak_dikenal'

    @app.get(
        '/api/artec/devices/{device_id}/online',
        response_class=PlainTextResponse,
    )
    def artec_device_online(device_id: str) -> str:
        device = database.get_device_status(
            app.state.database_path,
            device_id,
            device_stale_seconds,
        )
        is_online = bool(
            device
            and device['status'] == 'hidup'
            and device['connection_status'] == 'online'
        )
        return 'true' if is_online else 'false'

    @app.get(
        '/api/artec/devices/{device_id}/age',
        response_class=PlainTextResponse,
    )
    def artec_device_age(device_id: str) -> str:
        device = database.get_device_status(
            app.state.database_path,
            device_id,
            device_stale_seconds,
        )
        return str(device['age_seconds']) if device and device['age_seconds'] is not None else 'tidak_ada'

    @app.get(
        '/api/artec/devices/{device_id}/commands',
        response_class=PlainTextResponse,
    )
    def artec_device_commands(
        device_id: str,
        limit: int = Query(default=20, ge=1, le=100),
        device_token: str | None = Query(
            default=None,
            min_length=1,
            description='Token khusus unit; kirim melalui parameter URL.',
        ),
    ) -> str:
        commands = read_commands_for_device(device_id, limit, device_token)
        return format_text_rows(commands, ('id', 'actuator', 'position', 'component_id'))

    @app.get(
        '/api/artec/devices/{device_id}/{field}',
        response_class=PlainTextResponse,
    )
    def artec_device_field(
        device_id: str,
        field: Literal['name', 'last_seen'],
    ) -> str:
        device = database.get_device_status(
            app.state.database_path,
            device_id,
            device_stale_seconds,
        )
        if device is None:
            return 'tidak_dikenal'
        return str(device[field]) if device[field] is not None else 'tidak_ada'

    @app.get('/api/artec/telemetry/uptime', response_class=PlainTextResponse)
    def artec_telemetry_uptime() -> str:
        telemetry = database.latest_telemetry(app.state.database_path)
        return str(telemetry['uptime_seconds']) if telemetry else 'tidak_ada_data'

    @app.get('/api/artec/telemetry/status', response_class=PlainTextResponse)
    def artec_telemetry_status() -> str:
        telemetry = database.latest_telemetry(app.state.database_path)
        return telemetry['status'] if telemetry else 'tidak_ada_data'

    @app.get(
        '/api/artec/readings/{device_id}/{sensor_id}/value',
        response_class=PlainTextResponse,
    )
    def artec_sensor_value(device_id: str, sensor_id: str) -> str:
        reading = database.get_latest_sensor_reading(
            app.state.database_path,
            device_id,
            sensor_id,
        )
        return str(reading['value']) if reading else 'tidak_ada_data'

    @app.get(
        '/api/artec/readings/{device_id}/{sensor_id}/{field}',
        response_class=PlainTextResponse,
    )
    def artec_sensor_field(
        device_id: str,
        sensor_id: str,
        field: Literal['sensor_type', 'value', 'unit', 'recorded_at'],
    ) -> str:
        reading = database.get_latest_sensor_reading(
            app.state.database_path,
            device_id,
            sensor_id,
        )
        if reading is None:
            return 'tidak_ada_data'
        return str(reading[field]) if reading[field] is not None else 'tidak_ada'

    @app.get(
        '/api/artec/devices/{device_id}/components/{component_id}/condition',
        response_class=PlainTextResponse,
    )
    def artec_component_condition(device_id: str, component_id: str) -> str:
        component = database.get_device_component(app.state.database_path, component_id)
        if component is None or component['device_id'] != device_id:
            return 'tidak_ditemukan'
        return component['reported_condition'] or 'belum_dilaporkan'

    @app.get('/api/artec/predictions/class', response_class=PlainTextResponse)
    def artec_prediction_class() -> str:
        return read_prediction_name()

    @app.get('/api/artec/predictions/{field}', response_class=PlainTextResponse)
    def artec_prediction_field(
        field: Literal['id', 'class_name', 'confidence', 'access_status', 'captured_at'],
    ) -> str:
        prediction = database.latest_prediction(app.state.database_path)
        if prediction is None:
            return 'tidak_ada_data'
        if field == 'access_status':
            return access_response(prediction)['access_status']
        if field == 'class_name':
            return artec_prediction_class()
        return str(prediction[field])

    @app.get('/api/artec/access/status', response_class=PlainTextResponse)
    def artec_access_status() -> str:
        prediction = database.latest_prediction(app.state.database_path)
        return access_response(prediction)['access_status']

    @app.get('/api/artec/access/{field}', response_class=PlainTextResponse)
    def artec_access_field(
        field: Literal['is_trusted', 'identity', 'confidence', 'prediction_id', 'captured_at', 'expires_at'],
    ) -> str:
        value = access_response(database.latest_prediction(app.state.database_path))[field]
        if value is None:
            return 'tidak_ada'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)

    @app.post(
        '/api/artec/devices/{device_id}/status',
        response_class=PlainTextResponse,
    )
    def artec_update_device_status(
        device_id: str,
        status: Literal['hidup', 'mati'] = Query(),
    ) -> str:
        record = update_core_status(device_id, status=status)
        return record['status']

    @app.post(
        '/api/artec/telemetry',
        response_class=PlainTextResponse,
    )
    def artec_create_telemetry(
        uptime_seconds: int = Query(ge=0),
        status: str = Query(default='unknown', min_length=1, max_length=40),
    ) -> str:
        create_telemetry(uptime_seconds=uptime_seconds, status=status)
        return 'tersimpan'

    @app.post(
        '/api/artec/devices/{device_id}/readings',
        response_class=PlainTextResponse,
    )
    def artec_create_sensor_reading(
        device_id: str,
        sensor_id: str = Query(min_length=1, max_length=80),
        sensor_type: str = Query(min_length=1, max_length=80),
        value: float = Query(),
        unit: str | None = Query(default=None, max_length=24),
    ) -> str:
        create_sensor_reading(
            device_id,
            sensor_id=sensor_id,
            sensor_type=sensor_type,
            value=value,
            unit=unit,
        )
        return 'tersimpan'

    @app.post(
        '/api/artec/devices/{device_id}/components/{component_id}/condition',
        response_class=PlainTextResponse,
    )
    def artec_report_component_condition(
        device_id: str,
        component_id: str,
        condition: str = Query(min_length=1, max_length=80),
    ) -> str:
        report_component_condition(device_id, component_id, condition)
        return 'tersimpan'

    @app.post('/api/devices', response_model=DeviceStatusRecord, status_code=201)
    def create_device(payload: DeviceCreate) -> dict:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=422, detail='Nama alat tidak boleh kosong.')
        record = database.create_device(
            app.state.database_path,
            payload.device_id,
            name,
            device_stale_seconds,
        )
        if record is None:
            raise HTTPException(status_code=409, detail='ID alat sudah terdaftar.')
        return record

    @app.get('/api/devices/{device_id}/status', response_model=DeviceStatusRecord)
    def read_core_status(device_id: str) -> dict:
        record = database.get_device_status(
            app.state.database_path,
            device_id,
            device_stale_seconds,
        )
        if record is None:
            raise HTTPException(status_code=404, detail='ID core belum terdaftar.')
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
            app.state.database_path,
            resolved_device_id,
            resolved_status,
            device_stale_seconds,
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

    @app.post(
        '/api/devices/{device_id}/status',
        response_model=DeviceStatusRecord,
        summary='Laporkan status Core Unit',
        description=(
            'Kirim status Core Unit melalui query URL atau JSON body tanpa header autentikasi. '
            'POST berkala menjadi heartbeat; '
            'status hidup berubah menjadi mati setelah batas stale terlewati.'
        ),
    )
    def update_core_status(
        device_id: str,
        payload: DeviceCoreStatusUpdate | None = None,
        status: Literal['hidup', 'mati'] | None = Query(default=None),
    ) -> dict:
        resolved_status = payload.status if payload is not None else status
        if resolved_status is None:
            raise HTTPException(
                status_code=422,
                detail='Kirim status=hidup atau status=mati di URL, atau melalui JSON body.',
            )
        record = database.update_device_status(
            app.state.database_path,
            device_id,
            resolved_status,
            device_stale_seconds,
        )
        if record is None:
            raise HTTPException(status_code=404, detail='ID core belum terdaftar.')
        database.add_operation_event(
            app.state.database_path,
            'device_status_updated',
            device_id,
            value=resolved_status,
        )
        return record

    def normalize_component_payload(payload: DeviceComponentCreate) -> dict:
        if payload.enabled and not payload.confirmed:
            raise HTTPException(status_code=422, detail='Komponen harus dikonfirmasi sebelum diaktifkan.')
        if payload.confirmed and payload.device_id is None:
            raise HTTPException(status_code=422, detail='Komponen terkonfirmasi harus dipetakan ke unit.')
        if payload.device_id and database.get_device_status(app.state.database_path, payload.device_id) is None:
            raise HTTPException(status_code=404, detail='ID alat belum terdaftar.')
        if payload.component_type in {'dc_motor', 'servo', 'actuator'} and payload.confirmed:
            if not payload.safe_value or payload.safe_value not in payload.command_values:
                raise HTTPException(
                    status_code=422,
                    detail='Aktuator terkonfirmasi harus memiliki nilai aman yang diizinkan.',
                )
        return payload.model_dump()

    @app.get('/api/components', response_model=list[DeviceComponentRecord])
    def read_components(
        device_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=40,
            pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
        ),
    ) -> list[dict]:
        return database.list_device_components(app.state.database_path, device_id)

    @app.post('/api/components', response_model=DeviceComponentRecord, status_code=201)
    def create_component(payload: DeviceComponentCreate) -> dict:
        component = database.create_device_component(
            app.state.database_path,
            normalize_component_payload(payload),
        )
        if component is None:
            raise HTTPException(status_code=409, detail='ID komponen sudah terdaftar.')
        return component

    @app.put('/api/components/{component_id}', response_model=DeviceComponentRecord)
    def update_component(component_id: str, payload: DeviceComponentCreate) -> dict:
        if component_id != payload.component_id:
            raise HTTPException(status_code=422, detail='ID komponen pada URL dan body harus sama.')
        component = database.update_device_component(
            app.state.database_path,
            normalize_component_payload(payload),
        )
        if component is None:
            raise HTTPException(status_code=404, detail='Komponen belum terdaftar.')
        return component

    @app.post(
        '/api/devices/{device_id}/components/{component_id}/status',
        response_model=ComponentConditionReport,
        status_code=201,
    )
    def report_component_condition(
        device_id: str,
        component_id: str,
        condition: str = Query(min_length=1, max_length=80),
    ) -> dict:
        if database.get_device_status(app.state.database_path, device_id) is None:
            raise HTTPException(status_code=404, detail='ID alat belum terdaftar.')
        normalized_condition = condition.strip()
        if not normalized_condition:
            raise HTTPException(status_code=422, detail='Kondisi komponen tidak boleh kosong.')
        report = database.create_component_condition_report(
            app.state.database_path,
            device_id,
            component_id,
            normalized_condition,
        )
        if report is None:
            raise HTTPException(
                status_code=404,
                detail='Komponen belum terdaftar atau tidak dipetakan ke unit ini.',
            )
        return report

    @app.get(
        '/api/component-condition-reports',
        response_model=list[ComponentConditionReport],
    )
    def read_component_condition_reports(
        limit: int = Query(default=20, ge=1, le=100),
        device_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=40,
            pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
        ),
        component_id: str | None = Query(
            default=None,
            min_length=1,
            max_length=80,
            pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$',
        ),
    ) -> list[dict]:
        return database.list_component_condition_reports(
            app.state.database_path,
            limit,
            device_id,
            component_id,
        )

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

    @app.post('/api/devices/{device_id}/components/{component_id}/commands', response_model=dict)
    def command_device_component(
        device_id: str,
        component_id: str,
        payload: ActuatorCommandCreate | None = None,
        position: str | None = Query(default=None, min_length=1, max_length=40),
    ) -> dict:
        selected_position = payload.position if payload else position
        if selected_position is None:
            raise HTTPException(status_code=422, detail='Tentukan position di URL atau JSON body.')
        state = database.get_control_snapshot(app.state.database_path)
        if state['emergency_mode']:
            raise HTTPException(status_code=409, detail='Emergency aktif; command ditolak.')
        if state['mode'] != 'manual':
            raise HTTPException(status_code=409, detail='Pilih mode manual sebelum mengendalikan aktuator.')
        try:
            return database.queue_device_component_command(
                app.state.database_path,
                device_id,
                component_id,
                selected_position,
                'dashboard',
                device_stale_seconds,
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get('/api/devices/{device_id}/commands', response_model=list[dict])
    def read_commands_for_device(
        device_id: str,
        limit: int = Query(default=20, ge=1, le=100),
        device_token: str | None = Query(
            default=None,
            min_length=1,
            description='Token khusus unit. Kirim lewat query URL; wajib jika AGRO_DEVICE_TOKENS dikonfigurasi.',
        ),
    ) -> list[dict]:
        authorize_device(device_id, device_token)
        if database.get_device_status(app.state.database_path, device_id) is None:
            raise HTTPException(status_code=404, detail='ID alat belum terdaftar.')
        return database.list_pending_device_commands(app.state.database_path, device_id, limit)

    @app.post('/api/devices/{device_id}/commands/{command_id}/ack', response_model=dict)
    def acknowledge_device_scoped_command(
        device_id: str,
        command_id: int,
        payload: CommandAcknowledgement | None = None,
        actual_position: str | None = Query(default=None, min_length=1, max_length=40),
        success: bool = Query(default=True),
        detail: str = Query(default='', max_length=240),
        device_token: str | None = Query(
            default=None,
            min_length=1,
            description='Token khusus unit. Kirim lewat query URL; wajib jika AGRO_DEVICE_TOKENS dikonfigurasi.',
        ),
    ) -> dict:
        authorize_device(device_id, device_token)
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
            device_id,
        )
        if command is None:
            raise HTTPException(status_code=404, detail='Command tidak ditemukan untuk unit ini atau sudah diproses.')
        return command

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

    def format_text_rows(rows: list[dict], fields: tuple[str, ...]) -> str:
        if not rows:
            return 'kosong'
        return '\n'.join(
            '|'.join('' if row.get(field) is None else str(row[field]) for field in fields)
            for row in rows
        )

    @app.get('/api/artec/camera/status', response_class=PlainTextResponse)
    def artec_camera_state() -> str:
        return camera_status_response()['state']

    @app.get('/api/artec/camera/stream')
    async def artec_camera_stream() -> StreamingResponse:
        return await camera_stream()

    @app.post('/api/artec/camera/rescan', response_class=PlainTextResponse)
    def artec_camera_rescan() -> str:
        return rescan_cameras()['state']

    @app.post('/api/artec/camera/stop', response_class=PlainTextResponse)
    def artec_camera_stop() -> str:
        stop_camera()
        return 'stopped'

    @app.get('/api/artec/devices', response_class=PlainTextResponse)
    def artec_devices() -> str:
        devices = read_device_status()
        return format_text_rows(devices, ('device_id', 'status', 'connection_status'))

    @app.post('/api/artec/devices', response_class=PlainTextResponse)
    def artec_register_device(
        device_id: str = Query(min_length=1, max_length=40, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$'),
        name: str = Query(min_length=1, max_length=80),
    ) -> str:
        create_device(DeviceCreate(device_id=device_id, name=name))
        return 'tersimpan'

    @app.get('/api/artec/components', response_class=PlainTextResponse)
    def artec_components(
        device_id: str | None = Query(default=None, min_length=1, max_length=40),
    ) -> str:
        components = read_components(device_id)
        return format_text_rows(components, ('component_id', 'name', 'device_id'))

    @app.get(
        '/api/artec/components/{component_id}/{field}',
        response_class=PlainTextResponse,
    )
    def artec_component_field(
        component_id: str,
        field: Literal[
            'name', 'component_type', 'device_id', 'current_value', 'target_value',
            'reported_condition', 'enabled', 'confirmed',
        ],
    ) -> str:
        component = database.get_device_component(app.state.database_path, component_id)
        if component is None:
            return 'tidak_ditemukan'
        value = component.get(field)
        if value is None:
            return 'belum_ada'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)

    @app.post('/api/artec/components', response_class=PlainTextResponse)
    def artec_create_component(
        component_id: str = Query(min_length=1, max_length=80, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$'),
        name: str = Query(min_length=1, max_length=100),
        component_type: str = Query(min_length=1, max_length=60),
        device_id: str | None = Query(default=None, max_length=40),
        confirmed: bool = Query(default=False),
        enabled: bool = Query(default=False),
        command_values: str = Query(default=''),
        safe_value: str | None = Query(default=None, max_length=40),
        estimated_count: str | None = Query(default=None, max_length=32),
    ) -> str:
        payload = DeviceComponentCreate(
            component_id=component_id,
            name=name,
            component_type=component_type,
            device_id=device_id,
            confirmed=confirmed,
            enabled=enabled,
            command_values=[value for value in command_values.split(',') if value],
            safe_value=safe_value,
            estimated_count=estimated_count,
        )
        create_component(payload)
        return 'tersimpan'

    @app.post(
        '/api/artec/components/{component_id}',
        response_class=PlainTextResponse,
    )
    def artec_update_component(
        component_id: str,
        name: str = Query(min_length=1, max_length=100),
        component_type: str = Query(min_length=1, max_length=60),
        device_id: str | None = Query(default=None, max_length=40),
        confirmed: bool = Query(default=False),
        enabled: bool = Query(default=False),
        command_values: str = Query(default=''),
        safe_value: str | None = Query(default=None, max_length=40),
        estimated_count: str | None = Query(default=None, max_length=32),
    ) -> str:
        payload = DeviceComponentCreate(
            component_id=component_id,
            name=name,
            component_type=component_type,
            device_id=device_id,
            confirmed=confirmed,
            enabled=enabled,
            command_values=[value for value in command_values.split(',') if value],
            safe_value=safe_value,
            estimated_count=estimated_count,
        )
        update_component(component_id, payload)
        return 'tersimpan'

    @app.get('/api/artec/telemetry/history', response_class=PlainTextResponse)
    def artec_telemetry_history(limit: int = Query(default=10, ge=1, le=100)) -> str:
        records = read_telemetry(limit)
        return format_text_rows(records, ('uptime_seconds', 'status', 'recorded_at'))

    @app.get(
        '/api/artec/readings/{device_id}',
        response_class=PlainTextResponse,
    )
    def artec_reading_history(
        device_id: str,
        limit: int = Query(default=10, ge=1, le=500),
    ) -> str:
        records = read_sensor_readings(limit, device_id)
        return format_text_rows(records, ('sensor_id', 'sensor_type', 'value', 'unit', 'recorded_at'))

    @app.get(
        '/api/artec/devices/{device_id}/components/{component_id}/reports',
        response_class=PlainTextResponse,
    )
    def artec_condition_history(
        device_id: str,
        component_id: str,
        limit: int = Query(default=10, ge=1, le=100),
    ) -> str:
        reports = read_component_condition_reports(limit, device_id, component_id)
        return format_text_rows(reports, ('condition', 'reported_at'))

    @app.post('/api/artec/predictions', response_class=PlainTextResponse)
    async def artec_create_prediction(image: UploadFile = File(...)) -> str:
        prediction = await create_prediction(image)
        return prediction['access_status']

    @app.get('/api/artec/dashboard/{field}', response_class=PlainTextResponse)
    def artec_dashboard_field(
        field: Literal['uptime_seconds', 'telemetry_status', 'prediction_class', 'access_status'],
    ) -> str:
        if field == 'uptime_seconds':
            return artec_telemetry_uptime()
        if field == 'telemetry_status':
            return artec_telemetry_status()
        if field == 'prediction_class':
            return artec_prediction_class()
        return artec_access_status()

    @app.get('/api/artec/weather/{field}', response_class=PlainTextResponse)
    def artec_weather_field(
        field: Literal[
            'condition', 'temperature_c', 'apparent_temperature_c', 'humidity_percent',
            'precipitation_mm', 'wind_speed_kmh', 'weather_code', 'is_day',
        ],
    ) -> str:
        weather = read_weather()
        value = weather.get(field)
        if value is None:
            return 'tidak_ada_data'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)

    @app.get('/api/artec/control/{field}', response_class=PlainTextResponse)
    def artec_control_field(
        field: Literal[
            'mode', 'emergency_mode', 'drying_elapsed_seconds', 'drying_target_seconds',
            'drying_started_at', 'updated_at',
        ],
    ) -> str:
        state = read_control_state()
        value = state.get(field)
        if value is None:
            return 'tidak_ada'
        if isinstance(value, bool):
            return 'true' if value else 'false'
        return str(value)

    @app.get(
        '/api/artec/control/actuators/{actuator}/{field}',
        response_class=PlainTextResponse,
    )
    def artec_actuator_field(
        actuator: str,
        field: Literal['current_position', 'target_position', 'safe_position'],
    ) -> str:
        state = read_control_state()
        record = next((item for item in state['actuators'] if item['name'] == actuator), None)
        return str(record[field]) if record else 'tidak_ditemukan'

    @app.post('/api/artec/control/mode', response_class=PlainTextResponse)
    def artec_set_mode(mode: Literal['manual', 'auto'] = Query()) -> str:
        return update_control_mode(mode=mode)['mode']

    @app.post(
        '/api/artec/control/actuators/{actuator}',
        response_class=PlainTextResponse,
    )
    def artec_command_actuator(
        actuator: str,
        position: str = Query(min_length=1, max_length=40),
    ) -> str:
        command = command_actuator(actuator, position=position)
        return str(command['id'])

    @app.post('/api/artec/drying/start', response_class=PlainTextResponse)
    def artec_start_drying(target_seconds: int = Query(ge=60, le=86400)) -> str:
        start_drying(target_seconds=target_seconds)
        return 'dimulai'

    @app.post('/api/artec/drying/stop', response_class=PlainTextResponse)
    def artec_stop_drying() -> str:
        stop_drying()
        return 'dihentikan'

    @app.get('/api/artec/events', response_class=PlainTextResponse)
    def artec_event_history(limit: int = Query(default=10, ge=1, le=200)) -> str:
        events = read_events(limit)
        return format_text_rows(events, ('event_type', 'source', 'value', 'occurred_at'))

    @app.post('/api/artec/events', response_class=PlainTextResponse)
    def artec_create_event(
        event_type: str = Query(min_length=1, max_length=80),
        value: str | None = Query(default=None, max_length=160),
        duration_seconds: int | None = Query(default=None, ge=0),
    ) -> str:
        create_event(
            event_type=event_type,
            value=value,
            duration_seconds=duration_seconds,
            detail='{}',
        )
        return 'tersimpan'

    @app.get('/api/artec/emergency', response_class=PlainTextResponse)
    def artec_get_emergency() -> str:
        return read_emergency_status()

    @app.post('/api/artec/emergency', response_class=PlainTextResponse)
    def artec_set_emergency(mode: Literal['on', 'off'] = Query()) -> str:
        state = set_emergency(mode=mode)
        return 'on' if state['emergency_mode'] else 'off'

    @app.get('/api/artec/commands', response_class=PlainTextResponse)
    def artec_pending_commands(limit: int = Query(default=20, ge=1, le=100)) -> str:
        commands = read_device_commands(limit)
        return format_text_rows(commands, ('id', 'actuator', 'position'))

    @app.post(
        '/api/artec/devices/{device_id}/components/{component_id}/commands',
        response_class=PlainTextResponse,
    )
    def artec_command_component(
        device_id: str,
        component_id: str,
        position: str = Query(min_length=1, max_length=40),
    ) -> str:
        command = command_device_component(device_id, component_id, position=position)
        return str(command['id'])

    @app.post(
        '/api/artec/devices/{device_id}/commands/{command_id}/ack',
        response_class=PlainTextResponse,
    )
    def artec_ack_device_command(
        device_id: str,
        command_id: int,
        actual_position: str = Query(min_length=1, max_length=40),
        success: bool = Query(default=True),
        detail: str = Query(default='', max_length=240),
        device_token: str | None = Query(
            default=None,
            min_length=1,
            description='Token khusus unit; kirim melalui parameter URL.',
        ),
    ) -> str:
        command = acknowledge_device_scoped_command(
            device_id,
            command_id,
            actual_position=actual_position,
            success=success,
            detail=detail,
            device_token=device_token,
        )
        return command['status']

    @app.post(
        '/api/artec/device/commands/{command_id}/ack',
        response_class=PlainTextResponse,
    )
    def artec_ack_legacy_command(
        command_id: int,
        actual_position: str = Query(min_length=1, max_length=40),
        success: bool = Query(default=True),
        detail: str = Query(default='', max_length=240),
    ) -> str:
        command = acknowledge_device_command(
            command_id,
            actual_position=actual_position,
            success=success,
            detail=detail,
        )
        return command['status']

    def openapi_with_learning_groups() -> dict:
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=DOCS_TAGS,
            servers=app.servers,
        )
        for path, path_item in schema['paths'].items():
            if path.startswith('/api/artec/'):
                tag = 'ArtecRobo (teks)'
            elif path.startswith('/api/camera/') or path == '/api/health':
                tag = 'Sistem & kamera'
            elif (
                path.startswith('/api/components')
                or path.startswith('/api/component-condition-reports')
                or '/components/' in path
                or '/commands' in path
            ):
                tag = 'Komponen & commands'
            elif (
                path.startswith('/api/devices')
                or path.startswith('/api/readings')
                or path.startswith('/api/telemetry')
            ):
                tag = 'Devices & telemetri'
            elif path.startswith('/api/predictions') or path.startswith('/api/access'):
                tag = 'Identitas & prediksi'
            else:
                tag = 'Dashboard & kontrol'

            for operation in path_item.values():
                if isinstance(operation, dict) and 'responses' in operation:
                    operation['tags'] = [tag]

        app.openapi_schema = schema
        return schema

    app.openapi = openapi_with_learning_groups

    return app


app = create_app()