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
 *
 * CAMERA FRAMING. A browser audit found the original camera fixed at
 * `(30, 30, 30)` looking at the origin: fine for a small, roughly-centred
 * survey, but a real dataset can combine a small GPR footprint with a
 * DEM tile whose own points span hundreds of metres. At that scale the
 * DEM's points sat roughly 90 degrees outside the camera's view frustum --
 * the scene rendered, but nothing in it was ever visible. The camera is
 * now framed from the actual bounding sphere of whatever is being drawn
 * (see `computeLocalBounds`/`fitDistance` below), and "Fit to scene" /
 * "Reset view" both re-run that same computation, so a user who scrolls
 * into an empty void always has a one-click way back.
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

type LocalPoint = { x: number; y: number; z: number }

/** Clamp a value into [min, max]. Used only for rendering parameters (point/marker size, grid density) — never for a coordinate. */
export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * The bounding centre and radius of a set of already-local-metre points.
 * Pure and framework-free so the camera-framing math is testable without a
 * WebGL context: this is the "actual scene bounds" the audit asked for,
 * computed from what is really being drawn rather than assumed.
 *
 * Returns `null` for an empty input rather than a fabricated origin --
 * there is no real point to centre a camera on, and the caller (gated on
 * `hasAnyGeometry`) never has an empty set to pass in practice.
 */
export function computeLocalBounds(points: LocalPoint[]): { center: LocalPoint; radius: number } | null {
  if (points.length === 0) {
    return null
  }
  let minX = Infinity
  let minY = Infinity
  let minZ = Infinity
  let maxX = -Infinity
  let maxY = -Infinity
  let maxZ = -Infinity
  for (const p of points) {
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.z < minZ) minZ = p.z
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
    if (p.z > maxZ) maxZ = p.z
  }
  const center = { x: (minX + maxX) / 2, y: (minY + maxY) / 2, z: (minZ + maxZ) / 2 }
  let radius = 0
  for (const p of points) {
    const dx = p.x - center.x
    const dy = p.y - center.y
    const dz = p.z - center.z
    const d = Math.sqrt(dx * dx + dy * dy + dz * dz)
    if (d > radius) radius = d
  }
  // Floored, not zeroed: a single point (or several coincident ones) is a
  // real, valid scene and still needs a positive camera distance to frame.
  return { center, radius: Math.max(radius, 0.5) }
}

/**
 * Camera distance that fits a sphere of `radius` inside both the vertical
 * and horizontal field of view -- whichever is tighter, since `aspect` can
 * be either side of 1. The caller applies its own safety margin on top.
 */
export function fitDistance(radius: number, verticalFovRad: number, aspect: number): number {
  const vFov = verticalFovRad
  const hFov = 2 * Math.atan(Math.tan(vFov / 2) * aspect)
  const distV = radius / Math.sin(vFov / 2)
  const distH = radius / Math.sin(hFov / 2)
  return Math.max(distV, distH)
}

// A fixed, chosen viewing angle (elevated three-quarter view) -- not a
// scale-dependent position. Only the *distance* along this direction is
// derived from the data; the direction itself is a deliberate framing
// choice, same as any other renderer's default "isometric-ish" camera.
const FIT_DIRECTION = new THREE.Vector3(1, 0.8, 1).normalize()
const FIT_MARGIN = 1.35

/**
 * Reposition `camera`/`controls` to frame `bounds` entirely, with near/far
 * clipping planes and orbit-distance limits scaled to the same bounds --
 * never fixed constants, so a tiny survey and a continental DEM tile both
 * get a camera that can actually see what was rendered. Used for the
 * initial framing and for both "Fit to scene" and "Reset view": bounds are
 * fixed for the lifetime of one resolved payload, so recomputing them and
 * restoring the initial framing are the same operation here.
 */
function applyFit(
  camera: THREE.PerspectiveCamera,
  controls: OrbitControls,
  bounds: { center: LocalPoint; radius: number },
) {
  const vFovRad = (camera.fov * Math.PI) / 180
  const distance = fitDistance(bounds.radius, vFovRad, camera.aspect || 1) * FIT_MARGIN
  const center = new THREE.Vector3(bounds.center.x, bounds.center.y, bounds.center.z)

  camera.position.copy(center).addScaledVector(FIT_DIRECTION, distance)
  camera.near = Math.max(bounds.radius / 1000, 0.001)
  camera.far = (distance + bounds.radius) * 20 + 10
  camera.updateProjectionMatrix()

  controls.target.copy(center)
  controls.minDistance = Math.max(bounds.radius * 0.02, 0.05)
  controls.maxDistance = distance * 15
  controls.update()
}

function ResolvedScene({ payload }: { payload: ScenePayload }) {
  const mountRef = useRef<HTMLDivElement>(null)
  const fitCameraRef = useRef<(() => void) | null>(null)
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

  const hasSurface = (payload.surface?.points.length ?? 0) > 0
  const hasCandidates = placeable.length > 0
  const hasAnyGeometry = hasSurface || hasCandidates

  useEffect(() => {
    const mount = mountRef.current
    if (!mount || !hasAnyGeometry) {
      fitCameraRef.current = null
      return
    }

    // Computed before any renderer/DOM setup below: if this were ever
    // empty (unreachable given the `hasAnyGeometry` guard above, which
    // guarantees at least one local point exists) there would be nothing
    // to build or append yet, so bailing out here is always safe.
    const surfacePoints = payload.surface?.points ?? []
    let surfaceElevMean = 0
    const localSurface: LocalPoint[] = []
    if (surfacePoints.length > 0 && toLocal) {
      const elevs = surfacePoints.map((p) => p.elevation_m)
      surfaceElevMean = elevs.reduce((a, b) => a + b, 0) / elevs.length
      for (const p of surfacePoints) {
        const { x, z } = toLocal(p.lat, p.lon)
        localSurface.push({ x, y: p.elevation_m - surfaceElevMean, z })
      }
    }

    const localCandidates: (LocalPoint & { candidate: SceneCandidate })[] = []
    if (toLocal) {
      for (const c of placeable) {
        const { x, z } = toLocal(c.position.lat as number, c.position.lon as number)
        const y = (c.elevation.elevation_m as number) - surfaceElevMean
        localCandidates.push({ x, y, z, candidate: c })
      }
    }

    const bounds = computeLocalBounds([
      ...localSurface,
      ...localCandidates.map(({ x, y, z }) => ({ x, y, z })),
    ])
    if (!bounds) {
      fitCameraRef.current = null
      return
    }

    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0b0f14)

    const aspect = mount.clientHeight ? mount.clientWidth / mount.clientHeight : 1
    const camera = new THREE.PerspectiveCamera(50, aspect, 0.1, 100_000)
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
    // the module docstring). Coordinates are `toLocal`'s real lat/lon/
    // elevation transform -- nothing here moves or rescales a coordinate,
    // only the *rendering* parameters below (point size, grid size) are
    // derived from the data's own extent.
    //
    // Surface points and candidate markers live in their own group so the
    // reference grid (sized FROM this group's bounds, below) is never
    // itself part of the bounds it is sized to enclose.
    const dataGroup = new THREE.Group()

    if (localSurface.length > 0) {
      // A fixed, un-attenuated pixel size -- not world units. A coarse DEM's
      // few points sit far enough from a properly-fitted camera that even a
      // several-metre point would shrink to sub-pixel with distance
      // attenuation (this is the second half of the original visibility
      // bug: fitting the camera made the points reachable, but their old
      // world-unit, distance-attenuated size still shrank them away).
      // Fewer points render larger -- a sparse DEM tile should read as
      // individually visible samples, not a faint haze.
      const pointPixelSize = clamp(24 / Math.sqrt(localSurface.length), 3, 10)
      const geo = new THREE.BufferGeometry()
      const positions = new Float32Array(localSurface.length * 3)
      localSurface.forEach((p, i) => {
        positions[i * 3] = p.x
        positions[i * 3 + 1] = p.y
        positions[i * 3 + 2] = p.z
      })
      geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      const mat = new THREE.PointsMaterial({
        color: 0x8fbf7f,
        size: pointPixelSize,
        sizeAttenuation: false,
      })
      dataGroup.add(new THREE.Points(geo, mat))

      // A thin reference grid at the surface's own extent, purely for
      // visual grounding -- it carries no data of its own. Sized from
      // `bounds.radius` rather than a fixed 200 units, so a coarse DEM
      // tile spanning hundreds of metres still gets a grid that reaches
      // its points, and a tight local survey does not drown in one.
      const gridSize = Math.max(bounds.radius * 2.5, 1)
      const divisions = clamp(Math.round(gridSize / 10), 8, 40)
      const grid = new THREE.GridHelper(gridSize, divisions, 0x2c3742, 0x1a212a)
      grid.position.set(bounds.center.x, bounds.center.y, bounds.center.z)
      scene.add(grid)
    }

    // Candidates: small spheres, coloured by anomaly class, positioned at
    // their own declared/derived elevation relative to the surface mean.
    // Marker radius scales with the scene's own extent so a candidate is
    // neither an invisible speck in a large DEM nor an oversized blob in a
    // tight survey.
    const candidateRadius = clamp(bounds.radius * 0.02, 0.15, 6)
    const candidateMeshes: { mesh: THREE.Mesh; candidate: SceneCandidate }[] = []
    for (const lc of localCandidates) {
      const geo = new THREE.SphereGeometry(candidateRadius, 16, 16)
      const mat = new THREE.MeshStandardMaterial({
        color: lc.candidate.anomaly_class === 'unclassified' ? 0x9aa7b5 : 0xe0a030,
      })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.position.set(lc.x, lc.y, lc.z)
      mesh.userData.candidateId = lc.candidate.id
      dataGroup.add(mesh)
      candidateMeshes.push({ mesh, candidate: lc.candidate })
    }

    scene.add(dataGroup)

    const controls = new OrbitControls(camera, renderer.domElement)
    controls.enableDamping = true

    const fit = () => applyFit(camera, controls, bounds)
    fit()
    fitCameraRef.current = fit

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
      camera.aspect = mount.clientHeight ? mount.clientWidth / mount.clientHeight : 1
      camera.updateProjectionMatrix()
      renderer.setSize(mount.clientWidth, mount.clientHeight)
    }
    window.addEventListener('resize', onResize)

    return () => {
      fitCameraRef.current = null
      cancelAnimationFrame(frame)
      window.removeEventListener('resize', onResize)
      renderer.domElement.removeEventListener('click', onClick)
      controls.dispose()
      renderer.dispose()
      mount.removeChild(renderer.domElement)
    }
  }, [payload, toLocal, placeable, hasAnyGeometry])

  return (
    <div className="flex h-full flex-col">
      <div className="border-b border-border bg-muted/30 px-3.5 py-1.5">
        <p className="text-[11px] leading-relaxed text-muted-foreground">
          {payload.validation_status}
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          In plain terms: everything placed here uses positions and elevations that were either
          declared by someone or worked out from what was declared. That makes them useful for
          looking around and for spotting where evidence sits relative to the surface — it does
          not mean an independent survey has confirmed these are the true absolute coordinates.
        </p>
      </div>
      {hasAnyGeometry ? (
        <div className="relative min-h-0 flex-1">
          <div ref={mountRef} className="h-full w-full" />
          <div className="pointer-events-none absolute inset-x-0 top-2 flex flex-col items-center gap-1 px-16">
            {!hasSurface && (
              <span className="rounded-md bg-background/80 px-2 py-1 text-center text-[11px] text-muted-foreground">
                Surface unavailable — no positioned surface records for this dataset
              </span>
            )}
            {hasSurface && !hasCandidates && (
              <span className="max-w-md rounded-md bg-background/80 px-2 py-1 text-center text-[11px] text-muted-foreground">
                No subsurface candidates to display yet. The spatial scene is resolved, but no
                candidates with sufficient position/elevation information are currently
                available.
              </span>
            )}
          </div>
          <div className="absolute right-2 top-2 flex gap-1.5">
            <button
              type="button"
              onClick={() => fitCameraRef.current?.()}
              className="rounded-md border border-border bg-background/80 px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            >
              Fit to scene
            </button>
            <button
              type="button"
              onClick={() => fitCameraRef.current?.()}
              className="rounded-md border border-border bg-background/80 px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
            >
              Reset view
            </button>
          </div>
        </div>
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto p-3.5">
          <StateBox
            kind="empty"
            title="Nothing to render yet"
            detail="The spatial scene is resolved, but there is no surface data and no candidates with sufficient position/elevation information currently available."
          />
        </div>
      )}
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
