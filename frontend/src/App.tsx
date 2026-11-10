import { Component, lazy, Suspense, useEffect, useEffectEvent, useRef, useState, type ReactNode } from 'react'
import {
  Activity,
  AlertCircle,
  ArrowUpRight,
  Camera,
  Check,
  Copy,
  Cloud,
  CloudDrizzle,
  CloudFog,
  CloudLightning,
  CloudRain,
  Clock3,
  CloudSun,
  Droplets,
  Leaf,
  Moon,
  Pencil,
  Plus,
  Radio,
  RefreshCw,
  Send,
  Square,
  Sun,
  Upload,
  Wifi,
  WifiOff,
  Wind,
} from 'lucide-react'
import './App.css'

const MachineOverview = lazy(() => import('./components/MachineOverview'))

class MachineOverviewErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false }

  static getDerivedStateFromError() {
    return { hasError: true }
  }

  render() {
    if (this.state.hasError) {
      return <section className="machine-scene-loading" role="status">Visualisasi mesin tidak dapat dimuat.</section>
    }
    return this.props.children
  }
}

type Telemetry = {
  uptime_seconds: number
  status: string
  recorded_at: string
}

type SensorReading = {
  id: number
  device_id: string
  sensor_id: string
  sensor_type: string
  value: number
  unit: string | null
  recorded_at: string
}

type ScratchVariable = {
  name: string
  value: string | number | boolean | null
  updated_at: string
}

type EventFlag = {
  name: string
  active: boolean
  mode: 'once' | 'ack'
  updated_at: string
}

type DeviceComponent = {
  component_id: string
  name: string
  component_type: string
  estimated_count: string | null
  device_id: string | null
  confirmed: boolean
  enabled: boolean
  command_values: string[]
  safe_value: string | null
  current_value: string | null
  target_value: string | null
  updated_at: string
  reported_condition: string | null
  condition_reported_at: string | null
}

type ComponentConditionReport = {
  id: number
  device_id: string
  component_id: string
  condition: string
  reported_at: string
}

type ComponentConditionHistory = {
  items: ComponentConditionReport[]
  loading: boolean
  error: boolean
}

type Device = {
  device_id: string
  name: string
  status: 'belum_terhubung' | 'hidup' | 'mati'
  last_seen: string | null
  connection_status: 'never_seen' | 'online' | 'stale'
  age_seconds: number | null
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
  prediction_ready: boolean
  prediction_message: string | null
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
  precipitation_mm: number | null
  wind_speed_kmh: number | null
  weather_code: number
  is_day: boolean
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

type Theme = 'light' | 'dark'

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
  prediction_ready: false,
  prediction_message: null,
}

const eventLabels: Record<string, string> = {
  actuator_acknowledged: 'Aktuator selesai',
  actuator_commanded: 'Perintah aktuator',
  actuator_commands_superseded: 'Perintah digantikan',
  actuator_failed: 'Aktuator gagal',
  actuator_timeout: 'Perintah tidak mendapat ACK',
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

function formatAge(seconds: number) {
  if (seconds < 60) return `${seconds} detik lalu`
  if (seconds < 3600) return `${Math.floor(seconds / 60)} menit lalu`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} jam lalu`
  return `${Math.floor(seconds / 86400)} hari lalu`
}

function suggestUniqueId(value: string, existingIds: string[], maxLength: number) {
  const base = value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') || 'item'
  const existing = new Set(existingIds)
  let suffix = 1

  while (true) {
    const ending = `-${suffix}`
    const candidate = `${base.slice(0, maxLength - ending.length).replace(/-+$/g, '')}${ending}`
    if (!existing.has(candidate)) return candidate
    suffix += 1
  }
}

const API_BASE_URL = 'https://dev.pradnyasiwi.web.id'

function buildApiUrl(path: string) {
  const normalizedPath = path.startsWith('/') ? path : `/${path}`
  return `${API_BASE_URL}${normalizedPath}`.replace(/%7B/g, '{').replace(/%7D/g, '}')
}

function App() {
  const [dashboard, setDashboard] = useState(emptyDashboard)
  const [devices, setDevices] = useState<Device[]>([])
  const [components, setComponents] = useState<DeviceComponent[]>([])
  const [componentHistory, setComponentHistory] = useState<Record<string, ComponentConditionHistory>>({})
  const [sensorReadings, setSensorReadings] = useState<SensorReading[]>([])
  const [scratchVariables, setScratchVariables] = useState<ScratchVariable[]>([])
  const [eventFlags, setEventFlags] = useState<EventFlag[]>([])
  const [cameraStatus, setCameraStatus] = useState(emptyCameraStatus)
  const [apiOnline, setApiOnline] = useState(false)
  const [copiedEndpoint, setCopiedEndpoint] = useState('')
  const [uptimeInput, setUptimeInput] = useState('3600')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')
  const [weather, setWeather] = useState<Weather | null>(null)
  const [weatherLoading, setWeatherLoading] = useState(true)
  const [dryingTargetMinutes, setDryingTargetMinutes] = useState('60')
  const [variableNameInput, setVariableNameInput] = useState('')
  const [variableValueInput, setVariableValueInput] = useState('')
  const [variableValueType, setVariableValueType] = useState<'text' | 'number' | 'boolean' | 'null'>('text')
  const [editingVariableName, setEditingVariableName] = useState<string | null>(null)
  const [variableBusy, setVariableBusy] = useState(false)
  const [variableNotice, setVariableNotice] = useState('')
  const [eventNameInput, setEventNameInput] = useState('')
  const [eventValueInput, setEventValueInput] = useState('')
  const [eventBusy, setEventBusy] = useState(false)
  const [eventNotice, setEventNotice] = useState('')
  const [eventFlagNameInput, setEventFlagNameInput] = useState('')
  const [eventFlagModeInput, setEventFlagModeInput] = useState<EventFlag['mode']>('once')
  const [eventFlagBusy, setEventFlagBusy] = useState(false)
  const [eventFlagNotice, setEventFlagNotice] = useState('')
  const [deviceIdInput, setDeviceIdInput] = useState('')
  const [deviceNameInput, setDeviceNameInput] = useState('')
  const [editingDeviceId, setEditingDeviceId] = useState<string | null>(null)
  const [deviceBusy, setDeviceBusy] = useState(false)
  const [deviceNotice, setDeviceNotice] = useState('')
  const [componentIdInput, setComponentIdInput] = useState('')
  const [componentNameInput, setComponentNameInput] = useState('')
  const [componentTypeInput, setComponentTypeInput] = useState('other')
  const [componentEstimatedCountInput, setComponentEstimatedCountInput] = useState('')
  const [componentDeviceInput, setComponentDeviceInput] = useState('')
  const [componentValuesInput, setComponentValuesInput] = useState('')
  const [componentSafeInput, setComponentSafeInput] = useState('')
  const [componentConfirmedInput, setComponentConfirmedInput] = useState(false)
  const [componentNotice, setComponentNotice] = useState('')
  const [editingComponentId, setEditingComponentId] = useState<string | null>(null)
  const [theme, setTheme] = useState<Theme>(() => {
    const storedTheme = window.localStorage.getItem('agro-sembada-theme')
    if (storedTheme === 'light' || storedTheme === 'dark') return storedTheme
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  })
  const cameraImageRef = useRef<HTMLImageElement>(null)
  const cameraTimerRef = useRef<number | null>(null)
  const predictionBusyRef = useRef(false)

  async function copyEndpoint(path: string) {
    try {
      await navigator.clipboard.writeText(buildApiUrl(path))
      setCopiedEndpoint(path)
      window.setTimeout(() => setCopiedEndpoint(''), 1800)
    } catch {
      setCopiedEndpoint('error')
    }
  }

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    window.localStorage.setItem('agro-sembada-theme', theme)
  }, [theme])

  useEffect(() => {
    let active = true

    const refresh = async () => {
      try {
        const [dashboardResponse, devicesResponse, readingsResponse, componentsResponse, variablesResponse, eventFlagsResponse] = await Promise.all([
          fetch('/api/dashboard'),
          fetch('/api/devices'),
          fetch('/api/readings?limit=100'),
          fetch('/api/components'),
          fetch('/api/variables'),
          fetch('/api/event-flags'),
        ])
        if (!dashboardResponse.ok || !devicesResponse.ok || !readingsResponse.ok || !componentsResponse.ok || !variablesResponse.ok || !eventFlagsResponse.ok) {
          throw new Error('Backend tidak merespons')
        }
        const [data, deviceData, readingData, componentData, variableData, eventFlagData] = await Promise.all([
          dashboardResponse.json() as Promise<DashboardData>,
          devicesResponse.json() as Promise<Device[]>,
          readingsResponse.json() as Promise<SensorReading[]>,
          componentsResponse.json() as Promise<DeviceComponent[]>,
          variablesResponse.json() as Promise<ScratchVariable[]>,
          eventFlagsResponse.json() as Promise<EventFlag[]>,
        ])
        if (active) {
          setDashboard(data)
          setDevices(deviceData)
          setSensorReadings(readingData)
          setComponents(componentData)
          setScratchVariables(variableData)
          setEventFlags(eventFlagData)
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

  const stopCamera = async () => {
    try {
      const response = await fetch('/api/camera/stop', { method: 'POST' })
      const status = (await response.json()) as CameraStatus & { detail?: string }
      if (!response.ok) throw new Error(status.detail ?? 'Kamera gagal dihentikan.')
      setCameraStatus(status)
    } catch (error) {
      setCameraStatus((current) => ({
        ...current,
        state: 'error',
        message: error instanceof Error ? error.message : 'Kamera gagal dihentikan.',
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

  const processNextFrame = useEffectEvent(async () => {
    const cameraFrame = cameraImageRef.current
    if (cameraActive && cameraStatus.prediction_ready && cameraFrame?.complete && cameraFrame.naturalWidth > 0 && !predictionBusyRef.current) {
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
  })

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

  const editScratchVariable = (variable: ScratchVariable) => {
    setEditingVariableName(variable.name)
    setVariableNameInput(variable.name)
    setVariableValueInput(variable.value === null ? '' : String(variable.value))
    setVariableValueType(
      variable.value === null ? 'null' : typeof variable.value === 'boolean' ? 'boolean' : typeof variable.value === 'number' ? 'number' : 'text',
    )
    setVariableNotice('')
  }

  const cancelScratchVariableEdit = () => {
    setEditingVariableName(null)
    setVariableNameInput('')
    setVariableValueInput('')
    setVariableValueType('text')
    setVariableNotice('')
  }

  const saveScratchVariable = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const name = variableNameInput.trim()
    let value: ScratchVariable['value']

    if (variableValueType === 'null') {
      value = null
    } else if (variableValueType === 'boolean') {
      value = variableValueInput === 'true'
    } else if (variableValueType === 'number') {
      value = Number(variableValueInput)
      if (!variableValueInput.trim() || !Number.isFinite(value)) {
        setVariableNotice('Nilai angka tidak valid.')
        return
      }
    } else {
      value = variableValueInput
    }

    setVariableBusy(true)
    setVariableNotice('Menyimpan variabel...')
    try {
      const response = await fetch(`/api/variables/${encodeURIComponent(name)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ value }),
      })
      const body = (await response.json()) as ScratchVariable & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Variabel gagal disimpan.')
      setScratchVariables((current) => [...current.filter((item) => item.name !== body.name), body]
        .sort((first, second) => first.name.localeCompare(second.name)))
      setEditingVariableName(null)
      setVariableNotice(`Variabel ${body.name} berhasil disimpan.`)
    } catch (error) {
      setVariableNotice(error instanceof Error ? error.message : 'Tidak dapat menyimpan variabel.')
    } finally {
      setVariableBusy(false)
    }
  }

  const submitCustomEvent = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setEventBusy(true)
    setEventNotice('Mencatat event...')
    try {
      const response = await fetch('/api/events', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event_type: eventNameInput.trim(),
          value: eventValueInput.trim() || null,
          duration_seconds: null,
          detail: {},
        }),
      })
      const body = (await response.json()) as OperationEvent & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Event gagal dicatat.')
      setDashboard((current) => ({ ...current, events: [body, ...current.events].slice(0, 200) }))
      setEventNameInput('')
      setEventValueInput('')
      setEventNotice(`Event ${body.event_type} berhasil dicatat.`)
    } catch (error) {
      setEventNotice(error instanceof Error ? error.message : 'Tidak dapat mencatat event.')
    } finally {
      setEventBusy(false)
    }
  }

  const createEventFlag = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setEventFlagBusy(true)
    setEventFlagNotice('Membuat event flag...')
    try {
      const response = await fetch('/api/event-flags', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: eventFlagNameInput.trim(), mode: eventFlagModeInput }),
      })
      const body = (await response.json()) as EventFlag & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Event flag gagal dibuat.')
      setEventFlags((current) => [...current, body].sort((first, second) => first.name.localeCompare(second.name)))
      setEventFlagNameInput('')
      setEventFlagNotice(`Event ${body.name} siap dinyalakan.`)
    } catch (error) {
      setEventFlagNotice(error instanceof Error ? error.message : 'Tidak dapat membuat event flag.')
    } finally {
      setEventFlagBusy(false)
    }
  }

  const updateEventFlag = async (flag: EventFlag, changes: Partial<Pick<EventFlag, 'active' | 'mode'>>) => {
    setEventFlagBusy(true)
    setEventFlagNotice('Memperbarui event flag...')
    try {
      const response = await fetch(`/api/event-flags/${encodeURIComponent(flag.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(changes),
      })
      const body = (await response.json()) as EventFlag & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Event flag gagal diperbarui.')
      setEventFlags((current) => current.map((item) => item.name === body.name ? body : item))
      setEventFlagNotice(`${body.name} ${body.active ? 'aktif' : 'mati'} · ${body.mode === 'once' ? 'sekali dibaca' : 'menunggu reset Artec'}.`)
    } catch (error) {
      setEventFlagNotice(error instanceof Error ? error.message : 'Tidak dapat memperbarui event flag.')
    } finally {
      setEventFlagBusy(false)
    }
  }

  const registerDevice = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setDeviceBusy(true)
    setDeviceNotice('')
    const isEditing = editingDeviceId !== null

    try {
      const response = await fetch(
        isEditing ? `/api/devices/${encodeURIComponent(editingDeviceId)}` : '/api/devices',
        {
        method: isEditing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(isEditing
          ? { name: deviceNameInput.trim() }
          : { device_id: deviceIdInput.trim(), name: deviceNameInput.trim() }),
      })
      const body = (await response.json()) as Device & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? (isEditing ? 'Nama alat gagal diubah.' : 'Alat gagal ditambahkan.'))
      setDevices((current) => (isEditing
        ? current.map((device) => device.device_id === body.device_id ? body : device)
        : [...current, body]
      ).sort((first, second) => first.device_id.localeCompare(second.device_id)))
      setDeviceIdInput('')
      setDeviceNameInput('')
      setEditingDeviceId(null)
      setDeviceNotice(isEditing ? `Nama ${body.device_id} berhasil diubah.` : `${body.name} berhasil ditambahkan.`)
    } catch (error) {
      setDeviceNotice(error instanceof Error ? error.message : 'Tidak dapat menambahkan alat.')
    } finally {
      setDeviceBusy(false)
    }
  }

  const editDeviceName = (device: Device) => {
    setEditingDeviceId(device.device_id)
    setDeviceIdInput(device.device_id)
    setDeviceNameInput(device.name)
    setDeviceNotice('')
    document.getElementById('device-name')?.focus()
  }

  const cancelDeviceNameEdit = () => {
    setEditingDeviceId(null)
    setDeviceIdInput('')
    setDeviceNameInput('')
    setDeviceNotice('')
  }

  const fillComponentSuggestion = (inventoryId: string) => {
    const inventory = components.find((component) => component.component_id === inventoryId)
    if (!inventory) return

    const suggestedName = inventory.name.replace(/\s*\(perkiraan\)\s*/i, '').trim()
    const suggestedType = inventory.component_type.replace(/_estimate$/, '')
    const supportedTypes = ['dc_motor', 'servo', 'light_sensor', 'sound_sensor', 'ir_photoreflector']
    setComponentIdInput(suggestUniqueId(suggestedName, components.map((component) => component.component_id), 80))
    setComponentNameInput(suggestedName)
    setComponentTypeInput(supportedTypes.includes(suggestedType) ? suggestedType : 'other')
    setComponentEstimatedCountInput(inventory.estimated_count ?? '')
    setComponentDeviceInput('')
    setComponentConfirmedInput(false)
    setComponentNotice('Saran diterapkan. Verifikasi pemetaan fisik sebelum mengaktifkan command.')
  }

  const registerComponent = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setDeviceBusy(true)
    setComponentNotice('')
    const commandValues = componentValuesInput.split(',').map((value) => value.trim()).filter(Boolean)
    const isActuator = ['dc_motor', 'servo', 'actuator'].includes(componentTypeInput)
    const isEditing = editingComponentId !== null
    try {
      const componentUrl = isEditing
        ? `/api/components/${encodeURIComponent(editingComponentId)}`
        : '/api/components'
      const response = await fetch(componentUrl, {
        method: isEditing ? 'PUT' : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          component_id: componentIdInput.trim(),
          name: componentNameInput.trim(),
          component_type: componentTypeInput,
          estimated_count: componentEstimatedCountInput.trim() || null,
          device_id: componentDeviceInput || null,
          confirmed: componentConfirmedInput,
          enabled: componentConfirmedInput && isActuator,
          command_values: commandValues,
          safe_value: componentSafeInput.trim() || null,
        }),
      })
      const body = (await response.json()) as DeviceComponent & { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Komponen gagal ditambahkan.')
      setComponents((current) => {
        const next = isEditing
          ? current.map((component) => component.component_id === body.component_id ? body : component)
          : [...current, body]
        return next.sort((first, second) => first.component_id.localeCompare(second.component_id))
      })
      setComponentIdInput('')
      setComponentNameInput('')
      setComponentTypeInput('other')
      setComponentEstimatedCountInput('')
      setComponentDeviceInput('')
      setComponentValuesInput('')
      setComponentSafeInput('')
      setComponentConfirmedInput(false)
      setEditingComponentId(null)
      setComponentNotice(`${body.name} berhasil ${isEditing ? 'diperbarui' : 'ditambahkan'}.`)
    } catch (error) {
      setComponentNotice(error instanceof Error ? error.message : 'Tidak dapat menambahkan komponen.')
    } finally {
      setDeviceBusy(false)
    }
  }

  const editComponent = (component: DeviceComponent) => {
    setEditingComponentId(component.component_id)
    setComponentIdInput(component.component_id)
    setComponentNameInput(component.name)
    setComponentTypeInput(component.component_type)
    setComponentEstimatedCountInput(component.estimated_count ?? '')
    setComponentDeviceInput(component.device_id ?? '')
    setComponentValuesInput(component.command_values.join(', '))
    setComponentSafeInput(component.safe_value ?? '')
    setComponentConfirmedInput(component.confirmed)
    setComponentNotice('')
    document.getElementById('component-id')?.focus()
  }

  const cancelComponentEdit = () => {
    setEditingComponentId(null)
    setComponentIdInput('')
    setComponentNameInput('')
    setComponentTypeInput('other')
    setComponentEstimatedCountInput('')
    setComponentDeviceInput('')
    setComponentValuesInput('')
    setComponentSafeInput('')
    setComponentConfirmedInput(false)
    setComponentNotice('')
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

  const commandComponent = async (component: DeviceComponent, position: string) => {
    if (!component.device_id) return
    setBusy(true)
    try {
      const response = await fetch(
        `/api/devices/${encodeURIComponent(component.device_id)}/components/${encodeURIComponent(component.component_id)}/commands`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ position }),
        },
      )
      const body = (await response.json()) as { detail?: string }
      if (!response.ok) throw new Error(body.detail ?? 'Command aktuator gagal dikirim.')
      setNotice(`Command ${component.name} diterima server; menunggu unit mengambil dan mengirim ACK.`)
    } catch (error) {
      setNotice(error instanceof Error ? error.message : 'Command aktuator gagal dikirim.')
    } finally {
      setBusy(false)
    }
  }

  const loadComponentHistory = async (component: DeviceComponent) => {
    setComponentHistory((current) => ({
      ...current,
      [component.component_id]: {
        items: current[component.component_id]?.items ?? [],
        loading: true,
        error: false,
      },
    }))
    try {
      const params = new URLSearchParams({ component_id: component.component_id, limit: '10' })
      const response = await fetch(`/api/component-condition-reports?${params}`)
      const body = (await response.json()) as ComponentConditionReport[]
      if (!response.ok) throw new Error('Riwayat kondisi tidak tersedia.')
      setComponentHistory((current) => ({
        ...current,
        [component.component_id]: { items: body, loading: false, error: false },
      }))
    } catch {
      setComponentHistory((current) => ({
        ...current,
        [component.component_id]: {
          items: current[component.component_id]?.items ?? [],
          loading: false,
          error: true,
        },
      }))
    }
  }

  const prediction = dashboard.prediction
  const telemetry = dashboard.telemetry
  const access = dashboard.access
  const control = dashboard.control
  const roof = control.actuators.find((actuator) => actuator.name === 'roof')
  const dryingActive = control.drying_started_at !== null
  const controlsDisabled = busy || control.emergency_mode
  const activeDeviceCount = devices.filter(
    (device) => device.status === 'hidup' && device.connection_status === 'online',
  ).length
  const seenSensors = new Set<string>()
  const latestSensorReadings = sensorReadings.filter((reading) => {
    const key = `${reading.device_id}:${reading.sensor_id}`
    if (seenSensors.has(key)) return false
    seenSensors.add(key)
    return true
  }).slice(0, 12)
  const weatherCode = weather?.weather_code ?? -1
  const WeatherIcon = weatherCode >= 95
    ? CloudLightning
    : weatherCode === 45 || weatherCode === 48
      ? CloudFog
      : weatherCode >= 80 || (weatherCode >= 61 && weatherCode <= 65)
        ? CloudRain
        : weatherCode >= 51 && weatherCode <= 55
          ? CloudDrizzle
          : weatherCode === 3 || weatherCode === 2
            ? Cloud
            : weatherCode === 0 && !weather?.is_day
              ? Moon
              : weatherCode === 0
                ? Sun
                : CloudSun

  return (
    <main className="dashboard-shell">
      <header className="topbar">
        <a className="brand" href="#dashboard" aria-label="AGRO-SEMBADA dashboard">
          <img className="brand-mark" src="/assets/brand/dada.jpeg" alt="Logo SMPN 4 Pakem" width={44} height={44} />
          <span className="brand-name">AGRO<span>-</span>SEMBADA</span>
        </a>
        <div className="topbar-meta">
          <span className="team-label">PRADNYASIWI QUADTECH</span>
          <span className="school-label">SMPN 4 PAKEM</span>
        </div>
        <div className="topbar-actions">
          <button
            className="theme-toggle"
            type="button"
            onClick={() => setTheme((current) => current === 'dark' ? 'light' : 'dark')}
            aria-label={theme === 'dark' ? 'Aktifkan tema terang' : 'Aktifkan tema gelap'}
            title={theme === 'dark' ? 'Tema terang' : 'Tema gelap'}
          >
            {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
          </button>
          <div className={`connection-pill ${apiOnline ? 'is-online' : 'is-offline'}`}>
            {apiOnline ? <Wifi size={15} /> : <WifiOff size={15} />}
            <span>{apiOnline ? 'SERVER TERHUBUNG' : 'SERVER TERPUTUS'}</span>
          </div>
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
      </section>

      <section className="weather-panel" aria-labelledby="weather-title">
        <div className="weather-hero">
          <div className={`weather-visual ${weather?.is_day ? 'is-day' : 'is-night'}`} aria-hidden="true">
            <WeatherIcon size={70} strokeWidth={1.4} />
            {weather?.is_day && <span className="weather-sun-disc" />}
          </div>
          <div className="weather-current">
            <p className="section-index"><span className="weather-live-dot" /> CUACA SAAT INI</p>
            <h2 id="weather-title">{weather?.location ?? 'Cuaca Pakem'}</h2>
            {weather ? (
              <>
                <div className="weather-temperature">{Math.round(weather.temperature_c)}<span>°C</span></div>
                <p className="weather-condition">{weather.condition}<span> · </span>Terasa {Math.round(weather.apparent_temperature_c)}°C</p>
              </>
            ) : (
              <p className="weather-condition">{weatherLoading ? 'Mengambil kondisi terkini...' : 'Data cuaca tidak tersedia'}</p>
            )}
            <span className="weather-observed">{weather ? `DIPERBARUI ${formatTimestamp(weather.observed_at)}` : 'PAKEM, SLEMAN'}</span>
          </div>
        </div>
        <div className="weather-measures" aria-label="Visualisasi parameter cuaca terkini">
          <div className="weather-measure">
            <div className="weather-measure-heading"><span><Droplets size={15} /> KELEMBAPAN</span><strong>{weather ? `${Math.round(weather.humidity_percent)}%` : '--'}</strong></div>
            <div className="weather-bar"><span className="humidity-bar" style={{ width: `${weather ? Math.min(100, Math.max(0, weather.humidity_percent)) : 0}%` }} /></div>
            <small>RELATIF</small>
          </div>
          <div className="weather-measure">
            <div className="weather-measure-heading"><span><CloudRain size={15} /> CURAH HUJAN</span><strong>{weather?.precipitation_mm != null ? `${weather.precipitation_mm.toFixed(1)} mm` : '--'}</strong></div>
            <div className="weather-bar"><span className="rain-bar" style={{ width: `${weather?.precipitation_mm != null ? Math.min(100, Math.max(0, weather.precipitation_mm) * 10) : 0}%` }} /></div>
            <small>{weather?.precipitation_mm != null && weather.precipitation_mm > 0 ? 'SEDANG TURUN' : 'SAAT INI'}</small>
          </div>
          <div className="weather-measure">
            <div className="weather-measure-heading"><span><Wind size={15} /> KECEPATAN ANGIN</span><strong>{weather?.wind_speed_kmh != null ? `${Math.round(weather.wind_speed_kmh)} km/j` : '--'}</strong></div>
            <div className="weather-bar"><span className="wind-bar" style={{ width: `${weather?.wind_speed_kmh != null ? Math.min(100, Math.max(0, weather.wind_speed_kmh / 0.6)) : 0}%` }} /></div>
            <small>ANGIN PERMUKAAN</small>
          </div>
        </div>
      </section>

      <section className="panel devices-panel" aria-labelledby="devices-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">ALAT TERDAFTAR</p>
            <h2 id="devices-title">Status perangkat</h2>
          </div>
          <span className="device-summary"><span className={`device-summary-dot ${activeDeviceCount === 0 ? 'is-idle' : ''}`} />{activeDeviceCount} AKTIF <i>/</i> {devices.length} ALAT</span>
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
                  <span>{device.connection_status === 'stale' ? 'Laporan status terlambat' : device.age_seconds === null ? 'Belum pernah melapor' : `Terakhir ${formatAge(device.age_seconds)}`}</span>
                </div>
                <button
                  className="device-name-edit"
                  type="button"
                  onClick={() => editDeviceName(device)}
                  title={`Ubah nama ${device.name}`}
                  aria-label={`Ubah nama ${device.name}`}
                ><Pencil size={13} /></button>
              </div>
            ))}
          </div>
          <form className="device-form" onSubmit={(event) => void registerDevice(event)}>
            <div>
              <p className="section-index">{editingDeviceId ? 'PENGATURAN NAMA' : 'REGISTRASI'}</p>
              <h3>{editingDeviceId ? 'Ubah nama perangkat' : 'Tambah alat'}</h3>
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
            {!editingDeviceId && <>
              <div className="device-id-heading">
                <label htmlFor="device-id">ID alat</label>
                <button
                  type="button"
                  onClick={() => setDeviceIdInput(suggestUniqueId(deviceNameInput || 'alat', devices.map((device) => device.device_id), 40))}
                >Buat ID otomatis</button>
              </div>
              <input
                id="device-id"
                value={deviceIdInput}
                onChange={(event) => setDeviceIdInput(event.target.value)}
                placeholder="Contoh: pompa-air"
                pattern="[A-Za-z0-9][A-Za-z0-9_]*(-[A-Za-z0-9_]+)*"
                maxLength={40}
                required
              />
            </>}
            <button className="button button-primary" type="submit" disabled={deviceBusy || !apiOnline}>
              {editingDeviceId ? <Check size={15} /> : <Plus size={15} />}
              {editingDeviceId ? 'Simpan nama' : 'Tambah perangkat'}
            </button>
            {editingDeviceId && <button className="button button-secondary" type="button" onClick={cancelDeviceNameEdit}>Batal</button>}
            {deviceNotice && <p className="device-notice" role="status">{deviceNotice}</p>}
          </form>
        </div>
      </section>

      <MachineOverviewErrorBoundary>
        <Suspense fallback={<section className="machine-scene-loading" aria-live="polite">Memuat visualisasi unit...</section>}>
          <MachineOverview devices={devices} theme={theme} />
        </Suspense>
      </MachineOverviewErrorBoundary>

      <section className="panel sensor-panel" aria-labelledby="sensor-readings-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">TELEMETRI SENSOR</p>
            <h2 id="sensor-readings-title">Pembacaan terbaru</h2>
          </div>
          <span className="sensor-reading-count">{latestSensorReadings.length} SENSOR</span>
        </div>
        <div className="sensor-reading-list" aria-live="polite">
          {latestSensorReadings.length === 0 ? (
            <p className="empty-readings">Belum ada pembacaan sensor.</p>
          ) : latestSensorReadings.map((reading) => (
            <div className="sensor-reading-row" key={`${reading.device_id}:${reading.sensor_id}`}>
              <div className="sensor-reading-identity">
                <strong>{reading.sensor_id}</strong>
                <span>{reading.sensor_type} · {reading.device_id}</span>
              </div>
              <strong className="sensor-reading-value">
                {new Intl.NumberFormat('id-ID', { maximumFractionDigits: 2 }).format(reading.value)}{reading.unit ? ` ${reading.unit}` : ''}
              </strong>
              <span className="sensor-reading-time">{formatTimestamp(reading.recorded_at)}</span>
            </div>
          ))}
        </div>
      </section>

      <section className="panel components-panel" aria-labelledby="components-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">KATALOG HARDWARE</p>
            <h2 id="components-title">Komponen per unit</h2>
          </div>
          <span className="sensor-reading-count">{components.length} TERDAFTAR</span>
        </div>
        <div className="component-list" aria-live="polite">
          {components.length === 0 ? (
            <p className="empty-readings">Belum ada komponen yang dipetakan. Tambahkan komponen setelah unit dan wiring-nya terkonfirmasi.</p>
          ) : components.map((component) => {
            const owner = devices.find((device) => device.device_id === component.device_id)
            const canControl = component.confirmed && component.enabled && owner?.connection_status === 'online'
            return (
              <article className="component-row" key={component.component_id}>
                <div className="component-identity">
                  <strong>{component.name}</strong>
                  <span>{component.component_id} · {component.component_type}{component.estimated_count ? ` · ${component.estimated_count}` : ''}</span>
                </div>
                <span className={`component-mapping ${component.confirmed ? 'is-confirmed' : ''}`}>
                  {component.device_id ?? 'Belum dipetakan'} · {component.confirmed ? 'TERKONFIRMASI' : 'PERLU VERIFIKASI'}
                </span>
                <button className="component-edit" type="button" onClick={() => editComponent(component)} title={`Edit ${component.name}`} aria-label={`Edit ${component.name}`}>
                  <Pencil size={13} />
                </button>
                <div className="component-condition-row">
                  <span>Kondisi</span>
                  <strong>{component.reported_condition ?? 'Belum ada laporan'}</strong>
                  <small>{formatTimestamp(component.condition_reported_at ?? undefined)}</small>
                </div>
                <details
                  className="component-condition-history"
                  onToggle={(event) => {
                    if (event.currentTarget.open) void loadComponentHistory(component)
                  }}
                >
                  <summary>Riwayat kondisi</summary>
                  <div className="component-condition-history-list">
                    {componentHistory[component.component_id]?.loading ? (
                      <span>Memuat riwayat...</span>
                    ) : componentHistory[component.component_id]?.error ? (
                      <span>Riwayat tidak dapat dimuat.</span>
                    ) : componentHistory[component.component_id]?.items.length ? (
                      componentHistory[component.component_id].items.map((report) => (
                        <div key={report.id}>
                          <strong>{report.condition}</strong>
                          <time>{formatTimestamp(report.reported_at)}</time>
                        </div>
                      ))
                    ) : (
                      <span>Belum ada riwayat kondisi.</span>
                    )}
                  </div>
                </details>
                {component.command_values.length > 0 && (
                  <div className="component-command-row">
                    <span>Posisi {component.current_value ?? 'belum diketahui'} → target {component.target_value ?? '--'}</span>
                    <div className="component-command-buttons">
                      {component.command_values.map((value) => (
                        <button
                          className="button button-secondary"
                          key={value}
                          type="button"
                          disabled={!canControl || controlsDisabled || control.mode !== 'manual'}
                          onClick={() => void commandComponent(component, value)}
                        >{value}</button>
                      ))}
                    </div>
                  </div>
                )}
              </article>
            )
          })}
        </div>
        <form className="component-form" onSubmit={(event) => void registerComponent(event)}>
          <div className="component-form-heading">
            <strong>{editingComponentId ? 'Perbarui komponen' : 'Daftarkan komponen'}</strong>
            <span>Mapping awal boleh dibiarkan belum terkonfirmasi.</span>
          </div>
          <div className="component-form-grid">
            {!editingComponentId && <label className="component-suggestion">Saran dari inventaris<select value="" onChange={(event) => fillComponentSuggestion(event.target.value)}><option value="">Pilih inventaris untuk mengisi data</option>{components.filter((component) => component.component_type.endsWith('_estimate') || component.component_type === 'unconfirmed_inventory').map((component) => <option value={component.component_id} key={component.component_id}>{component.name}{component.estimated_count ? ` · ${component.estimated_count}` : ''}</option>)}</select></label>}
            <label>ID komponen<input id="component-id" value={componentIdInput} onChange={(event) => setComponentIdInput(event.target.value)} pattern="[A-Za-z0-9][A-Za-z0-9_]*(-[A-Za-z0-9_]+)*" maxLength={80} required placeholder="motor-elevator-1" disabled={editingComponentId !== null} /></label>
            <label>Nama<input value={componentNameInput} onChange={(event) => setComponentNameInput(event.target.value)} maxLength={100} required placeholder="Motor elevator" /></label>
            <label>Jenis<select value={componentTypeInput} onChange={(event) => setComponentTypeInput(event.target.value)}><option value="dc_motor">Motor DC</option><option value="servo">Servo</option><option value="light_sensor">Sensor cahaya</option><option value="sound_sensor">Sensor suara</option><option value="ir_photoreflector">IR photoreflector</option><option value="other">Lainnya</option></select></label>
            <label>Perkiraan jumlah<input value={componentEstimatedCountInput} onChange={(event) => setComponentEstimatedCountInput(event.target.value)} maxLength={32} placeholder="mis. sekitar 4" /></label>
            <label>Core Unit<select value={componentDeviceInput} onChange={(event) => setComponentDeviceInput(event.target.value)}><option value="">Belum dipetakan</option>{devices.map((device) => <option value={device.device_id} key={device.device_id}>{device.name}</option>)}</select></label>
            {['dc_motor', 'servo'].includes(componentTypeInput) && <>
              <label>Nilai command<input value={componentValuesInput} onChange={(event) => setComponentValuesInput(event.target.value)} placeholder="forward, reverse, stop" /></label>
              <label>Nilai aman<input value={componentSafeInput} onChange={(event) => setComponentSafeInput(event.target.value)} placeholder="stop" /></label>
            </>}
          </div>
          <label className="component-confirm-label"><input type="checkbox" checked={componentConfirmedInput} onChange={(event) => setComponentConfirmedInput(event.target.checked)} /> Saya sudah memverifikasi pemetaan fisik dan posisi aman</label>
          <div className="component-form-actions">
            <button className="button button-primary" type="submit" disabled={deviceBusy || !apiOnline}><Plus size={15} /> {editingComponentId ? 'Perbarui komponen' : 'Simpan komponen'}</button>
            {editingComponentId && <button className="button button-secondary" type="button" onClick={cancelComponentEdit}>Batal</button>}
          </div>
          {componentNotice && <p className="device-notice" role="status">{componentNotice}</p>}
        </form>
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
          {cameraActive && !cameraStatus.prediction_ready && (
            <p className="camera-model-note">Preview kamera aktif; {cameraStatus.prediction_message ?? 'model Keras belum siap untuk analisis.'}</p>
          )}

          <div className="camera-controls">
            <button
              className="button button-secondary"
              type="button"
              onClick={() => void (cameraActive ? stopCamera() : rescanCameras())}
              disabled={cameraStatus.state === 'scanning'}
            >
              {cameraActive ? <Square size={14} /> : <RefreshCw size={15} />}
              {cameraActive ? 'Matikan kamera' : cameraStatus.state === 'scanning' ? 'Memindai kamera...' : 'Pindai semua kamera'}
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
            <div className="event-methods"><span className="post-label">POST</span><span className="get-label">GET</span></div>
          </div>
          <div className="event-flag-manager">
            <div className="event-flag-heading">
              <strong>Sinyal untuk ArtecRobo</strong>
              <span>GET sekali baca atau tunggu POST false dari alat</span>
            </div>
            <form className="event-flag-create" onSubmit={(event) => void createEventFlag(event)}>
              <label>
                <span>Nama flag</span>
                <input
                  value={eventFlagNameInput}
                  onChange={(event) => setEventFlagNameInput(event.target.value)}
                  pattern="[A-Za-z0-9][A-Za-z0-9_-]*"
                  maxLength={80}
                  required
                  placeholder="buka_lumbung"
                />
              </label>
              <label>
                <span>Reset</span>
                <select value={eventFlagModeInput} onChange={(event) => setEventFlagModeInput(event.target.value as EventFlag['mode'])}>
                  <option value="once">Setelah GET pertama</option>
                  <option value="ack">Saat Artec POST false</option>
                </select>
              </label>
              <button className="button button-secondary" type="submit" disabled={eventFlagBusy || !apiOnline}>
                <Plus size={14} /> Buat flag
              </button>
            </form>
            <div className="event-flag-list" aria-live="polite">
              {eventFlags.length === 0 ? (
                <p className="empty-events">Belum ada flag untuk ArtecRobo.</p>
              ) : eventFlags.map((flag) => (
                <div className="event-flag-row" key={flag.name}>
                  <div className="event-flag-identity">
                    <strong>{flag.name}</strong>
                    <span className={flag.active ? 'event-flag-active' : ''}>{flag.active ? 'AKTIF' : 'MATI'}</span>
                  </div>
                  <select
                    aria-label={`Mode reset ${flag.name}`}
                    value={flag.mode}
                    disabled={eventFlagBusy || !apiOnline}
                    onChange={(event) => void updateEventFlag(flag, { mode: event.target.value as EventFlag['mode'] })}
                  >
                    <option value="once">Sekali dibaca</option>
                    <option value="ack">Tunggu POST false</option>
                  </select>
                  <button
                    className={flag.active ? 'button button-secondary' : 'button button-primary'}
                    type="button"
                    disabled={eventFlagBusy || !apiOnline}
                    onClick={() => void updateEventFlag(flag, { active: !flag.active })}
                  >{flag.active ? 'Matikan' : 'Nyalakan'}</button>
                </div>
              ))}
            </div>
            {eventFlagNotice && <p className="device-notice" role="status">{eventFlagNotice}</p>}
          </div>
          <form className="event-compose" onSubmit={(event) => void submitCustomEvent(event)}>
            <label>
              <span>Nama event</span>
              <input
                value={eventNameInput}
                onChange={(event) => setEventNameInput(event.target.value)}
                maxLength={80}
                required
                placeholder="panen_dimulai"
              />
            </label>
            <label>
              <span>Nilai</span>
              <input
                value={eventValueInput}
                onChange={(event) => setEventValueInput(event.target.value)}
                maxLength={160}
                placeholder="blok_1 (opsional)"
              />
            </label>
            <button className="button button-primary" type="submit" disabled={eventBusy || !apiOnline}>
              <Send size={14} /> Catat event
            </button>
            {eventNotice && <p className="device-notice" role="status">{eventNotice}</p>}
          </form>
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

      <section className="panel variables-panel" aria-labelledby="variables-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">05 / SCRATCH</p>
            <h2 id="variables-title">Variabel tersimpan</h2>
          </div>
          <span className="sensor-reading-count">{scratchVariables.length} VARIABEL</span>
        </div>
        <div className="variable-manager-layout">
          <div className="scratch-variable-list" aria-live="polite">
            {scratchVariables.length === 0 ? (
              <p className="empty-readings">Belum ada variabel. Buat variabel pertama di samping.</p>
            ) : scratchVariables.map((variable) => (
              <div className="scratch-variable-row" key={variable.name}>
                <div className="scratch-variable-identity">
                  <strong>{variable.name}</strong>
                  <span>{variable.value === null ? 'KOSONG' : typeof variable.value} · {formatTimestamp(variable.updated_at)}</span>
                </div>
                <code>{variable.value === null ? 'null' : String(variable.value)}</code>
                <button
                  className="component-edit"
                  type="button"
                  onClick={() => editScratchVariable(variable)}
                  title={`Ubah ${variable.name}`}
                  aria-label={`Ubah variabel ${variable.name}`}
                ><Pencil size={13} /></button>
              </div>
            ))}
          </div>
          <form className="scratch-variable-form" onSubmit={(event) => void saveScratchVariable(event)}>
            <strong>{editingVariableName ? `Ubah ${editingVariableName}` : 'Buat variabel'}</strong>
            <label htmlFor="scratch-variable-name">Nama variabel</label>
            <input
              id="scratch-variable-name"
              value={variableNameInput}
              onChange={(event) => setVariableNameInput(event.target.value)}
              maxLength={80}
              required
              disabled={editingVariableName !== null}
              placeholder="jumlah_panen"
            />
            <label htmlFor="scratch-variable-type">Tipe nilai</label>
            <select
              id="scratch-variable-type"
              value={variableValueType}
              onChange={(event) => {
                const nextType = event.target.value as typeof variableValueType
                setVariableValueType(nextType)
                if (nextType === 'boolean') setVariableValueInput('true')
                if (nextType === 'null') setVariableValueInput('')
              }}
            >
              <option value="text">Teks</option>
              <option value="number">Angka</option>
              <option value="boolean">Boolean</option>
              <option value="null">Kosong (null)</option>
            </select>
            <label htmlFor="scratch-variable-value">Nilai</label>
            {variableValueType === 'boolean' ? (
              <select id="scratch-variable-value" value={variableValueInput} onChange={(event) => setVariableValueInput(event.target.value)}>
                <option value="true">true</option>
                <option value="false">false</option>
              </select>
            ) : (
              <input
                id="scratch-variable-value"
                type={variableValueType === 'number' ? 'number' : 'text'}
                step={variableValueType === 'number' ? 'any' : undefined}
                value={variableValueInput}
                onChange={(event) => setVariableValueInput(event.target.value)}
                maxLength={500}
                required={variableValueType !== 'null'}
                disabled={variableValueType === 'null'}
                placeholder={variableValueType === 'null' ? 'null' : variableValueType === 'number' ? '42' : 'Sedang dijemur'}
              />
            )}
            <div className="scratch-variable-actions">
              <button className="button button-primary" type="submit" disabled={variableBusy || !apiOnline}>
                <Check size={14} /> Simpan variabel
              </button>
              {editingVariableName && <button className="button button-secondary" type="button" onClick={cancelScratchVariableEdit}>Batal</button>}
            </div>
            {variableNotice && <p className="device-notice" role="status">{variableNotice}</p>}
          </form>
        </div>
      </section>

      <section className="api-docs-panel panel" aria-labelledby="api-docs-title">
        <div className="panel-heading compact-heading">
          <div>
            <p className="section-index">06 / REFERENSI API</p>
            <h2 id="api-docs-title">Endpoint siap disalin</h2>
          </div>
          <a className="docs-link" href="/docs" target="_blank" rel="noreferrer">
            Buka Swagger <ArrowUpRight size={13} />
          </a>
        </div>
        <div className="quick-endpoints">
          {[
            { method: 'GET', path: '/api/dashboard', label: 'Ringkasan dashboard' },
            { method: 'GET', path: '/api/devices', label: 'Daftar perangkat' },
            { method: 'GET', path: '/api/readings', label: 'Data sensor' },
            { method: 'POST', path: '/api/telemetry', label: 'Kirim telemetri' },
            { method: 'GET', path: '/api/artec/devices/{device_id}/online', label: 'Status online per perangkat' },
          ].map((endpoint) => (
            <button
              className="endpoint-copy"
              key={endpoint.path}
              type="button"
              onClick={() => void copyEndpoint(endpoint.path)}
              title={`Salin ${endpoint.path}`}
            >
              <span className={`endpoint-method ${endpoint.method.toLowerCase()}`}>{endpoint.method}</span>
              <span className="endpoint-description">
                <strong>{endpoint.label}</strong>
                <code>{endpoint.path}</code>
              </span>
              <span className="endpoint-action" aria-label={copiedEndpoint === endpoint.path ? 'Tersalin' : 'Salin endpoint'}>
                {copiedEndpoint === endpoint.path ? <Check size={15} /> : <Copy size={15} />}
              </span>
            </button>
          ))}
        </div>
        <p className="form-footnote" role="status">
          {copiedEndpoint === 'error' ? 'Gagal menyalin. Coba lagi.' : copiedEndpoint ? 'Link API tersalin ke clipboard.' : 'Klik endpoint untuk menyalin link lengkap.'}
        </p>
      </section>

      <footer className="footer"><span>AGRO-SEMBADA <i>×</i> PRADNYASIWI QUADTECH</span><span>SMPN 4 PAKEM <b>·</b> SISTEM MONITORING</span></footer>
    </main>
  )
}

export default App
