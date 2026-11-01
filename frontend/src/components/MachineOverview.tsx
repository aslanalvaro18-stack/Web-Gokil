import { Canvas } from '@react-three/fiber'
import { Html, OrbitControls } from '@react-three/drei'
import { useEffect, useState } from 'react'

type Unit = {
  device_id: string
  name: string
  status: 'belum_terhubung' | 'hidup' | 'mati'
  connection_status: 'never_seen' | 'online' | 'stale'
}

type MachineOverviewProps = {
  devices: Unit[]
}

const UNIT_IDS = Array.from({ length: 6 }, (_, index) => `alat-${index + 1}`)

function statusColor(unit?: Unit) {
  if (unit?.connection_status === 'online' && unit.status === 'hidup') return '#b9d65b'
  if (unit?.connection_status === 'stale') return '#d79b42'
  return '#8d9990'
}

function CoreUnit({ unit, index }: { unit?: Unit; index: number }) {
  const column = index % 3
  const row = Math.floor(index / 3)
  const position: [number, number, number] = [(column - 1) * 2.25, 0, (row - 0.5) * 2.05]
  const color = statusColor(unit)

  return (
    <group position={position}>
      <mesh position={[0, 0, 0]} castShadow receiveShadow>
        <boxGeometry args={[1.5, 0.34, 1.15]} />
        <meshStandardMaterial color="#253b32" roughness={0.45} metalness={0.18} />
      </mesh>
      <mesh position={[0, 0.23, 0]} castShadow>
        <boxGeometry args={[1.12, 0.16, 0.78]} />
        <meshStandardMaterial color={color} roughness={0.4} metalness={0.12} />
      </mesh>
      <mesh position={[0, 0.34, 0]}>
        <boxGeometry args={[0.26, 0.05, 0.26]} />
        <meshStandardMaterial color="#f0f3db" emissive={color} emissiveIntensity={0.24} />
      </mesh>
      <Html position={[0, 0.82, 0]} center distanceFactor={8}>
        <div className="machine-unit-label">
          <strong>{unit?.name ?? `Core Unit ${index + 1}`}</strong>
          <span>{unit?.device_id ?? UNIT_IDS[index]}</span>
        </div>
      </Html>
    </group>
  )
}

function Scene({ devices }: MachineOverviewProps) {
  const unitById = new Map(devices.map((unit) => [unit.device_id, unit]))
  return (
    <>
      <ambientLight intensity={1.7} />
      <directionalLight position={[4, 8, 5]} intensity={2.2} castShadow />
      <directionalLight position={[-5, 4, -4]} intensity={0.8} color="#91ad83" />
      <gridHelper args={[12, 16, '#829385', '#c4cec4']} position={[0, -0.72, 0]} />
      {UNIT_IDS.map((deviceId, index) => (
        <CoreUnit key={deviceId} unit={unitById.get(deviceId)} index={index} />
      ))}
      <OrbitControls
        makeDefault
        enablePan={false}
        minDistance={7}
        maxDistance={15}
        minPolarAngle={0.55}
        maxPolarAngle={1.45}
        target={[0, 0, 0]}
      />
    </>
  )
}

export default function MachineOverview({ devices }: MachineOverviewProps) {
  const [webglAvailable, setWebglAvailable] = useState(true)

  useEffect(() => {
    try {
      const canvas = document.createElement('canvas')
      setWebglAvailable(Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl')))
    } catch {
      setWebglAvailable(false)
    }
  }, [])

  return (
    <section className="machine-overview" aria-labelledby="machine-overview-title">
      <div className="machine-overview-heading">
        <div>
          <p className="section-index">ARSITEKTUR UNIT</p>
          <h2 id="machine-overview-title">Satu mesin, enam Core Unit</h2>
          <p className="machine-overview-note">Skema visual saja. Posisi fisik dan koneksi antarunit belum dipetakan.</p>
        </div>
        <span className="schematic-tag">SKEMATIS</span>
      </div>
      <div className="machine-overview-body">
        <div className="machine-scene" role="img" aria-label="Visual skematis enam Core Unit ArtecRobo 2.0">
          {webglAvailable ? (
            <Canvas camera={{ position: [8, 7, 9], fov: 36 }} dpr={[1, 1.5]} shadows>
              <color attach="background" args={['#e9eee7']} />
              <Scene devices={devices} />
            </Canvas>
          ) : (
            <div className="machine-fallback">
              {UNIT_IDS.map((deviceId, index) => (
                <div className="machine-fallback-unit" key={deviceId}>
                  <span style={{ backgroundColor: statusColor(devices.find((unit) => unit.device_id === deviceId)) }} />
                  <strong>Core Unit {index + 1}</strong>
                  <small>{deviceId}</small>
                </div>
              ))}
            </div>
          )}
        </div>
        <aside className="machine-inventory" aria-label="Perkiraan inventaris komponen">
          <div className="inventory-heading">
            <span>INVENTARIS AGREGAT</span>
            <small>PERKIRAAN</small>
          </div>
          <div className="inventory-row"><span>Motor DC</span><strong>~4</strong></div>
          <div className="inventory-row"><span>Servo</span><strong>~6</strong></div>
          <div className="inventory-row"><span>Sensor cahaya</span><strong>2</strong></div>
          <div className="inventory-row"><span>Sensor suara</span><strong>4</strong></div>
          <div className="inventory-row"><span>IR photoreflector</span><strong>?</strong></div>
          <p>Belum dibagi per unit. Sensor dan aktuator yang belum dikonfirmasi tidak ditampilkan sebagai posisi fisik.</p>
          <div className="machine-legend">
            <span><i className="legend-online" /> Online</span>
            <span><i className="legend-stale" /> Terlambat</span>
            <span><i className="legend-offline" /> Belum aktif</span>
          </div>
        </aside>
      </div>
    </section>
  )
}