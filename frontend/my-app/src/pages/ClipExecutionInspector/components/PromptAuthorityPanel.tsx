import { useInspectorLabels } from '../labels';
import type { Projection } from '../types';
import { SourceBadge, SourceDetails } from './ClipSummary';

export default function PromptAuthorityPanel({ projection }: { projection: Projection }) {
  const l = useInspectorLabels();
  return <section data-testid="inspector-authority"><h3>{l.authority}</h3>{projection.authority_items.map(item => <details key={item.title} className="cei-authority" open={item.status === 'ABSENT'}>
    <summary>{item.title} <SourceBadge status={item.status} /></summary>
    {item.message && <p>{item.message}</p>}<small>{item.submitted_verified ? 'Submitted graph text verified' : 'Submitted connection not verified'} · {item.presence}</small>
    {item.sections.map((section, i) => <div key={i}><pre>{section.text}</pre><SourceDetails sources={[section.source]} /></div>)}
  </details>)}</section>;
}
