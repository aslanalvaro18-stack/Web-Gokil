from app.services.local_camera import LocalCameraService


class FakeEncodedFrame:
    def tobytes(self) -> bytes:
        return b'jpeg-frame'


class FakeCapture:
    def __init__(self, device_path: str, working_devices: set[str]) -> None:
        self.device_path = device_path
        self.working_devices = working_devices

    def isOpened(self) -> bool:
        return True

    def set(self, _property: int, _value: int) -> None:
        return None

    def read(self) -> tuple[bool, object | None]:
        return self.device_path in self.working_devices, object()

    def release(self) -> None:
        return None


class FakeOpenCV:
    CAP_V4L2 = 200
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4

    def __init__(self, working_devices: set[str] | None = None) -> None:
        self.opened_devices: list[str] = []
        self.working_devices = working_devices or {'/dev/video1'}

    def VideoCapture(self, device_path: str, _backend: int) -> FakeCapture:
        self.opened_devices.append(device_path)
        return FakeCapture(device_path, self.working_devices)

    def imencode(self, _extension: str, _frame: object) -> tuple[bool, FakeEncodedFrame]:
        return True, FakeEncodedFrame()


def test_scanner_checks_every_device_and_selects_first_working_camera() -> None:
    opencv = FakeOpenCV()
    service = LocalCameraService(
        camera_paths=lambda: ['/dev/video0', '/dev/video1', '/dev/video2'],
        cv2_module=opencv,
    )

    capture = service._scan_for_capture()

    assert capture is not None
    assert opencv.opened_devices[:3] == ['/dev/video0', '/dev/video1', '/dev/video2']
    assert opencv.opened_devices[-1] == '/dev/video1'
    assert service.get_status()['state'] == 'online'
    assert service.get_status()['active_device'] == '/dev/video1'
    assert service.latest_frame() == b'jpeg-frame'
    capture.release()


def test_scanner_prefers_physical_camera_over_virtual_camera(monkeypatch) -> None:
    opencv = FakeOpenCV(working_devices={'/dev/video0', '/dev/video1'})
    service = LocalCameraService(
        camera_paths=lambda: ['/dev/video0', '/dev/video1'],
        cv2_module=opencv,
    )
    monkeypatch.setattr(
        service,
        '_device_name',
        lambda path: 'Iriun Webcam' if path == '/dev/video0' else 'HP TrueVision HD Camera',
    )

    capture = service._scan_for_capture()

    assert capture is not None
    assert service.get_status()['active_device'] == '/dev/video1'
    capture.release()