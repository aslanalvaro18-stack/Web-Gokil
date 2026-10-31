import { useEffect, useRef, useState } from 'react'
import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  Camera,
  Check,
  Clock3,
  CloudSun,
  Droplets,
  Leaf,
  Plus,
  Radio,
  RefreshCw,
  Send,
  Square,
  Upload,
  Wifi,
  WifiOff,
} from 'lucide-react'
import './App.css'

type Telemetry = {
  uptime_seconds: number
  status: string
  recorded_at: string
}

type Device = {
  device_id: string
  name: string
  status: 'belum_terhubung' | 'hidup' | 'mati'
  last_seen: string | null
}

type CameraDevice = {
  device: string
  name: string
  available: boolean
  message: string
}

type CameraStatus = {
  state: 'stopped' | 'scanning' | 'online' | 'offline' | 'unavailable' | 'error'
  active_device: string | null
  active_name: string | null
  devices: CameraDevice[]
  message: string
}

type Prediction = {
  class_name: string
  confidence: number
  captured_at: string
  access_status: 'trusted' | 'untrusted' | 'unknown'
}

type AccessDecision = {
  access_status: 'trusted' | 'untrusted' | 'unknown'
  is_trusted: boolean
  message: string
}

type Actuator = {
  name: string
  current_position: string
  target_position: string
  safe_position: string
}

type ControlState = {
  mode: 'manual' | 'auto'
  emergency_mode: boolean
  drying_started_at: string | null
  drying_target_seconds: number | null
  drying_elapsed_seconds: number
  updated_at: string
  actuators: Actuator[]
  pending_commands: { id: number; actuator: string; position: string; source: string }[]
}

type OperationEvent = {
  id: number
  event_type: string
  source: string
  actuator: string | null
  value: string | null
  duration_seconds: number | null
  detail: Record<string, unknown>
  occurred_at: string
}

type Weather = {
  location: string
  temperature_c: number
  apparent_temperature_c: number
  humidity_percent: number
  condition: string
  observed_at: string
}

type DashboardData = {
  telemetry: Telemetry | null
  prediction: Prediction | null
  access: AccessDecision
  control: ControlState
  events: OperationEvent[]
}

const emptyDashboard: DashboardData = {
  telemetry: null,
  prediction: null,
  access: { access_status: 'unknown', is_trusted: false, message: 'Belum ada hasil.' },
  control: {
    mode: 'manual',
    emergency_mode: false,
    drying_started_at: null,
    drying_target_seconds: null,
    drying_elapsed_seconds: 0,
    updated_at: '',
    actuators: [],
    pending_commands: [],
  },
  events: [],
}

const emptyCameraStatus: CameraStatus = {
  state: 'stopped',
  active_device: null,
  active_name: null,
  devices: [],
  message: 'Menunggu status kamera.',
}

const eventLabels: Record<string, string> = {
  actuator_acknowledged: 'Aktuator selesai',
  actuator_commanded: 'Perintah aktuator',
  actuator_commands_superseded: 'Perintah digantikan',
  actuator_failed: 'Aktuator gagal',
  drying_completed: 'Penjemuran selesai',
  drying_started: 'Penjemuran dimulai',
  emergency_activated: 'Emergency aktif',
  emergency_cleared: 'Emergency dinonaktifkan',
  face_identified: 'Identitas diperiksa',
  mode_changed: 'Mode kontrol berubah',
  telemetry_received: 'Telemetri diterima',
}

function formatDuration(totalSeconds: number) {
  const seconds = Math.max(0, Math.floor(totalSeconds))
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor((seconds % 86400) / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  const remainder = seconds % 60

  return days > 0
    ? `${days} hari ${hours} jam`
    : `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${remainder.toString().padStart(2, '0')}`
}

function formatTimestamp(value: string | undefined) {
  if (!value) return 'Belum ada data'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Waktu tidak tersedia'
  return new Intl.DateTimeFormat('id-ID', {
    hour: '2-digit',
    minute: '2-digit',
    day: 'numeric',
    month: 'short',
  }).format(date)
}

function App() {
  const [dashboard, setDashboard] = useState(emptyDashboard)
  const [devices, setDevices] = useState<Device[]>([])
  const [cameraStatus, setCameraStatus] = useState(emptyCameraStatus)
  const [apiOnline, setApiOnline] = useState(false)
  const [uptimeInput, setUptimeInput] = useState('3600')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [weather, setWeather] = useState<Weather | null>(null)
  const [weatherLoading, setWeatherLoading] = useState(true)
  const [dryingTargetMinutes, setDryingTargetMinutes] = useState('60')
  const [deviceIdInput, setDeviceIdInput] = useState('')
  const [deviceNameInput, setDeviceNameInput] = useState('')
  const [deviceBusy, setDeviceBusy] = useState(false)
  const [deviceNotice, setDeviceNotice] = useState('')
  const cameraImageRef = useRef<HTMLImageElement>(null)
  const cameraTimerRef = useRef<number | null>(null)
  const predictionBusyRef = useRef(false)

  useEffect(() => {
    let active = true

    const refresh = async () => {
      try {
        const [dashboardResponse, devicesResponse] = await Promise.all([
          fetch('/api/dashboard'),
          fetch('/api/devices'),
        ])
        if (!dashboardResponse.ok || !devicesResponse.ok) throw new Error('Backend tidak merespons')
        const [data, deviceData] = await Promise.all([
          dashboardResponse.json() as Promise<DashboardData>,
          devicesResponse.json() as Promise<Device[]>,
        ])
        if (active) {
          setDashboard(data)
          setDevices(deviceData)
          setApiOnline(true)
        }
      } catch {
        if (active) setApiOnline(false)
      }
    }

    const refreshWeather = async () => {
      try {
        const response = await fetch('/api/weather')
        if (!response.ok) throw new Error('Cuaca tidak tersedia')
        const data = (await response.json()) as Weather
        if (active) setWeather(data)
      } catch {
        if (active) setWeather(null)
      } finally {
        if (active) setWeatherLoading(false)
      }
    }

    const refreshCamera = async () => {
      try {
        const response = await fetch('/api/camera/status')
        if (!response.ok) throw new Error('Status kamera tidak tersedia.')
        const status = (await response.json()) as CameraStatus
        if (active) setCameraStatus(status)
      } catch {
        if (active) {
          setCameraStatus({
            ...emptyCameraStatus,
            state: 'unavailable',
            message: 'Backend kamera tidak merespons.',
          })
        }
      }
    }

    void refresh()
    void refreshWeather()
    void refreshCamera()
    const interval = window.setInterval(() => void refresh(), 5000)
    const weatherInterval = window.setInterval(() => void refreshWeather(), 600000)
    const cameraInterval = window.setInterval(() => void refreshCamera(), 2000)
    return () => {
      active = false
      window.clearInterval(interval)
      window.clearInterval(weatherInterval)
      window.clearInterval(cameraInterval)
      if (cameraTimerRef.current !== null) window.clearTimeout(cameraTimerRef.current)
    }
  }, [])

  const rescanCameras = async () => {
    setCameraStatus((current) => ({
      ...current,
      state: 'scanning',
      message: 'Memindai semua kamera Linux...',
    }))
    try {
      const response = await fetch('/api/camera/rescan', {
        method: 'POST',
      })
      const status = (await response.json()) as CameraStatus & { detail?: string }
      if (!response.ok) throw new Error(status.detail ?? 'Pemindaian kamera gagal.')
      setCameraStatus(status)
    } catch (error) {
      setCameraStatus((current) => ({
        ...current,
        state: 'error',
        message: error instanceof Error ? error.message : 'Pemindaian kamera gagal.',
      }))
    }
  }

  const sendImage = async (image: Blob, filename: string, quiet = false) => {
    if (predictionBusyRef.current) return
    predictionBusyRef.current = true
    if (!quiet) {
      setBusy(true)
      setNotice('Mengirim gambar ke model Keras di laptop...')
    }
    const formData = new FormData()
    formData.append('image', image, filename)

    try {
      const response = await fetch('/api/predictions', {
        method: 'POST',
        body: formData,
      })
      const body = (await response.json()) as { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Prediksi gagal diproses')
      const predictionResult = body as Prediction
      const accessMessages = {
        trusted: 'Identitas cocok dengan daftar yang diizinkan.',
        untrusted: 'Identitas tidak termasuk daftar yang diizinkan.',
        unknown: 'Keyakinan model rendah atau hasil sudah kedaluwarsa.',
      }
      setDashboard((current) => ({
        ...current,
        prediction: predictionResult,
        access: {
          access_status: predictionResult.access_status,
          is_trusted: predictionResult.access_status === 'trusted',
          message: accessMessages[predictionResult.access_status],
        },
      }))
      if (!quiet) setNotice('Identitas berhasil dianalisis.')
    } catch (error) {
      if (!quiet) setNotice(error instanceof Error ? error.message : 'Tidak dapat mengirim gambar.')
    } finally {
      predictionBusyRef.current = false
      if (!quiet) setBusy(false)
    }
  }

  const processNextFrame = async () => {
    const cameraFrame = cameraImageRef.current
    if (cameraActive && cameraFrame?.complete && cameraFrame.naturalWidth > 0 && !predictionBusyRef.current) {
      const canvas = document.createElement('canvas')
      canvas.width = cameraFrame.naturalWidth
      canvas.height = cameraFrame.naturalHeight
      canvas.getContext('2d')?.drawImage(cameraFrame, 0, 0)
      const imageBlob = await new Promise<Blob | null>((resolve) =>
        canvas.toBlob(resolve, 'image/jpeg', 0.82),
      )
      if (imageBlob) await sendImage(imageBlob, 'laptop-camera.jpg', true)
    }
    if (cameraActive) {
      cameraTimerRef.current = window.setTimeout(() => void processNextFrame(), 1200)
    }
  }

  const cameraActive = cameraStatus.state === 'online'

  useEffect(() => {
    if (cameraTimerRef.current !== null) window.clearTimeout(cameraTimerRef.current)
    cameraTimerRef.current = cameraActive
      ? window.setTimeout(() => void processNextFrame(), 700)
      : null
    return () => {
      if (cameraTimerRef.current !== null) window.clearTimeout(cameraTimerRef.current)
    }
  }, [cameraActive])

  const submitTelemetry = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setBusy(true)
    setNotice('Mengirim data uptime...')

    try {
      const response = await fetch('/api/telemetry', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          uptime_seconds: Number(uptimeInput),
          status: 'running',
        }),
      })
      const body = (await response.json()) as { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Data uptime gagal disimpan')
      setDashboard((current) => ({ ...current, telemetry: body as Telemetry }))
      setNotice('Data uptime berhasil disimpan.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Tidak dapat menyimpan uptime.')
    } finally {
      setBusy(false)
    }
  }

  const registerDevice = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setDeviceBusy(true)
    setDeviceNotice('')

    try {
      const response = await fetch('/api/devices', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          device_id: deviceIdInput.trim(),
          name: deviceNameInput.trim(),
        }),
      })
      const body = (await response.json()) as Device & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Alat gagal ditambahkan.')
      setDevices((current) => [...current, body].sort((first, second) => first.device_id.localeCompare(second.device_id)))
      setDeviceIdInput('')
      setDeviceNameInput('')
      setDeviceNotice(`${body.name} berhasil ditambahkan.`)
    } catch (error) {
      setDeviceNotice(error instanceof Error ? error.message : 'Tidak dapat menambahkan alat.')
    } finally {
      setDeviceBusy(false)
    }
  }

  const postControl = async (path: string, payload: Record<string, unknown>) => {
    setBusy(true)
    setNotice('Mengirim perintah ke backend...')
    try {
      const response = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      const body = (await response.json()) as { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Perintah gagal diproses')
      setNotice('Perintah tercatat. Alat akan mengambil command dan mengirim ACK.')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Tidak dapat mengirim perintah.')
    } finally {
      setBusy(false)
    }
  }

  const startDrying = () => {
    const minutes = Number(dryingTargetMinutes)
    if (!Number.isFinite(minutes) || minutes < 1 || minutes > 1440) {
      setNotice('Target jemur harus antara 1 menit dan 24 jam.')
      return
    }
    void postControl('/api/drying/start', { target_seconds: Math.round(minutes * 60) })
  }

  const prediction = dashboard.prediction
  const telemetry = dashboard.telemetry
  const access = dashboard.access
  const control = dashboard.control
  const roof = control.actuators.find((actuator) => actuator.name === 'roof')
  const dryingActive = control.drying_started_at !== null
  const controlsDisabled = busy || control.emergency_mode
  const activeDeviceCount = devices.filter((device) => device.status === 'hidup').length

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <a className="brand" href="#dashboard" aria-label="AGRO-SEMBADA dashboard">
          <img className="brand-mark" src="/assets/brand/dada.jpeg" alt="" width={44} height={44} />
          <span className="brand-name">AGRO<span>-</span>SEMBADA</span>
        </a>
        <div className="topbar-meta">
          <span className="team-label">PRADNYASIWI QUADTECH</span>
          <span className="school-label">SMPN 4 PAKEM</span>
        </div>
        <div className={`connection-pill ${apiOnline ? 'is-online' : 'is-offline'}`}>
          {apiOnline ? <Wifi size={15} /> : <WifiOff size={15} />}
          <span>{apiOnline ? 'SERVER TERHUBUNG' : 'SERVER TERPUTUS'}</span>
        </div>
      </header>

      <section className="page-heading" id="dashboard">
        <div>
          <p className="eyebrow"><span className="eyebrow-dot" /> SISTEM PEMANTAUAN ALAT</p>
          <h1>Ruang kendali <span>AGRO-SEMBADA</span></h1>
        </div>
        <div className="last-sync"><RefreshCw size={14} /> Data diperbarui otomatis tiap 5 detik</div>
      </section>

      <section className="metrics-row" aria-label="Ringkasan kondisi alat">
        <article className="metric metric-runtime">
          <div className="metric-top"><span>WAKTU OPERASI</span><Clock3 size={17} /></div>
          <strong>{formatDuration(telemetry?.uptime_seconds ?? 0)}</strong>
          <div className="metric-foot">{telemetry ? `Diperbarui ${formatTimestamp(telemetry.recorded_at)}` : 'Menunggu data pertama'}</div>
        </article>
        <article className="metric metric-status">
          <div className="metric-top"><span>STATUS ALAT</span><Activity size={17} /></div>
          <strong className="status-value"><span className={`status-dot ${telemetry?.status === 'running' ? 'active' : ''}`} />{telemetry?.status === 'running' ? 'Berjalan' : 'Belum diketahui'}</strong>
          <div className="metric-foot">{telemetry ? 'Status terakhir dari alat' : 'Belum ada telemetri tersimpan'}</div>
        </article>
        <article className="metric metric-model">
          <div className="metric-top"><span>MODEL VISI</span><Radio size={17} /></div>
          <strong>{prediction ? 'Aktif' : 'Menunggu'}</strong>
          <div className="metric-foot">Identifikasi wajah · Keras</div>
        </article>
        <article className="metric metric-weather">
          <div className="metric-top"><span>CUACA PAKEM</span><CloudSun size={17} /></div>
          <strong>{weather ? `${Math.round(weather.temperature_c)}°C` : weatherLoading ? 'Memuat' : '--'}</strong>
          <div className="metric-foot">{weather ? weather.condition : weatherLoading ? 'Mengambil data terkini' : 'Cuaca tidak tersedia'}</div>
        </article>
      </section>

      <section className="panel devices-panel" aria-labelledby="devices-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">ALAT TERDAFTAR</p>
            <h2 id="devices-title">Status perangkat</h2>
          </div>
          <span className="device-summary"><span className="device-summary-dot" />{activeDeviceCount} AKTIF <i>/</i> {devices.length} ALAT</span>
        </div>
        <div className="device-layout">
          <div className="device-list" aria-live="polite">
            {devices.length === 0 ? (
              <p className="empty-devices">Belum ada alat terdaftar.</p>
            ) : devices.map((device) => (
              <div className="device-row" key={device.device_id}>
                <span className={`device-indicator device-${device.status}`} />
                <div className="device-identity">
                  <strong>{device.name}</strong>
                  <span>{device.device_id}</span>
                </div>
                <div className={`device-state device-state-${device.status}`}>
                  <strong>{device.status === 'hidup' ? 'HIDUP' : device.status === 'mati' ? 'MATI' : 'BELUM TERHUBUNG'}</strong>
                  <span>{formatTimestamp(device.last_seen ?? undefined)}</span>
                </div>
              </div>
            ))}
          </div>
          <form className="device-form" onSubmit={(event) => void registerDevice(event)}>
            <div>
              <p className="section-index">REGISTRASI</p>
              <h3>Tambah alat</h3>
            </div>
            <label htmlFor="device-name">Nama alat</label>
            <input
              id="device-name"
              value={deviceNameInput}
              onChange={(event) => setDeviceNameInput(event.target.value)}
              placeholder="Contoh: Pompa air"
              maxLength={80}
              required
            />
            <label htmlFor="device-id">ID alat</label>
            <input
              id="device-id"
              value={deviceIdInput}
              onChange={(event) => setDeviceIdInput(event.target.value)}
              placeholder="Contoh: pompa-air"
              pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
              maxLength={40}
              required
            />
            <button className="button button-primary" type="submit" disabled={deviceBusy || !apiOnline}>
              <Plus size={15} /> Tambah perangkat
            </button>
            {deviceNotice && <p className="device-notice" role="status">{deviceNotice}</p>}
          </form>
        </div>
      </section>

      <section className="workspace-grid">
        <article className="panel camera-panel">
          <div className="panel-heading">
            <div>
              <p className="section-index">01 / IDENTIFIKASI WAJAH</p>
              <h2>Verifikasi identitas</h2>
            </div>
            <span className={`live-tag ${cameraActive ? 'live' : cameraStatus.state === 'scanning' ? 'scanning' : ''}`}><span />{cameraActive ? 'LIVE' : cameraStatus.state === 'scanning' ? 'SCAN' : 'SIAP'}</span>
          </div>

          <div className={`camera-stage ${cameraActive ? 'camera-on' : ''}`}>
            {cameraActive ? (
              <img ref={cameraImageRef} src="/api/camera/stream" alt="Pratinjau kamera laptop" />
            ) : (
              <div className="camera-empty">
                <div className="camera-symbol"><Camera size={28} strokeWidth={1.6} /></div>
                <strong>{cameraStatus.state === 'scanning' ? 'Memindai kamera' : 'Kamera belum aktif'}</strong>
                <span>{cameraStatus.message}</span>
              </div>
            )}
            <span className="stage-corner corner-tl" /><span className="stage-corner corner-tr" />
            <span className="stage-corner corner-bl" /><span className="stage-corner corner-br" />
          </div>

          {cameraStatus.devices.length > 0 && (
            <div className="camera-device-list" aria-label="Hasil pemindaian kamera">
              {cameraStatus.devices.map((device) => (
                <div className="camera-device-row" key={device.device}>
                  <span className={`camera-device-dot ${device.available ? 'available' : ''}`} />
                  <strong>{device.name}</strong>
                  <span>{device.device}</span>
                  <small>{device.message}</small>
                </div>
              ))}
            </div>
          )}

          <div className="camera-controls">
            <button
              className="button button-secondary"
              type="button"
              onClick={() => void rescanCameras()}
              disabled={cameraStatus.state === 'scanning'}
            >
              <RefreshCw size={15} /> {cameraStatus.state === 'scanning' ? 'Memindai kamera...' : 'Pindai ulang kamera'}
            </button>
            <label className="button button-secondary upload-button">
              <Upload size={16} /> Unggah foto
              <input
                type="file"
                accept="image/*"
                capture="user"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0]
                  if (file) void sendImage(file, file.name)
                  event.currentTarget.value = ''
                }}
                disabled={busy || cameraActive}
              />
            </label>
          </div>
          {notice && <p className="notice" role="status">{busy ? <RefreshCw size={14} className="spin" /> : <AlertCircle size={14} />}{notice}</p>}
        </article>

        <article className="panel prediction-panel">
          <div className="panel-heading">
            <div>
              <p className="section-index">02 / HASIL ANALISIS</p>
              <h2>Hasil identifikasi</h2>
            </div>
            <span className="model-chip"><span className="model-chip-dot" /> PYTHON MODEL</span>
          </div>

          <div className="prediction-result">
            <div className="prediction-icon"><Leaf size={23} /></div>
            <div className="prediction-copy">
              <span>IDENTITAS TERDETEKSI</span>
              <strong>{prediction?.class_name ?? 'Belum ada hasil'}</strong>
            </div>
            <ArrowUpRight className="result-arrow" size={19} />
          </div>
          <div className={`access-result access-${access.access_status}`}>
            <span className="access-indicator" />
            <div>
              <strong>{access.access_status === 'trusted' ? 'TERPERCAYA' : access.access_status === 'untrusted' ? 'TIDAK DIIZINKAN' : 'BELUM PASTI'}</strong>
              <span>{access.message}</span>
            </div>
          </div>
          <div className="confidence-block">
            <div className="confidence-label"><span>Keyakinan model</span><strong>{prediction ? `${Math.round(prediction.confidence * 100)}%` : '--'}</strong></div>
            <div className="confidence-track"><span style={{ width: `${Math.min(100, Math.max(0, (prediction?.confidence ?? 0) * 100))}%` }} /></div>
          </div>
          <div className="result-detail"><Clock3 size={15} /><span>Waktu analisis</span><strong>{formatTimestamp(prediction?.captured_at)}</strong></div>
          {!prediction && <p className="empty-hint">Pasang model wajah Keras dan token perangkat di server untuk mengaktifkan identifikasi.</p>}
          {prediction && <div className="success-note"><Check size={14} /> Hasil dari Keras · kedaluwarsa setelah 15 detik</div>}
        </article>
      </section>

      <section className="control-grid">
        <article className="panel control-panel">
          <div className="panel-heading">
            <div>
              <p className="section-index">03 / KENDALI ALAT</p>
              <h2>Mode operasi</h2>
            </div>
            <span className={`emergency-state ${control.emergency_mode ? 'emergency-on' : ''}`}>
              <span /> EMERGENCY {control.emergency_mode ? 'ON' : 'OFF'}
            </span>
          </div>

          <div className="control-mode-row">
            <div className="mode-switch" role="group" aria-label="Mode operasi">
              <button
                type="button"
                className={control.mode === 'manual' ? 'selected' : ''}
                aria-pressed={control.mode === 'manual'}
                disabled={controlsDisabled}
                onClick={() => void postControl('/api/control/mode', { mode: 'manual' })}
              >MANUAL</button>
              <button
                type="button"
                className={control.mode === 'auto' ? 'selected' : ''}
                aria-pressed={control.mode === 'auto'}
                disabled={controlsDisabled}
                onClick={() => void postControl('/api/control/mode', { mode: 'auto' })}
              >AUTO</button>
            </div>
            <button
              type="button"
              className={`button ${control.emergency_mode ? 'button-emergency-active' : 'button-emergency'}`}
              disabled={busy}
              onClick={() => void postControl('/api/emergency', { enabled: !control.emergency_mode })}
            >
              <AlertCircle size={15} />
              {control.emergency_mode ? 'Matikan emergency' : 'Emergency'}
            </button>
          </div>

          <div className="control-details">
            <div className="actuator-block">
              <div className="control-label-row"><span>ATAP</span><span>POSISI: {roof?.current_position ?? 'unknown'}</span></div>
              <div className="actuator-actions">
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={controlsDisabled || control.mode !== 'manual'}
                  onClick={() => void postControl('/api/control/actuators/roof', { position: 'open' })}
                ><ArrowUpRight size={15} /> Buka atap</button>
                <button
                  className="button button-secondary"
                  type="button"
                  disabled={controlsDisabled || control.mode !== 'manual'}
                  onClick={() => void postControl('/api/control/actuators/roof', { position: 'closed' })}
                ><Square size={14} /> Tutup atap</button>
                <span className="target-position">Target: {roof?.target_position ?? 'closed'}</span>
              </div>
            </div>

            <div className="drying-block">
              <div className="control-label-row">
                <span>SESI JEMUR</span>
                <span>{dryingActive ? `BERJALAN · ${formatDuration(control.drying_elapsed_seconds)}` : 'TIDAK AKTIF'}</span>
              </div>
              <div className="drying-actions">
                <label htmlFor="drying-minutes">Target</label>
                <input
                  id="drying-minutes"
                  type="number"
                  min="1"
                  max="1440"
                  step="1"
                  value={dryingTargetMinutes}
                  onChange={(event) => setDryingTargetMinutes(event.target.value)}
                  disabled={dryingActive}
                />
                <span>menit</span>
                {dryingActive ? (
                  <button className="button button-dark" type="button" disabled={controlsDisabled} onClick={() => void postControl('/api/drying/stop', {})}>
                    <Square size={14} /> Akhiri sesi
                  </button>
                ) : (
                  <button className="button button-dark" type="button" disabled={controlsDisabled} onClick={startDrying}>
                    <Clock3 size={15} /> Mulai jemur
                  </button>
                )}
              </div>
            </div>
          </div>
          <p className="control-footnote">
            {control.mode === 'auto'
              ? 'Auto: atap dibuka saat siang tanpa hujan; atap ditutup saat hujan, malam, atau target selesai.'
              : 'Manual: command atap hanya dikirim saat mode manual aktif.'}
            {control.pending_commands.length > 0 && ` · ${control.pending_commands.length} command menunggu alat`}
          </p>
        </article>

        <article className="panel event-panel">
          <div className="panel-heading compact-heading">
            <div>
              <p className="section-index">04 / LOG OPERASI</p>
              <h2>Aktivitas alat</h2>
            </div>
            <span className="get-label">GET</span>
          </div>
          <div className="event-list">
            {dashboard.events.length === 0 ? (
              <p className="empty-events">Belum ada event operasi.</p>
            ) : dashboard.events.slice(0, 6).map((event) => (
              <div className="event-row" key={event.id}>
                <span className={`event-marker event-${event.source}`} />
                <div className="event-copy">
                  <strong>{eventLabels[event.event_type] ?? event.event_type.replaceAll('_', ' ')}</strong>
                  <span>{event.actuator ? `${event.actuator} · ` : ''}{formatTimestamp(event.occurred_at)}</span>
                </div>
                <span className="event-value">
                  {event.duration_seconds !== null ? formatDuration(event.duration_seconds) : event.value ?? event.source}
                </span>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="bottom-grid">
        <article className="panel telemetry-panel">
          <div className="panel-heading compact-heading">
            <div>
              <p className="section-index">03 / TELEMETRI</p>
              <h2>Kirim data operasi</h2>
            </div>
            <span className="post-label">POST</span>
          </div>
          <form className="telemetry-form" onSubmit={(event) => void submitTelemetry(event)}>
            <label htmlFor="uptime">Lama alat telah berjalan <span>(detik)</span></label>
            <div className="form-row">
              <input id="uptime" type="number" min="0" step="1" value={uptimeInput} onChange={(event) => setUptimeInput(event.target.value)} required />
              <button className="button button-dark" type="submit" disabled={busy}><Send size={15} /> Kirim data</button>
            </div>
          </form>
          <p className="form-footnote">Perangkat dapat mengirim format JSON yang sama ke endpoint telemetri.</p>
        </article>

        <article className="panel history-panel">
          <div className="panel-heading compact-heading">
            <div>
              <p className="section-index">04 / AKTIVITAS</p>
              <h2>Data terbaru</h2>
            </div>
            <span className="get-label">GET</span>
          </div>
          <div className="activity-list">
            <div className="activity-row">
              <span className="activity-icon telemetry-icon"><Activity size={15} /></span>
              <div><strong>Telemetri alat</strong><span>{telemetry ? formatTimestamp(telemetry.recorded_at) : 'Menunggu data'}</span></div>
              <span className="activity-value">{telemetry ? formatDuration(telemetry.uptime_seconds) : '--'}</span>
            </div>
            <div className="activity-row">
              <span className="activity-icon prediction-icon-small"><Leaf size={15} /></span>
              <div><strong>Identitas wajah</strong><span>{prediction ? formatTimestamp(prediction.captured_at) : 'Menunggu analisis'}</span></div>
              <span className="activity-value">{access.access_status === 'trusted' ? 'TERPERCAYA' : access.access_status === 'untrusted' ? 'DITOLAK' : '--'}</span>
            </div>
            <div className="activity-row weather-activity">
              <span className="activity-icon weather-icon"><Droplets size={15} /></span>
              <div><strong>Cuaca Pakem</strong><span>{weather?.location ?? (weatherLoading ? 'Memuat data cuaca' : 'Tidak tersedia')}</span></div>
              <span className="activity-value">{weather ? `${Math.round(weather.humidity_percent)}% RH` : '--'}</span>
            </div>
          </div>
        </article>
      </section>

      <footer className="footer"><span>AGRO-SEMBADA <i>×</i> PRADNYASIWI QUADTECH</span><span>SMPN 4 PAKEM <b>·</b> SISTEM MONITORING</span></footer>
    </main>
  )
}

export default App
