# Model Teachable Machine

Salin ekspor model **klasifikasi gambar wajah** Teachable Machine ke folder ini:

- `keras_model.h5`
- `labels.txt`

Model dimuat secara malas pada permintaan prediksi pertama. Backend mengubah gambar menjadi RGB 224x224 dan menormalisasi piksel ke rentang -1 sampai 1, sesuai ekspor image model Teachable Machine.

Gunakan label kelas per orang yang diizinkan, misalnya `owner`, dan satu atau lebih kelas `unknown`/`visitor`. Atur label yang diizinkan melalui `AGRO_TRUSTED_LABELS`; confidence minimum diatur dengan `AGRO_MIN_CONFIDENCE` (default 0.85). Confidence rendah selalu menghasilkan `unknown`.

Model klasifikasi gambar bukan pemeriksa keaslian wajah. Ia tidak mendeteksi foto cetak, layar, atau video, jadi keputusan ini tidak boleh menjadi satu-satunya faktor untuk membuka pintu.