# AGRO-SEMBADA Dashboard

Dashboard pemantauan alat AGRO-SEMBADA oleh Pradnyasiwi QuadTech, SMPN 4 Pakem. Frontend berjalan di browser iPad dan backend Python berjalan di Linux.

## Menjalankan aplikasi

Dari folder proyek, jalankan semua service dengan satu perintah:

```bash
./run.sh
```

Script menyiapkan virtual environment/dependency bila belum tersedia, lalu menjalankan backend dan frontend di background. Untuk menghentikan keduanya:

```bash
./unrun.sh
```

Backend otomatis membuka kamera laptop saat `./run.sh` dijalankan. Untuk menjalankan dashboard tanpa kamera, set `AGRO_CAMERA_AUTOSTART=0` sebelum menjalankan script. Tombol di panel kamera dapat mematikan atau memindai ulang kamera.

Log tersimpan di `.run/backend.log` dan `.run/frontend.log`. Script tidak akan menghentikan proses lain jika port 3000 atau 5173 sudah digunakan.

Pastikan iPad dan komputer Linux berada di jaringan yang sama, lalu buka `http://ALAMAT-IP-LINUX:5173` di iPad. Alamat IP Linux dapat dilihat dengan `hostname -I`. Vite meneruskan `/api` ke backend lokal di port 3000.

Saat `./run.sh` dijalankan di Linux, backend otomatis memindai semua `/dev/video*`, mencoba setiap device, lalu membuka kamera pertama yang menghasilkan gambar. Dashboard menampilkan stream kamera laptop; browser tidak meminta izin kamera.

Jika daftar kamera menunjukkan akses ditolak, pastikan pengguna Linux memiliki izin grup `video`. Jalankan `sudo usermod -aG video "$USER"`, lalu logout dan login kembali sebelum menjalankan ulang aplikasi. Pada mesin ini, kamera HP berada di `/dev/video1`; `/dev/video0` adalah Iriun output dan `/dev/video2` adalah node metadata.

## API

| Method | Endpoint | Keterangan |
| --- | --- | --- |
| `GET` | `/api/health` | Plain text: `ok` |
| `GET` | `/api/camera/status` | Status scanner dan daftar semua device kamera Linux |
| `GET` | `/api/camera/stream` | Stream MJPEG dari kamera laptop yang aktif |
| `POST` | `/api/camera/rescan` | Pindai ulang semua device kamera |
| `POST` | `/api/camera/stop` | Matikan kamera laptop |
| `POST` | `/api/telemetry` | Simpan uptime dan status alat |
| `GET` | `/api/telemetry?limit=20` | Ambil riwayat telemetri, maksimal 100 baris |
| `POST` | `/api/devices/{id}/readings` | Simpan pembacaan sensor terstruktur dari kit terdaftar |
| `GET` | `/api/readings?limit=100` | Ambil riwayat pembacaan sensor, opsional filter `device_id` |
| `POST` | `/api/devices` | Daftarkan alat baru dengan ID dan nama |
| `POST` | `/api/devices/status` | Terima status `hidup`/`mati` dari alat yang sudah terdaftar |
| `GET` | `/api/devices` | Ambil status terakhir seluruh alat |
| `GET` | `/api/components` | Ambil katalog komponen; opsional filter `device_id` |
| `POST` | `/api/components` | Daftarkan komponen terkonfirmasi atau placeholder belum dipetakan |
| `PUT` | `/api/components/{component_id}` | Perbarui pemetaan dan konfigurasi komponen |
| `POST` | `/api/devices/{device_id}/components/{component_id}/status?condition=normal` | Simpan kondisi komponen yang dilaporkan unit pemilik |
| `GET` | `/api/component-condition-reports?component_id=...&limit=10` | Ambil riwayat kondisi komponen, terbaru lebih dahulu |
| `POST` | `/api/devices/{device_id}/components/{component_id}/commands` | Antrekan command hanya untuk aktuator terkonfirmasi pada unit pemilik |
| `GET` | `/api/devices/{device_id}/commands` | Ambil command milik unit; wajib header `X-Device-Token` |
| `POST` | `/api/devices/{device_id}/commands/{id}/ack` | ACK command milik unit; wajib header `X-Device-Token` |
| `POST` | `/api/predictions` | Kirim snapshot wajah ke model Keras di laptop; multipart field `image` |
| `GET` | `/api/predictions` | Plain text kelas terakhir, misalnya `owner`; `unknown` jika belum dikenal/kedaluwarsa |
| `GET` | `/api/predictions/latest` | Ambil prediksi terakhir |
| `GET` | `/api/access/latest` | Ambil keputusan akses terkini |
| `GET` | `/api/dashboard` | Ambil telemetri, identitas, dan keputusan akses terakhir |
| `GET` | `/api/weather` | Cuaca terkini untuk Pakem, Sleman |
| `GET` | `/api/control/state` | Mode, sesi jemur, posisi aktuator, dan command menunggu |
| `POST` | `/api/control/mode?mode=auto` | Ubah mode tanpa JSON body |
| `POST` | `/api/control/actuators/{name}?position=open` | Kirim posisi aktuator saat manual |
| `POST` | `/api/drying/start?target_seconds=3600` | Mulai sesi jemur tanpa JSON body |
| `POST` | `/api/drying/stop` | Akhiri sesi dan catat durasi |
| `GET` | `/api/events?limit=50` | Ambil riwayat operasi |
| `POST` | `/api/events?event_type=...` | Catat event tambahan dari alat |
| `GET` | `/api/emergency` | Plain text status: `on` atau `off` |
| `GET` | `/api/emergency?mode=on` | Aktifkan emergency dan antrekan posisi aman |
| `POST` | `/api/emergency?mode=off` | Nonaktifkan emergency tanpa JSON body |
| `GET` | `/api/device/commands` | ArtecRobo mengambil command tertunda |
| `POST` | `/api/device/commands/{id}/ack?actual_position=closed` | ACK hasil command tanpa JSON body |

Contoh alat mengirim status:

```bash
curl -X POST http://localhost:3000/api/devices -H 'Content-Type: application/json' -d '{"device_id":"pompa-air","name":"Pompa Air"}'
curl -X POST http://localhost:3000/api/devices/status -H 'Content-Type: application/json' -d '{"device_id":"alat-1","status":"hidup"}'
curl -X POST 'http://localhost:3000/api/devices/status?device_id=alat-1&status=hidup'
```

Enam ID awal adalah `alat-1` sampai `alat-6`; alat tambahan dapat didaftarkan dari dashboard atau endpoint di atas. Gunakan ID yang sama saat mengirim status. `status` menerima `hidup` atau `mati`. Perangkat bisa memakai contoh URL terakhir tanpa header atau body. Status awal adalah `belum_terhubung`; `last_seen` mencatat waktu POST terakhir. Respons juga menyertakan `connection_status` (`never_seen`, `online`, `stale`) dan `age_seconds`. Batas stale default 30 detik dan dapat diubah dengan `AGRO_DEVICE_STALE_SECONDS`.

Contoh POST telemetri:

```bash
curl -X POST http://localhost:3000/api/telemetry \
  -H 'Content-Type: application/json' \
  -d '{"uptime_seconds": 7250, "status": "running"}'
```

Perangkat dapat mengirim JSON yang sama. `uptime_seconds` harus bilangan bulat non-negatif; `status` berupa teks, misalnya `running`, `stopped`, atau `unknown`.

Pembacaan sensor disimpan terpisah dari uptime/status. Setiap bacaan mencantumkan `sensor_id`, `sensor_type`, `value`, dan `unit` opsional. Pelaporan sensor juga memperbarui heartbeat kit. `POST` menerima JSON atau parameter URL agar dapat dipakai perangkat yang hanya mengirim parameter:

```bash
curl -X POST http://localhost:3000/api/devices/alat-1/readings \
  -H 'Content-Type: application/json' \
  -d '{"sensor_id":"light-1","sensor_type":"light","value":360,"unit":"lux"}'
curl -X POST 'http://localhost:3000/api/devices/alat-1/readings?sensor_id=light-1&sensor_type=light&value=360&unit=lux'
curl 'http://localhost:3000/api/readings?device_id=alat-1&limit=20'
```

## Kondisi komponen IoT

Setiap komponen harus sudah terdaftar dan dipetakan ke `device_id` unit yang mengirim laporan. ArtecRobo dapat mengirim kondisi sebagai parameter URL tanpa JSON body atau header:

```bash
curl -X POST 'http://localhost:3000/api/devices/alat-1/components/motor-elevator-1/status?condition=normal'
curl -X POST 'http://localhost:3000/api/devices/alat-1/components/motor-elevator-1/status?condition=perlu_dicek'
curl 'http://localhost:3000/api/component-condition-reports?device_id=alat-1&component_id=motor-elevator-1&limit=10'
```

`condition` adalah teks non-kosong maksimal 80 karakter; gunakan nilai konsisten seperti `normal`, `perlu_dicek`, atau `rusak`. Server mencatat waktu setiap laporan. Katalog `/api/components` menyertakan `reported_condition` dan `condition_reported_at` dari laporan terbaru. Pelaporan ini tidak mengubah posisi aktuator dan tidak memperbarui heartbeat unit. Komponen yang belum dipetakan atau dilaporkan melalui unit yang bukan pemiliknya akan ditolak.

Endpoint kondisi ini belum memakai token perangkat. Batasi akses backend ke LAN tepercaya dengan firewall dan jangan expose port API ke internet publik. CORS bukan pengganti autentikasi.

## Komponen dan command per unit

Katalog komponen tidak mengasumsikan pembagian fisik. Komponen perkiraan dapat didaftarkan dengan `device_id: null`, `confirmed: false`, dan `enabled: false`; tandai pemetaan terkonfirmasi hanya setelah wiring dan unit pemilik diverifikasi. Contoh placeholder motor:

Saat database pertama kali dibuat, backend menambahkan enam baris inventaris agregat: motor DC sekitar 4, servo 6, sensor cahaya 2, sensor suara 4, IR photoreflector belum pasti, dan sensor lain belum terkonfirmasi. Semua baris itu tidak memiliki pemilik unit, tidak terkonfirmasi, dan tidak dapat dikendalikan; pecah menjadi komponen fisik setelah daftar final tersedia.

```bash
curl -X POST http://localhost:3000/api/components \
  -H 'Content-Type: application/json' \
  -d '{"component_id":"motor-elevator-1","name":"Motor elevator","component_type":"dc_motor","device_id":null,"confirmed":false,"enabled":false,"command_values":[],"safe_value":null}'
```

Untuk aktuator yang sudah dipetakan, `device_id` harus menunjuk alat terdaftar. `confirmed` dan `enabled` harus aktif, `safe_value` wajib termasuk `command_values`, dan alat harus berstatus online agar server menerima command. Nilai seperti `forward`, `reverse`, atau `stop` hanyalah contoh; gunakan nilai yang benar-benar didukung program unit.

Command disimpan dengan pemilik unit dan komponen. Poller tidak dapat melihat command unit lain, endpoint global lama tidak menampilkan command terarah, dan ACK dari unit yang salah ditolak. Unit perlu mengirim header token:

```bash
export AGRO_DEVICE_TOKENS='{"alat-1":"TOKEN_ALAT_1","alat-2":"TOKEN_ALAT_2"}'
curl -H 'X-Device-Token: TOKEN_ALAT_1' http://localhost:3000/api/devices/alat-1/commands
curl -X POST http://localhost:3000/api/devices/alat-1/commands/12/ack \
  -H 'X-Device-Token: TOKEN_ALAT_1' \
  -H 'Content-Type: application/json' \
  -d '{"actual_position":"stop","success":true}'
```

Token harus disetel secara lokal di backend dan unit/gateway; jangan menaruh nilai asli di repo atau membagikannya. Tanpa token untuk unit, polling/ACK per-unit dinonaktifkan. Program blok ArtecRobo yang ada di workspace belum tersedia untuk membuktikan dukungan header HTTP; gateway dapat menjadi jembatan. API saja tidak menjalankan motor: firmware/gateway tetap harus mem-poll command, menerapkannya, dan mengirim ACK.

Dashboard menyediakan visualisasi 3D skematis enam Core Unit dan daftar inventaris agregat perkiraan. Tata letak/koneksi fisik belum diketahui; visual tidak menggambarkan posisi motor atau sensor. Model mesin yang akurat memerlukan foto/CAD dan pemetaan komponen. Tema terang/gelap dapat dipilih dari tombol di header dan disimpan pada browser.

## Identifikasi wajah dan ArtecRobo 2.0

Model Keras mengklasifikasikan foto yang diterima; label kelas menentukan identitas. Label yang diizinkan secara default adalah `owner`, `trusted`, dan `terpercaya` (pencocokan tidak membedakan huruf besar/kecil). Kelas lain menghasilkan `untrusted`. Confidence di bawah ambang menghasilkan `unknown`, yang selalu dianggap tidak tepercaya.

Ekspor model klasifikasi gambar Teachable Machine ke `backend/models/teachable_machine/keras_model.h5`, beserta `labels.txt`. Buat kelas terpisah untuk setiap orang yang diizinkan dan kelas seperti `unknown`/`visitor` untuk orang lain. Latih dengan variasi pencahayaan dan sudut wajah. Runtime mengharapkan input RGB 224x224 yang dinormalisasi ke rentang -1 sampai 1.

Atur environment sebelum menjalankan backend:

```bash
export AGRO_TRUSTED_LABELS="owner,trusted,terpercaya"
export AGRO_MIN_CONFIDENCE="0.85"
export AGRO_ACCESS_MAX_AGE_SECONDS="15"
```

Endpoint legacy umum dan kontrol dashboard yang lama belum memakai autentikasi. Endpoint poll/ACK per-unit yang baru memerlukan `AGRO_DEVICE_TOKENS`, tetapi jalankan seluruh API hanya pada LAN tepercaya, gunakan firewall, dan jangan expose port ke internet publik.

Contoh POST foto dari perangkat:

```bash
curl -X POST http://localhost:3000/api/predictions \
  -F 'image=@foto-tanaman.jpg'
```

Foto wajah maksimal 10 MB. Server tidak menyimpan file foto, hanya label, confidence, waktu, dan keputusan akses. GET perangkat tidak menjalankan inferensi; perangkat mengirim foto melalui POST lalu mengambil hasil melalui GET.

Contoh polling GET ArtecRobo:

```bash
curl http://localhost:3000/api/access/latest
```

Untuk polling teks kelas terakhir dari ArtecRobo:

```bash
curl http://localhost:3000/api/predictions
```

Respons berupa teks biasa, misalnya `owner`, `visitor`, atau `unknown`.

Respons ringkas:

```json
{
  "prediction_id": 17,
  "identity": "owner",
  "access_status": "trusted",
  "is_trusted": true,
  "confidence": 0.94,
  "captured_at": "2026-10-31T08:30:00+00:00",
  "expires_at": "2026-10-31T08:30:15+00:00",
  "message": "Identitas cocok dengan daftar yang diizinkan."
}
```

Jika belum ada hasil, confidence terlalu rendah, atau hasil lebih lama daripada batas waktu, status menjadi `unknown` dan `is_trusted` bernilai `false`. ArtecRobo sebaiknya memproses setiap `prediction_id` hanya sekali dan menolak data kedaluwarsa.

**Batas keamanan:** klasifikasi wajah biasa bukan liveness detection dan dapat tertipu foto/video. Jangan menghubungkan respons model ini sebagai satu-satunya mekanisme pembuka kunci. Gunakan verifikasi liveness/faktor kedua, autentikasi perangkat, HTTPS tepercaya, serta pengendali pintu lokal dengan kondisi gagal-tertutup. Format HTTP di atas adalah kontrak API generik; library dan format program ArtecRobo 2.0 bergantung pada firmware yang digunakan.

## Cuaca Pakem

`GET /api/weather` mengambil kondisi cuaca terkini Pakem, Sleman dari Open-Meteo dan tidak memerlukan API key. Server Linux perlu akses internet. Dashboard menampilkan suhu, kondisi, dan kelembapan; jika layanan cuaca tidak dapat dijangkau, panel cuaca menampilkan status tidak tersedia.

Dokumentasi API interaktif tersedia di `http://localhost:3000/docs` saat backend aktif.

## Manual, auto, dan emergency

Mode awal adalah `manual`. Di mode manual, dashboard dapat mengantrekan posisi atap `open` atau `closed`. Mulai sesi jemur dengan target detik; sistem mencatat waktu mulai, waktu selesai, dan durasi aktual. `POST /api/events` menerima event tambahan seperti pembacaan sensor atau aktivitas alat lain, sehingga event itu ikut tersimpan di SQLite dan tampil di log operasi.

Di mode `auto`, backend mengevaluasi kondisi setiap 15 detik (ubah dengan `AGRO_AUTOMATION_INTERVAL_SECONDS`). Tanpa sesi jemur, atap kembali ke posisi aman. Saat sesi aktif, atap dibuka jika siang dan tidak hujan; atap ditutup saat hujan, malam, data cuaca gagal, atau durasi target tercapai. Sesi yang mencapai target dihentikan otomatis dan lama prosesnya dicatat.

Aktifkan emergency dengan GET berikut. Perintah ini hanya mengaktifkan emergency dan mengantrekan posisi aman:

```bash
curl 'http://localhost:3000/api/emergency?mode=on'
```

Emergency menghentikan sesi jemur, menonaktifkan command manual/auto, mengganti command tertunda, lalu mengantrekan semua aktuator ke posisi aman. GET `/api/emergency` tanpa parameter `mode` hanya membaca status dan mengembalikan plain text `on` atau `off`. Reset emergency memakai POST `http://localhost:3000/api/emergency?mode=off`. Posisi aman default atap adalah `closed`; atur aktuator lain dengan environment JSON, misalnya `AGRO_SAFE_POSITIONS='{"roof":"closed","pump":"off"}'`.

`AGRO_ACTUATOR_POSITIONS` membatasi nilai posisi yang dapat dikirim melalui API. Tambahkan nama aktuator dan posisi yang benar-benar didukung firmware; setiap nama di `AGRO_SAFE_POSITIONS` juga harus memiliki posisi aman yang diizinkan.

ArtecRobo mengambil command tertunda melalui GET `/api/device/commands`, menjalankannya di firmware, lalu mengirim ACK ke `/api/device/commands/{id}/ack` dengan `actual_position`, `success`, dan `detail`. Command terbaru menggantikan command lama yang masih pending. Backend hanya mengantrekan perintah; penggerak fisik tetap harus dibuat dan diuji di firmware sesuai pin, driver, sensor, dan protokol alat. Emergency juga bergantung pada robot yang sedang online untuk menerima command; sediakan interlock/failsafe lokal pada perangkat.

Contoh mengambil command:

```bash
curl http://localhost:3000/api/device/commands
```

Contoh command tanpa header atau JSON body:

```bash
curl -X POST 'http://localhost:3000/api/control/mode?mode=auto'
curl -X POST 'http://localhost:3000/api/drying/start?target_seconds=3600'
curl -X POST 'http://localhost:3000/api/telemetry?uptime_seconds=7250&status=running'
curl -X POST 'http://localhost:3000/api/events?event_type=drying_note&value=mulai'
curl -X POST 'http://localhost:3000/api/device/commands/12/ack?actual_position=closed'
```

Command yang tidak mendapat ACK selama 60 detik otomatis berstatus `timeout` dan dicatat sebagai event `actuator_timeout`; command timeout tidak mengubah posisi aktuator yang tercatat. Log lengkap termasuk telemetri, sesi mulai/selesai, perubahan mode, command, ACK/gagal/timeout, emergency, dan event khusus tersedia di `GET /api/events`.

## Model Teachable Machine

Backend mendukung model **image classification** Teachable Machine yang diekspor sebagai Keras `keras_model.h5` beserta `labels.txt`. `./run.sh` otomatis memakai pasangan file di root proyek atau `backend/models/teachable_machine/`, lalu memasang TensorFlow dan runtime Keras legacy untuk kompatibilitas model jika tersedia.

```bash
cd backend
source .venv/bin/activate
pip install -r requirements-ml.txt
```

Nama file dan lokasi dapat diubah menggunakan environment variable `AGRO_MODEL_PATH` dan `AGRO_LABELS_PATH`. Model di proyek ini memiliki label `Varo` dan `GTW`; jika keduanya boleh dianggap tepercaya, jalankan `AGRO_TRUSTED_LABELS='Varo,GTW' ./run.sh`. Secara default label di luar daftar tepercaya tidak diberi akses.

Database SQLite dibuat otomatis di `backend/data/agro_sembada.db`. Lokasinya dapat diubah dengan `AGRO_DATABASE_PATH`. Untuk origin frontend selain Vite lokal, atur `AGRO_CORS_ORIGINS` sebagai daftar origin yang dipisahkan koma.

## Logo

Logo sekolah yang dipakai pada header dan favicon berada di `frontend/public/assets/brand/dada.jpeg`.

## Tes

```bash
backend/.venv/bin/python -m pytest backend
npm --prefix frontend run build
```

Tes backend menggunakan classifier tiruan dan database sementara, jadi tidak membutuhkan model Keras atau koneksi cuaca. API perangkat tidak memakai autentikasi; gunakan hanya pada LAN tepercaya, aktifkan firewall, dan jangan expose API ke internet publik.