import { useEffect, useMemo, useState } from 'react';
import { createPortal } from 'react-dom';
import ELK from 'elkjs/lib/elk.bundled.js';
import {
  Background, Controls, Handle, MarkerType, Position, ReactFlow,
  ReactFlowProvider, useReactFlow, type Edge, type Node, type NodeProps,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';
import { Maximize2, Minimize2, Search } from 'lucide-react';
import { useTranslation } from '../stores/i18nStore';
import { parseWorkflowGraph, type WorkflowGraph, type WorkflowGraphNode } from './workflowGraph';

type FlowNode = Node<{ graphNode: WorkflowGraphNode; dimmed: boolean }, 'workflow'>;

const nodeTypes = { workflow: WorkflowNodeCard };
const elk = new ELK();

function valueText(value: unknown): string {
  if (typeof value === 'string') return value;
  if (value === undefined) return '—';
  try { return JSON.stringify(value); } catch { return String(value); }
}

function WorkflowNodeCard({ data, selected }: NodeProps<FlowNode>) {
  const { graphNode, dimmed } = data;
  const previewInputs = graphNode.inputs.filter(input => !input.source).slice(0, 2);
  return (
    <div className={`w-60 overflow-hidden rounded-lg border bg-white shadow-sm transition-colors ${selected ? 'border-blue-600 ring-2 ring-blue-200' : graphNode.mappingKeys.length ? 'border-emerald-400' : 'border-slate-300'} ${dimmed ? 'opacity-30' : ''}`}>
      <Handle type="target" position={Position.Left} isConnectable={false} className="!h-2.5 !w-2.5 !border-white !bg-slate-400" />
      <div className="border-b border-slate-100 bg-slate-50 px-3 py-2">
        <div className="flex items-start gap-2">
          <span className="shrink-0 rounded bg-slate-200 px-1.5 py-0.5 font-mono text-[10px] text-slate-600">#{graphNode.id}</span>
          <span className="min-w-0 flex-1 break-words text-left text-xs font-semibold leading-4 text-slate-800" title={graphNode.title}>{graphNode.title}</span>
          {graphNode.mappingKeys.length > 0 && <span className="h-2 w-2 shrink-0 rounded-full bg-emerald-500" title={graphNode.mappingKeys.join(', ')} />}
        </div>
        <div className="mt-1 truncate text-left font-mono text-[10px] text-slate-500" title={graphNode.classType}>{graphNode.classType}</div>
      </div>
      {previewInputs.length > 0 && (
        <div className="space-y-1 px-3 py-2">
          {previewInputs.map(input => (
            <div key={input.name} className="flex gap-2 text-[10px] leading-4">
              <span className="max-w-[45%] shrink-0 truncate text-slate-500" title={input.name}>{input.name}</span>
              <span className="min-w-0 flex-1 truncate text-right font-mono text-slate-700" title={valueText(input.value)}>{valueText(input.value)}</span>
            </div>
          ))}
        </div>
      )}
      <Handle type="source" position={Position.Right} isConnectable={false} className="!h-2.5 !w-2.5 !border-white !bg-blue-500" />
    </div>
  );
}

async function layoutPositions(graph: WorkflowGraph): Promise<Record<string, { x: number; y: number }>> {
  if (graph.nodes.every(node => node.position)) {
    return Object.fromEntries(graph.nodes.map(node => [node.id, node.position!]));
  }
  const layout = await elk.layout({
    id: 'workflow',
    layoutOptions: {
      'elk.algorithm': 'layered',
      'elk.direction': 'RIGHT',
      'elk.spacing.nodeNode': '44',
      'elk.layered.spacing.nodeNodeBetweenLayers': '110',
      'elk.layered.nodePlacement.strategy': 'NETWORK_SIMPLEX',
    },
    children: graph.nodes.map(node => ({ id: node.id, width: 240, height: 105 })),
    edges: graph.edges.map(edge => ({ id: edge.id, sources: [edge.source], targets: [edge.target] })),
  });
  return Object.fromEntries((layout.children || []).map(node => [node.id, { x: node.x || 0, y: node.y || 0 }]));
}

function WorkflowGraphContent({ graph }: { graph: WorkflowGraph }) {
  const { t } = useTranslation();
  const { setCenter } = useReactFlow<FlowNode, Edge>();
  const [positions, setPositions] = useState<Record<string, { x: number; y: number }> | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [fullscreen, setFullscreen] = useState(false);

  useEffect(() => {
    if (!fullscreen) return;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
        setFullscreen(false);
      }
    };
    window.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown, true);
    };
  }, [fullscreen]);

  useEffect(() => {
    let cancelled = false;
    setPositions(null);
    setSelectedId(null);
    setQuery('');
    layoutPositions(graph).then(result => {
      if (!cancelled) setPositions(result);
    }).catch(() => {
      if (!cancelled) setPositions(Object.fromEntries(graph.nodes.map((node, index) => [node.id, { x: (index % 5) * 340, y: Math.floor(index / 5) * 160 }])));
    });
    return () => { cancelled = true; };
  }, [graph]);

  const normalizedQuery = query.trim().toLowerCase();
  const matches = useMemo(() => normalizedQuery ? graph.nodes.filter(node =>
    [node.id, node.title, node.classType, ...node.mappingKeys, ...node.inputs.map(input => input.name)]
      .some(value => value.toLowerCase().includes(normalizedQuery))) : [], [graph, normalizedQuery]);
  const matchingIds = useMemo(() => new Set(matches.map(node => node.id)), [matches]);
  const selected = graph.nodes.find(node => node.id === selectedId);
  const titleById = useMemo(() => new Map(graph.nodes.map(node => [node.id, node.title])), [graph]);

  const nodes = useMemo<FlowNode[]>(() => positions ? graph.nodes.map(node => ({
    id: node.id,
    type: 'workflow',
    position: positions[node.id] || { x: 0, y: 0 },
    data: { graphNode: node, dimmed: Boolean(normalizedQuery) && !matchingIds.has(node.id) && selectedId !== node.id },
    selected: selectedId === node.id,
  })) : [], [graph, positions, normalizedQuery, matchingIds, selectedId]);
  const edges = useMemo<Edge[]>(() => graph.edges.map(edge => {
    const related = selectedId === edge.source || selectedId === edge.target;
    return {
      id: edge.id,
      source: edge.source,
      target: edge.target,
      label: related ? edge.input : undefined,
      labelStyle: { fontSize: 10, fill: '#475569' },
      labelBgStyle: { fill: '#fff', fillOpacity: 0.9 },
      markerEnd: { type: MarkerType.ArrowClosed, color: related ? '#2563eb' : '#94a3b8' },
      style: { stroke: related ? '#2563eb' : '#94a3b8', strokeWidth: related ? 2.5 : 1.5, opacity: selectedId && !related ? 0.35 : 1 },
    };
  }), [graph, selectedId]);

  const focusNode = (id: string) => {
    setSelectedId(id);
    const position = positions?.[id];
    if (position) void setCenter(position.x + 120, position.y + 52, { zoom: 0.9, duration: 300 });
  };

  const graphView = (
    <div
      className={fullscreen
        ? 'fixed inset-0 z-[100] flex h-[100dvh] w-screen flex-col overflow-hidden bg-white'
        : 'flex h-[65vh] min-h-[420px] flex-col overflow-hidden rounded-lg border border-slate-200 bg-white'}
      role={fullscreen ? 'dialog' : undefined}
      aria-modal={fullscreen ? true : undefined}
      aria-label={fullscreen ? t('tasks.workflowGraphFullscreen') : undefined}
    >
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 px-3 py-2 text-xs text-slate-600">
        {fullscreen && <span className="font-semibold text-slate-800">{t('tasks.workflowGraph')}</span>}
        <span>{t('tasks.workflowGraphSummary', { nodes: graph.nodes.length, edges: graph.edges.length })}</span>
        <span className="inline-flex items-center gap-1"><span className="h-2 w-2 rounded-full bg-emerald-500" />{t('tasks.workflowGraphMapped')}</span>
        <div className="relative ml-auto w-full sm:w-64">
          <Search className="pointer-events-none absolute left-2.5 top-2 h-4 w-4 text-slate-400" />
          <input
            value={query}
            onChange={event => setQuery(event.target.value)}
            placeholder={t('tasks.workflowGraphSearch')}
            aria-label={t('tasks.workflowGraphSearch')}
            className="w-full rounded-md border border-slate-200 py-1.5 pl-8 pr-2 text-xs outline-none focus:border-blue-400"
          />
        </div>
        <button
          type="button"
          onClick={() => setFullscreen(value => !value)}
          aria-label={t(fullscreen ? 'tasks.workflowGraphExitFullscreen' : 'tasks.workflowGraphFullscreen')}
          title={t(fullscreen ? 'tasks.workflowGraphExitFullscreen' : 'tasks.workflowGraphFullscreen')}
          className="rounded-md border border-slate-200 p-1.5 text-slate-600 hover:border-blue-300 hover:bg-blue-50 hover:text-blue-700"
        >
          {fullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
        </button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <div className="relative min-h-[280px] min-w-0 flex-1 bg-slate-50">
          {!positions ? (
            <div className="flex h-full items-center justify-center text-sm text-slate-500">{t('tasks.workflowGraphLayout')}</div>
          ) : (
            <ReactFlow<FlowNode, Edge>
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              nodesDraggable={false}
              nodesConnectable={false}
              onNodeClick={(_, node) => setSelectedId(node.id)}
              onPaneClick={() => setSelectedId(null)}
              fitView
              fitViewOptions={{ padding: 0.15, maxZoom: 1 }}
              minZoom={0.05}
              maxZoom={2}
            >
              <Background gap={18} size={1} color="#e2e8f0" />
              <Controls showInteractive={false} />
            </ReactFlow>
          )}
        </div>
        <aside className="flex max-h-64 w-full shrink-0 flex-col overflow-y-auto border-t border-slate-200 bg-white md:max-h-none md:w-80 md:border-l md:border-t-0">
          {normalizedQuery && (
            <div className="border-b border-slate-100 p-3">
              <div className="mb-2 text-xs font-medium text-slate-600">{t('tasks.workflowGraphMatches', { count: matches.length })}</div>
              <div className="max-h-28 space-y-1 overflow-y-auto">
                {matches.map(node => (
                  <button key={node.id} type="button" onClick={() => focusNode(node.id)} className="block w-full truncate rounded px-2 py-1 text-left text-xs text-blue-700 hover:bg-blue-50" title={node.title}>#{node.id} {node.title}</button>
                ))}
              </div>
            </div>
          )}
          {selected ? (
            <div className="p-4">
              <div className="text-sm font-semibold text-slate-900">#{selected.id} {selected.title}</div>
              <div className="mt-1 break-all font-mono text-xs text-slate-500">{selected.classType}</div>
              {selected.mappingKeys.length > 0 && (
                <div className="mt-3 rounded-md bg-emerald-50 p-2 text-xs text-emerald-800">
                  <div className="font-medium">{t('tasks.workflowGraphMapped')}</div>
                  <div className="mt-1 break-all font-mono">{selected.mappingKeys.join(', ')}</div>
                </div>
              )}
              <h5 className="mb-2 mt-4 text-xs font-semibold text-slate-700">{t('tasks.workflowGraphInputs', { count: selected.inputs.length })}</h5>
              <div className="space-y-2">
                {selected.inputs.map(input => (
                  <div key={input.name} className="rounded-md border border-slate-200 p-2 text-xs">
                    <div className="break-all font-mono font-semibold text-slate-600">{input.name}</div>
                    {input.source ? (
                      <button type="button" onClick={() => focusNode(input.source!.nodeId)} className="mt-1 break-all text-left text-blue-600 hover:underline">
                        ← #{input.source.nodeId} {titleById.get(input.source.nodeId)} · {t('tasks.workflowGraphOutput', { index: input.source.output })}
                      </button>
                    ) : (
                      <pre className="mt-1 max-h-44 overflow-auto whitespace-pre-wrap break-all font-mono text-slate-800">{valueText(input.value)}</pre>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="flex flex-1 items-center justify-center p-6 text-center text-sm text-slate-500">{t('tasks.workflowGraphSelectNode')}</div>
          )}
        </aside>
      </div>
    </div>
  );
  return fullscreen ? createPortal(graphView, document.body) : graphView;
}

export default function WorkflowGraphView({ workflow, nodeMapping }: { workflow: unknown; nodeMapping?: unknown }) {
  const { t } = useTranslation();
  const graph = useMemo(() => parseWorkflowGraph(workflow, nodeMapping), [workflow, nodeMapping]);
  if (!graph) return <div className="rounded-lg border border-amber-200 bg-amber-50 p-6 text-center text-sm text-amber-800">{t('tasks.workflowGraphUnavailable')}</div>;
  return <ReactFlowProvider><WorkflowGraphContent graph={graph} /></ReactFlowProvider>;
}
