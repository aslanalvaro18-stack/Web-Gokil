import json
import time
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen


class WeatherUnavailableError(Exception):
    pass


WEATHER_CODES = {
    0: 'Cerah',
    1: 'Cerah berawan',
    2: 'Berawan sebagian',
    3: 'Mendung',
    45: 'Berkabut',
    48: 'Kabut tebal',
    51: 'Gerimis ringan',
    53: 'Gerimis',
    55: 'Gerimis lebat',
    61: 'Hujan ringan',
    63: 'Hujan',
    65: 'Hujan lebat',
    71: 'Salju ringan',
    73: 'Salju',
    75: 'Salju lebat',
    80: 'Hujan lokal ringan',
    81: 'Hujan lokal',
    82: 'Hujan lokal lebat',
    95: 'Badai petir',
    96: 'Badai petir dan hujan es',
    99: 'Badai petir lebat',
}
WEATHER_CACHE_SECONDS = 60
_weather_cache_lock = Lock()
_weather_cache_time = 0.0
_weather_cache: dict | None = None


def get_pakem_weather() -> dict:
    global _weather_cache, _weather_cache_time
    with _weather_cache_lock:
        if _weather_cache and time.monotonic() - _weather_cache_time < WEATHER_CACHE_SECONDS:
            return dict(_weather_cache)

    query = urlencode(
        {
            'latitude': -7.66,
            'longitude': 110.42,
            'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m,is_day',
            'timezone': 'Asia/Jakarta',
        }
    )
    request_url = f'https://api.open-meteo.com/v1/forecast?{query}'
    try:
        with urlopen(request_url, timeout=8) as response:
            payload = json.loads(response.read())
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise WeatherUnavailableError('Data cuaca Pakem tidak dapat diambil saat ini.') from error

    current = payload.get('current')
    if not isinstance(current, dict) or 'temperature_2m' not in current:
        raise WeatherUnavailableError('Respons layanan cuaca tidak memiliki data terkini.')

    weather_code = int(current.get('weather_code', -1))
    result = {
        'location': 'Pakem, Sleman',
        'temperature_c': current.get('temperature_2m'),
        'apparent_temperature_c': current.get('apparent_temperature'),
        'humidity_percent': current.get('relative_humidity_2m'),
        'precipitation_mm': current.get('precipitation'),
        'wind_speed_kmh': current.get('wind_speed_10m'),
        'weather_code': weather_code,
        'is_day': bool(current.get('is_day', 0)),
        'condition': WEATHER_CODES.get(weather_code, 'Kondisi tidak diketahui'),
        'observed_at': current.get('time'),
    }
    with _weather_cache_lock:
        _weather_cache = result
        _weather_cache_time = time.monotonic()
    return dict(result)