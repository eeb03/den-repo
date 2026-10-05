import { VolumeViewer } from '@/components/volume/volume-viewer'

export default async function DatasetVolumePage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <VolumeViewer datasetId={datasetId} />
}
