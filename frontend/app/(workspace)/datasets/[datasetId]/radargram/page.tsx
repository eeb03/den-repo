import { RadargramInspector } from '@/components/radargram/radargram-inspector'

export default async function DatasetRadargramPage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <RadargramInspector datasetId={datasetId} />
}
