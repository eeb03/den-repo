'use client'

import Link from 'next/link'
import { Fragment, useEffect, useMemo, useState } from 'react'
import useSWR from 'swr'
import { AppHeader } from '@/components/shell/app-header'
import { Panel, PanelHeader } from '@/components/subterra/panel'
import { StateBox } from '@/components/subterra/state-box'
import { Button } from '@/components/ui/button'
import {
  type DisplayWindow, type Polarity, type VolumeCursor, centreCursor, cursorFromCoord,
  defaultWindow, formatZ,
} from '@/lib/volume'
import { ApiError, api } from '@/services/api'
import type { FieldName, Orientation, VolumeConfig, VolumePreview, VolumeProduct } from '@/types/volume'
import { SlicePane } from './slice-pane'
import { type Render3DSettings, Volume3D } from './volume-3d'

const swrOpts = {
  revalidateOnFocus: false,
  keepPreviousData: true,
  shouldRetryOnError: (e: unknown) => !(e instanceof ApiError && e.isAbsence),
}

const ORIENTATIONS: Orientation[] = ['xy', 'xz', 'yz']
const FIT = { zoom: 1, panX: 0, panY: 0 }

/**
 * Subterra Volume V1 viewer: CT/MRI-style inspection of ONE reconstructed
 * volume through synchronized XY, XZ, YZ and 3D panes.
 *
 * WHAT IT SHOWS. A reconstructed radar response and how each voxel is
 * supported -- never an object, a class, or a material. The ground-truth
 * overlay (BAM only) is a separate, labelled layer drawn on top; it is never
 * part of the volume and never reaches the reconstruction.
 *
 * ONE CURSOR. `cursor` lives here; every pane reads it and reports changes
 * through `setCursor`.
 */
export function VolumeViewer({ datasetId }: { datasetId: string }) {
  const list = useSWR(['volumes', datasetId], () => api.listVolumes(datasetId), swrOpts)
  const dataset = useSWR(['dataset', datasetId], () => api.getDataset(datasetId), swrOpts)
  const [chosen, setSelected] = useState<string | null>(null)
  const volumes = list.data?.volumes ?? []
  const selected = chosen ?? volumes[0]?.id ?? null

  return (
    <>
      <AppHeader
        title={`Volume — ${dataset.data?.name ?? datasetId}`}
        subtitle="Reconstructed radar response with per-voxel support. An image, not an interpretation."
        actions={
          <Link href={`/datasets/${encodeURIComponent(datasetId)}`} className="text-xs text-primary hover:underline">
            Back to workspace
          </Link>
        }
      />
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-3 p-3 xl:grid-cols-[17rem_minmax(0,1fr)]">
        <Panel className="min-h-0 overflow-y-auto">
          <PanelHeader title="Volumes" count={volumes.length} />
          <div className="space-y-2 px-3 pb-3 text-xs">
            {list.error && <StateBox kind="error" title="Could not list volumes" detail={String(list.error)} />}
            {volumes.length === 0 && !list.isLoading && (
              <p className="text-muted-foreground">No volume has been built for this dataset yet.</p>
            )}
            <ul className="space-y-1.5" data-testid="volume-list">
              {volumes.map((v) => (
                <li key={v.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(v.id)}
                    aria-pressed={selected === v.id}
                    className={`w-full rounded-lg border px-2 py-1.5 text-left ${selected === v.id ? 'border-primary/50 bg-primary/10' : 'border-border'}`}
                  >
                    <span className="block font-medium">{v.reconstruction_method}</span>
                    <span className="block text-muted-foreground">
                      {v.shape.join('×')} · {v.z_domain === 'depth' ? 'depth' : 'two-way time'} · {v.coordinate_frame.replace('_', ' ')}
                    </span>
                    <span className="block text-muted-foreground">built {v.created_at.slice(0, 19).replace('T', ' ')} UTC · {v.id}</span>
                    {v.staleness.stale && <span className="block font-medium text-amber-500">STALE — inputs changed</span>}
                  </button>
                </li>
              ))}
            </ul>
            <CreateVolume datasetId={datasetId} onCreated={(id) => { list.mutate(); setSelected(id) }} />
          </div>
        </Panel>
        {selected ? <VolumeInspector datasetId={datasetId} volumeId={selected} /> : (
          <Panel className="flex items-center justify-center p-6">
            <StateBox kind="empty" title="No volume selected"
              detail="Preview a reconstruction on the left; Subterra states what it can and cannot build before it builds anything." />
          </Panel>
        )}
      </div>
    </>
  )
}

/* ------------------------------------------------------------------ create */

function CreateVolume({ datasetId, onCreated }: { datasetId: string; onCreated: (id: string) => void }) {
  const [cfg, setCfg] = useState<VolumeConfig>({
    z_domain: 'auto', migration: 'stolt_fk_3d', interpolation: 'nearest_no_fill',
    output_line_spacing_m: null, max_gap_line_spacings: 2, dewow: true, background_removal: 'none',
  })
  const [preview, setPreview] = useState<VolumePreview | null>(null)
  const [busy, setBusy] = useState<'preview' | 'create' | null>(null)
  const [error, setError] = useState<string | null>(null)
  const set = (patch: Partial<VolumeConfig>) => { setCfg({ ...cfg, ...patch }); setPreview(null) }

  return (
    <div className="mt-3 space-y-2 border-t border-border pt-3" data-testid="volume-create">
      <p className="font-medium text-foreground">New volume</p>
      <label className="flex items-center justify-between gap-2">Z axis
        <select aria-label="z domain" value={cfg.z_domain} onChange={(e) => set({ z_domain: e.target.value as VolumeConfig['z_domain'] })} className="rounded border border-border bg-background px-1">
          <option value="auto">auto (depth only if sufficient)</option><option value="depth">depth</option><option value="time">two-way time</option>
        </select></label>
      <label className="flex items-center justify-between gap-2">Migration
        <select aria-label="migration" value={cfg.migration} onChange={(e) => set({ migration: e.target.value as VolumeConfig['migration'] })} className="rounded border border-border bg-background px-1">
          <option value="none">none</option><option value="stolt_fk_3d">Stolt F-K 3D</option>
        </select></label>
      <label className="flex items-center justify-between gap-2">Gridding
        <select aria-label="interpolation" value={cfg.interpolation} onChange={(e) => set({ interpolation: e.target.value as VolumeConfig['interpolation'] })} className="rounded border border-border bg-background px-1">
          <option value="nearest_no_fill">nearest, no fill</option><option value="linear_bounded">linear, bounded</option>
        </select></label>
      <label className="flex items-center justify-between gap-2">Line spacing (m)
        <input aria-label="output line spacing" type="number" step="0.001" placeholder="measured"
          value={cfg.output_line_spacing_m ?? ''} onChange={(e) => set({ output_line_spacing_m: e.target.value ? Number(e.target.value) : null })}
          className="w-20 rounded border border-border bg-background px-1" /></label>
      <label className="flex items-center justify-between gap-2">Max gap (line spacings)
        <input aria-label="max gap" type="number" step="0.5" min="1" value={cfg.max_gap_line_spacings}
          onChange={(e) => set({ max_gap_line_spacings: Number(e.target.value) })} className="w-16 rounded border border-border bg-background px-1" /></label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.dewow} onChange={(e) => set({ dewow: e.target.checked })} /> Dewow</label>
      <label className="flex items-center gap-2"><input type="checkbox" checked={cfg.background_removal === 'line_mean'}
        onChange={(e) => set({ background_removal: e.target.checked ? 'line_mean' : 'none' })} /> Line-mean background removal</label>
      <Button size="sm" variant="outline" disabled={busy !== null} onClick={async () => {
        setBusy('preview'); setError(null)
        try { setPreview(await api.previewVolume(datasetId, cfg)) } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)) }
        setBusy(null)
      }}>{busy === 'preview' ? 'Checking…' : 'Preview'}</Button>
      {preview && <PreviewResult p={preview} />}
      {preview?.possible && (
        <Button size="sm" disabled={busy !== null} onClick={async () => {
          setBusy('create'); setError(null)
          try { const v = await api.createVolume(datasetId, cfg); setPreview(null); onCreated(v.id) } catch (e) { setError(e instanceof ApiError ? e.detail : String(e)) }
          setBusy(null)
        }}>{busy === 'create' ? 'Reconstructing…' : 'Confirm: create volume'}</Button>
      )}
      {error && <p className="text-destructive" role="alert">{error}</p>}
    </div>
  )
}

function PreviewResult({ p }: { p: VolumePreview }) {
  return (
    <div className="space-y-1 rounded-lg border border-border p-2" data-testid="volume-preview">
      <p className={p.possible ? 'font-medium text-emerald-500' : 'font-medium text-destructive'}>
        {p.possible ? 'Reconstruction is possible' : 'Reconstruction refused'}
      </p>
      {p.refusals.map((r) => <p key={r} className="text-destructive">• {r}</p>)}
      {p.depth && (
        <p>Z: <b>{p.depth.z_domain === 'depth' ? 'depth (m)' : 'two-way time (ns) — not depth'}</b>
          {p.depth.velocity_m_per_ns ? ` · v ${p.depth.velocity_m_per_ns.toFixed(4)} m/ns` : ''}
          {p.depth.time_zero_ns != null ? ` · t0 ${p.depth.time_zero_ns.toFixed(3)} ns` : ''}</p>
      )}
      {p.estimated_shape && <p>Shape {p.estimated_shape.join('×')} · voxel {p.voxel_spacing?.map((v, i) => `${v.toPrecision(3)} ${p.voxel_spacing_units?.[i]}`).join(' × ')}</p>}
      {p.estimated_bytes && <p>≈ {(p.estimated_bytes / 1e6).toFixed(0)} MB on the server</p>}
      {p.interpolation_required !== undefined && <p>Interpolation required: {p.interpolation_required ? 'yes' : 'no'}</p>}
      {p.missing.map((m) => <p key={m} className="text-muted-foreground">Missing: {m}</p>)}
      {p.notes.map((m) => <p key={m} className="text-amber-500">{m}</p>)}
    </div>
  )
}

/* ------------------------------------------------------------------ inspector */

function VolumeInspector({ datasetId, volumeId }: { datasetId: string; volumeId: string }) {
  const vol = useSWR(['volume', datasetId, volumeId], () => api.getVolume(datasetId, volumeId), swrOpts)
  if (vol.error) return <Panel className="p-4"><StateBox kind="error" title="Could not load volume" detail={String(vol.error)} /></Panel>
  if (!vol.data) return <Panel className="p-4 text-xs text-muted-foreground">Loading volume…</Panel>
  return <Inspector key={volumeId} datasetId={datasetId} volume={vol.data} />
}

function Inspector({ datasetId, volume }: { datasetId: string; volume: VolumeProduct }) {
  const [cursor, setCursor] = useState<VolumeCursor>(() => centreCursor(volume))
  const [field, setField] = useState<FieldName>('response_envelope')
  const stats = volume.fields.find((f) => f.property_name === field)?.stats ?? {}
  const [display, setDisplay] = useState<DisplayWindow>(() => defaultWindow(stats, false))
  const chooseField = (f: FieldName) => {
    setField(f)
    setDisplay(defaultWindow(volume.fields.find((x) => x.property_name === f)?.stats ?? {}, f === 'radar_response'))
  }
  const [thickness, setThickness] = useState(1)
  const [showSupport, setShowSupport] = useState(true)
  const [showInterpolated, setShowInterpolated] = useState(true)
  const [showGT, setShowGT] = useState(false)
  const [views, setViews] = useState<Record<Orientation, typeof FIT>>({ xy: FIT, xz: FIT, yz: FIT })
  const [r3, setR3] = useState<Render3DSettings>({
    threshold: 0.25, opacity: 0.35, clipMin: [0, 0, 0], clipMax: [1, 1, 1], showSlices: true, showSupport: false,
  })
  const [goto, setGoto] = useState({ x: '', y: '', z: '' })

  const sliceKey = (o: Orientation, idx: number) => ['slice', datasetId, volume.id, o, idx, field, thickness]
  const xy = useSWR(sliceKey('xy', cursor.k), () => api.getVolumeSlice(datasetId, volume.id, 'xy', cursor.k, field, thickness), swrOpts)
  const xz = useSWR(sliceKey('xz', cursor.j), () => api.getVolumeSlice(datasetId, volume.id, 'xz', cursor.j, field, thickness), swrOpts)
  const yz = useSWR(sliceKey('yz', cursor.i), () => api.getVolumeSlice(datasetId, volume.id, 'yz', cursor.i, field, thickness), swrOpts)
  const slices = { xy: xy.data, xz: xz.data, yz: yz.data }
  const render = useSWR(['render3d', datasetId, volume.id], () => api.getVolumeRender3d(datasetId, volume.id, 'response_envelope'), swrOpts)
  const gt = useSWR(['gt', datasetId, volume.id], () => api.getVolumeGroundTruth(datasetId, volume.id), swrOpts)

  // the voxel inspector follows the cursor, a little behind a drag
  const [voxelAt, setVoxelAt] = useState(cursor)
  useEffect(() => { const t = setTimeout(() => setVoxelAt(cursor), 150); return () => clearTimeout(t) }, [cursor])
  const voxel = useSWR(['voxel', datasetId, volume.id, voxelAt.i, voxelAt.j, voxelAt.k],
    () => api.getVoxel(datasetId, volume.id, voxelAt.i, voxelAt.j, voxelAt.k), swrOpts)

  const zLabel = volume.z_domain === 'depth' ? 'Depth' : 'Two-way time'
  const fmt = useMemo(() => (v: number) => (Math.abs(v) >= 100 ? v.toFixed(0) : v.toPrecision(3)), [])

  return (
    <div className="grid min-h-0 grid-cols-1 gap-3 2xl:grid-cols-[minmax(0,1fr)_20rem]">
      <Panel className="min-h-0">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-border px-3 py-2 text-xs" data-testid="crosshair-readout">
          <span className="font-medium">Crosshair</span>
          <span data-testid="cursor-x">X = {cursor.x_m.toFixed(3)} m</span>
          <span data-testid="cursor-y">Y = {cursor.y_m.toFixed(3)} m</span>
          <span data-testid="cursor-z">{zLabel} = {formatZ(cursor.z, cursor.zUnit)}</span>
          <span className="text-muted-foreground">voxel ({cursor.i}, {cursor.j}, {cursor.k})</span>
          {volume.staleness.stale && (
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-medium text-amber-500" data-testid="stale-banner">
              STALE: {volume.staleness.reasons.join('; ')} — {volume.staleness.action}
            </span>
          )}
          <span className="ml-auto flex items-center gap-1">
            <input aria-label="go to x" placeholder="x m" value={goto.x} onChange={(e) => setGoto({ ...goto, x: e.target.value })} className="w-14 rounded border border-border bg-background px-1" />
            <input aria-label="go to y" placeholder="y m" value={goto.y} onChange={(e) => setGoto({ ...goto, y: e.target.value })} className="w-14 rounded border border-border bg-background px-1" />
            <input aria-label="go to z" placeholder={volume.z_axis.unit === 'm' ? 'depth m' : 'ns'} value={goto.z} onChange={(e) => setGoto({ ...goto, z: e.target.value })} className="w-16 rounded border border-border bg-background px-1" />
            <Button size="xs" variant="outline" onClick={() => setCursor(cursorFromCoord(volume,
              goto.x ? Number(goto.x) : cursor.x_m, goto.y ? Number(goto.y) : cursor.y_m, goto.z ? Number(goto.z) : cursor.z))}>Go to coordinate</Button>
            <Button size="xs" variant="outline" onClick={() => setViews({ xy: FIT, xz: FIT, yz: FIT })}>Fit volume</Button>
            <Button size="xs" variant="outline" onClick={() => { setViews({ xy: FIT, xz: FIT, yz: FIT }); setCursor(centreCursor(volume)); setDisplay(defaultWindow(stats, field === 'radar_response')); setThickness(1) }}>Reset view</Button>
          </span>
        </div>
        <div className="grid min-h-[36rem] flex-1 grid-cols-1 grid-rows-[repeat(4,18rem)] gap-px bg-border md:grid-cols-2 md:grid-rows-2">
          {ORIENTATIONS.map((o) => (
            <div key={o} className="flex min-h-0 flex-col bg-card">
              <SlicePane orientation={o} volume={volume} slice={slices[o]} cursor={cursor} onCursor={setCursor}
                display={display} showSupport={showSupport} showInterpolated={showInterpolated}
                groundTruth={gt.data} showGroundTruth={showGT}
                view={views[o]} onView={(v) => setViews({ ...views, [o]: v })} />
            </div>
          ))}
          <div className="flex min-h-0 flex-col bg-card">
            <Volume3D volume={volume} render={render.data} cursor={cursor} onCursor={setCursor}
              settings={r3} groundTruth={gt.data} showGroundTruth={showGT} />
          </div>
        </div>
      </Panel>

      <Panel className="min-h-0 overflow-y-auto">
        <PanelHeader title="Display" />
        <div className="space-y-2 px-3 pb-3 text-xs" data-testid="volume-controls">
          <label className="flex items-center justify-between gap-2">Field
            <select aria-label="field" value={field} onChange={(e) => chooseField(e.target.value as FieldName)} className="rounded border border-border bg-background px-1">
              <option value="response_envelope">response envelope</option><option value="radar_response">radar response (signed)</option>
            </select></label>
          <Slider label="Window" value={display.window} min={0} max={(stats.abs_max || 1) * 2} onChange={(v) => setDisplay({ ...display, window: v })} fmt={fmt} />
          <Slider label="Level" value={display.level} min={-(stats.abs_max || 1)} max={stats.abs_max || 1} onChange={(v) => setDisplay({ ...display, level: v })} fmt={fmt} />
          <Slider label="Gain (display)" value={display.gain} min={0.1} max={10} step={0.1} onChange={(v) => setDisplay({ ...display, gain: v })} fmt={(v) => v.toFixed(1)} />
          <label className="flex items-center justify-between gap-2">Polarity
            <select aria-label="polarity" value={display.polarity} onChange={(e) => setDisplay({ ...display, polarity: e.target.value as Polarity })} className="rounded border border-border bg-background px-1">
              <option value="signed">signed</option><option value="inverted">inverted</option><option value="absolute">absolute</option>
            </select></label>
          <Slider label="Slice thickness (voxels)" value={thickness} min={1} max={15} step={2} onChange={setThickness} fmt={(v) => String(v)} />
          <Slider label="3D opacity" value={r3.opacity} min={0.02} max={1} step={0.01} onChange={(v) => setR3({ ...r3, opacity: v })} fmt={(v) => v.toFixed(2)} />
          <Slider label="3D amplitude threshold" value={r3.threshold} min={0} max={0.95} step={0.01} onChange={(v) => setR3({ ...r3, threshold: v })} fmt={(v) => v.toFixed(2)} />
          {(['x', 'y', 'z'] as const).map((a, n) => (
            <Slider key={a} label={`3D clip ${a} (min–max)`} value={r3.clipMin[n] ?? 0} min={0} max={0.95} step={0.01}
              onChange={(v) => { const m = [...r3.clipMin] as [number, number, number]; m[n] = v; setR3({ ...r3, clipMin: m }) }} fmt={(v) => `${(v * 100).toFixed(0)}%`} />
          ))}
          <Toggle label="Support / confidence overlay" checked={showSupport} onChange={(v) => { setShowSupport(v); setR3({ ...r3, showSupport: v }) }} />
          <Toggle label="Show interpolated voxels" checked={showInterpolated} onChange={setShowInterpolated} />
          <Toggle label="Slice planes in 3D" checked={r3.showSlices} onChange={(v) => setR3({ ...r3, showSlices: v })} />
          <Toggle label="Ground-truth overlay (separate layer)" checked={showGT} onChange={setShowGT}
            disabled={!gt.data?.available} hint={gt.data && !gt.data.available ? gt.data.reason : undefined} />
          <SupportLegend volume={volume} />
        </div>
        <PanelHeader title="Voxel" />
        <div className="space-y-1 px-3 pb-3 text-xs" data-testid="voxel-inspector">
          {voxel.data ? (
            <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
              <dt className="text-muted-foreground">X</dt><dd>{voxel.data.x_m.toFixed(3)} m</dd>
              <dt className="text-muted-foreground">Y</dt><dd>{voxel.data.y_m.toFixed(3)} m</dd>
              <dt className="text-muted-foreground">{zLabel}</dt><dd>{formatZ(voxel.data.z, voxel.data.z_unit)}</dd>
              {Object.entries(voxel.data.values).map(([k, v]) => (<Fragment key={k}><dt className="text-muted-foreground">{k}</dt><dd>{v === null ? 'empty (unsupported)' : v.toPrecision(5)}</dd></Fragment>))}
              <dt className="text-muted-foreground">Support</dt><dd data-testid="voxel-support"><b>{voxel.data.support_class}</b> — {voxel.data.support_meaning}</dd>
              <dt className="text-muted-foreground">Support count</dt><dd>{voxel.data.support_count} <span className="text-muted-foreground">({voxel.data.support_count_meaning})</span></dd>
              <dt className="text-muted-foreground">Nearest measurement</dt><dd>{voxel.data.nearest_measurement_distance_m === null ? '—' : `${(voxel.data.nearest_measurement_distance_m * 1000).toFixed(1)} mm`}</dd>
              <dt className="text-muted-foreground">Interpolation distance</dt><dd>{voxel.data.interpolation_distance_m === null ? 'not interpolated' : `${(voxel.data.interpolation_distance_m * 1000).toFixed(1)} mm`}</dd>
              <dt className="text-muted-foreground">Method</dt><dd>{voxel.data.reconstruction_method}</dd>
              <dt className="text-muted-foreground">Depth calibration</dt><dd>{describeCalibration(voxel.data.depth_calibration)}</dd>
              <dt className="text-muted-foreground">Source frame(s)</dt><dd className="break-all">{voxel.data.source_frames.join(', ')}</dd>
              <dt className="text-muted-foreground">Frame</dt><dd>{voxel.data.coordinate_frame.replace('_', ' ')}</dd>
            </dl>
          ) : <p className="text-muted-foreground">Click any pane to inspect a voxel.</p>}
        </div>
        <PanelHeader title="What this volume is" />
        <div className="space-y-1 px-3 pb-3 text-xs text-muted-foreground" data-testid="volume-provenance">
          <p><b className="text-foreground">{volume.reconstruction_method}</b></p>
          <p>Migration: {volume.migration.method}{volume.migration.velocity_m_per_ns ? ` · v ${volume.migration.velocity_m_per_ns.toFixed(4)} m/ns (${volume.migration.velocity_source})` : ''}{volume.migration.time_zero_ns != null ? ` · t0 ${volume.migration.time_zero_ns.toFixed(3)} ns (${volume.migration.time_zero_source})` : ''}</p>
          <p>Z: {volume.coordinate_frame.z_meaning}; origin: {volume.coordinate_frame.z_origin}</p>
          <p>Frame: {volume.coordinate_frame.kind.replace('_', ' ')} — {volume.coordinate_frame.notes.join(' ')}</p>
          <p>Gridding: {volume.interpolation.max_gap_rule}</p>
          <p>Processing: {volume.processing.filter((s) => s.applied).map((s) => s.name).join(' → ')}</p>
          <p className="text-foreground">{volume.what_it_is_not}</p>
          <p>{volume.validation_status}</p>
        </div>
      </Panel>
    </div>
  )
}

function describeCalibration(c: Record<string, unknown>): string {
  if (!c.used_for_depth) return 'not used: time-domain volume'
  const v = c.velocity as { value_m_per_ns?: number; basis?: string } | null
  const tz = c.time_zero as { correction_ns?: number; status?: string } | null
  return `v ${v?.value_m_per_ns?.toFixed(4)} m/ns (${v?.basis}); t0 ${tz?.correction_ns?.toFixed(3)} ns (${tz?.status})` +
    (c.depth_calibration_declaration_id ? `; declaration ${String(c.depth_calibration_declaration_id).slice(0, 8)}` : '')
}

function Slider({ label, value, min, max, step, onChange, fmt }: {
  label: string; value: number; min: number; max: number; step?: number; onChange: (v: number) => void; fmt: (v: number) => string
}) {
  return (
    <label className="block">
      <span className="flex justify-between"><span>{label}</span><span className="text-muted-foreground">{fmt(value)}</span></span>
      <input type="range" aria-label={label} className="w-full" min={min} max={max} step={step ?? (max - min) / 200}
        value={value} onChange={(e) => onChange(Number(e.target.value))} />
    </label>
  )
}

function Toggle({ label, checked, onChange, disabled, hint }: {
  label: string; checked: boolean; onChange: (v: boolean) => void; disabled?: boolean; hint?: string
}) {
  return (
    <label className={`flex items-start gap-2 ${disabled ? 'opacity-50' : ''}`} title={hint}>
      <input type="checkbox" aria-label={label} checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span>{label}{hint && <span className="block text-muted-foreground">{hint}</span>}</span>
    </label>
  )
}

function SupportLegend({ volume }: { volume: VolumeProduct }) {
  const total = Object.values(volume.support_summary).reduce((a, b) => a + b, 0) || 1
  return (
    <div className="mt-2 space-y-0.5 rounded-lg border border-border p-2" data-testid="support-legend">
      <p className="font-medium">Voxel support</p>
      {(['MEASURED', 'RECONSTRUCTED', 'INTERPOLATED', 'UNSUPPORTED'] as const).map((k) => (
        <p key={k} className="flex justify-between gap-2">
          <span>
            <span className={`mr-1 inline-block size-2 rounded-sm ${k === 'INTERPOLATED' ? 'bg-amber-400' : k === 'UNSUPPORTED' ? 'bg-zinc-700' : 'bg-zinc-300'}`} />
            {k.toLowerCase()}
          </span>
          <span className="text-muted-foreground">{((100 * (volume.support_summary[k] ?? 0)) / total).toFixed(1)}%</span>
        </p>
      ))}
      <p className="text-muted-foreground">Unsupported voxels are empty (checkerboard), never filled.</p>
    </div>
  )
}

