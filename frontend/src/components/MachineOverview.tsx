import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import { useState } from 'react'

type Unit = {
  device_id: string
  name: string
  status: 'belum_terhubung' | 'hidup' | 'mati'
  connection_status: 'never_seen' | 'online' | 'stale'
}

type MachineOverviewProps = {
  devices: Unit[]
  theme: 'light' | 'dark'
}

const UNIT_IDS = Array.from({ length: 6 }, (_, index) => `alat-${index + 1}`)
const BLOCK_COLORS = ['#7bd6d0', '#f4f0e2', '#f66c32', '#e83d4b', '#17538b']

function statusColor(unit?: Unit) {
  if (unit?.connection_status === 'online' && unit.status === 'hidup') return '#b9d65b'
  if (unit?.connection_status === 'stale') return '#d79b42'
  return '#8d9990'
}

function Beam({
  position,
  size,
  color,
}: {
  position: [number, number, number]
  size: [number, number, number]
  color: string
}) {
  return (
    <mesh position={position} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshStandardMaterial color={color} roughness={0.68} />
    </mesh>
  )
}

function ModularPost({ x, z, height }: { x: number; z: number; height: number }) {
  const segmentCount = Math.ceil(height / 0.34)
  const segmentHeight = height / segmentCount
  return (
    <group position={[x, 0, z]}>
      {Array.from({ length: segmentCount }, (_, index) => (
        <Beam
          key={index}
          position={[0, segmentHeight * (index + 0.5), 0]}
          size={[0.24, segmentHeight * 0.88, 0.24]}
          color={BLOCK_COLORS[(index + Math.round((x + z) * 2)) % BLOCK_COLORS.length]}
        />
      ))}
      <mesh position={[0, height + 0.035, 0]} castShadow>
        <cylinderGeometry args={[0.09, 0.09, 0.07, 8]} />
        <meshStandardMaterial color="#f4f0e2" roughness={0.62} />
      </mesh>
    </group>
  )
}

function StuddedBeam({
  position,
  size,
  color,
}: {
  position: [number, number, number]
  size: [number, number, number]
  color: string
}) {
  const runsAlongX = size[0] >= size[2]
  const runLength = runsAlongX ? size[0] : size[2]
  const studCount = Math.max(2, Math.floor(runLength / 0.3))
  return (
    <group position={position}>
      <Beam position={[0, 0, 0]} size={size} color={color} />
      {Array.from({ length: studCount }, (_, index) => {
        const offset = -runLength / 2 + ((index + 0.5) * runLength) / studCount
        return (
          <mesh
            key={index}
            position={[
              runsAlongX ? offset : 0,
              size[1] / 2 + 0.035,
              runsAlongX ? 0 : offset,
            ]}
            castShadow
          >
            <cylinderGeometry args={[0.055, 0.055, 0.07, 8]} />
            <meshStandardMaterial color={color} roughness={0.62} />
          </mesh>
        )
      })}
    </group>
  )
}

function Gear({ position, radius = 0.32 }: { position: [number, number, number]; radius?: number }) {
  const toothCount = 10
  return (
    <group position={position} rotation={[0, 0, Math.PI / 2]}>
      <mesh castShadow>
        <cylinderGeometry args={[radius, radius, 0.14, 16]} />
        <meshStandardMaterial color="#ed3945" roughness={0.58} />
      </mesh>
      {Array.from({ length: toothCount }, (_, index) => {
        const angle = (index / toothCount) * Math.PI * 2
        return (
          <mesh
            key={index}
            position={[Math.cos(angle) * radius, 0, Math.sin(angle) * radius]}
            rotation={[0, -angle, 0]}
            castShadow
          >
            <boxGeometry args={[0.16, 0.17, 0.13]} />
            <meshStandardMaterial color="#ed3945" roughness={0.58} />
          </mesh>
        )
      })}
      <mesh>
        <cylinderGeometry args={[0.12, 0.12, 0.17, 12]} />
        <meshStandardMaterial color="#f4f0e2" roughness={0.55} />
      </mesh>
    </group>
  )
}

function ServoMotor({
  position,
  rotationY = 0,
}: {
  position: [number, number, number]
  rotationY?: number
}) {
  return (
    <group position={position} rotation={[0, rotationY, 0]} scale={1.22}>
      <Beam position={[0, 0, 0]} size={[0.64, 0.46, 0.56]} color="#28383c" />
      <Beam position={[0, 0, 0.29]} size={[0.46, 0.32, 0.035]} color="#f4f0e2" />
      <Beam position={[0, 0.02, 0.314]} size={[0.17, 0.17, 0.025]} color="#17538b" />
      <mesh position={[0, 0.23, 0]} castShadow>
        <cylinderGeometry args={[0.19, 0.19, 0.12, 12]} />
        <meshStandardMaterial color="#ed3945" roughness={0.5} />
      </mesh>
      <mesh position={[0, 0.3, 0]} castShadow>
        <cylinderGeometry args={[0.08, 0.08, 0.14, 10]} />
        <meshStandardMaterial color="#f4f0e2" metalness={0.28} roughness={0.42} />
      </mesh>
      <Beam position={[0, 0.36, 0]} size={[0.52, 0.08, 0.11]} color="#ed3945" />
      <Beam position={[-0.43, 0, 0]} size={[0.18, 0.54, 0.62]} color="#7bd6d0" />
      <Beam position={[0.43, 0, 0]} size={[0.18, 0.54, 0.62]} color="#7bd6d0" />
    </group>
  )
}

function DCMotor({
  position,
  rotationY = 0,
}: {
  position: [number, number, number]
  rotationY?: number
}) {
  return (
    <group position={position} rotation={[0, rotationY, 0]} scale={1.12}>
      <Beam position={[-0.38, 0, 0]} size={[0.56, 0.5, 0.58]} color="#f4f0e2" />
      <Beam position={[-0.38, 0, 0.31]} size={[0.36, 0.34, 0.045]} color="#f66c32" />
      <mesh position={[0.03, 0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow receiveShadow>
        <cylinderGeometry args={[0.29, 0.29, 0.86, 16]} />
        <meshStandardMaterial color="#58666a" metalness={0.22} roughness={0.5} />
      </mesh>
      {[-0.19, -0.07, 0.05, 0.17].map((x) => (
        <mesh key={x} position={[x, 0, 0]} rotation={[0, Math.PI / 2, 0]}>
          <torusGeometry args={[0.285, 0.04, 6, 12]} />
          <meshStandardMaterial color="#849092" metalness={0.26} roughness={0.45} />
        </mesh>
      ))}
      <mesh position={[0.44, 0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow>
        <cylinderGeometry args={[0.1, 0.1, 0.3, 12]} />
        <meshStandardMaterial color="#c6d0cb" metalness={0.42} roughness={0.32} />
      </mesh>
      <mesh position={[0.61, 0, 0]} rotation={[0, 0, Math.PI / 2]} castShadow>
        <cylinderGeometry args={[0.22, 0.22, 0.14, 12]} />
        <meshStandardMaterial color="#ed3945" roughness={0.52} />
      </mesh>
      <Beam position={[-0.4, -0.34, 0]} size={[0.72, 0.12, 0.68]} color="#17538b" />
    </group>
  )
}

function SideLift() {
  const liftX = 2.14
  const liftZ = 0.58
  const railHeight = 3.45
  return (
    <group>
      <ModularPost x={liftX} z={liftZ} height={railHeight} />
      <ModularPost x={liftX} z={-liftZ} height={railHeight} />
      {[0.3, 0.75, 2.85, 3.4].map((height, index) => (
        <StuddedBeam
          key={height}
          position={[liftX, height, 0]}
          size={[0.3, 0.16, 1.36]}
          color={BLOCK_COLORS[index % BLOCK_COLORS.length]}
        />
      ))}
      <Beam position={[1.8, 1.15, 0]} size={[1.05, 0.14, 0.16]} color="#f4f0e2" />
      <Beam position={[1.8, 2.55, 0]} size={[1.05, 0.14, 0.16]} color="#f66c32" />
      <StuddedBeam position={[liftX, 1.62, 0]} size={[0.92, 0.15, 1.32]} color="#7bd6d0" />
      <Beam position={[1.88, 1.79, 0]} size={[0.82, 0.09, 0.9]} color="#f4f0e2" />
      <Gear position={[liftX + 0.41, 0.75, 0.92]} radius={0.29} />
      <Gear position={[liftX + 0.2, 3.0, 0.76]} radius={0.29} />
      <DCMotor position={[liftX - 0.2, 0.75, 0.92]} />
      <Beam position={[liftX + 0.28, 3.08, 0]} size={[0.74, 0.46, 0.85]} color="#f4f0e2" />
      <Beam position={[liftX + 0.68, 3.1, 0]} size={[0.12, 0.58, 0.72]} color="#f66c32" />
      <Beam position={[liftX + 0.33, 2.88, 0.45]} size={[0.52, 0.09, 0.08]} color="#17538b" />
      <ServoMotor position={[liftX + 0.36, 2.5, 0.83]} rotationY={Math.PI / 2} />
    </group>
  )
}

function MainMachine({ devices }: { devices: Unit[] }) {
  const halfWidth = 1.52
  const halfDepth = 0.9
  const frameHeight = 3.35
  const unitById = new Map(devices.map((unit) => [unit.device_id, unit]))

  return (
    <>
      <ambientLight intensity={1.35} />
      <directionalLight position={[4, 8, 5]} intensity={2.3} castShadow />
      <directionalLight position={[-5, 4, -4]} intensity={1.1} color="#c6e7dc" />
      <gridHelper args={[12, 20, '#788a82', '#bdc9c1']} position={[0, -0.04, 0]} />

      {[-halfWidth, halfWidth].flatMap((x) => [-halfDepth, halfDepth].map((z) => (
        <ModularPost key={`${x}-${z}`} x={x} z={z} height={frameHeight} />
      )))}

      {[0.14, 3.35].flatMap((y) => [
        <StuddedBeam key={`x-${y}`} position={[0, y, -halfDepth]} size={[3.18, 0.17, 0.18]} color="#7bd6d0" />,
        <StuddedBeam key={`z-${y}`} position={[0, y, halfDepth]} size={[3.18, 0.17, 0.18]} color="#f66c32" />,
        <Beam key={`side-a-${y}`} position={[-halfWidth, y, 0]} size={[0.18, 0.17, 1.8]} color="#f4f0e2" />,
        <Beam key={`side-b-${y}`} position={[halfWidth, y, 0]} size={[0.18, 0.17, 1.8]} color="#e83d4b" />,
      ])}

      {[1.02, 2.55].flatMap((y, index) => [
        <StuddedBeam key={`cross-x-${y}`} position={[0, y, -halfDepth]} size={[3.1, 0.14, 0.17]} color={BLOCK_COLORS[index + 1]} />,
        <StuddedBeam key={`cross-z-${y}`} position={[0, y, halfDepth]} size={[3.1, 0.14, 0.17]} color={BLOCK_COLORS[index + 2]} />,
      ])}

      <Beam position={[0, 1.65, 0]} size={[2.75, 0.12, 1.42]} color="#23343b" />
      <Beam position={[0, 1.74, 0]} size={[2.58, 0.1, 1.24]} color="#f4f0e2" />
      {Array.from({ length: 9 }, (_, index) => (
        <mesh key={index} position={[-1.12 + index * 0.28, 1.84, 0]} rotation={[Math.PI / 2, 0, 0]} castShadow>
          <cylinderGeometry args={[0.075, 0.075, 1.12, 10]} />
          <meshStandardMaterial color={index % 2 ? '#68747a' : '#9ba6a2'} metalness={0.18} roughness={0.48} />
        </mesh>
      ))}

      <DCMotor position={[0.72, 1.26, 1.03]} />
      <ServoMotor position={[-0.68, 2.08, 1.03]} />
      <ServoMotor position={[0.43, 2.08, 1.03]} />

      <Beam position={[-0.55, 2.58, 0]} size={[0.12, 0.9, 0.12]} color="#f66c32" />
      <Beam position={[0.55, 2.58, 0]} size={[0.12, 0.9, 0.12]} color="#7bd6d0" />
      <StuddedBeam position={[0, 3.0, 0]} size={[1.15, 0.14, 0.18]} color="#f4f0e2" />

      {UNIT_IDS.map((deviceId, index) => (
        <mesh key={deviceId} position={[-1.12 + index * 0.45, 3.48, 1.03]} castShadow>
          <boxGeometry args={[0.16, 0.12, 0.07]} />
          <meshStandardMaterial color={statusColor(unitById.get(deviceId))} emissive={statusColor(unitById.get(deviceId))} emissiveIntensity={0.34} />
        </mesh>
      ))}

      <SideLift />
      <OrbitControls
        makeDefault
        enablePan={false}
        enableDamping
        minDistance={5.5}
        maxDistance={13}
        minPolarAngle={0.18}
        maxPolarAngle={2.85}
        target={[0.35, 1.72, 0]}
      />
    </>
  )
}

export default function MachineOverview({ devices, theme }: MachineOverviewProps) {
  const [webglAvailable] = useState(() => {
    try {
      const canvas = document.createElement('canvas')
      return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
    } catch {
      return false
    }
  })

  return (
    <section className="machine-overview" aria-labelledby="machine-overview-title">
      <div className="machine-overview-heading">
        <div>
          <p className="section-index">MODEL 3D KONSEPTUAL</p>
          <h2 id="machine-overview-title">Mesin modular ArtecRobo 2.0</h2>
          <p className="machine-overview-note">Rangka dan lift samping mengikuti foto referensi; ukuran serta sambungan belum terukur.</p>
        </div>
        <span className="schematic-tag">BISA DIPUTAR</span>
      </div>
      <div className="machine-overview-body">
        <div className="machine-scene" role="img" aria-label="Model 3D konseptual ArtecRobo 2.0 dengan lift samping terpasang">
          {webglAvailable ? (
            <Canvas camera={{ position: [8.6, 6.7, 9.2], fov: 30 }} dpr={[1, 1.5]} gl={{ preserveDrawingBuffer: true }}>
              <color attach="background" args={[theme === 'dark' ? '#121a16' : '#e9eee7']} />
              <MainMachine devices={devices} />
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
            <span>KOMPONEN</span>
            <small>PERKIRAAN</small>
          </div>
          <div className="inventory-row"><span>Motor DC</span><strong>~4</strong></div>
          <div className="inventory-row"><span>Servo</span><strong>~6</strong></div>
          <div className="inventory-row"><span>Sensor cahaya</span><strong>2</strong></div>
          <div className="inventory-row"><span>Sensor suara</span><strong>4</strong></div>
          <div className="inventory-row"><span>IR photoreflector</span><strong>?</strong></div>
          <p>Jumlah dari inventaris awal. Posisi detail sensor dan aktuator masih perlu diverifikasi langsung.</p>
          <div className="machine-unit-list" aria-label="Status enam Core Unit">
            {UNIT_IDS.map((deviceId, index) => {
              const unit = devices.find((device) => device.device_id === deviceId)
              const status = unit?.connection_status === 'online' && unit.status === 'hidup'
                ? 'Online'
                : unit?.connection_status === 'stale'
                  ? 'Terlambat'
                  : 'Belum aktif'
              return (
                <div className="machine-unit-status" key={deviceId}>
                  <i style={{ backgroundColor: statusColor(unit) }} />
                  <span>Core Unit {index + 1}</span>
                  <small>{deviceId}</small>
                  <strong>{status}</strong>
                </div>
              )
            })}
          </div>
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