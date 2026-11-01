import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

DEVICE_IDS = tuple(f'alat-{number}' for number in range(1, 7))
COMMAND_TIMEOUT_SECONDS = 60


@contextmanager
def _connect(database_path: Path) -> Iterator[sqlite3.Connection]:
    if str(database_path) != ':memory:':
        database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database_path), timeout=10)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database(database_path: Path) -> None:
    with _connect(database_path) as connection:
        connection.executescript(
            '''
            CREATE TABLE IF NOT EXISTS telemetry (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uptime_seconds INTEGER NOT NULL CHECK (uptime_seconds >= 0),
                status TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sensor_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                value REAL NOT NULL,
                unit TEXT,
                recorded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS device_status (
                device_id TEXT PRIMARY KEY,
                name TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('belum_terhubung', 'hidup', 'mati')),
                last_seen TEXT
            );
            CREATE TABLE IF NOT EXISTS predictions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                class_name TEXT NOT NULL,
                confidence REAL NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
                captured_at TEXT NOT NULL,
                access_status TEXT NOT NULL DEFAULT 'unknown'
            );
            CREATE TABLE IF NOT EXISTS controller_state (
                singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
                mode TEXT NOT NULL DEFAULT 'manual',
                emergency_mode INTEGER NOT NULL DEFAULT 0,
                drying_started_at TEXT,
                drying_target_seconds INTEGER,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actuator_state (
                name TEXT PRIMARY KEY,
                current_position TEXT NOT NULL DEFAULT 'unknown',
                target_position TEXT NOT NULL,
                safe_position TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actuator_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actuator TEXT NOT NULL,
                position TEXT NOT NULL,
                source TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                requested_at TEXT NOT NULL,
                completed_at TEXT,
                detail TEXT NOT NULL DEFAULT '',
                device_id TEXT,
                component_id TEXT
            );
            CREATE TABLE IF NOT EXISTS device_components (
                component_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                component_type TEXT NOT NULL,
                estimated_count TEXT,
                device_id TEXT,
                confirmed INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 0,
                command_values TEXT NOT NULL DEFAULT '[]',
                safe_value TEXT,
                current_value TEXT,
                target_value TEXT,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS component_condition_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                component_id TEXT NOT NULL,
                condition TEXT NOT NULL,
                reported_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS operation_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                source TEXT NOT NULL,
                actuator TEXT,
                value TEXT,
                duration_seconds INTEGER,
                detail TEXT NOT NULL DEFAULT '{}',
                occurred_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sensor_readings_recorded_at_idx
                ON sensor_readings (recorded_at DESC);
            CREATE INDEX IF NOT EXISTS sensor_readings_device_idx
                ON sensor_readings (device_id, id DESC);
            CREATE INDEX IF NOT EXISTS component_condition_reports_component_idx
                ON component_condition_reports (component_id, id DESC);
            '''
        )
        prediction_columns = {
            row['name'] for row in connection.execute('PRAGMA table_info(predictions)')
        }
        if 'access_status' not in prediction_columns:
            connection.execute(
                "ALTER TABLE predictions ADD COLUMN access_status TEXT NOT NULL DEFAULT 'unknown'"
            )
        device_columns = {
            row['name'] for row in connection.execute('PRAGMA table_info(device_status)')
        }
        if 'name' not in device_columns:
            connection.execute(
                "ALTER TABLE device_status ADD COLUMN name TEXT NOT NULL DEFAULT ''"
            )
        command_columns = {
            row['name'] for row in connection.execute('PRAGMA table_info(actuator_commands)')
        }
        if 'device_id' not in command_columns:
            connection.execute('ALTER TABLE actuator_commands ADD COLUMN device_id TEXT')
        if 'component_id' not in command_columns:
            connection.execute('ALTER TABLE actuator_commands ADD COLUMN component_id TEXT')
        connection.execute(
            'CREATE INDEX IF NOT EXISTS actuator_device_pending_idx '
            'ON actuator_commands (device_id, status, id)'
        )
        component_columns = {
            row['name'] for row in connection.execute('PRAGMA table_info(device_components)')
        }
        if 'estimated_count' not in component_columns:
            connection.execute('ALTER TABLE device_components ADD COLUMN estimated_count TEXT')
        connection.execute("UPDATE device_status SET name = device_id WHERE name = ''")
        now = datetime.now(timezone.utc).isoformat(timespec='seconds')
        connection.execute(
            'INSERT OR IGNORE INTO controller_state (singleton_id, updated_at) VALUES (1, ?)',
            (now,),
        )
        connection.executemany(
            'INSERT OR IGNORE INTO device_status (device_id, name, status) VALUES (?, ?, ?)',
            [
                (device_id, f'Alat {number}', 'belum_terhubung')
                for number, device_id in enumerate(DEVICE_IDS, start=1)
            ],
        )
        for number, device_id in enumerate(DEVICE_IDS, start=1):
            connection.execute(
                'UPDATE device_status SET name = ? WHERE device_id = ? AND name = ?',
                (f'Alat {number}', device_id, device_id),
            )
        connection.executemany(
            '''
            INSERT OR IGNORE INTO device_components
                (component_id, name, component_type, estimated_count, device_id,
                 confirmed, enabled, command_values, updated_at)
            VALUES (?, ?, ?, ?, NULL, 0, 0, '[]', ?)
            ''',
            [
                ('inventory-dc-motors', 'Motor DC (perkiraan)', 'dc_motor_estimate', 'sekitar 4', now),
                ('inventory-servos', 'Servo (perkiraan)', 'servo_estimate', '6', now),
                ('inventory-light-sensors', 'Sensor cahaya (perkiraan)', 'light_sensor_estimate', '2', now),
                ('inventory-sound-sensors', 'Sensor suara (perkiraan)', 'sound_sensor_estimate', '4', now),
                ('inventory-ir-photoreflectors', 'IR photoreflector', 'ir_photoreflector_estimate', 'belum pasti', now),
                ('inventory-other-sensors', 'Sensor lain', 'unconfirmed_inventory', 'belum terkonfirmasi', now),
            ],
        )


def _device_status_with_freshness(record: dict, stale_after_seconds: int) -> dict:
    last_seen = record['last_seen']
    if last_seen is None:
        return {**record, 'connection_status': 'never_seen', 'age_seconds': None}

    seen_at = datetime.fromisoformat(last_seen)
    if seen_at.tzinfo is None:
        seen_at = seen_at.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - seen_at).total_seconds())
    return {
        **record,
        'connection_status': 'stale' if age >= stale_after_seconds else 'online',
        'age_seconds': int(age),
    }


def list_device_status(database_path: Path, stale_after_seconds: int = 30) -> list[dict]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            'SELECT device_id, name, status, last_seen FROM device_status ORDER BY device_id'
        ).fetchall()
    return [_device_status_with_freshness(dict(row), stale_after_seconds) for row in rows]


def get_device_status(database_path: Path, device_id: str) -> dict | None:
    with _connect(database_path) as connection:
        row = connection.execute(
            'SELECT device_id, name, status, last_seen FROM device_status WHERE device_id = ?',
            (device_id,),
        ).fetchone()
    return dict(row) if row else None


def _decode_device_component(row: sqlite3.Row | dict) -> dict:
    component = dict(row)
    component['confirmed'] = bool(component['confirmed'])
    component['enabled'] = bool(component['enabled'])
    component['command_values'] = json.loads(component['command_values'])
    return component


_DEVICE_COMPONENT_SELECT = '''
    SELECT device_components.*,
        (SELECT condition FROM component_condition_reports
         WHERE component_condition_reports.component_id = device_components.component_id
         ORDER BY component_condition_reports.id DESC LIMIT 1) AS reported_condition,
        (SELECT reported_at FROM component_condition_reports
         WHERE component_condition_reports.component_id = device_components.component_id
         ORDER BY component_condition_reports.id DESC LIMIT 1) AS condition_reported_at
    FROM device_components
'''


def list_device_components(database_path: Path, device_id: str | None = None) -> list[dict]:
    with _connect(database_path) as connection:
        if device_id is None:
            rows = connection.execute(
                f'{_DEVICE_COMPONENT_SELECT} ORDER BY component_id'
            ).fetchall()
        else:
            rows = connection.execute(
                f'{_DEVICE_COMPONENT_SELECT} WHERE device_id = ? ORDER BY component_id',
                (device_id,),
            ).fetchall()
    return [_decode_device_component(row) for row in rows]


def get_device_component(database_path: Path, component_id: str) -> dict | None:
    with _connect(database_path) as connection:
        row = connection.execute(
            f'{_DEVICE_COMPONENT_SELECT} WHERE component_id = ?', (component_id,)
        ).fetchone()
    return _decode_device_component(row) if row else None


def create_component_condition_report(
    database_path: Path,
    device_id: str,
    component_id: str,
    condition: str,
) -> dict | None:
    reported_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        component = connection.execute(
            'SELECT device_id FROM device_components WHERE component_id = ?',
            (component_id,),
        ).fetchone()
        if component is None or component['device_id'] != device_id:
            return None
        cursor = connection.execute(
            '''
            INSERT INTO component_condition_reports
                (device_id, component_id, condition, reported_at)
            VALUES (?, ?, ?, ?)
            ''',
            (device_id, component_id, condition, reported_at),
        )
        row = connection.execute(
            'SELECT * FROM component_condition_reports WHERE id = ?',
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def list_component_condition_reports(
    database_path: Path,
    limit: int = 50,
    device_id: str | None = None,
    component_id: str | None = None,
) -> list[dict]:
    clauses = []
    parameters: list[str | int] = []
    if device_id is not None:
        clauses.append('device_id = ?')
        parameters.append(device_id)
    if component_id is not None:
        clauses.append('component_id = ?')
        parameters.append(component_id)
    where_clause = f"WHERE {' AND '.join(clauses)}" if clauses else ''
    parameters.append(limit)
    with _connect(database_path) as connection:
        rows = connection.execute(
            f'''SELECT * FROM component_condition_reports
                {where_clause} ORDER BY id DESC LIMIT ?''',
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def create_device_component(database_path: Path, component: dict) -> dict | None:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    try:
        with _connect(database_path) as connection:
            connection.execute(
                '''
                INSERT INTO device_components
                    (component_id, name, component_type, estimated_count, device_id, confirmed, enabled,
                     command_values, safe_value, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    component['component_id'],
                    component['name'],
                    component['component_type'],
                    component['estimated_count'],
                    component['device_id'],
                    int(component['confirmed']),
                    int(component['enabled']),
                    json.dumps(component['command_values']),
                    component['safe_value'],
                    now,
                ),
            )
            row = connection.execute(
                'SELECT * FROM device_components WHERE component_id = ?',
                (component['component_id'],),
            ).fetchone()
    except sqlite3.IntegrityError:
        return None
    return _decode_device_component(row)


def update_device_component(database_path: Path, component: dict) -> dict | None:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        cursor = connection.execute(
            '''
            UPDATE device_components
            SET name = ?, component_type = ?, estimated_count = ?, device_id = ?, confirmed = ?, enabled = ?,
                command_values = ?, safe_value = ?, updated_at = ?
            WHERE component_id = ?
            ''',
            (
                component['name'],
                component['component_type'],
                component['estimated_count'],
                component['device_id'],
                int(component['confirmed']),
                int(component['enabled']),
                json.dumps(component['command_values']),
                component['safe_value'],
                now,
                component['component_id'],
            ),
        )
        if cursor.rowcount == 0:
            return None
        row = connection.execute(
            'SELECT * FROM device_components WHERE component_id = ?',
            (component['component_id'],),
        ).fetchone()
    return _decode_device_component(row)


def create_device(
    database_path: Path,
    device_id: str,
    name: str,
    stale_after_seconds: int = 30,
) -> dict | None:
    try:
        with _connect(database_path) as connection:
            connection.execute(
                "INSERT INTO device_status (device_id, name, status) VALUES (?, ?, 'belum_terhubung')",
                (device_id, name),
            )
            row = connection.execute(
                'SELECT device_id, name, status, last_seen FROM device_status WHERE device_id = ?',
                (device_id,),
            ).fetchone()
    except sqlite3.IntegrityError:
        return None
    return _device_status_with_freshness(dict(row), stale_after_seconds)


def update_device_status(
    database_path: Path,
    device_id: str,
    status: str,
    stale_after_seconds: int = 30,
) -> dict | None:
    last_seen = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        connection.execute(
            'UPDATE device_status SET status = ?, last_seen = ? WHERE device_id = ?',
            (status, last_seen, device_id),
        )
        row = connection.execute(
            'SELECT device_id, name, status, last_seen FROM device_status WHERE device_id = ?',
            (device_id,),
        ).fetchone()
    return _device_status_with_freshness(dict(row), stale_after_seconds) if row else None


def configure_safe_positions(database_path: Path, safe_positions: dict[str, str]) -> None:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        for name, position in safe_positions.items():
            connection.execute(
                '''
                INSERT INTO actuator_state (name, current_position, target_position, safe_position, updated_at)
                VALUES (?, 'unknown', ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET safe_position = excluded.safe_position
                ''',
                (name, position, position, now),
            )


def save_telemetry(database_path: Path, uptime_seconds: int, status: str) -> dict:
    recorded_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        cursor = connection.execute(
            'INSERT INTO telemetry (uptime_seconds, status, recorded_at) VALUES (?, ?, ?)',
            (uptime_seconds, status, recorded_at),
        )
        row = connection.execute(
            'SELECT id, uptime_seconds, status, recorded_at FROM telemetry WHERE id = ?',
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def list_telemetry(database_path: Path, limit: int) -> list[dict]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            'SELECT id, uptime_seconds, status, recorded_at FROM telemetry ORDER BY id DESC LIMIT ?',
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def latest_telemetry(database_path: Path) -> dict | None:
    with _connect(database_path) as connection:
        row = connection.execute(
            'SELECT id, uptime_seconds, status, recorded_at FROM telemetry ORDER BY id DESC LIMIT 1'
        ).fetchone()
    return dict(row) if row else None


def save_sensor_reading(
    database_path: Path,
    device_id: str,
    sensor_id: str,
    sensor_type: str,
    value: float,
    unit: str | None,
) -> dict | None:
    recorded_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        device = connection.execute(
            'SELECT device_id FROM device_status WHERE device_id = ?', (device_id,)
        ).fetchone()
        if device is None:
            return None
        cursor = connection.execute(
            '''
            INSERT INTO sensor_readings
                (device_id, sensor_id, sensor_type, value, unit, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (device_id, sensor_id, sensor_type, value, unit, recorded_at),
        )
        connection.execute(
            "UPDATE device_status SET status = 'hidup', last_seen = ? WHERE device_id = ?",
            (recorded_at, device_id),
        )
        row = connection.execute(
            'SELECT * FROM sensor_readings WHERE id = ?', (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def list_sensor_readings(
    database_path: Path,
    limit: int,
    device_id: str | None = None,
) -> list[dict]:
    with _connect(database_path) as connection:
        if device_id is None:
            rows = connection.execute(
                'SELECT * FROM sensor_readings ORDER BY id DESC LIMIT ?', (limit,)
            ).fetchall()
        else:
            rows = connection.execute(
                'SELECT * FROM sensor_readings WHERE device_id = ? ORDER BY id DESC LIMIT ?',
                (device_id, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def save_prediction(
    database_path: Path,
    class_name: str,
    confidence: float,
    access_status: str,
) -> dict:
    captured_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        cursor = connection.execute(
            'INSERT INTO predictions (class_name, confidence, captured_at, access_status) VALUES (?, ?, ?, ?)',
            (class_name, confidence, captured_at, access_status),
        )
        row = connection.execute(
            'SELECT id, class_name, confidence, captured_at, access_status FROM predictions WHERE id = ?',
            (cursor.lastrowid,),
        ).fetchone()
    return dict(row)


def latest_prediction(database_path: Path) -> dict | None:
    with _connect(database_path) as connection:
        row = connection.execute(
            'SELECT id, class_name, confidence, captured_at, access_status FROM predictions ORDER BY id DESC LIMIT 1'
        ).fetchone()
    return dict(row) if row else None


def get_dashboard_data(database_path: Path) -> dict:
    return {
        'telemetry': latest_telemetry(database_path),
        'prediction': latest_prediction(database_path),
    }


def add_operation_event(
    database_path: Path,
    event_type: str,
    source: str,
    *,
    actuator: str | None = None,
    value: str | None = None,
    duration_seconds: int | None = None,
    detail: dict | None = None,
) -> dict:
    occurred_at = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        cursor = connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, actuator, value, duration_seconds, detail, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                event_type,
                source,
                actuator,
                value,
                duration_seconds,
                json.dumps(detail or {}, ensure_ascii=True),
                occurred_at,
            ),
        )
        row = connection.execute(
            'SELECT * FROM operation_events WHERE id = ?', (cursor.lastrowid,)
        ).fetchone()
    return _decode_event(dict(row))


def _decode_event(event: dict) -> dict:
    event['detail'] = json.loads(event['detail'])
    return event


def list_operation_events(database_path: Path, limit: int) -> list[dict]:
    with _connect(database_path) as connection:
        rows = connection.execute(
            'SELECT * FROM operation_events ORDER BY id DESC LIMIT ?', (limit,)
        ).fetchall()
    return [_decode_event(dict(row)) for row in rows]


def get_control_snapshot(database_path: Path) -> dict:
    expire_pending_commands(database_path, COMMAND_TIMEOUT_SECONDS)
    now = datetime.now(timezone.utc)
    with _connect(database_path) as connection:
        state_row = connection.execute(
            'SELECT * FROM controller_state WHERE singleton_id = 1'
        ).fetchone()
        actuator_rows = connection.execute(
            'SELECT * FROM actuator_state ORDER BY name'
        ).fetchall()
        command_rows = connection.execute(
            "SELECT * FROM actuator_commands WHERE status = 'pending' ORDER BY id"
        ).fetchall()

    state = dict(state_row)
    state['emergency_mode'] = bool(state['emergency_mode'])
    started_at = state['drying_started_at']
    state['drying_elapsed_seconds'] = (
        max(0, int((now - datetime.fromisoformat(started_at)).total_seconds()))
        if started_at
        else 0
    )
    state['actuators'] = [dict(row) for row in actuator_rows]
    state['pending_commands'] = [dict(row) for row in command_rows]
    return state


def set_control_mode(database_path: Path, mode: str, source: str = 'dashboard') -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        previous = connection.execute(
            'SELECT mode, emergency_mode FROM controller_state WHERE singleton_id = 1'
        ).fetchone()
        if previous['emergency_mode']:
            raise ValueError('Mode tidak dapat diubah saat emergency aktif.')
        connection.execute(
            'UPDATE controller_state SET mode = ?, updated_at = ? WHERE singleton_id = 1',
            (mode, now),
        )
        connection.execute(
            '''
            INSERT INTO operation_events (event_type, source, value, detail, occurred_at)
            VALUES ('mode_changed', ?, ?, ?, ?)
            ''',
            (source, mode, json.dumps({'previous_mode': previous['mode']}), now),
        )
    return get_control_snapshot(database_path)


def set_emergency_mode(database_path: Path, enabled: bool, source: str = 'dashboard') -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        previous = connection.execute(
            'SELECT emergency_mode FROM controller_state WHERE singleton_id = 1'
        ).fetchone()
        if bool(previous['emergency_mode']) == enabled:
            return get_control_snapshot(database_path)

        connection.execute(
            'UPDATE controller_state SET emergency_mode = ?, updated_at = ? WHERE singleton_id = 1',
            (int(enabled), now),
        )
        event_type = 'emergency_activated' if enabled else 'emergency_cleared'
        connection.execute(
            '''
            INSERT INTO operation_events (event_type, source, value, detail, occurred_at)
            VALUES (?, ?, ?, '{}', ?)
            ''',
            (event_type, source, 'on' if enabled else 'off', now),
        )
        if enabled:
            actuators = connection.execute(
                'SELECT name, safe_position FROM actuator_state'
            ).fetchall()
            for actuator in actuators:
                superseded = connection.execute(
                    '''
                    UPDATE actuator_commands
                    SET status = 'superseded', completed_at = ?, detail = 'Superseded by emergency'
                    WHERE actuator = ? AND status = 'pending'
                    ''',
                    (now, actuator['name']),
                ).rowcount
                if superseded:
                    connection.execute(
                        '''
                        INSERT INTO operation_events
                            (event_type, source, actuator, value, detail, occurred_at)
                        VALUES ('actuator_commands_superseded', 'emergency', ?, ?, ?, ?)
                        ''',
                        (
                            actuator['name'],
                            actuator['safe_position'],
                            json.dumps({'count': superseded}),
                            now,
                        ),
                    )
                connection.execute(
                    '''
                    INSERT INTO actuator_commands (actuator, position, source, requested_at, detail)
                    VALUES (?, ?, 'emergency', ?, 'Move to configured safe position')
                    ''',
                    (actuator['name'], actuator['safe_position'], now),
                )
                connection.execute(
                    'UPDATE actuator_state SET target_position = ?, updated_at = ? WHERE name = ?',
                    (actuator['safe_position'], now, actuator['name']),
                )
            components = connection.execute(
                '''
                SELECT * FROM device_components
                WHERE device_id IS NOT NULL AND confirmed = 1 AND enabled = 1
                    AND component_type IN ('dc_motor', 'servo', 'actuator')
                '''
            ).fetchall()
            for component in components:
                command_values = json.loads(component['command_values'])
                safe_value = component['safe_value']
                if safe_value not in command_values:
                    continue
                connection.execute(
                    '''
                    UPDATE actuator_commands
                    SET status = 'superseded', completed_at = ?, detail = 'Superseded by emergency'
                    WHERE component_id = ? AND status = 'pending'
                    ''',
                    (now, component['component_id']),
                )
                cursor = connection.execute(
                    '''
                    INSERT INTO actuator_commands
                        (actuator, position, source, requested_at, detail, device_id, component_id)
                    VALUES (?, ?, 'emergency', ?, 'Move to configured safe value', ?, ?)
                    ''',
                    (
                        component['component_id'],
                        safe_value,
                        now,
                        component['device_id'],
                        component['component_id'],
                    ),
                )
                connection.execute(
                    '''
                    UPDATE device_components SET target_value = ?, updated_at = ?
                    WHERE component_id = ?
                    ''',
                    (safe_value, now, component['component_id']),
                )
                connection.execute(
                    '''
                    INSERT INTO operation_events
                        (event_type, source, actuator, value, detail, occurred_at)
                    VALUES ('actuator_commanded', 'emergency', ?, ?, ?, ?)
                    ''',
                    (
                        component['component_id'],
                        safe_value,
                        json.dumps({
                            'command_id': cursor.lastrowid,
                            'device_id': component['device_id'],
                        }),
                        now,
                    ),
                )
    return get_control_snapshot(database_path)


def queue_actuator_command(
    database_path: Path,
    actuator: str,
    position: str,
    source: str,
    detail: str = '',
) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        known_actuator = connection.execute(
            'SELECT name FROM actuator_state WHERE name = ?', (actuator,)
        ).fetchone()
        if not known_actuator:
            raise KeyError(f'Aktuator {actuator} belum dikonfigurasi.')
        superseded = connection.execute(
            '''
            UPDATE actuator_commands
            SET status = 'superseded', completed_at = ?, detail = 'Superseded by newer target'
            WHERE actuator = ? AND status = 'pending'
            ''',
            (now, actuator),
        ).rowcount
        if superseded:
            connection.execute(
                '''
                INSERT INTO operation_events
                    (event_type, source, actuator, value, detail, occurred_at)
                VALUES ('actuator_commands_superseded', ?, ?, ?, ?, ?)
                ''',
                (
                    source,
                    actuator,
                    position,
                    json.dumps({'count': superseded}),
                    now,
                ),
            )
        cursor = connection.execute(
            '''
            INSERT INTO actuator_commands (actuator, position, source, requested_at, detail)
            VALUES (?, ?, ?, ?, ?)
            ''',
            (actuator, position, source, now, detail),
        )
        connection.execute(
            'UPDATE actuator_state SET target_position = ?, updated_at = ? WHERE name = ?',
            (position, now, actuator),
        )
        connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, actuator, value, detail, occurred_at)
            VALUES ('actuator_commanded', ?, ?, ?, ?, ?)
            ''',
            (source, actuator, position, json.dumps({'command_id': cursor.lastrowid}), now),
        )
        row = connection.execute(
            'SELECT * FROM actuator_commands WHERE id = ?', (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def acknowledge_actuator_command(
    database_path: Path,
    command_id: int,
    actual_position: str,
    success: bool,
    detail: str = '',
    device_id: str | None = None,
) -> dict | None:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        command = connection.execute(
            'SELECT * FROM actuator_commands WHERE id = ?', (command_id,)
        ).fetchone()
        if (
            not command
            or command['status'] != 'pending'
            or (device_id is None and command['device_id'] is not None)
            or (device_id is not None and command['device_id'] != device_id)
        ):
            return None
        status = 'acknowledged' if success else 'failed'
        connection.execute(
            'UPDATE actuator_commands SET status = ?, completed_at = ?, detail = ? WHERE id = ?',
            (status, now, detail, command_id),
        )
        if success:
            connection.execute(
                'UPDATE actuator_state SET current_position = ?, updated_at = ? WHERE name = ?',
                (actual_position, now, command['actuator']),
            )
            if command['component_id']:
                connection.execute(
                    '''
                    UPDATE device_components SET current_value = ?, updated_at = ?
                    WHERE component_id = ? AND device_id = ?
                    ''',
                    (actual_position, now, command['component_id'], command['device_id']),
                )
        event_type = 'actuator_acknowledged' if success else 'actuator_failed'
        connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, actuator, value, detail, occurred_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                event_type,
                command['source'],
                command['actuator'],
                actual_position,
                json.dumps({'command_id': command_id, 'detail': detail}),
                now,
            ),
        )
        row = connection.execute(
            'SELECT * FROM actuator_commands WHERE id = ?', (command_id,)
        ).fetchone()
    return dict(row)


def list_pending_commands(database_path: Path, limit: int) -> list[dict]:
    expire_pending_commands(database_path, COMMAND_TIMEOUT_SECONDS)
    with _connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM actuator_commands WHERE status = 'pending' AND device_id IS NULL ORDER BY id LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_pending_device_commands(database_path: Path, device_id: str, limit: int) -> list[dict]:
    expire_pending_commands(database_path, COMMAND_TIMEOUT_SECONDS)
    with _connect(database_path) as connection:
        rows = connection.execute(
            '''
            SELECT * FROM actuator_commands
            WHERE status = 'pending' AND device_id = ? ORDER BY id LIMIT ?
            ''',
            (device_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def queue_device_component_command(
    database_path: Path,
    device_id: str,
    component_id: str,
    position: str,
    source: str,
    stale_after_seconds: int,
) -> dict:
    now_datetime = datetime.now(timezone.utc)
    now = now_datetime.isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        device = connection.execute(
            'SELECT status, last_seen FROM device_status WHERE device_id = ?',
            (device_id,),
        ).fetchone()
        if device is None:
            raise KeyError('ID alat belum terdaftar.')
        if device['status'] != 'hidup' or device['last_seen'] is None:
            raise ValueError('Alat belum melaporkan status hidup.')
        last_seen = datetime.fromisoformat(device['last_seen'])
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if (now_datetime - last_seen).total_seconds() >= stale_after_seconds:
            raise ValueError('Alat tidak online; command ditolak.')

        component = connection.execute(
            'SELECT * FROM device_components WHERE component_id = ? AND device_id = ?',
            (component_id, device_id),
        ).fetchone()
        if component is None:
            raise KeyError('Komponen tidak terdaftar pada alat ini.')
        if component['component_type'] not in {'dc_motor', 'servo', 'actuator'}:
            raise ValueError('Komponen ini bukan aktuator yang dapat dikendalikan.')
        if not component['confirmed'] or not component['enabled']:
            raise ValueError('Mapping aktuator belum dikonfirmasi dan diaktifkan.')
        command_values = json.loads(component['command_values'])
        if component['safe_value'] not in command_values:
            raise ValueError('Konfigurasi posisi aman aktuator belum valid.')
        if position not in command_values:
            raise ValueError('Nilai command tidak diizinkan untuk aktuator ini.')

        superseded = connection.execute(
            '''
            UPDATE actuator_commands
            SET status = 'superseded', completed_at = ?, detail = 'Superseded by newer target'
            WHERE status = 'pending' AND device_id = ? AND component_id = ?
            ''',
            (now, device_id, component_id),
        ).rowcount
        cursor = connection.execute(
            '''
            INSERT INTO actuator_commands
                (actuator, position, source, requested_at, detail, device_id, component_id)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (component_id, position, source, now, '', device_id, component_id),
        )
        connection.execute(
            '''
            UPDATE device_components SET target_value = ?, updated_at = ?
            WHERE component_id = ? AND device_id = ?
            ''',
            (position, now, component_id, device_id),
        )
        connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, actuator, value, detail, occurred_at)
            VALUES ('actuator_commanded', ?, ?, ?, ?, ?)
            ''',
            (
                source,
                component_id,
                position,
                json.dumps({'command_id': cursor.lastrowid, 'device_id': device_id}),
                now,
            ),
        )
        if superseded:
            connection.execute(
                '''
                INSERT INTO operation_events
                    (event_type, source, actuator, value, detail, occurred_at)
                VALUES ('actuator_commands_superseded', ?, ?, ?, ?, ?)
                ''',
                (
                    source,
                    component_id,
                    position,
                    json.dumps({'count': superseded, 'device_id': device_id}),
                    now,
                ),
            )
        row = connection.execute(
            'SELECT * FROM actuator_commands WHERE id = ?', (cursor.lastrowid,)
        ).fetchone()
    return dict(row)


def expire_pending_commands(database_path: Path, timeout_seconds: int) -> int:
    now = datetime.now(timezone.utc)
    completed_at = now.isoformat(timespec='seconds')
    expired_count = 0
    with _connect(database_path) as connection:
        rows = connection.execute(
            "SELECT * FROM actuator_commands WHERE status = 'pending' ORDER BY id"
        ).fetchall()
        for row in rows:
            requested_at = datetime.fromisoformat(row['requested_at'])
            if requested_at.tzinfo is None:
                requested_at = requested_at.replace(tzinfo=timezone.utc)
            if (now - requested_at).total_seconds() < timeout_seconds:
                continue

            detail = f'Timed out after {timeout_seconds} seconds without ACK'
            connection.execute(
                "UPDATE actuator_commands SET status = 'timeout', completed_at = ?, detail = ? WHERE id = ?",
                (completed_at, detail, row['id']),
            )
            connection.execute(
                '''
                INSERT INTO operation_events
                    (event_type, source, actuator, value, detail, occurred_at)
                VALUES ('actuator_timeout', ?, ?, ?, ?, ?)
                ''',
                (
                    row['source'],
                    row['actuator'],
                    row['position'],
                    json.dumps({'command_id': row['id'], 'timeout_seconds': timeout_seconds}),
                    completed_at,
                ),
            )
            expired_count += 1
    return expired_count


def start_drying_session(database_path: Path, target_seconds: int, source: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        state = connection.execute(
            'SELECT drying_started_at FROM controller_state WHERE singleton_id = 1'
        ).fetchone()
        if state['drying_started_at']:
            raise ValueError('Sesi jemur sudah berjalan.')
        connection.execute(
            '''
            UPDATE controller_state
            SET drying_started_at = ?, drying_target_seconds = ?, updated_at = ?
            WHERE singleton_id = 1
            ''',
            (now, target_seconds, now),
        )
        connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, value, detail, occurred_at)
            VALUES ('drying_started', ?, ?, ?, ?)
            ''',
            (source, str(target_seconds), json.dumps({'target_seconds': target_seconds}), now),
        )
    return get_control_snapshot(database_path)


def stop_drying_session(database_path: Path, source: str) -> dict | None:
    now_datetime = datetime.now(timezone.utc)
    now = now_datetime.isoformat(timespec='seconds')
    with _connect(database_path) as connection:
        state = connection.execute(
            'SELECT drying_started_at, drying_target_seconds FROM controller_state WHERE singleton_id = 1'
        ).fetchone()
        if not state['drying_started_at']:
            return None
        started = datetime.fromisoformat(state['drying_started_at'])
        duration_seconds = max(0, int((now_datetime - started).total_seconds()))
        connection.execute(
            '''
            UPDATE controller_state
            SET drying_started_at = NULL, drying_target_seconds = NULL, updated_at = ?
            WHERE singleton_id = 1
            ''',
            (now,),
        )
        connection.execute(
            '''
            INSERT INTO operation_events
                (event_type, source, value, duration_seconds, detail, occurred_at)
            VALUES ('drying_completed', ?, ?, ?, ?, ?)
            ''',
            (
                source,
                str(state['drying_target_seconds']),
                duration_seconds,
                json.dumps({'started_at': state['drying_started_at']}),
                now,
            ),
        )
    return get_control_snapshot(database_path)