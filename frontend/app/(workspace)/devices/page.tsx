import { AppHeader } from '@/components/shell/app-header'
import { DevicePanel } from '@/components/devices/device-panel'

export default function DevicesPage() {
  return (
    <>
      <AppHeader
        title="Devices"
        subtitle="Instruments and acquisition sessions, recorded for provenance. Subterra does not communicate with hardware."
      />
      <div className="min-h-0 flex-1 overflow-y-auto p-5">
        <div className="mx-auto max-w-3xl">
          <DevicePanel />
        </div>
      </div>
    </>
  )
}
