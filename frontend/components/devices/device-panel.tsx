'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useSWRConfig } from 'swr'
import { ApiError, api } from '@/services/api'
import { useDevices, useImportFormats } from '@/hooks/use-subterra'
import { Panel, PanelBody, PanelHeader, Field } from '@/components/subterra/panel'
import { buttonVariants } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { NO_VALUE, formatDateTime } from '@/lib/format'
import type { SessionPayload, SessionState } from '@/types/subterra'

/**
 * Devices and acquisition sessions.
 *
 * NOTHING HERE CONTROLS HARDWARE, and the interface must not suggest otherwise.
 * There is no "connect", no "disconnect", no live telemetry and no acquisition
 * progress, because Subterra cannot talk to an instrument and a button for a
 * command the system cannot execute is a lie with a cursor on it. What this
 * screen does is record provenance: which instrument somebody says they used,
 * and which acquisition event produced which evidence.
 *
 * EVERYTHING TYPED HERE IS USER-DECLARED, and the screen says so next to the
 * fields rather than in a footnote. A serial number somebody remembered is not
 * one an instrument reported; when an adapter eventually reads one off
 * hardware, the label will change and the difference will still be visible.
 *
 * A SIMULATED DEVICE IS LABELLED WHEREVER IT APPEARS. Test data that cannot be
 * told from measurement is the worst thing an acquisition layer can leak, so
 * the marker travels with the device and into the dataset's provenance.
 *
 * CAPABILITY IS NOT EVIDENCE. The gap between what the device can produce and
 * what the session actually provided is rendered as its own list, in the
 * backend's words, because a device that can report a position has said nothing
 * about whether this survey got one.
 */
export function DevicePanel() {
  // SWR rather than a manual effect: the repo fetches this way everywhere, and
  // setting state inside an effect is what the lint rule is there to stop.
  const { data: devices } = useDevices()
  // The export-format picker offers exactly what the platform can read, from
  // the same registry the import screen does -- never a second hardcoded
  // list that could promise a format Subterra cannot actually ingest.
  const { data: importFormats } = useImportFormats()
  const { mutate } = useSWRConfig()
  const [session, setSession] = useState<SessionPayload | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [registering, setRegistering] = useState(false)
  // Where the operator says a scan is about to happen, in their own words --
  // a site description, not a geometry, and not read back from any dataset.
  // Keyed per device since several devices can each start a session. Blank
  // sends nothing, never an empty string that would look like a declared
  // site.
  const [surveyAreaDrafts, setSurveyAreaDrafts] = useState<Record<string, string>>({})
  // What the operator says this scan is referenced to, in their own words --
  // a claim, not a spatial registration, and never a default EPSG code.
  // Same per-device draft pattern as survey area.
  const [coordinateSystemDrafts, setCoordinateSystemDrafts] = useState<Record<string, string>>({})
  const [form, setForm] = useState({
    manufacturer: '',
    model: '',
    serial_number: '',
    device_type: 'gpr',
    simulated: false,
    // What the instrument CAN produce. Declared here so the gap between
    // capability and evidence is reachable at all: without these, every
    // session trivially provides everything its device claims, and the
    // distinction the stage exists for never appears.
    reports_position: false,
    reports_orientation: false,
    reports_absolute_time: false,
    // The DeviceProfile: declared facts about the instrument, not a
    // measurement and not a hardware connection. Every field stays optional
    // -- an empty string here means undeclared, not zero.
    frequency_mhz: '',
    channels: '',
    sample_interval_ns: '',
    samples_per_trace: '',
    supported_export_formats: [] as string[],
    // HOW this device's evidence is meant to arrive -- not a connection.
    // Unchecked (the default) means undeclared, never "file_drop" by
    // default. There is no way to select network or serial: neither is
    // implemented, and a selectable option that would only 422 on submit
    // would look like a working choice.
    file_drop: false,
  })

  function fail(err: unknown) {
    setError(
      err instanceof ApiError
        ? err.detail
        : 'could not reach the Subterra API. Is the backend running?',
    )
  }

  async function register(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      // Sampling configuration is free-form on the backend; only the keys the
      // operator actually filled in are sent, so a blank field means
      // undeclared rather than a fabricated 0.
      const samplingConfiguration: Record<string, number> = {}
      if (form.sample_interval_ns !== '') {
        samplingConfiguration.sample_interval_ns = Number(form.sample_interval_ns)
      }
      if (form.samples_per_trace !== '') {
        samplingConfiguration.samples_per_trace = Number(form.samples_per_trace)
      }

      await api.registerDevice({
        device_type: form.device_type,
        manufacturer: form.manufacturer || undefined,
        model: form.model || undefined,
        serial_number: form.serial_number || undefined,
        kind: form.simulated ? 'simulated' : 'physical',
        capabilities: {
          modalities: [form.device_type],
          reports_position: form.reports_position,
          reports_orientation: form.reports_orientation,
          reports_absolute_time: form.reports_absolute_time,
          frequency_mhz: form.frequency_mhz === '' ? undefined : Number(form.frequency_mhz),
          channels: form.channels === '' ? undefined : Number(form.channels),
          sampling_configuration: samplingConfiguration,
          supported_export_formats: form.supported_export_formats,
        },
        adapter: form.file_drop ? { transport: 'file_drop' } : undefined,
      })
      setForm({
        ...form,
        manufacturer: '',
        model: '',
        serial_number: '',
        frequency_mhz: '',
        channels: '',
        sample_interval_ns: '',
        samples_per_trace: '',
        supported_export_formats: [],
        file_drop: false,
      })
      setRegistering(false)
      await mutate('devices')
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function startSession(deviceId: string) {
    setBusy(true)
    setError(null)
    try {
      const surveyArea = surveyAreaDrafts[deviceId]?.trim()
      const coordinateSystem = coordinateSystemDrafts[deviceId]?.trim()
      const { session: created } = await api.createSession(deviceId, {
        survey_area: surveyArea || undefined,
        coordinate_system: coordinateSystem || undefined,
      })
      setSession(await api.getSession(created.id))
      setSurveyAreaDrafts((prev) => ({ ...prev, [deviceId]: '' }))
      setCoordinateSystemDrafts((prev) => ({ ...prev, [deviceId]: '' }))
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  async function move(to: SessionState) {
    if (!session) return
    setBusy(true)
    setError(null)
    try {
      setSession(await api.moveSession(session.session.id, to))
    } catch (err) {
      fail(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-4">
      <Panel>
        <PanelHeader title="Devices" count={devices?.length} />
        <PanelBody>
          <p className="text-xs leading-relaxed text-muted-foreground">
            A record of the instrument used, for provenance. Subterra does not
            communicate with hardware: nothing here connects to a device, and no
            measurement is produced by registering one.
          </p>

          {devices?.length === 0 && !registering && (
            <p className="mt-3 text-xs text-muted-foreground">
              No devices recorded yet.
            </p>
          )}

          {devices?.map((device) => (
            <div
              key={device.id}
              data-device={device.id}
              className="mt-3 border-t border-border pt-3 first:border-t-0"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-medium text-foreground">
                  {[device.manufacturer, device.model].filter(Boolean).join(' ') ||
                    device.label ||
                    device.device_type}
                </span>
                {device.is_simulated && (
                  <span
                    data-simulated
                    className="rounded border border-border px-1.5 py-px font-mono text-[10px] uppercase tracking-wider text-muted-foreground"
                  >
                    Simulated — not real hardware
                  </span>
                )}
              </div>
              <dl className="mt-1.5">
                <Field label="Type">{device.device_type}</Field>
                <Field label="Serial">
                  {device.serial_number ?? NO_VALUE}
                  {device.serial_number && (
                    <span className="ml-2 text-[11px] text-muted-foreground">
                      {device.identity_source === 'user_declared'
                        ? 'user supplied'
                        : 'device reported'}
                    </span>
                  )}
                </Field>
                <Field label="Recorded">{formatDateTime(device.created_at)}</Field>
                <Field label="Frequency">
                  {device.capabilities.frequency_mhz != null
                    ? `${device.capabilities.frequency_mhz} MHz`
                    : NO_VALUE}
                </Field>
                <Field label="Channels">
                  {device.capabilities.channels ?? NO_VALUE}
                </Field>
                <Field label="Export formats">
                  {device.capabilities.supported_export_formats?.length
                    ? device.capabilities.supported_export_formats.join(', ')
                    : NO_VALUE}
                </Field>
                <Field label="Evidence arrives via">
                  {device.adapter?.transport ?? NO_VALUE}
                </Field>
              </dl>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor={`survey-area-${device.id}`}>
                  Survey area (optional)
                </label>
                <input
                  id={`survey-area-${device.id}`}
                  data-survey-area-draft
                  type="text"
                  placeholder="Survey area (optional)"
                  value={surveyAreaDrafts[device.id] ?? ''}
                  onChange={(e) =>
                    setSurveyAreaDrafts((prev) => ({ ...prev, [device.id]: e.target.value }))
                  }
                  className="h-7 min-w-0 flex-1 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
                <label className="sr-only" htmlFor={`coordinate-system-${device.id}`}>
                  Coordinate system claim (optional)
                </label>
                <input
                  id={`coordinate-system-${device.id}`}
                  data-coordinate-system-draft
                  type="text"
                  placeholder="Coordinate system claim (optional)"
                  value={coordinateSystemDrafts[device.id] ?? ''}
                  onChange={(e) =>
                    setCoordinateSystemDrafts((prev) => ({ ...prev, [device.id]: e.target.value }))
                  }
                  className="h-7 min-w-0 flex-1 rounded-lg border border-border bg-background px-2 text-xs text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                />
                <button
                  type="button"
                  data-action="start-session"
                  disabled={busy}
                  onClick={() => startSession(device.id)}
                  className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
                >
                  New acquisition session
                </button>
              </div>
            </div>
          ))}

          {registering ? (
            <form onSubmit={register} data-device-form className="mt-4 space-y-2">
              {/*
                Stated on the form, not in a footnote: everything below is a
                claim by the person typing it.
              */}
              <p className="text-[11px] leading-relaxed text-muted-foreground">
                Everything you enter here is recorded as user-supplied. Subterra
                cannot read a serial number off an instrument, so it will not claim
                the device reported one.
              </p>
              {(['manufacturer', 'model', 'serial_number'] as const).map((name) => (
                <div key={name}>
                  <label
                    htmlFor={`device-${name}`}
                    className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
                  >
                    {name.replace('_', ' ')}
                  </label>
                  <input
                    id={`device-${name}`}
                    value={form[name]}
                    onChange={(e) => setForm({ ...form, [name]: e.target.value })}
                    className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                  />
                </div>
              ))}
              {/*
                CAPABILITY, NOT EVIDENCE. Ticking these says the instrument is
                able to report something -- never that any particular session
                did. A session that provides none of them shows the difference
                as its capability gap.
              */}
              <fieldset className="space-y-1 pt-1">
                <legend className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  What this device can report
                </legend>
                {(
                  [
                    ['reports_position', 'a position'],
                    ['reports_orientation', 'an orientation'],
                    ['reports_absolute_time', 'an absolute acquisition time'],
                  ] as const
                ).map(([name, label]) => (
                  <label
                    key={name}
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                  >
                    <input
                      id={`device-${name}`}
                      type="checkbox"
                      checked={form[name]}
                      onChange={(e) => setForm({ ...form, [name]: e.target.checked })}
                    />
                    Can report {label}
                  </label>
                ))}
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  What the instrument is capable of — not what any session actually
                  provided. Each session records that separately.
                </p>
              </fieldset>

              {/*
                THE DEVICE PROFILE. Declared facts about the instrument, same
                as everything else on this form -- not a measurement, and not
                evidence that any session actually used these settings. Every
                field stays optional: leaving one blank is undeclared, not
                zero.
              */}
              <fieldset className="space-y-2 pt-1">
                <legend className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  Device profile
                </legend>
                <div className="grid grid-cols-2 gap-2">
                  {(
                    [
                      ['frequency_mhz', 'Frequency (MHz)'],
                      ['channels', 'Channels'],
                      ['sample_interval_ns', 'Sample interval (ns)'],
                      ['samples_per_trace', 'Samples per trace'],
                    ] as const
                  ).map(([name, label]) => (
                    <div key={name}>
                      <label
                        htmlFor={`device-${name}`}
                        className="block font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground"
                      >
                        {label}
                      </label>
                      <input
                        id={`device-${name}`}
                        type="number"
                        inputMode="decimal"
                        value={form[name]}
                        onChange={(e) => setForm({ ...form, [name]: e.target.value })}
                        className="mt-1 w-full rounded-lg border border-border bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50"
                      />
                    </div>
                  ))}
                </div>

                <div>
                  <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                    Export formats
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
                    File formats this instrument can write, from the formats
                    Subterra can actually read.
                  </p>
                  <div className="mt-1.5 flex flex-wrap gap-2">
                    {importFormats?.supported.map((ext) => {
                      const checked = form.supported_export_formats.includes(ext)
                      return (
                        <label
                          key={ext}
                          className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground"
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={() =>
                              setForm({
                                ...form,
                                supported_export_formats: checked
                                  ? form.supported_export_formats.filter((f) => f !== ext)
                                  : [...form.supported_export_formats, ext],
                              })
                            }
                          />
                          {ext}
                        </label>
                      )
                    })}
                  </div>
                </div>
              </fieldset>

              {/*
                THE DEVICE ADAPTER. Declares HOW this device's evidence is
                meant to arrive -- not a connection, and not evidence that
                anything has arrived. Only file drop is offered as a real
                choice: network and serial are named below so the operator
                knows the platform recognises them, but neither is a button
                that could look like it connects to anything.
              */}
              <fieldset className="space-y-1 pt-1">
                <legend className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                  How this device&rsquo;s evidence arrives
                </legend>
                <label className="flex items-center gap-2 text-xs text-muted-foreground">
                  <input
                    id="device-file_drop"
                    type="checkbox"
                    checked={form.file_drop}
                    onChange={(e) => setForm({ ...form, file_drop: e.target.checked })}
                  />
                  Files this device writes are dropped into Import
                </label>
                <p className="text-[11px] leading-relaxed text-muted-foreground">
                  Network and serial transports are named in the platform but
                  not implemented — Subterra cannot connect to either, and
                  neither is offered as an option here.
                </p>
              </fieldset>

              <label className="flex items-center gap-2 text-xs text-muted-foreground">
                <input
                  id="device-simulated"
                  type="checkbox"
                  checked={form.simulated}
                  onChange={(e) => setForm({ ...form, simulated: e.target.checked })}
                />
                This is a simulated device, not real hardware
              </label>
              <div className="flex gap-2">
                <button
                  type="submit"
                  disabled={busy}
                  className={cn(buttonVariants({ variant: 'default', size: 'sm' }))}
                >
                  Record device
                </button>
                <button
                  type="button"
                  onClick={() => setRegistering(false)}
                  className={cn(buttonVariants({ variant: 'ghost', size: 'sm' }))}
                >
                  Cancel
                </button>
              </div>
            </form>
          ) : (
            <button
              type="button"
              data-action="register-device"
              onClick={() => setRegistering(true)}
              className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'mt-4')}
            >
              Record a device
            </button>
          )}
        </PanelBody>
      </Panel>

      {session && <SessionView payload={session} onMove={move} busy={busy} />}

      {error && (
        <p
          data-device-error
          role="alert"
          className="rounded-lg border border-destructive/40 px-3 py-2 text-xs leading-relaxed text-foreground"
        >
          {error}
        </p>
      )}
    </div>
  )
}

/** The lifecycle transitions offered from each state. Mirrors the backend's table. */
const NEXT_STATES: Record<SessionState, SessionState[]> = {
  CREATED: ['READY', 'CANCELLED'],
  READY: ['ACQUIRING', 'CANCELLED'],
  ACQUIRING: ['COMPLETED', 'CANCELLED'],
  COMPLETED: [],
  CANCELLED: [],
  FAILED: [],
}

function SessionView({
  payload,
  onMove,
  busy,
}: {
  payload: SessionPayload
  onMove: (to: SessionState) => void
  busy: boolean
}) {
  const { session, device, capability_gap: gap } = payload
  return (
    <Panel>
      <PanelHeader title="Acquisition session" />
      <PanelBody>
        <div data-session={session.id} data-session-state={session.state}>
          <dl>
            <Field label="State">{session.state}</Field>
            <Field label="Device">
              {[device?.manufacturer, device?.model].filter(Boolean).join(' ') ||
                device?.device_type ||
                NO_VALUE}
              {device?.is_simulated && (
                <span data-simulated className="ml-2 text-[11px] text-muted-foreground">
                  simulated — not real hardware
                </span>
              )}
            </Field>
            <Field label="Started">{formatDateTime(session.started_at)}</Field>
            <Field label="Ended">{formatDateTime(session.ended_at)}</Field>
          </dl>

          {/*
            The gap between what the device can produce and what this session
            actually provided. Rendered in the backend's words: a device that
            can report a position has said nothing about whether this survey
            got one.
          */}
          {gap.length > 0 && (
            <div data-capability-gap className="mt-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Not provided by this session
              </p>
              <ul className="mt-1 space-y-1">
                {gap.map((item) => (
                  <li
                    key={item}
                    data-gap
                    className="flex gap-2 text-xs leading-relaxed text-muted-foreground"
                  >
                    <span aria-hidden className="select-none text-primary">
                      &middot;
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {session.failure_stage && (
            <p data-session-failure className="mt-3 text-xs leading-relaxed text-muted-foreground">
              Failed at {session.failure_stage}: {session.failure_message}
            </p>
          )}

          {payload.acquisitions.length > 0 && (
            <div className="mt-3">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Acquisitions
              </p>
              <ul className="mt-1 space-y-1">
                {payload.acquisitions.map((a) => (
                  <li key={a.acquisition_id} data-session-acquisition className="text-xs">
                    <span className="text-foreground">{a.original_filename}</span>{' '}
                    <span className="text-muted-foreground">({a.state})</span>
                    {a.dataset_id && (
                      <>
                        {' — '}
                        <Link
                          href={`/datasets/${encodeURIComponent(a.dataset_id)}/report`}
                          className="text-primary underline-offset-4 hover:underline"
                        >
                          dataset report
                        </Link>
                      </>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {session.state === 'READY' || session.state === 'ACQUIRING' ? (
            <p className="mt-3 text-xs leading-relaxed text-muted-foreground">
              This session can receive acquisitions. Import a file from{' '}
              <Link
                href={`/import?session=${encodeURIComponent(session.id)}`}
                className="text-primary underline-offset-4 hover:underline"
              >
                Import
              </Link>{' '}
              — a session produces evidence through the same acquisition boundary a
              dropped file does, attributed to this session.
            </p>
          ) : null}

          <div className="mt-3 flex flex-wrap gap-2">
            {NEXT_STATES[session.state].map((next) => (
              <button
                key={next}
                type="button"
                data-action={`session-${next.toLowerCase()}`}
                disabled={busy}
                onClick={() => onMove(next)}
                className={cn(buttonVariants({ variant: 'outline', size: 'sm' }))}
              >
                {next === 'READY' && 'Mark ready'}
                {next === 'ACQUIRING' && 'Begin acquiring'}
                {next === 'COMPLETED' && 'Complete session'}
                {next === 'CANCELLED' && 'Cancel session'}
              </button>
            ))}
          </div>
        </div>
      </PanelBody>
    </Panel>
  )
}
