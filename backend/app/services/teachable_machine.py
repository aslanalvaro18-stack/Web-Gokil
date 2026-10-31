import io
from pathlib import Path


class ModelUnavailableError(Exception):
    pass


class InvalidImageError(Exception):
    pass


class TeachableMachineClassifier:
    def __init__(self, model_path: Path, labels_path: Path) -> None:
        self.model_path = model_path
        self.labels_path = labels_path
        self._model = None
        self._labels: list[str] | None = None

    def _load_model(self):
        if not self.model_path.is_file():
            raise ModelUnavailableError(
                f'Model belum dipasang. Letakkan keras_model.h5 di {self.model_path}.'
            )
        if not self.labels_path.is_file():
            raise ModelUnavailableError(
                f'File labels.txt belum dipasang di {self.labels_path}.'
            )

        try:
            import tensorflow as tf
        except ImportError as error:
            raise ModelUnavailableError(
                'TensorFlow belum terpasang. Instal backend/requirements-ml.txt.'
            ) from error

        try:
            self._model = tf.keras.models.load_model(self.model_path, compile=False)
            self._labels = [
                line.strip().split(' ', 1)[-1]
                for line in self.labels_path.read_text(encoding='utf-8').splitlines()
                if line.strip()
            ]
        except Exception as error:
            self._model = None
            self._labels = None
            raise ModelUnavailableError(f'Model Teachable Machine tidak dapat dimuat: {error}') from error

        if not self._labels:
            raise ModelUnavailableError('labels.txt kosong atau tidak memiliki kelas.')

    def predict(self, image_bytes: bytes) -> tuple[str, float]:
        if self._model is None or self._labels is None:
            self._load_model()

        try:
            import numpy as np
            from PIL import Image, UnidentifiedImageError

            with Image.open(io.BytesIO(image_bytes)) as source:
                image = source.convert('RGB').resize((224, 224))
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise InvalidImageError('File yang dikirim bukan gambar yang valid.') from error
        except ImportError as error:
            raise ModelUnavailableError('Pillow dan NumPy belum terpasang di backend.') from error

        image_array = np.asarray(image, dtype=np.float32)
        image_array = (image_array / 127.5) - 1
        scores = np.asarray(self._model.predict(np.expand_dims(image_array, axis=0), verbose=0))[0]
        class_index = int(np.argmax(scores))
        if class_index >= len(self._labels):
            raise ModelUnavailableError('Jumlah labels tidak cocok dengan keluaran model.')
        return self._labels[class_index], float(scores[class_index])