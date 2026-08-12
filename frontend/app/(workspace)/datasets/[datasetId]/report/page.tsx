import { DatasetReportView } from '@/components/report/dataset-report'

export default async function DatasetReportPage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <DatasetReportView datasetId={datasetId} />
}
