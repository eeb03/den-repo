'use client'

import { useEffect, useRef, useState } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { type VolumeCursor, cursorFromCoord, decodeU8 } from '@/lib/volume'
import type { ResponseRegion } from '@/types/region'
import type { GroundTruthOverlay, VolumeProduct, VolumeRender3D } from '@/types/volume'

export interface Render3DSettings {
  threshold: number   // 0..1 of the display texture
  opacity: number     // 0..1
  clipMin: [number, number, number]   // fractions of x, y, z extent
  clipMax: [number, number, number]
  showSlices: boolean
  showSupport: boolean
}

interface Uniforms {
  uData: { value: THREE.Data3DTexture | null }
  uSupport: { value: THREE.Data3DTexture | null }
  uCam: { value: THREE.Vector3 }
  uThreshold: { value: number }
  uOpacity: { value: number }
  uClipMin: { value: THREE.Vector3 }
  uClipMax: { value: THREE.Vector3 }
  uShowSupport: { value: number }
  uSteps: { value: number }
}

const VERT = /* glsl */ `
out vec3 vPos;
void main() {
  vPos = position;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}`

// Front-to-back ray marching through the unit box [-0.5, 0.5]^3 in OBJECT space.
// Texture axes: s = volume x, t = volume y, r = depth / time (down).
const FRAG = /* glsl */ `
precision highp float;
precision highp sampler3D;
in vec3 vPos;
out vec4 outColor;
uniform sampler3D uData;
uniform sampler3D uSupport;
uniform vec3 uCam;
uniform float uThreshold;
uniform float uOpacity;
uniform vec3 uClipMin;
uniform vec3 uClipMax;
uniform int uShowSupport;
uniform float uSteps;
vec2 hitBox(vec3 o, vec3 d) {
  vec3 inv = 1.0 / d;
  vec3 t0 = (vec3(-0.5) - o) * inv;
  vec3 t1 = (vec3(0.5) - o) * inv;
  vec3 tmin = min(t0, t1), tmax = max(t0, t1);
  return vec2(max(max(tmin.x, tmin.y), tmin.z), min(min(tmax.x, tmax.y), tmax.z));
}
void main() {
  vec3 dir = normalize(vPos - uCam);
  vec2 hit = hitBox(uCam, dir);
  float t0 = max(hit.x, 0.0);
  if (hit.y <= t0) discard;
  float dt = 1.7320508 / uSteps;
  vec4 acc = vec4(0.0);
  for (float t = t0; t < hit.y; t += dt) {
    vec3 p = uCam + dir * t;
    vec3 tc = vec3(p.x + 0.5, p.z + 0.5, 0.5 - p.y);
    if (any(lessThan(tc, uClipMin)) || any(greaterThan(tc, uClipMax))) continue;
    float v = texture(uData, tc).r;
    float a = clamp((v - uThreshold) / max(1.0 - uThreshold, 1e-3), 0.0, 1.0);
    a = pow(a, 1.5) * uOpacity;
    if (a <= 0.0) continue;
    vec3 c = vec3(0.92);
    if (uShowSupport == 1) {
      float s = texture(uSupport, tc).r * 255.0;
      if (s > 0.5 && s < 1.5) c = vec3(1.0, 0.67, 0.0);
    }
    acc.rgb += (1.0 - acc.a) * a * c;
    acc.a += (1.0 - acc.a) * a;
    if (acc.a > 0.97) break;
  }
  if (acc.a < 0.01) discard;
  outColor = acc;
}`

/**
 * The SAME volume as the slice panes, ray-marched on the GPU from a bounded
 * DISPLAY-ONLY texture (block-max downsample; the original resolution is
 * shown under the pane). Draws the three cursor planes and, optionally, the
 * ground-truth wireframes as a separate magenta layer. Clicking a slice plane
 * moves the shared cursor.
 */
export function Volume3D({
  volume, render, cursor, onCursor, settings, groundTruth, showGroundTruth,
  regions = [], showRegions = false, selectedRegion = null, onSelectRegion,
}: {
  volume: VolumeProduct
  render: VolumeRender3D | undefined
  cursor: VolumeCursor
  onCursor: (c: VolumeCursor) => void
  settings: Render3DSettings
  groundTruth?: GroundTruthOverlay
  showGroundTruth: boolean
  /** Response regions: a separate layer of bounding boxes (green; selected amber). */
  regions?: ResponseRegion[]
  showRegions?: boolean
  selectedRegion?: string | null
  onSelectRegion?: (id: string | null) => void
}) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const state = useRef<{
    renderer: THREE.WebGLRenderer; scene: THREE.Scene; camera: THREE.PerspectiveCamera
    controls: OrbitControls; mesh: THREE.Mesh; material: THREE.ShaderMaterial
    uniforms: Uniforms
    slices: THREE.Group; gt: THREE.Group; regionBoxes: THREE.Group; marker: THREE.Mesh; dims: THREE.Vector3; raf: number
  } | null>(null)
  const [fps, setFps] = useState<number | null>(null)
  const [unsupported, setUnsupported] = useState<string | null>(() =>
    typeof document === 'undefined' || document.createElement('canvas').getContext('webgl2')
      ? null
      : 'WebGL2 is not available in this browser, so the 3D pane is off; the slice panes are unaffected.')
  const onCursorRef = useRef(onCursor)
  useEffect(() => { onCursorRef.current = onCursor }, [onCursor])
  const onSelectRef = useRef(onSelectRegion)
  useEffect(() => { onSelectRef.current = onSelectRegion }, [onSelectRegion])

  // physical extent; a time-domain z is scaled for display and says so
  const [nx, ny, nz] = volume.shape
  const Lx = nx * volume.x_axis.step, Ly = ny * volume.y_axis.step
  const zIsDepth = volume.z_axis.unit === 'm'
  const Lz = zIsDepth ? nz * volume.z_axis.step : 0.5 * Math.max(Lx, Ly)

  // --- one-time scene setup --------------------------------------------------
  useEffect(() => {
    const el = wrapRef.current
    if (!el) return
    let renderer: THREE.WebGLRenderer
    try {
      const canvas = document.createElement('canvas')
      const gl = canvas.getContext('webgl2')
      if (!gl) return
      renderer = new THREE.WebGLRenderer({ canvas, context: gl, antialias: false })
    } catch {
      queueMicrotask(() => setUnsupported('WebGL2 could not start; the slice panes are unaffected.'))
      return
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5))
    renderer.setClearColor(0x111214)
    el.appendChild(renderer.domElement)
    renderer.domElement.style.width = '100%'
    renderer.domElement.style.height = '100%'
    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(40, 1, 0.001, 100)
    const span = Math.max(Lx, Ly, Lz)
    camera.position.set(span * 0.9, span * 0.7, span * 1.3)
    const controls = new OrbitControls(camera, renderer.domElement)
    controls.target.set(0, 0, 0)
    const dims = new THREE.Vector3(Lx, Lz, Ly)
    const uniforms = {
      uData: { value: null as THREE.Data3DTexture | null }, uSupport: { value: null as THREE.Data3DTexture | null },
      uCam: { value: new THREE.Vector3() }, uThreshold: { value: 0.2 }, uOpacity: { value: 0.3 },
      uClipMin: { value: new THREE.Vector3(0, 0, 0) }, uClipMax: { value: new THREE.Vector3(1, 1, 1) },
      uShowSupport: { value: 0 }, uSteps: { value: 256 },
    }
    const material = new THREE.ShaderMaterial({
      glslVersion: THREE.GLSL3, vertexShader: VERT, fragmentShader: FRAG,
      side: THREE.BackSide, transparent: true, depthWrite: false,
      uniforms,
    })
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), material)
    mesh.scale.copy(dims)
    scene.add(mesh)
    const outline = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(1, 1, 1)),
      new THREE.LineBasicMaterial({ color: 0x555a66 }))
    outline.scale.copy(dims)
    scene.add(outline)
    const slices = new THREE.Group()
    scene.add(slices)
    const gt = new THREE.Group()
    const regionBoxes = new THREE.Group()
    scene.add(regionBoxes)
    scene.add(gt)
    const marker = new THREE.Mesh(new THREE.SphereGeometry(span * 0.008, 12, 12),
      new THREE.MeshBasicMaterial({ color: 0x22d3ee }))
    scene.add(marker)

    const resize = () => {
      const w = el.clientWidth || 300, h = el.clientHeight || 200
      renderer.setSize(w, h, false)
      camera.aspect = w / h
      camera.updateProjectionMatrix()
    }
    resize()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(resize) : null
    ro?.observe(el)

    let frames = 0, last = performance.now()
    const inv = new THREE.Matrix4()
    const loop = () => {
      controls.update()
      inv.copy(mesh.matrixWorld).invert()
      uniforms.uCam.value.copy(camera.position).applyMatrix4(inv)
      renderer.render(scene, camera)
      frames++
      const now = performance.now()
      if (now - last > 1000) { setFps(Math.round((frames * 1000) / (now - last))); frames = 0; last = now }
      st.raf = requestAnimationFrame(loop)
    }
    const st = { renderer, scene, camera, controls, mesh, material, uniforms, slices, gt, regionBoxes, marker, dims, raf: 0 }
    state.current = st
    st.raf = requestAnimationFrame(loop)

    // click a slice plane -> move the shared cursor
    const ray = new THREE.Raycaster()
    const onClick = (ev: MouseEvent) => {
      const r = renderer.domElement.getBoundingClientRect()
      const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      const hit = ray.intersectObjects(slices.children.filter((o) => o.userData.pickable), false)[0]
      if (!hit) return
      const p = hit.point
      const v = volume
      const x = p.x + Lx / 2 + v.x_axis.origin
      const y = p.z + Ly / 2 + v.y_axis.origin
      const zf = (Lz / 2 - p.y) / Lz
      const z = v.z_axis.origin + zf * nz * v.z_axis.step
      onCursorRef.current(cursorFromCoord(v, x, y, z))
    }
    renderer.domElement.addEventListener('dblclick', onClick)
    // single click on a region box selects that region (a drag to orbit does not)
    let down: { x: number; y: number } | null = null
    const onDown = (ev: PointerEvent) => { down = { x: ev.clientX, y: ev.clientY } }
    const onUp = (ev: PointerEvent) => {
      if (!down || Math.hypot(ev.clientX - down.x, ev.clientY - down.y) > 4) { down = null; return }
      down = null
      const r = renderer.domElement.getBoundingClientRect()
      const ndc = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1)
      ray.setFromCamera(ndc, camera)
      const hit = ray.intersectObjects(regionBoxes.children.filter((o) => o.userData.regionId), false)[0]
      if (hit) onSelectRef.current?.(hit.object.userData.regionId as string)
    }
    renderer.domElement.addEventListener('pointerdown', onDown)
    renderer.domElement.addEventListener('pointerup', onUp)
    return () => {
      cancelAnimationFrame(st.raf)
      ro?.disconnect()
      renderer.domElement.removeEventListener('dblclick', onClick)
      renderer.domElement.removeEventListener('pointerdown', onDown)
      renderer.domElement.removeEventListener('pointerup', onUp)
      controls.dispose()
      renderer.dispose()
      renderer.domElement.remove()
      state.current = null
    }
    // the scene is rebuilt only when a different volume is shown
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [volume.id])

  // --- texture ----------------------------------------------------------------
  useEffect(() => {
    const st = state.current
    if (!st || !render) return
    const [sx, sy, sz] = render.shape
    const tex = new THREE.Data3DTexture(decodeU8(render.data_u8_b64), sx, sy, sz)
    tex.format = THREE.RedFormat
    tex.type = THREE.UnsignedByteType
    tex.minFilter = tex.magFilter = THREE.LinearFilter
    tex.unpackAlignment = 1
    tex.needsUpdate = true
    const sup = new THREE.Data3DTexture(decodeU8(render.support_u8_b64), sx, sy, sz)
    sup.format = THREE.RedFormat
    sup.type = THREE.UnsignedByteType
    sup.minFilter = sup.magFilter = THREE.NearestFilter
    sup.unpackAlignment = 1
    sup.needsUpdate = true
    st.uniforms.uData.value = tex
    st.uniforms.uSupport.value = sup
    return () => { tex.dispose(); sup.dispose() }
  }, [render])

  // --- settings -------------------------------------------------------------------
  useEffect(() => {
    const st = state.current
    if (!st) return
    const u = st.uniforms
    u.uThreshold.value = settings.threshold
    u.uOpacity.value = settings.opacity
    // clip fractions are (x, y, z); texture axes are (x, y, depth)
    u.uClipMin.value.set(...settings.clipMin)
    u.uClipMax.value.set(...settings.clipMax)
    u.uShowSupport.value = settings.showSupport ? 1 : 0
  }, [settings])

  // --- cursor planes ----------------------------------------------------------------
  useEffect(() => {
    const st = state.current
    if (!st) return
    st.slices.clear()
    const px = cursor.x_m - volume.x_axis.origin - Lx / 2 + volume.x_axis.step / 2
    const pz = cursor.y_m - volume.y_axis.origin - Ly / 2 + volume.y_axis.step / 2
    const py = Lz / 2 - ((cursor.k + 0.5) / nz) * Lz
    st.marker.position.set(px, py, pz)
    if (!settings.showSlices) return
    const mk = (w: number, h: number, pos: THREE.Vector3, rot: THREE.Euler, color: number) => {
      const plane = new THREE.Mesh(new THREE.PlaneGeometry(w, h), new THREE.MeshBasicMaterial({
        color, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false }))
      plane.position.copy(pos); plane.rotation.copy(rot); plane.userData.pickable = true
      const edge = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.PlaneGeometry(w, h)),
        new THREE.LineBasicMaterial({ color }))
      edge.position.copy(pos); edge.rotation.copy(rot)
      st.slices.add(plane, edge)
    }
    mk(Lx, Ly, new THREE.Vector3(0, py, 0), new THREE.Euler(-Math.PI / 2, 0, 0), 0x22d3ee)   // XY
    mk(Lx, Lz, new THREE.Vector3(0, 0, pz), new THREE.Euler(0, 0, 0), 0x38bdf8)              // XZ
    mk(Ly, Lz, new THREE.Vector3(px, 0, 0), new THREE.Euler(0, Math.PI / 2, 0), 0x818cf8)    // YZ
  }, [cursor, settings.showSlices, volume, Lx, Ly, Lz, nz])

  // --- response regions: bounding boxes (separate layer) --------------------------------
  useEffect(() => {
    const st = state.current
    if (!st) return
    st.regionBoxes.clear()
    if (!showRegions) return
    const X = (x: number) => x - volume.x_axis.origin - Lx / 2
    const Z = (y: number) => y - volume.y_axis.origin - Ly / 2
    const Y = (k: number) => Lz / 2 - (k / nz) * Lz
    for (const g of regions) {
      const [i0, i1, j0, j1, k0, k1] = g.index_bounds
      const sel = g.id === selectedRegion
      const w = (i1 - i0 + 1) * volume.x_axis.step, d = (j1 - j0 + 1) * volume.y_axis.step
      const h = ((k1 - k0 + 1) / nz) * Lz
      const pos = new THREE.Vector3(X(volume.x_axis.origin + (i0 + i1 + 1) / 2 * volume.x_axis.step) , Y((k0 + k1 + 1) / 2),
                                    Z(volume.y_axis.origin + (j0 + j1 + 1) / 2 * volume.y_axis.step))
      const box = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), new THREE.MeshBasicMaterial({
        color: sel ? 0xffbf00 : 0x4ade80, transparent: true, opacity: sel ? 0.18 : 0.04, depthWrite: false }))
      box.position.copy(pos)
      box.userData.regionId = g.id
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(new THREE.BoxGeometry(w, h, d)),
        new THREE.LineBasicMaterial({ color: sel ? 0xffbf00 : 0x4ade80 }))
      edges.position.copy(pos)
      st.regionBoxes.add(box, edges)
    }
  }, [regions, showRegions, selectedRegion, volume, Lx, Ly, Lz, nz])

  // --- ground truth wireframes (separate layer) ------------------------------------------
  useEffect(() => {
    const st = state.current
    if (!st) return
    st.gt.clear()
    if (!showGroundTruth || !groundTruth?.available || !zIsDepth) return
    const mat = new THREE.LineDashedMaterial({ color: 0xe040fb, dashSize: Lx / 120, gapSize: Lx / 200 })
    const X = (x: number) => x - volume.x_axis.origin - Lx / 2
    const Z = (y: number) => y - volume.y_axis.origin - Ly / 2
    const Y = (z: number) => Lz / 2 - (z - volume.z_axis.origin)
    const add = (geo: THREE.BufferGeometry, pos: THREE.Vector3, rot?: THREE.Euler) => {
      const l = new THREE.LineSegments(new THREE.EdgesGeometry(geo), mat)
      l.position.copy(pos)
      if (rot) l.rotation.copy(rot)
      l.computeLineDistances()
      st.gt.add(l)
    }
    for (const g of groundTruth.objects) {
      if (g.kind === 'duct') {
        add(new THREE.CylinderGeometry(g.radius_m, g.radius_m, g.y_range_m[1] - g.y_range_m[0], 16, 1, true),
          new THREE.Vector3(X(g.x_m), Y(g.z_centre_m), Z((g.y_range_m[0] + g.y_range_m[1]) / 2)),
          new THREE.Euler(Math.PI / 2, 0, 0))
      } else if (g.kind === 'box') {
        const [x0, x1] = g.x_range_m, [y0, y1] = g.y_range_m, [z0, z1] = g.z_range_m
        add(new THREE.BoxGeometry(x1 - x0, z1 - z0, y1 - y0),
          new THREE.Vector3(X((x0 + x1) / 2), Y((z0 + z1) / 2), Z((y0 + y1) / 2)))
      } else if (g.kind === 'plane') {
        const [x0, x1] = g.x_range_m, [y0, y1] = g.y_range_m
        add(new THREE.PlaneGeometry(x1 - x0, y1 - y0),
          new THREE.Vector3(X((x0 + x1) / 2), Y(g.z_m), Z((y0 + y1) / 2)), new THREE.Euler(-Math.PI / 2, 0, 0))
      }
    }
  }, [groundTruth, showGroundTruth, volume, Lx, Ly, Lz, zIsDepth])

  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="pane-3d">
      <div className="flex items-center justify-between gap-2 px-2 py-1 text-[11px] text-muted-foreground">
        <span className="font-medium text-foreground">3D volume</span>
        <span data-testid="pane-3d-fps" data-fps={fps ?? ''}>{fps !== null ? `${fps} fps` : ''}</span>
      </div>
      <div ref={wrapRef} className="relative min-h-0 flex-1">
        {unsupported && <p className="p-3 text-xs text-muted-foreground">{unsupported}</p>}
        {showGroundTruth && groundTruth?.available && (
          <span className="pointer-events-none absolute left-1 top-1 z-10 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-[#e040fb]">
            {groundTruth.label}
          </span>
        )}
      </div>
      {render && (
        <p className="px-2 py-1 text-[10px] text-muted-foreground" data-testid="pane-3d-note">
          DISPLAY-ONLY texture {render.shape.join('×')} (block {render.block_factors.join('×')}) of the
          {' '}{render.original_shape.join('×')} scientific volume, |{render.field}|.
          {!zIsDepth && ' Time axis scaled for display.'} Drag to orbit, double-click a plane to move the cursor.
        </p>
      )}
    </div>
  )
}
