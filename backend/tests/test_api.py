import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.services.teachable_machine import TeachableMachineClassifier


def test_openapi_docs_have_local_server_groups_and_request_examples(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'docs.db', FakeClassifier(), camera_autostart=False)
    schema = app.openapi()
    poll_parameters = schema['paths']['/api/devices/{device_id}/commands']['get']['parameters']
    token_parameter = next(parameter for parameter in poll_parameters if parameter['name'] == 'X-Device-Token')
    with TestClient(app) as client:
        docs = client.get('/docs')

    assert schema['servers'][0]['url'] == '/'
    assert 'Mulai mencoba' in schema['info']['description']
    assert schema['paths']['/api/telemetry']['post']['tags'] == ['Devices & telemetri']
    assert schema['paths']['/api/artec/health']['get']['tags'] == ['ArtecRobo (teks)']
    assert schema['components']['schemas']['TelemetryCreate']['examples'] == [
        {'uptime_seconds': 7250, 'status': 'running'}
    ]
    assert schema['components']['schemas']['DeviceComponentCreate']['examples'][0]['confirmed'] is False
    assert token_parameter['in'] == 'query'
    assert docs.status_code == 200
    assert 'copy-api-url' in docs.text
    assert 'copy-api-url-try' in docs.text
    assert 'Salin URL request' in docs.text


class FakeClassifier:
    def __init__(self, prediction: tuple[str, float] = ('owner', 0.94)) -> None:
        self.prediction = prediction

    def predict(self, image_bytes: bytes) -> tuple[str, float]:
        assert image_bytes == b'test image bytes'
        return self.prediction


def test_artecrobo_origin_can_access_api_methods_and_headers(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    origin = 'https://app.artec-kk.co.jp'
    with TestClient(app) as client:
        response = client.options(
            '/api/components/example',
            headers={
                'Origin': origin,
                'Access-Control-Request-Method': 'PUT',
                'Access-Control-Request-Headers': 'content-type,x-device-token',
            },
        )

    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin
    assert 'PUT' in response.headers['access-control-allow-methods']
    assert 'x-device-token' in response.headers['access-control-allow-headers'].lower()


def test_artec_text_api_reports_individual_values_and_all_online(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        initial_all_online = client.get('/api/artec/devices/all-online')
        status = client.post('/api/artec/devices/core-1/status?status=hidup')
        online = client.get('/api/artec/devices/core-1/online')
        device_status = client.get('/api/artec/devices/core-1/status')
        remaining_devices_online = client.get('/api/artec/devices/all-online')

        for number in range(2, 7):
                client.post(f'/api/artec/devices/core-{number}/status?status=hidup')
        all_online = client.get('/api/artec/devices/all-online')

        reading = client.post(
            '/api/artec/devices/core-1/readings'
            '?sensor_id=light-1&sensor_type=light&value=360&unit=lux'
        )
        reading_value = client.get('/api/artec/readings/core-1/light-1/value')
        telemetry = client.post(
            '/api/artec/telemetry?uptime_seconds=7250&status=running'
        )
        uptime = client.get('/api/artec/telemetry/uptime')
        telemetry_status = client.get('/api/artec/telemetry/status')
        component = client.post(
            '/api/components',
            json={
                'component_id': 'motor-1',
                'name': 'Motor 1',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
            },
        )
        condition = client.post(
            '/api/artec/devices/core-1/components/motor-1/condition?condition=normal'
        )
        latest_condition = client.get(
            '/api/artec/devices/core-1/components/motor-1/condition'
        )

    assert initial_all_online.text == 'false'
    assert initial_all_online.headers['content-type'].startswith('text/plain')
    assert status.text == 'hidup'
    assert status.headers['content-type'].startswith('text/plain')
    assert online.text == 'true'
    assert device_status.text == 'hidup'
    assert remaining_devices_online.text == 'false'
    assert all_online.text == 'true'
    assert reading.text == 'tersimpan'
    assert reading_value.text == '360.0'
    assert telemetry.text == 'tersimpan'
    assert uptime.text == '7250'
    assert telemetry_status.text == 'running'
    assert component.status_code == 201
    assert condition.text == 'tersimpan'
    assert condition.headers['content-type'].startswith('text/plain')
    assert latest_condition.text == 'normal'


def test_artec_aliases_cover_control_events_weather_and_components(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(),
        weather_provider=lambda: {'condition': 'Cerah', 'temperature_c': 23.5},
    )
    with TestClient(app) as client:
        component = client.post(
            '/api/artec/components'
            '?component_id=lamp-1&name=Lampu&component_type=light&device_id=core-1'
        )
        component_name = client.get('/api/artec/components/lamp-1/name')
        components = client.get('/api/artec/components')
        weather = client.get('/api/artec/weather/temperature_c')
        mode = client.post('/api/artec/control/mode?mode=manual')
        actuator = client.post('/api/artec/control/actuators/roof?position=closed')
        target = client.get('/api/artec/control/actuators/roof/target_position')
        event = client.post('/api/artec/events?event_type=artec_test&value=ok')
        events = client.get('/api/artec/events?limit=1')
        emergency = client.post('/api/artec/emergency?mode=on')
        emergency_state = client.get('/api/artec/emergency')
        client.post('/api/artec/emergency?mode=off')

    assert component.text == 'tersimpan'
    assert component_name.text == 'Lampu'
    assert 'lamp-1|Lampu|core-1' in components.text
    assert weather.text == '23.5'
    assert mode.text == 'manual'
    assert actuator.text.isdigit()
    assert target.text == 'closed'
    assert event.text == 'tersimpan'
    assert 'artec_test|device|ok|' in events.text
    assert emergency.text == 'on'
    assert emergency_state.text == 'on'


def test_artec_time_and_date_are_plain_text(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        time_response = client.get('/api/artec/time')
        date_response = client.get('/api/artec/date')

    assert time_response.status_code == 200
    assert time_response.text[:2].isdigit() and time_response.text[2] == '.'
    assert time_response.text[3:].isdigit() and len(time_response.text) == 5
    assert time_response.headers['content-type'].startswith('text/plain')
    assert date_response.status_code == 200
    assert date_response.text.split(', ')[0] in {
        'Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat', 'Sabtu', 'Minggu',
    }
    assert date_response.text.split(', ')[2] in {
        'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
        'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
    }
    assert date_response.headers['content-type'].startswith('text/plain')


def test_artec_event_flags_support_one_shot_and_ack_modes(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        one_shot = client.post('/api/event-flags', json={'name': 'buka_lumbung', 'mode': 'once'})
        client.put('/api/event-flags/buka_lumbung', json={'active': True})
        first_read = client.get('/api/artec/events/buka_lumbung')
        consumed_read = client.get('/api/artec/events/buka_lumbung')

        ack_flag = client.post('/api/event-flags', json={'name': 'tutup_lumbung', 'mode': 'ack'})
        client.put('/api/event-flags/tutup_lumbung', json={'active': True})
        held_read_1 = client.get('/api/artec/events/tutup_lumbung')
        held_read_2 = client.get('/api/artec/events/tutup_lumbung')
        reset = client.post('/api/artec/events/tutup_lumbung?value=false')
        reset_read = client.get('/api/artec/events/tutup_lumbung')
        flags = client.get('/api/event-flags').json()

    assert one_shot.status_code == 201
    assert first_read.text == 'true'
    assert consumed_read.text == 'false'
    assert ack_flag.status_code == 201
    assert held_read_1.text == held_read_2.text == 'true'
    assert reset.text == 'tersimpan'
    assert reset_read.text == 'false'
    assert {flag['name']: flag['mode'] for flag in flags} == {
        'buka_lumbung': 'once',
        'tutup_lumbung': 'ack',
    }


def test_artec_aliases_cover_json_collections_and_snapshots(tmp_path: Path) -> None:
    app = create_app(
        tmp_path / 'test.db',
        FakeClassifier(),
        weather_provider=lambda: {'condition': 'Cerah', 'temperature_c': 23.5},
    )
    with TestClient(app) as client:
        status = client.post('/api/artec/devices/status?device_id=core-1&status=hidup')
        telemetry = client.post('/api/artec/telemetry?uptime_seconds=7250&status=running')
        reading = client.post(
            '/api/artec/devices/core-1/readings'
            '?sensor_id=light-1&sensor_type=light&value=360&unit=lux'
        )
        component = client.post(
            '/api/artec/components?component_id=lamp-1&name=Lampu&component_type=light&device_id=core-1'
        )
        component_record = client.get('/api/artec/components/lamp-1')
        telemetry_list = client.get('/api/artec/telemetry?limit=10')
        readings = client.get('/api/artec/readings?device_id=core-1&limit=10')
        condition_reports = client.get('/api/artec/component-condition-reports?device_id=core-1')
        device_record = client.get('/api/artec/devices/core-1')
        dashboard = client.get('/api/artec/dashboard')
        control = client.get('/api/artec/control/state')
        weather = client.get('/api/artec/weather')
        prediction = client.get('/api/artec/predictions/latest')
        access = client.get('/api/artec/access/latest')

    assert status.text == 'hidup'
    assert telemetry.text == 'tersimpan'
    assert reading.text == 'tersimpan'
    assert component.text == 'tersimpan'
    assert '7250|running|' in telemetry_list.text
    assert 'core-1|light-1|light|360.0|lux|' in readings.text
    assert 'lamp-1|Lampu|light|core-1|' in component_record.text
    assert 'core-1|Core Unit 1|hidup|online|' in device_record.text
    assert condition_reports.text == 'kosong'
    assert 'uptime_seconds|7250' in dashboard.text
    assert 'emergency_mode|false' in control.text
    assert 'temperature_c|23.5' in weather.text
    assert prediction.text == 'tidak_ada_data'
    assert access.text.startswith('unknown|false|')


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


def test_device_name_update_preserves_status_and_heartbeat(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        client.post('/api/devices/core-1/status?status=hidup')
        before = client.get('/api/devices/core-1/status').json()
        renamed = client.put('/api/devices/core-1', json={'name': 'Core Unit Pengering'})
        after = client.get('/api/devices/core-1/status').json()
        unknown = client.put('/api/devices/core-99', json={'name': 'Core Unit 99'})
        blank = client.put('/api/devices/core-1', json={'name': '   '})

    assert renamed.status_code == 200
    assert renamed.json()['name'] == 'Core Unit Pengering'
    assert after['name'] == 'Core Unit Pengering'
    assert after['status'] == before['status']
    assert after['last_seen'] == before['last_seen']
    assert unknown.status_code == 404
    assert blank.status_code == 422


def test_sensor_readings_accept_json_and_url_parameters(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        json_reading = client.post(
            '/api/devices/core-1/readings',
            json={
                'sensor_id': 'light-1',
                'sensor_type': 'light',
                'value': 360,
                'unit': 'lux',
            },
        )
        query_reading = client.post(
            '/api/devices/core-2/readings'
            '?sensor_id=sound-1&sensor_type=sound&value=47&unit=dB'
        )
        history = client.get('/api/readings?limit=10').json()
        device = next(
            item for item in client.get('/api/devices').json()
            if item['device_id'] == 'core-1'
        )
        unknown_device = client.post(
            '/api/devices/alat-7/readings',
            json={'sensor_id': 'light-1', 'sensor_type': 'light', 'value': 1},
        )

    assert json_reading.status_code == 201
    assert json_reading.json()['value'] == 360
    assert json_reading.json()['unit'] == 'lux'
    assert query_reading.status_code == 201
    assert len(history) == 2
    assert device['status'] == 'hidup'
    assert device['connection_status'] == 'online'
    assert unknown_device.status_code == 404


def test_scratch_variables_round_trip_json_and_artec_text(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        number_written = client.post('/api/variables/jumlah_panen', json={'value': 42})
        number_read = client.get('/api/variables/jumlah_panen')
        text_written = client.post(
            '/api/artec/variables/status_jemur?value=sedang%20dijemur'
        )
        text_read = client.get('/api/artec/variables/status_jemur')
        typed_written = client.post('/api/artec/variables/siap?value=true')
        typed_read = client.get('/api/variables/siap')
        all_variables = client.get('/api/variables')
        text_variables = client.get('/api/artec/variables')
        missing_variable = client.get('/api/artec/variables/belum_ada')

    assert number_written.status_code == 200
    assert number_read.json()['value'] == 42
    assert isinstance(number_read.json()['value'], int)
    assert text_written.text == 'tersimpan'
    assert text_read.text == 'sedang dijemur'
    assert typed_written.text == 'tersimpan'
    assert typed_read.json()['value'] is True
    assert {item['name'] for item in all_variables.json()} == {
        'jumlah_panen', 'siap', 'status_jemur'
    }
    assert 'status_jemur|sedang dijemur|' in text_variables.text
    assert missing_variable.text == 'tidak_ada'


def test_component_condition_reports_keep_history_and_enforce_owner(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        component = client.post(
            '/api/components',
            json={
                'component_id': 'elevator-motor-1',
                'name': 'Motor elevator 1',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
            },
        )
        first_report = client.post(
            '/api/devices/core-1/components/elevator-motor-1/status?condition=normal'
        )
        second_report = client.post(
            '/api/devices/core-1/components/elevator-motor-1/status?condition=perlu_dicek'
        )
        wrong_owner = client.post(
            '/api/devices/core-2/components/elevator-motor-1/status?condition=rusak'
        )
        unknown_component = client.post(
            '/api/devices/core-1/components/missing/status?condition=normal'
        )
        unmapped_component = client.post(
            '/api/devices/core-1/components/inventory-dc-motors/status?condition=normal'
        )
        empty_condition = client.post(
            '/api/devices/core-1/components/elevator-motor-1/status?condition=%20%20'
        )
        oversized_condition = client.post(
            '/api/devices/core-1/components/elevator-motor-1/status?condition='
            f'{"x" * 81}'
        )
        latest_component = next(
            item for item in client.get('/api/components').json()
            if item['component_id'] == 'elevator-motor-1'
        )
        history = client.get(
            '/api/component-condition-reports?device_id=core-1'
            '&component_id=elevator-motor-1&limit=10'
        )
        component_position = latest_component['current_value']

    assert component.status_code == 201
    assert first_report.status_code == 201
    assert first_report.json()['condition'] == 'normal'
    assert second_report.status_code == 201
    assert wrong_owner.status_code == 404
    assert unknown_component.status_code == 404
    assert unmapped_component.status_code == 404
    assert empty_condition.status_code == 422
    assert oversized_condition.status_code == 422
    assert latest_component['reported_condition'] == 'perlu_dicek'
    assert latest_component['condition_reported_at'] == second_report.json()['reported_at']
    assert [item['condition'] for item in history.json()] == ['perlu_dicek', 'normal']
    assert component_position is None


def test_six_devices_can_report_status(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        initial = client.get('/api/devices')
        updated = client.post(
            '/api/devices/status',
            json={'device_id': 'core-2', 'status': 'hidup'},
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
            '/api/devices/status?device_id=core-3&status=hidup'
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
    assert initial.json()[0]['name'] == 'Core Unit 1'
    assert updated.status_code == 200
    assert updated.json()['status'] == 'hidup'
    assert updated.json()['last_seen'] is not None
    assert next(device for device in statuses if device['device_id'] == 'core-2')['status'] == 'hidup'
    assert created.status_code == 201
    assert created.json()['name'] == 'Pompa Air'
    assert created_status.json()['status'] == 'mati'
    assert url_status.status_code == 200
    assert url_status.json()['status'] == 'hidup'
    assert missing_status.status_code == 422
    assert next(device for device in statuses if device['device_id'] == 'pompa-air')['status'] == 'mati'
    assert duplicate.status_code == 409


def test_core_status_endpoint_expires_to_mati_after_ten_seconds(tmp_path: Path) -> None:
    database_path = tmp_path / 'test.db'
    app = create_app(database_path, FakeClassifier())
    with TestClient(app) as client:
        heartbeat = client.post('/api/devices/core-1/status', json={'status': 'hidup'})
        current_status = client.get('/api/devices/core-1/status')
        url_heartbeat = client.post('/api/devices/core-2/status?status=hidup')
        with sqlite3.connect(database_path) as connection:
            expired_at = (datetime.now(timezone.utc) - timedelta(seconds=11)).isoformat()
            connection.execute(
                'UPDATE device_status SET last_seen = ? WHERE device_id = ?',
                (expired_at, 'core-1'),
            )
        expired = next(
            item for item in client.get('/api/devices').json()
            if item['device_id'] == 'core-1'
        )
        unknown_core = client.post('/api/devices/core-unknown/status', json={'status': 'hidup'})
        unknown_status = client.get('/api/devices/core-unknown/status')

    assert heartbeat.status_code == 200
    assert heartbeat.json()['status'] == 'hidup'
    assert current_status.status_code == 200
    assert current_status.json()['status'] == 'hidup'
    assert current_status.json()['connection_status'] == 'online'
    assert url_heartbeat.status_code == 200
    assert url_heartbeat.json()['status'] == 'hidup'
    assert expired['status'] == 'mati'
    assert expired['connection_status'] == 'stale'
    assert expired['age_seconds'] >= 10
    assert unknown_core.status_code == 404
    assert unknown_status.status_code == 404


def test_estimated_component_inventory_stays_unassigned_and_disabled(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        response = client.get('/api/components')

    components = {component['component_id']: component for component in response.json()}
    assert components['inventory-dc-motors']['estimated_count'] == 'sekitar 4'
    assert components['inventory-servos']['estimated_count'] == '6'
    assert components['inventory-light-sensors']['estimated_count'] == '2'
    assert components['inventory-sound-sensors']['estimated_count'] == '4'
    assert components['inventory-ir-photoreflectors']['estimated_count'] == 'belum pasti'
    assert all(component['device_id'] is None for component in components.values())
    assert all(not component['confirmed'] and not component['enabled'] for component in components.values())


def test_legacy_command_table_migrates_to_device_scoped_columns(tmp_path: Path) -> None:
    database_path = tmp_path / 'legacy.db'
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            '''
            CREATE TABLE actuator_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actuator TEXT NOT NULL,
                position TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                completed_at TEXT,
                detail TEXT NOT NULL DEFAULT ''
            )
            '''
        )

    app = create_app(database_path, FakeClassifier())
    with TestClient(app):
        with sqlite3.connect(database_path) as connection:
            columns = {
                row[1] for row in connection.execute('PRAGMA table_info(actuator_commands)')
            }
            component_columns = {
                row[1] for row in connection.execute('PRAGMA table_info(device_components)')
            }
            condition_report_tables = {
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }

    assert {'device_id', 'component_id'} <= columns
    assert {'device_id', 'estimated_count', 'confirmed', 'enabled'} <= component_columns
    assert 'component_condition_reports' in condition_report_tables


def test_device_status_reports_stale_and_never_seen_connections(tmp_path: Path) -> None:
    database_path = tmp_path / 'test.db'
    app = create_app(database_path, FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/devices/status',
            json={'device_id': 'core-1', 'status': 'hidup'},
        )
        stale_time = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                'UPDATE device_status SET last_seen = ? WHERE device_id = ?',
                (stale_time, 'core-1'),
            )
        devices = client.get('/api/devices').json()

    stale_device = next(device for device in devices if device['device_id'] == 'core-1')
    never_seen_device = next(device for device in devices if device['device_id'] == 'core-2')
    assert stale_device['status'] == 'mati'
    assert stale_device['connection_status'] == 'stale'
    assert stale_device['age_seconds'] >= 60
    assert never_seen_device['connection_status'] == 'never_seen'
    assert never_seen_device['age_seconds'] is None
    

def test_legacy_alat_ids_migrate_to_core_ids_and_keep_history(tmp_path: Path) -> None:
    database_path = tmp_path / 'legacy-device-ids.db'
    app = create_app(database_path, FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/components',
            json={
                'component_id': 'motor-1',
                'name': 'Motor 1',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
            },
        )
        client.post(
            '/api/devices/core-1/readings',
            json={'sensor_id': 'light-1', 'sensor_type': 'light', 'value': 360},
        )
        client.post('/api/devices/core-1/components/motor-1/status?condition=normal')
        client.post('/api/devices/core-1/status?status=hidup')

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "UPDATE device_status SET device_id = 'alat-1', name = 'Alat 1' "
            "WHERE device_id = 'core-1'"
        )
        for table in (
            'sensor_readings',
            'device_components',
            'component_condition_reports',
            'actuator_commands',
        ):
            connection.execute(
                f"UPDATE {table} SET device_id = 'alat-1' WHERE device_id = 'core-1'"
            )
        connection.execute(
            "UPDATE operation_events SET source = 'alat-1' WHERE source = 'core-1'"
        )

    migrated_app = create_app(database_path, FakeClassifier())
    with TestClient(migrated_app) as client:
        devices = client.get('/api/devices').json()
        readings = client.get('/api/readings?device_id=core-1').json()
        components = client.get('/api/components?device_id=core-1').json()
        reports = client.get(
            '/api/component-condition-reports?device_id=core-1&component_id=motor-1'
        ).json()
        events = client.get('/api/events?limit=20').json()

    assert {device['device_id'] for device in devices} == {
        f'core-{number}' for number in range(1, 7)
    }
    assert next(device for device in devices if device['device_id'] == 'core-1')['name'] == 'Core Unit 1'
    assert readings[0]['device_id'] == 'core-1'
    assert components[0]['device_id'] == 'core-1'
    assert reports[0]['device_id'] == 'core-1'
    assert any(event['source'] == 'core-1' for event in events)


def test_unacknowledged_command_times_out_and_is_logged(tmp_path: Path) -> None:
    database_path = tmp_path / 'test.db'
    app = create_app(database_path, FakeClassifier())
    with TestClient(app) as client:
        client.post('/api/control/actuators/roof', json={'position': 'open'})
        command = client.get('/api/device/commands').json()[0]
        stale_time = (datetime.now(timezone.utc) - timedelta(seconds=90)).isoformat()
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                'UPDATE actuator_commands SET requested_at = ? WHERE id = ?',
                (stale_time, command['id']),
            )
        state = client.get('/api/control/state').json()
        events = client.get('/api/events').json()
        late_ack = client.post(
            f"/api/device/commands/{command['id']}/ack",
            json={'actual_position': 'open'},
        )

    assert state['pending_commands'] == []
    assert next(event for event in events if event['event_type'] == 'actuator_timeout')
    assert late_ack.status_code == 404


def test_device_commands_are_authenticated_and_scoped_to_component_owner(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        'AGRO_DEVICE_TOKENS',
        '{"core-1":"device-token-1","core-2":"device-token-2"}',
    )
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        for device_id in ('core-1', 'core-2'):
            client.post(
                '/api/devices/status',
                json={'device_id': device_id, 'status': 'hidup'},
            )
        component = client.post(
            '/api/components',
            json={
                'component_id': 'elevator-motor-1',
                'name': 'Motor elevator 1',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
                'confirmed': True,
                'enabled': True,
                'command_values': ['forward', 'reverse', 'stop'],
                'safe_value': 'stop',
            },
        )
        command = client.post(
            '/api/devices/core-1/components/elevator-motor-1/commands',
            json={'position': 'forward'},
        )
        missing_token = client.get('/api/devices/core-1/commands')
        invalid_token = client.get(
            '/api/devices/core-1/commands?X-Device-Token=wrong-token'
        )
        owner_commands = client.get(
            '/api/devices/core-1/commands?X-Device-Token=device-token-1',
        )
        artec_owner_commands = client.get(
            '/api/artec/devices/core-1/commands?X-Device-Token=device-token-1',
        )
        legacy_commands = client.get('/api/device/commands')
        other_commands = client.get(
            '/api/devices/core-2/commands?X-Device-Token=device-token-2',
        )
        wrong_owner_ack = client.post(
            f"/api/devices/core-2/commands/{command.json()['id']}/ack?X-Device-Token=device-token-2",
            json={'actual_position': 'forward'},
        )
        legacy_ack = client.post(
            f"/api/device/commands/{command.json()['id']}/ack",
            json={'actual_position': 'forward'},
        )
        acknowledged = client.post(
            f"/api/devices/core-1/commands/{command.json()['id']}/ack?X-Device-Token=device-token-1",
            json={'actual_position': 'forward'},
        )
        artec_command = client.post(
            '/api/devices/core-1/components/elevator-motor-1/commands',
            json={'position': 'reverse'},
        )
        artec_acknowledged = client.post(
            f"/api/artec/devices/core-1/commands/{artec_command.json()['id']}/ack"
            '?actual_position=reverse&X-Device-Token=device-token-1',
        )
        openapi = client.get('/openapi.json').json()
        components = client.get('/api/components?device_id=core-1').json()

    assert component.status_code == 201
    assert command.status_code == 200
    assert missing_token.status_code == 401
    assert invalid_token.status_code == 401
    assert [item['id'] for item in owner_commands.json()] == [command.json()['id']]
    assert str(command.json()['id']) in artec_owner_commands.text
    assert other_commands.json() == []
    assert legacy_commands.json() == []
    assert wrong_owner_ack.status_code == 404
    assert legacy_ack.status_code == 404
    assert acknowledged.status_code == 200
    assert artec_command.status_code == 200
    assert artec_acknowledged.status_code == 200
    assert components[0]['current_value'] == 'reverse'
    poll_parameters = openapi['paths']['/api/devices/{device_id}/commands']['get']['parameters']
    assert any(parameter['name'] == 'X-Device-Token' and parameter['in'] == 'query' for parameter in poll_parameters)


def test_unconfirmed_component_cannot_be_controlled(tmp_path: Path) -> None:
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/devices/status',
            json={'device_id': 'core-1', 'status': 'hidup'},
        )
        component = client.post(
            '/api/components',
            json={
                'component_id': 'unknown-motor',
                'name': 'Motor belum dipetakan',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
                'command_values': ['forward', 'stop'],
            },
        )
        command = client.post(
            '/api/devices/core-1/components/unknown-motor/commands',
            json={'position': 'forward'},
        )

    assert component.status_code == 201
    assert command.status_code == 409


def test_emergency_replaces_pending_component_command_with_safe_value(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv('AGRO_DEVICE_TOKENS', '{"core-1":"device-token-1"}')
    app = create_app(tmp_path / 'test.db', FakeClassifier())
    with TestClient(app) as client:
        client.post(
            '/api/devices/status',
            json={'device_id': 'core-1', 'status': 'hidup'},
        )
        client.post(
            '/api/components',
            json={
                'component_id': 'elevator-motor-1',
                'name': 'Motor elevator 1',
                'component_type': 'dc_motor',
                'device_id': 'core-1',
                'confirmed': True,
                'enabled': True,
                'command_values': ['forward', 'stop'],
                'safe_value': 'stop',
            },
        )
        client.post(
            '/api/devices/core-1/components/elevator-motor-1/commands',
            json={'position': 'forward'},
        )
        emergency = client.post('/api/emergency', json={'enabled': True})
        commands = client.get(
            '/api/devices/core-1/commands?X-Device-Token=device-token-1',
        ).json()
        blocked = client.post(
            '/api/devices/core-1/components/elevator-motor-1/commands',
            json={'position': 'forward'},
        )

    assert emergency.status_code == 200
    assert len(commands) == 1
    assert commands[0]['position'] == 'stop'
    assert commands[0]['source'] == 'emergency'
    assert blocked.status_code == 409


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