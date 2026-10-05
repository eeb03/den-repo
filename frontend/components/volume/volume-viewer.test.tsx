/**
 * The Volume viewer: preview before build, confirmation, four panes on one
 * cursor, voxel provenance, and the ground-truth overlay as a separate,
 * labelled, opt-in layer. jsdom has no WebGL, so the 3D pane reports that
 * and the slice panes carry on.
 */
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { SWRConfig } from 'swr'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VolumeProduct, VolumeSlice, VoxelInfo } from '@/types/volume'
import { VolumeViewer } from './volume-viewer'

const api = {
  listVolumes: vi.fn(), getDataset: vi.fn(), getVolume: vi.fn(), getVolumeSlice: vi.fn(), getVoxel: vi.fn(),
  getVolumeRender3d: vi.fn(), getVolumeGroundTruth: vi.fn(), previewVolume: vi.fn(), createVolume: vi.fn(),
}
vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api')
  return { ...actual, api: new Proxy({}, { get: (_t, k: string) => (...a: unknown[]) => (api as Record<string, (...x: unknown[]) => unknown>)[k]!(...a) }) }
})

const axis = (name: string, n: number, step: number, unit = 'm') => ({ name, n, origin: 0, step, unit, description: '' })
const VOL = {
  id: 'v1', dataset_id: 'ds', frame_ids: ['ds:grid'],
  coordinate_frame: { kind: 'local_volume', description: 'local', x_meaning: 'x', y_meaning: 'y', z_meaning: 'depth below the surface, m', z_origin: 'calibrated surface', absolute_elevation: false, notes: ['no horizontal registration declared: a local volume'] },
  x_axis: axis('x', 8, 0.005), y_axis: axis('y', 6, 0.005), z_axis: axis('depth', 10, 0.002),
  z_domain: 'depth', shape: [8, 6, 10], voxel_spacing: [0.005, 0.005, 0.002],
  fields: [{ property_name: 'radar_response', unit: 'a.u.', value_kind: 'reconstructed', description: '', method: '', evidence_sources: [], stats: { abs_p99: 1, abs_max: 2 } },
    { property_name: 'response_envelope', unit: 'a.u.', value_kind: 'derived', description: '', method: '', evidence_sources: [], stats: { abs_p99: 1, abs_max: 2 } }],
  primary_field: 'radar_response',
  support_summary: { MEASURED: 0, RECONSTRUCTED: 480, INTERPOLATED: 0, UNSUPPORTED: 0 },
  reconstruction_method: 'Stolt F-K 3D migration, nearest_no_fill gridding, depth domain',
  processing: [{ name: 'dewow', applied: true, parameters: {}, note: '' }],
  migration: { method: 'stolt_fk_3d', velocity_m_per_ns: 0.1289, velocity_source: 'calibrated_from_known_geometry', time_zero_ns: 1.08, time_zero_source: 'calibrated', assumptions: [], parameters: {} },
  interpolation: { mode: 'nearest_no_fill', output_line_spacing_m: 0.005, max_gap_m: 0.01, max_gap_rule: 'rule' },
  calibration_provenance: {}, created_at: '2026-10-05T00:00:00Z',
  validation_status: 'A reconstructed image, not a validated detection',
  what_it_is_not: 'Not density, material, moisture, probability or mineral content.',
  performance: {}, notes: [], staleness: { stale: false, reasons: [] },
  support_class_meaning: { MEASURED: 'm', RECONSTRUCTED: 'r', INTERPOLATED: 'i', UNSUPPORTED: 'u' },
  support_class_values: { UNSUPPORTED: 0, INTERPOLATED: 1, RECONSTRUCTED: 2, MEASURED: 3 },
} as unknown as VolumeProduct

function sliceFor(o: string, index: number): VolumeSlice {
  const dims = { xy: [6, 8], xz: [10, 8], yz: [10, 6] }[o]!
  const n = dims[0]! * dims[1]!
  const f = new Float32Array(n).fill(0.5)
  return { volume_id: 'v1', orientation: o as VolumeSlice['orientation'], index, field: 'response_envelope', thickness_voxels: 1,
    rows: dims[0]!, cols: dims[1]!, axes: { rows: '', cols: '' }, stats: {},
    values_f32_b64: btoa(String.fromCharCode(...new Uint8Array(f.buffer))), support_u8_b64: btoa('\u0002'.repeat(n)) }
}

beforeEach(() => {
  HTMLCanvasElement.prototype.getContext = (() => null) as unknown as HTMLCanvasElement['getContext']
  Object.values(api).forEach((f) => f.mockReset())
  api.listVolumes.mockResolvedValue({ dataset_id: 'ds', volumes: [{ id: 'v1', created_at: '', z_domain: 'depth', reconstruction_method: VOL.reconstruction_method, shape: [8, 6, 10], coordinate_frame: 'local_volume', staleness: { stale: false, reasons: [] } }] })
  api.getDataset.mockResolvedValue({ id: 'ds', name: 'BAM Pk266 1.5 GHz Rot00' })
  api.getVolume.mockResolvedValue(VOL)
  api.getVolumeSlice.mockImplementation((_d: string, _v: string, o: string, i: number) => Promise.resolve(sliceFor(o, i)))
  api.getVoxel.mockImplementation((_d: string, _v: string, i: number, j: number, k: number) => Promise.resolve({
    i, j, k, x_m: i * 0.005, y_m: j * 0.005, z: k * 0.002, z_unit: 'm', z_domain: 'depth', z_meaning: '', values: { radar_response: 0.1, response_envelope: 0.5 },
    support_class: 'RECONSTRUCTED', support_meaning: 'at a measured trace position', support_count: 9, support_count_meaning: 'c',
    nearest_measurement_distance_m: 0, interpolation_distance_m: null, reconstruction_method: VOL.reconstruction_method, migration: {},
    depth_calibration: { used_for_depth: true, velocity: { value_m_per_ns: 0.1289, basis: 'calibrated_from_known_geometry' }, time_zero: { correction_ns: 1.08, status: 'calibrated' } },
    source_frames: ['ds:grid'], coordinate_frame: 'local_volume', validation_status: '' } as VoxelInfo))
  api.getVolumeRender3d.mockResolvedValue(undefined)
  api.getVolumeGroundTruth.mockResolvedValue({ label: 'GROUND TRUTH — NOT INPUT TO RECONSTRUCTION', available: true, objects: [] })
})
afterEach(cleanup)

const wrap = () => render(<SWRConfig value={{ provider: () => new Map(), dedupingInterval: 0 }}><VolumeViewer datasetId="ds" /></SWRConfig>)

describe('VolumeViewer', () => {
  it('shows four panes driven by one cursor, and the voxel at that cursor', async () => {
    wrap()
    await screen.findByTestId('pane-xy')
    expect(screen.getByTestId('pane-xz')).toBeTruthy()
    expect(screen.getByTestId('pane-yz')).toBeTruthy()
    expect(screen.getByTestId('pane-3d')).toBeTruthy()
    expect(screen.getByTestId('cursor-x').textContent).toContain('X = 0.020 m')
    await waitFor(() => expect(screen.getByTestId('voxel-support').textContent).toContain('RECONSTRUCTED'))
    // moving the XY slice slider (depth) changes the cursor everyone reads
    fireEvent.change(screen.getByLabelText('XY slice position'), { target: { value: '7' } })
    await waitFor(() => expect(screen.getByTestId('cursor-z').textContent).toContain('14.0 mm depth'))
    await waitFor(() => expect(api.getVolumeSlice).toHaveBeenCalledWith('ds', 'v1', 'xy', 7, 'response_envelope', 1))
    // the XZ / YZ panes keep their own slice but redraw from the same cursor
    expect(screen.getByTestId('pane-xz-index').textContent).toContain('slice 4/6')
  })

  it('states what the volume is not, and keeps ground truth opt-in and labelled', async () => {
    wrap()
    await screen.findByTestId('volume-provenance')
    expect(screen.getByTestId('volume-provenance').textContent).toContain('Not density, material')
    expect(screen.queryByText('GROUND TRUTH — NOT INPUT TO RECONSTRUCTION')).toBeNull()
    const toggle = await screen.findByLabelText('Ground-truth overlay (separate layer)')
    await waitFor(() => expect((toggle as HTMLInputElement).disabled).toBe(false))
    fireEvent.click(toggle)
    expect((await screen.findAllByText('GROUND TRUTH — NOT INPUT TO RECONSTRUCTION')).length).toBeGreaterThan(0)
  })

  it('previews before it builds, and builds only on explicit confirmation', async () => {
    api.listVolumes.mockResolvedValue({ dataset_id: 'ds', volumes: [] })
    api.previewVolume.mockResolvedValue({ possible: false, refusals: ['1 measured line(s): a single radar line is a 2D B-scan'], notes: [], missing: [], resolved: {} })
    wrap()
    fireEvent.click(await screen.findByText('Preview'))
    expect(await screen.findByText(/Reconstruction refused/)).toBeTruthy()
    expect(screen.queryByText('Confirm: create volume')).toBeNull()
    expect(api.createVolume).not.toHaveBeenCalled()

    api.previewVolume.mockResolvedValue({ possible: true, refusals: [], notes: [], missing: [], resolved: {}, depth: { z_domain: 'depth', depth_scientifically_sufficient: true }, estimated_shape: [8, 6, 10] })
    api.createVolume.mockResolvedValue(VOL)
    fireEvent.click(screen.getByText('Preview'))
    fireEvent.click(await screen.findByText('Confirm: create volume'))
    await waitFor(() => expect(api.createVolume).toHaveBeenCalledTimes(1))
  })

  it('says a stale volume is stale, and why', async () => {
    api.getVolume.mockResolvedValue({ ...VOL, staleness: { stale: true, reasons: ['the applied time zero changed since this volume was built'], action: 'regenerate the volume' } })
    wrap()
    expect((await screen.findByTestId('stale-banner')).textContent).toContain('time zero changed')
  })
})
