import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.teachable_machine import TeachableMachineClassifier


class FakeClassifier:
    def __init__(self, prediction: tuple[str, float] = ('owner', 0.94)) -> None:
        self.prediction = prediction

    def predict(self, image_bytes: bytes) -> tuple[str, float]:
        assert image_bytes == b'test image bytes'
        return self.prediction


def test_telemetry_is_saved_and_returned(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.post(
            '/api/telemetry',
            json={'uptime_seconds': 7250, 'status': 'running'},
        )

        assert response.status_code == 200
        assert response.json()['uptime_seconds'] == 7250
        assert response.json()['status'] == 'running'

        dashboard = client.get('/api/dashboard').json()
        history = client.get('/api/telemetry?limit=5').json()

    assert dashboard['telemetry']['uptime_seconds'] == 7250
    assert len(history) == 1


def test_six_devices_can_report_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        initial = client.get('/api/devices')
        updated = client.post(
            '/api/devices/status',
            json={'device_id': 'alat-2', 'status': 'hidup'},
        )
        created = client.post(
            '/api/devices',
            json={'device_id': 'pompa-air', 'name': 'Pompa Air'},
        )
        created_status = client.post(
            '/api/devices/status',
            json={'device_id': 'pompa-air', 'status': 'mati'},
        )
        url_status = client.post(
            '/api/devices/status?device_id=alat-3&status=hidup'
        )
        missing_status = client.post('/api/devices/status')
        statuses = client.get('/api/devices').json()
        duplicate = client.post(
            '/api/devices',
            json={'device_id': 'pompa-air', 'name': 'Pompa Air'},
        )

    assert initial.status_code == 200
    assert len(initial.json()) == 6
    assert all(device['status'] == 'belum_terhubung' for device in initial.json())
    assert initial.json()[0]['name'] == 'Alat 1'
    assert updated.status_code == 200
    assert updated.json()['status'] == 'hidup'
    assert updated.json()['last_seen'] is not None
    assert next(device for device in statuses if device['device_id'] == 'alat-2')['status'] == 'hidup'
    assert created.status_code == 201
    assert created.json()['name'] == 'Pompa Air'
    assert created_status.json()['status'] == 'mati'
    assert url_status.status_code == 200
    assert url_status.json()['status'] == 'hidup'
    assert missing_status.status_code == 422
    assert next(device for device in statuses if device['device_id'] == 'pompa-air')['status'] == 'mati'
    assert duplicate.status_code == 409


def test_health_returns_plain_text_ok(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.get('/api/health')

    assert response.status_code == 200
    assert response.text == 'ok'
    assert response.headers['content-type'].startswith('text/plain')


def test_camera_status_is_available_without_camera_hardware(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier(), camera_autostart=False)
    with TestClient(app) as client:
        response = client.get('/api/camera/status')

    assert response.status_code == 200
    assert response.json()['state'] == 'stopped'
    assert response.json()['prediction_ready'] is True


def test_artecrobo_can_use_url_parameters_without_auth(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        telemetry = client.post(
            '/api/telemetry?uptime_seconds=900&status=running'
        )
        manual = client.post(
            '/api/control/actuators/roof?position=open'
        )
        commands = client.get('/api/device/commands').json()
        emergency = client.get('/api/emergency?mode=on')
        safe_commands = client.get('/api/device/commands').json()
        acknowledgement = client.post(
            f"/api/device/commands/{safe_commands[0]['id']}/ack"
            '?actual_position=closed'
        )
        cleared = client.post('/api/emergency?mode=off')

    assert telemetry.status_code == 200
    assert telemetry.json()['uptime_seconds'] == 900
    assert manual.status_code == 200
    assert commands[0]['position'] == 'open'
    assert emergency.text == 'on'
    assert len(safe_commands) == 1
    assert safe_commands[0]['position'] == 'closed'
    assert acknowledgement.status_code == 200
    assert acknowledgement.json()['status'] == 'acknowledged'
    assert cleared.status_code == 200


def test_image_prediction_is_saved_for_get_endpoints(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'test image bytes', 'image/jpeg')},
        )

        assert response.status_code == 200
        assert response.json()['class_name'] == 'owner'
        assert response.json()['confidence'] == 0.94
        assert response.json()['access_status'] == 'trusted'

        latest = client.get('/api/predictions/latest').json()
        dashboard = client.get('/api/dashboard').json()
        access = client.get('/api/access/latest').json()

    assert latest['class_name'] == 'owner'
    assert dashboard['prediction']['confidence'] == 0.94
    assert access['access_status'] == 'trusted'
    assert access['is_trusted'] is True


def test_unknown_face_does_not_get_trusted_access(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(('visitor', 0.99)),
    )
    with TestClient(app) as client:
        response = client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'test image bytes', 'image/jpeg')},
        )
        access = client.get('/api/access/latest').json()

    assert response.json()['access_status'] == 'untrusted'
    assert access['is_trusted'] is False


def test_low_confidence_returns_unknown_access(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(('owner', 0.6)),
    )
    with TestClient(app) as client:
        response = client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'test image bytes', 'image/jpeg')},
        )

    assert response.json()['access_status'] == 'unknown'


def test_access_endpoint_needs_no_token(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.get('/api/access/latest')

    assert response.status_code == 200
    assert response.json()['access_status'] == 'unknown'


def test_stale_trusted_result_expires_to_unknown(tmp_path: Path) -> None:
    database_path = tmp_path / 'test.db'
    app = create_app(database_path, FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'test image bytes', 'image/jpeg')},
        )
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
        with sqlite3.connect(database_path) as connection:
            connection.execute('UPDATE predictions SET captured_at = ?', (stale_time,))
        response = client.get('/api/access/latest')

    assert response.json()['access_status'] == 'unknown'
    assert response.json()['is_trusted'] is False


def test_predictions_get_returns_latest_identity_as_plain_text(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'test image bytes', 'image/jpeg')},
        )
        response = client.get('/api/predictions')

    assert response.status_code == 200
    assert response.text == 'owner'
    assert response.headers['content-type'].startswith('text/plain')


def test_weather_endpoint_uses_configured_provider(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(),
        weather_provider=lambda: {'location': 'Pakem, Sleman', 'temperature_c': 26.0},
    )
    with TestClient(app) as client:
        response = client.get('/api/weather')

    assert response.status_code == 200
    assert response.json()['temperature_c'] == 26.0


def test_auto_drying_opens_in_good_weather_and_logs_duration(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(),
        weather_provider=lambda: {
            'is_day': True,
            'precipitation_mm': 0,
            'weather_code': 0,
        },
    )
    with TestClient(app) as client:
        mode = client.post('/api/control/mode', json={'mode': 'auto'})
        initial_command = client.get('/api/device/commands').json()[0]
        client.post(
            f"/api/device/commands/{initial_command['id']}/ack",
            json={'actual_position': 'closed'},
        )

        drying = client.post(
            '/api/drying/start',
            json={'target_seconds': 3600},
        )
        open_command = client.get('/api/device/commands').json()
        stopped = client.post('/api/drying/stop')
        close_command = client.get('/api/device/commands').json()
        events = client.get('/api/events?limit=20').json()

    assert mode.status_code == 200
    assert drying.json()['drying_started_at'] is not None
    assert [command['position'] for command in open_command] == ['open']
    assert stopped.json()['drying_started_at'] is None
    assert [command['position'] for command in close_command] == ['closed']
    completed = next(event for event in events if event['event_type'] == 'drying_completed')
    assert completed['duration_seconds'] is not None


def test_emergency_supersedes_manual_command_and_reports_on(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        manual = client.post(
            '/api/control/actuators/roof',
            json={'position': 'open'},
        )
        emergency = client.post(
            '/api/emergency', json={'enabled': True}
        )
        status = client.get('/api/emergency')
        commands = client.get('/api/device/commands').json()
        blocked = client.post(
            '/api/control/actuators/roof',
            json={'position': 'open'},
        )
        cleared = client.post(
            '/api/emergency', json={'enabled': False}
        )

    assert manual.status_code == 200
    assert emergency.json()['emergency_mode'] is True
    assert status.text == 'on'
    assert status.headers['content-type'].startswith('text/plain')
    assert len(commands) == 1
    assert commands[0]['position'] == 'closed'
    assert commands[0]['source'] == 'emergency'
    assert blocked.status_code == 409
    assert cleared.status_code == 200


def test_weather_rain_keeps_auto_roof_closed(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(),
        weather_provider=lambda: {
            'is_day': True,
            'precipitation_mm': 2.0,
            'weather_code': 61,
        },
    )
    with TestClient(app) as client:
        client.post('/api/control/mode', json={'mode': 'auto'})
        commands = client.get('/api/device/commands').json()
        client.post(
            '/api/drying/start',
            json={'target_seconds': 3600},
        )
        safe_commands = client.get('/api/device/commands').json()

    assert commands[0]['position'] == 'closed'
    assert [command['position'] for command in safe_commands] == ['closed']


def test_auto_stops_drying_when_target_duration_is_reached(tmp_path: Path) -> None:
    database_path = tmp_path / 'test.db'
    app = create_app(
        database_path,
        FakeClassifier(),
        weather_provider=lambda: {
            'is_day': True,
            'precipitation_mm': 0,
            'weather_code': 0,
        },
    )
    with TestClient(app) as client:
        client.post('/api/control/mode', json={'mode': 'auto'})
        client.post(
            '/api/drying/start',
            json={'target_seconds': 60},
        )
        started_in_past = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                'UPDATE controller_state SET drying_started_at = ?', (started_in_past,)
            )
        state = client.post('/api/control/mode', json={'mode': 'auto'}).json()
        pending = client.get('/api/device/commands').json()
        events = client.get('/api/events?limit=20').json()

    assert state['drying_started_at'] is None
    assert [command['position'] for command in pending] == ['closed']
    completed = next(event for event in events if event['event_type'] == 'drying_completed')
    assert completed['duration_seconds'] >= 60


def test_generic_device_event_is_persisted(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.post(
            '/api/events',
            json={
                'event_type': 'soil_moisture_sampled',
                'value': '42%',
                'duration_seconds': 3,
                'detail': {'sensor': 'soil-1'},
            },
        )
        events = client.get('/api/events').json()

    assert response.status_code == 200
    assert events[0]['event_type'] == 'soil_moisture_sampled'
    assert events[0]['detail']['sensor'] == 'soil-1'


def test_prediction_without_model_returns_actionable_error(tmp_path: Path) -> None:
    predictor = TeachableMachineClassifier(
        tmp_path / 'missing_model.h5', tmp_path / 'missing_labels.txt'
    )
    app = create_app(tmp_path / 'test.db', predictor)
    with TestClient(app) as client:
        response = client.post(
            '/api/predictions',
            files={'image': ('sample.jpg', b'image bytes', 'image/jpeg')},
        )

    assert response.status_code == 503
    assert 'keras_model.h5' in response.json()['detail']


def test_invalid_telemetry_is_rejected(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.post(
            '/api/telemetry',
            json={'uptime_seconds': -1, 'status': 'running'},
        )

    assert response.status_code == 422