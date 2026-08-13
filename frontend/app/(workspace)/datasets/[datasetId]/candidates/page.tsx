import { CandidateIntelligenceView } from '@/components/candidates/candidate-intelligence'

export default async function DatasetCandidatesPage({
  params,
}: {
  params: Promise<{ datasetId: string }>
}) {
  const { datasetId } = await params
  return <CandidateIntelligenceView datasetId={datasetId} />
}
