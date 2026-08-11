import { SpatialReferenceView } from '@/components/spatial/spatial-reference'

export default async function SpatialReferencePage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <SpatialReferenceView datasetId={datasetId} />
}
