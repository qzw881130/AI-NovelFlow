import { useInspectorLabels } from '../labels';
import { seconds } from '../presentation';
import type { ArtifactList, Projection } from '../types';

export function ExecutionResultOptions({ executions, selectedTaskId }: {
  executions: ArtifactList['artifacts']; selectedTaskId: string;
}) {
  return <>{!executions.some(e => e.task_id === selectedTaskId) && <option value={selectedTaskId}>Exec {selectedTaskId}</option>}
    {executions.map(e => <option value={e.task_id} key={e.task_id} title={`${e.task_id} · created ${e.created_at}`}>
      Rev {e.clip_plan_revision ?? '—'} · Exec {e.task_id.slice(0, 8)} · {e.status}
    </option>)}</>;
}

export function VideoSource({ taskId, videoSha, surface }: {
  taskId: string; videoSha: string | null; surface: string;
}) {
  return <p className="cei-video-source" data-testid={`${surface}-source`}>Source: Exec <code title={taskId}>{taskId.slice(0, 8)}</code>
    {' · '}Video SHA <code title={videoSha || undefined}>{videoSha ? `${videoSha.slice(0, 12)}…` : '—'}</code>
  </p>;
}

export default function ExecutionIdentity({ projection: p }: { projection: Projection }) {
  const l = useInspectorLabels();
  return <div className="cei-execution-identity" data-testid="execution-identity">
    <h3>Execution Identity</h3>
    <dl className="cei-identity-grid">
      <div><dt title={l.revisionMeaning}>Revision</dt><dd>{p.clip_ref.clip_plan_revision ?? '—'}</dd></div>
      <div><dt>Execution</dt><dd><code title={p.execution.task_id}>{p.execution.task_id.slice(0, 8)}</code></dd></div>
      <div><dt>Status</dt><dd>{p.execution.status}</dd></div>
      <div><dt>Operation</dt><dd>{p.artifact.capability}</dd></div>
      <div><dt>Video</dt><dd>{p.media.frame_count ?? '—'} frames · {p.media.fps ?? '—'} fps · {seconds(p.media.video_duration)}</dd></div>
      <div><dt>Video SHA</dt><dd><code title={p.artifact.video_sha256 || undefined}>{p.artifact.video_sha256 ? `${p.artifact.video_sha256.slice(0, 12)}…` : '—'}</code></dd></div>
    </dl>
    <p className="cei-identity-help">{l.executionMeaning}</p>
  </div>;
}
