import glob
import importlib
import os
import threading
from pathlib import Path
from typing import Callable


class LocalCameraService:
    def __init__(
        self,
        *,
        camera_paths: Callable[[], list[str]] | None = None,
        cv2_module=None,
        retry_seconds: float = 5,
    ) -> None:
        self._camera_paths_source = camera_paths or self._find_camera_paths
        self._cv2 = cv2_module
        self._retry_seconds = retry_seconds
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._rescan_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest_frame: bytes | None = None
        self._status = {
            'state': 'stopped',
            'active_device': None,
            'active_name': None,
            'devices': [],
            'message': 'Kamera belum dijalankan.',
        }

    @staticmethod
    def _find_camera_paths() -> list[str]:
        paths = glob.glob('/dev/video[0-9]*')
        return sorted(paths, key=lambda path: int(Path(path).name.removeprefix('video')))

    @staticmethod
    def _device_name(device_path: str) -> str:
        device_name = Path(device_path).name
        name_path = Path('/sys/class/video4linux') / device_name / 'name'
        try:
            return name_path.read_text(encoding='utf-8').strip() or device_name
        except OSError:
            return device_name

    @staticmethod
    def _is_virtual_camera(name: str) -> bool:
        normalized_name = name.casefold()
        return any(marker in normalized_name for marker in ('iriun', 'loopback', 'virtual', 'obs'))

    def _load_cv2(self):
        if self._cv2 is None:
            self._cv2 = importlib.import_module('cv2')
        return self._cv2

    def _set_status(self, **updates) -> None:
        with self._lock:
            self._status.update(updates)

    def get_status(self) -> dict:
        with self._lock:
            return {
                **self._status,
                'devices': [dict(device) for device in self._status['devices']],
            }

    def latest_frame(self) -> bytes | None:
        with self._lock:
            return self._latest_frame

    def start(self) -> dict:
        if self._thread is not None and self._thread.is_alive():
            return self.get_status()
        self._stop_event.clear()
        self._rescan_event.set()
        self._set_status(state='scanning', message='Memindai semua kamera Linux...')
        self._thread = threading.Thread(target=self._run, name='local-camera', daemon=True)
        self._thread.start()
        return self.get_status()

    def rescan(self) -> dict:
        if self._thread is None or not self._thread.is_alive():
            return self.start()
        self._set_status(state='scanning', message='Memindai ulang semua kamera Linux...')
        self._rescan_event.set()
        return self.get_status()

    def stop(self) -> None:
        self._stop_event.set()
        self._rescan_event.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
        self._set_status(state='stopped', message='Kamera dihentikan.')

    def _open_capture(self, cv2, device_path: str):
        backend = getattr(cv2, 'CAP_V4L2', 0)
        capture = cv2.VideoCapture(device_path, backend)
        if capture.isOpened():
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        return capture

    def _scan_for_capture(self):
        self._set_status(
            state='scanning',
            active_device=None,
            active_name=None,
            devices=[],
            message='Memindai semua kamera Linux...',
        )
        try:
            cv2 = self._load_cv2()
        except ImportError:
            self._set_status(
                state='unavailable',
                message='OpenCV belum terpasang. Jalankan ulang ./run.sh untuk memasang dependency kamera.',
            )
            return None

        paths = self._camera_paths_source()
        if not paths:
            self._set_status(state='offline', message='Tidak ditemukan device kamera /dev/video*.')
            return None

        devices = []
        for device_path in paths:
            device = {
                'device': device_path,
                'name': self._device_name(device_path),
                'available': False,
                'message': 'Sedang diuji...',
            }
            capture = None
            try:
                capture = self._open_capture(cv2, device_path)
                if not capture.isOpened():
                    device['message'] = (
                        'Akses ditolak; periksa izin grup video.'
                        if not os.access(device_path, os.R_OK)
                        else 'Tidak dapat membuka device video.'
                    )
                else:
                    ok, frame = capture.read()
                    if ok and frame is not None:
                        device['available'] = True
                        device['message'] = 'Kamera siap.'
                    else:
                        device['message'] = 'Tidak menghasilkan frame video.'
            except Exception as error:
                device['message'] = f'Gagal memeriksa kamera: {error}'
            finally:
                if capture is not None:
                    capture.release()
            devices.append(device)
            self._set_status(devices=devices)

        available_devices = [device for device in devices if device['available']]
        selected_device = next(
            (
                device
                for device in available_devices
                if not self._is_virtual_camera(device['name'])
            ),
            available_devices[0] if available_devices else None,
        )
        selected_path = selected_device['device'] if selected_device else None
        if selected_path is None:
            details = '; '.join(
                f"{device['device']}: {device['message']}" for device in devices
            )
            self._set_status(
                state='offline',
                message=f'Tidak ada kamera yang bisa dibuka. {details}',
            )
            return None

        capture = self._open_capture(cv2, selected_path)
        if not capture.isOpened():
            capture.release()
            self._set_status(
                state='offline',
                message=f'Kamera {selected_path} tidak bisa dibuka kembali untuk streaming.',
            )
            return None

        ok, frame = capture.read()
        if not ok or frame is None:
            capture.release()
            self._set_status(
                state='offline',
                message=f'Kamera {selected_path} tidak mengirim frame.',
            )
            return None

        encoded_ok, encoded = cv2.imencode('.jpg', frame)
        if encoded_ok:
            with self._lock:
                self._latest_frame = encoded.tobytes()
        active_name = next(
            device['name'] for device in devices if device['device'] == selected_path
        )
        self._set_status(
            state='online',
            active_device=selected_path,
            active_name=active_name,
            message=f'Kamera aktif: {active_name} ({selected_path}).',
        )
        return capture

    def _run(self) -> None:
        capture = None
        try:
            while not self._stop_event.is_set():
                if capture is None or self._rescan_event.is_set():
                    if capture is not None:
                        capture.release()
                    self._rescan_event.clear()
                    capture = self._scan_for_capture()
                    if capture is None:
                        self._stop_event.wait(self._retry_seconds)
                        self._rescan_event.set()
                        continue

                if self._rescan_event.is_set():
                    continue

                try:
                    ok, frame = capture.read()
                except Exception:
                    ok, frame = False, None
                if not ok or frame is None:
                    capture.release()
                    capture = None
                    self._set_status(
                        state='scanning',
                        active_device=None,
                        active_name=None,
                        message='Kamera terputus; mencoba mendeteksi ulang...',
                    )
                    self._rescan_event.set()
                    continue

                try:
                    cv2 = self._load_cv2()
                    encoded_ok, encoded = cv2.imencode('.jpg', frame)
                    if encoded_ok:
                        with self._lock:
                            self._latest_frame = encoded.tobytes()
                except Exception as error:
                    self._set_status(state='error', message=f'Gagal memproses frame kamera: {error}')
                    self._stop_event.wait(1)
                self._stop_event.wait(0.04)
        finally:
            if capture is not None:
                capture.release()
            if self._stop_event.is_set():
                self._set_status(state='stopped', message='Kamera dihentikan.')