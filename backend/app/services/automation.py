from pathlib import Path
from typing import Callable

from app import database

RAIN_CODES = {51, 53, 55, 61, 63, 65, 80, 81, 82, 95, 96, 99}


def run_automation_cycle(
    database_path: Path,
    weather_provider: Callable[[], dict],
) -> dict | None:
    control = database.get_control_snapshot(database_path)
    if control['mode'] != 'auto' or control['emergency_mode']:
        return None

    roof = next((item for item in control['actuators'] if item['name'] == 'roof'), None)
    if roof is None:
        return None

    target_position = roof['safe_position']
    reason = 'Tidak ada sesi jemur aktif; kembali ke posisi aman.'
    drying_started_at = control['drying_started_at']
    target_seconds = control['drying_target_seconds']

    if drying_started_at and target_seconds:
        if control['drying_elapsed_seconds'] >= target_seconds:
            database.stop_drying_session(database_path, 'auto')
            reason = 'Durasi jemur tercapai; sesi dihentikan otomatis.'
        else:
            try:
                weather = weather_provider()
                is_raining = (
                    float(weather.get('precipitation_mm') or 0) > 0
                    or int(weather.get('weather_code', -1)) in RAIN_CODES
                )
                is_day = bool(weather.get('is_day', False))
                if not is_raining and is_day:
                    target_position = 'open'
                    reason = 'Siang dan tidak hujan; atap dibuka untuk penjemuran.'
                else:
                    reason = 'Hujan atau malam; atap ditutup untuk melindungi alat.'
            except Exception:
                reason = 'Data cuaca tidak tersedia; atap kembali ke posisi aman.'

    has_pending_target = any(
        command['actuator'] == 'roof' and command['position'] == target_position
        for command in control['pending_commands']
    )
    if target_position == roof['target_position'] and (
        roof['current_position'] == target_position or has_pending_target
    ):
        return None

    return database.queue_actuator_command(
        database_path,
        'roof',
        target_position,
        'auto',
        detail=reason,
    )