'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { QueryState } from '@/components/subterra/query-state'
import { StateBox } from '@/components/subterra/state-box'
import { useDatasets, useScene } from '@/hooks/use-subterra'
import type { SceneCandidate, ScenePayload } from '@/types/subterra'

/**
 * The reconstructed scene: a real 3D spatial view of what Subterra currently
 * knows about one dataset's declared surface and its spatially-resolvable
 * anomaly candidates, elevation-anchored when (and only when)
 * `GET /api/scene/{id}` says `resolved: true`.
 *
 * WHAT THIS IS NOT. It does not compute a position, an elevation, or a
 * candidate — `api/scene.py` already decided all of that, using only
 * declared and derived values `fusion.vertical_reference.assess` has
 * already cleared. This component only draws what it is handed, and draws
 * exactly the honesty state the payload carries: unresolved datasets get
 * the same "here is why, here is what's missing" treatment every other
 * unresolved view in this workspace already uses, never an empty or
 * misleading 3D canvas.
 *
 * WHY POINTS, NOT A TRIANGULATED SURFACE. `surface.points` is a downsampled,
 * possibly irregular sample of positioned records -- triangulating a
 * continuous ground mesh through it would interpolate terrain nobody
 * measured between those points. Rendering it as a point cloud draws
 * exactly the evidence that exists and nothing else.
 *
 * WHY A SEPARATE "not shown" LIST. A candidate missing a position or an
 * elevation is never placed at a fallback coordinate -- the same rule
 * `components/subterra/not-on-map.tsx` already enforces for objects and
 * labels. It is listed instead, with the backend's own reason.
 */
export function ReconstructedScene({ datasetId }: { datasetId: string }) {
  // GPR and its surface (DEM/LiDAR) are almost always two separate
  // datasets in this platform -- not two frames in one -- so the surface
  // to use is a real choice, not a fixed default. Left unset, the scene
  // looks for a surface frame within `datasetId` itself, same as
  // `/api/views/resolve` already does.
  const [surfaceDatasetId, setSurfaceDatasetId] = useState<string | undefined>(undefined)
  const { data: allDatasets } = useDatasets()
  const { data, error, isLoading } = useScene(datasetId, surfaceDatasetId)

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-2 border-b border-border px-3.5 py-1.5">
        <label className="text-[11px] text-muted-foreground" htmlFor="scene-surface-dataset">
          Surface dataset
        </label>
        <select
          id="scene-surface-dataset"
          value={surfaceDatasetId ?? ''}
          onChange={(e) => setSurfaceDatasetId(e.target.value || undefined)}
          className="rounded-md border border-border bg-background px-1.5 py-0.5 text-[11px] text-foreground"
        >
          <option value="">(this dataset)</option>
          {(allDatasets ?? [])
            .filter((d) => d.id !== datasetId)
            .map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
        </select>
      </div>
      <QueryState
        isLoading={isLoading}
        error={error}
        absenceTitle="Scene unavailable"
        errorTitle="Could not load the reconstructed scene"
        skeletonRows={2}
      />
      {data && (data.resolved ? <ResolvedScene payload={data} /> : <UnresolvedScene payload={data} />)}
    </div>
  )
}

function UnresolvedScene({ payload }: { payload: ScenePayload }) {
  return (
    <div className="flex h-full flex-col gap-3 overflow-y-auto p-3.5">
      <StateBox
        kind="unavailable"
        title="3D scene unavailable"
        detail={payload.resolution_reason ?? 'This dataset has not cleared the vertical-reference gate yet.'}
      />
      {payload.missing.length > 0 && (
        <div>
          <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            What is missing
          </h3>
          <ul className="mt-1.5 space-y-1">
            {payload.missing.map((m, i) => (
              <li key={i} className="text-[11px] leading-relaxed text-muted-foreground">
                · {m}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
          Current data can still be inspected
        </h3>
        <ul className="mt-1.5 space-y-1">
          {Object.entries(payload.diagnostic_views).map(([label, href]) => (
            <li key={label}>
              <a href={href} className="text-[11px] text-primary underline-offset-4 hover:underline">
                {label}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </div>
  )
}

/** Metres per degree of longitude at a given latitude — WGS84 sphere approximation, fine at scene scale. */
function metresPerDegreeLon(latDeg: number): number {
  return 111_320 * Math.cos((latDeg * Math.PI) / 180)
}
const METRES_PER_DEGREE_LAT = 110_540

function ResolvedScene({ payload }: { payload: ScenePayload }) {
  const mountRef = useRef<HTMLDivElement>(null)
  const [selected, setSelected] = useState<SceneCandidate | null>(null)

  // A local metres-based frame centred on the surface's own mean position,
  // so the scene draws at a human scale instead of at raw lat/lon degrees.
  const origin = useMemo(() => {
    const pts = payload.surface?.points ?? []
    if (pts.length > 0) {
      const lat = pts.reduce((s, p) => s + p.lat, 0) / pts.length
      const lon = pts.reduce((s, p) => s + p.lon, 0) / pts.length
      return { lat, lon }
    }
    // No surface to centre on -- fall back to the mean of whatever
    // candidates do carry a position, so the scene still centres on real
    // data rather than an arbitrary point.
    const positioned = payload.candidates.filter((c) => c.position.available)
    if (positioned.length > 0) {
      const lat = positioned.reduce((s, c) => s + (c.position.lat as number), 0) / positioned.length
      const lon = positioned.reduce((s, c) => s + (c.position.lon as number), 0) / positioned.length
      return { lat, lon }
    }
    // Nothing at all to place -- there is no real point to centre on.
    return null
  }, [payload.surface, payload.candidates])

  const toLocal = useMemo(() => {
    if (!origin) return null
    const mLon = metresPerDegreeLon(origin.lat) || 1
    return (lat: number, lon: number) => ({
      x: (lon - origin.lon) * mLon,
      z: (lat - origin.lat) * METRES_PER_DEGREE_LAT,
    })
  }, [origin])

  const placeable = payload.candidates.filter((c) => c.position.available && c.elevation.available)
  const notShown = payload.candidates.filter((c) => !c.position.available || !c.elevation.available)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0b0f14)

    const camera = new THREE.PerspectiveCamera(
      50,
      mount.clientWidth / mount.clientHeight,
      0.1,
      100_000,
    )
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(mount.clientWidth, mount.clientHeight)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    mount.appendChild(renderer.domElement)

    scene.add(new THREE.AmbientLight(0xffffff, 0.9))
    const sun = new THREE.DirectionalLight(0xffffff, 0.6)
    sun.position.set(50, 100, 50)
    scene.add(sun)

    // The surface: a point cloud, coloured by elevation, at its own
    // declared/derived height -- never a fabricated continuous mesh (see
    // the module docstring).
    const surfacePoints = payload.surface?.points ?? []
    let surfaceElevMean = 0
    if (surfacePoints.length > 0 && toLocal) {
      const elevs = surfacePoints.map((p) => p.elevation_m)
      surfaceElevMean = elevs.reduce((a, b) => a + b, 0) / elevs.length
      const geo = new THREE.BufferGeometry()
      const positions = new Float32Array(surfacePoints.length * 3)
      surfacePoints.forEach((p, i) => {
        const { x, z } = toLocal(p.lat, p.lon)
        positions[i * 3] = x
        positions[i * 3 + 1] = p.elevation_m - surfaceElevMean
        positions[i * 3 + 2] = z
      })
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      const mat = new THREE.PointsMaterial({ color: 0x8fbf7f, size: 0.6, sizeAttenuation: true })
      scene.add(new THREE.Points(geo, mat))

      // A thin reference grid at the surface's mean elevation, purely for
      // visual grounding -- it carries no data of its own.
      const grid = new THREE.GridHelper(200, 20, 0x2c3742, 0x1a212a)
      scene.add(grid)
    }

    // Candidates: small spheres, coloured by anomaly class, positioned at
    // their own declared/derived elevation relative to the surface mean.
    const candidateMeshes: { mesh: THREE.Mesh; candidate: SceneCandidate }[] = []
    for (const c of placeable) {
      if (!toLocal) break
      const { x, z } = toLocal(c.position.lat as number, c.position.lon as number)
      const y = (c.elevation.elevation_m as number) - surfaceElevMean
      const geo = new THREE.SphereGeometry(0.8, 16, 16)
      const mat = new THREE.MeshStandardMaterial({
        color: c.anomaly_class === 'unclassified' ? 0x9aa7b5 : 0xe0a030,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(x, y, z)
      mesh.userData.candidateId = c.id
      scene.add(mesh)
      candidateMeshes.push({ mesh, candidate: c })
    }

    camera.position.set(30, 30, 30)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.set(0, 0, 0)
    controls.enableDamping = true

    const raycaster = new THREE.Raycaster()
    const onClick = (ev: MouseEvent) => {
      const rect = renderer.domElement.getBoundingClientRect()
      const pointer = new THREE.Vector2(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1,
      )
      raycaster.setFromCamera(pointer, camera)
      const hit = raycaster.intersectObjects(candidateMeshes.map((c) => c.mesh))[0]
      if (hit) {
        const found = candidateMeshes.find((c) => c.mesh === hit.object)
        if (found) setSelected(found.candidate)
      }
    }
    renderer.domElement.addEventListener('click', onClick)

    let frame = 0
    const animate = () => {
      frame = requestAnimationFrame(animate)
      controls.update()
      renderer.render(scene, camera)
    }
    animate()

    const onResize = () => {
      if (!mount) return
      camera.aspect = mount.clientWidth / mount.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(mount.clientWidth, mount.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('click', onClick)
      controls.dispose()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
    }
  }, [payload, toLocal, placeable])

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-muted/30 px-3.5 py-1.5">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {payload.validation_status}
        </p>
      </div>
      <div className="relative min-h-0 flex-1">
        <div ref={mountRef} className="h-full w-full" />
        {isSurfaceEmpty(payload) && (
          <div className="pointer-events-none absolute inset-x-0 top-2 flex justify-center">
            <span className="rounded-md bg-background/80 px-2 py-1 text-[11px] text-muted-foreground">
              Surface unavailable — no positioned surface records for this dataset
            </span>
          </div>
        )}
      </div>
      {selected && <CandidateDetail candidate={selected} onClose={() => setSelected(null)} />}
      {placeable.length > 0 && (
        <div className="max-h-28 overflow-y-auto border-t border-border px-3.5 py-2">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            Candidates in this scene — {placeable.length}
          </h3>
          <ul className="mt-1 flex flex-wrap gap-1.5">
            {placeable.map((c) => (
              <li key={c.id}>
                <button
                  type="button"
                  onClick={() => setSelected(c)}
                  aria-pressed={selected?.id === c.id}
                  className={`rounded-md border px-1.5 py-0.5 text-[11px] transition-colors ${
                    selected?.id === c.id
                      ? 'border-primary/50 bg-primary/10 text-foreground'
                      : 'border-border text-muted-foreground hover:border-primary/30 hover:text-foreground'
                  }`}
                >
                  {c.anomaly_class} · {c.score.toFixed(1)}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
      {notShown.length > 0 && (
        <div className="max-h-32 overflow-y-auto border-t border-border px-3.5 py-2">
          <h3 className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
            Not shown in this scene — {notShown.length}
          </h3>
          <ul className="mt-1 space-y-1">
            {notShown.map((c) => (
              <li key={c.id} className="text-[11px] leading-relaxed text-muted-foreground">
                <code className="text-foreground">{c.id.slice(0, 12)}…</code>{' '}
                {!c.position.available ? c.position.reason : c.elevation.reason}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

function isSurfaceEmpty(payload: ScenePayload): boolean {
  return (payload.surface?.points.length ?? 0) === 0
}

function CandidateDetail({
  candidate,
  onClose,
}: {
  candidate: SceneCandidate
  onClose: () => void
}) {
  return (
    <div className="border-t border-border bg-muted/20 p-3">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium text-foreground">Anomaly candidate</p>
          <code className="text-[11px] text-muted-foreground">{candidate.id}</code>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="text-[11px] text-muted-foreground hover:text-foreground"
        >
          Close
        </button>
      </div>
      <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
        <Field label="Shape class">{candidate.anomaly_class}</Field>
        <Field label="Score">{candidate.score.toFixed(2)}</Field>
        <Field label="Elevation">
          {candidate.elevation.available
            ? `${(candidate.elevation.elevation_m as number).toFixed(2)} m`
            : 'unavailable'}
        </Field>
        <Field label="Depth">
          {candidate.elevation.depth_m != null ? `${candidate.elevation.depth_m.toFixed(2)} m` : '—'}
          {' · '}
          {candidate.elevation.depth_certainty}
        </Field>
        <Field label="Position basis">{candidate.position.basis}</Field>
        <Field label="Source file">{candidate.source_file}</Field>
      </dl>
      <p className="mt-2 text-[11px] leading-relaxed text-muted-foreground">
        {candidate.note}
      </p>
      <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
        <strong className="text-foreground">Elevation provenance:</strong> {candidate.elevation.provenance}
      </p>
      <p className="text-[11px] leading-relaxed text-muted-foreground">
        {candidate.score_meaning}
      </p>
      <a
        href={candidate.evidence_reference}
        className="mt-2 inline-block text-[11px] text-primary underline-offset-4 hover:underline"
      >
        Inspect this evidence in the radargram
      </a>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd className="text-foreground">{children}</dd>
    </div>
  )
}
