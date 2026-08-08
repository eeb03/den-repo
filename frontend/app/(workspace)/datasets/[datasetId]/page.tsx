import { DatasetWorkspace } from '@/components/workspace/dataset-workspace'

export default async function DatasetWorkspacePage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <DatasetWorkspace datasetId={datasetId} />
}
