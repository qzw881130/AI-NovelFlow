export interface WorkflowGraphInput {
  name: string;
  value: unknown;
  source?: { nodeId: string; output: number };
}

export interface WorkflowGraphNode {
  id: string;
  title: string;
  classType: string;
  inputs: WorkflowGraphInput[];
  mappingKeys: string[];
  position?: { x: number; y: number };
}

export interface WorkflowGraphEdge {
  id: string;
  source: string;
  target: string;
  output: number;
  input: string;
}

export interface WorkflowGraph {
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
}

type JsonRecord = Record<string, unknown>;

const isRecord = (value: unknown): value is JsonRecord =>
  typeof value === 'object' && value !== null && !Array.isArray(value);

const record = (value: unknown): JsonRecord => isRecord(value) ? value : {};
const stringValue = (value: unknown): string => typeof value === 'string' ? value : '';
const nodeId = (value: unknown): string => typeof value === 'string' || typeof value === 'number' ? String(value) : '';

function mappingLabels(mapping: unknown, ids: Set<string>): Map<string, string[]> {
  const labels = new Map<string, string[]>();
  for (const [key, value] of Object.entries(record(mapping))) {
    // Mapping objects also contain literal settings such as scale_value.
    if (!/node(?:_\d+)?(?:_id)?$/.test(key) && !/_node_id$/.test(key)) continue;
    const id = nodeId(value);
    if (!ids.has(id)) continue;
    labels.set(id, [...(labels.get(id) || []), key]);
  }
  return labels;
}

function parseApiWorkflow(workflow: JsonRecord, mapping: unknown): WorkflowGraph | null {
  const entries: Array<[string, JsonRecord]> = Object.entries(workflow).flatMap(([id, value]) =>
    isRecord(value) && typeof value.class_type === 'string' ? [[id, value]] : []);
  if (!entries.length) return null;

  const ids = new Set(entries.map(([id]) => id));
  const labels = mappingLabels(mapping, ids);
  const edges: WorkflowGraphEdge[] = [];
  const nodes = entries.map(([id, rawNode]) => {
    const inputs = Object.entries(record(rawNode.inputs)).map(([name, value]) => {
      const sourceId = Array.isArray(value) && value.length === 2 ? nodeId(value[0]) : '';
      const output = Array.isArray(value) ? value[1] : undefined;
      const source = ids.has(sourceId) && Number.isInteger(output) && output >= 0
        ? { nodeId: sourceId, output: output as number }
        : undefined;
      if (source) edges.push({ id: `${sourceId}:${source.output}->${id}:${name}`, source: sourceId, target: id, output: source.output, input: name });
      return { name, value, source };
    });
    const title = stringValue(record(rawNode._meta).title) || stringValue(rawNode.class_type);
    return { id, title, classType: stringValue(rawNode.class_type), inputs, mappingKeys: labels.get(id) || [] };
  });
  return { nodes, edges };
}

function parseUiWorkflow(workflow: JsonRecord, mapping: unknown): WorkflowGraph | null {
  const rawNodes = Array.isArray(workflow.nodes) ? workflow.nodes.filter(isRecord) : [];
  if (!rawNodes.length) return null;
  const ids = new Set(rawNodes.map(node => nodeId(node.id)).filter(Boolean));
  const labels = mappingLabels(mapping, ids);
  const linkById = new Map<string, { source: string; output: number }>();
  for (const link of Array.isArray(workflow.links) ? workflow.links : []) {
    if (!Array.isArray(link) || link.length < 5) continue;
    const source = nodeId(link[1]);
    if (ids.has(source) && Number.isInteger(link[2])) {
      linkById.set(nodeId(link[0]), { source, output: link[2] as number });
    }
  }

  const edges: WorkflowGraphEdge[] = [];
  const nodes = rawNodes.flatMap(rawNode => {
    const id = nodeId(rawNode.id);
    if (!id) return [];
    const inputs: WorkflowGraphInput[] = [];
    if (Array.isArray(rawNode.inputs)) {
      for (const [index, rawInput] of rawNode.inputs.entries()) {
        const slot = record(rawInput);
        const name = stringValue(slot.name) || String(index);
        const link = linkById.get(nodeId(slot.link));
        const source = link ? { nodeId: link.source, output: link.output } : undefined;
        if (source) edges.push({ id: `${source.nodeId}:${source.output}->${id}:${name}`, source: source.nodeId, target: id, output: source.output, input: name });
        inputs.push({ name, value: slot.value, source });
      }
    } else {
      for (const [name, value] of Object.entries(record(rawNode.inputs))) {
        const sourceId = Array.isArray(value) && value.length === 2 ? nodeId(value[0]) : '';
        const output = Array.isArray(value) ? value[1] : undefined;
        const source = ids.has(sourceId) && Number.isInteger(output) && output >= 0
          ? { nodeId: sourceId, output: output as number } : undefined;
        if (source) edges.push({ id: `${sourceId}:${source.output}->${id}:${name}`, source: sourceId, target: id, output: source.output, input: name });
        inputs.push({ name, value, source });
      }
    }
    for (const [name, value] of Object.entries(record(rawNode.widgets_values_named))) {
      if (!inputs.some(input => input.name === name)) inputs.push({ name, value });
    }
    if (Array.isArray(rawNode.widgets_values) && !Object.keys(record(rawNode.widgets_values_named)).length) {
      rawNode.widgets_values.forEach((value: unknown, index: number) => inputs.push({ name: `widget ${index + 1}`, value }));
    }
    const pos = rawNode.pos;
    const position = Array.isArray(pos) && pos.length >= 2 && Number.isFinite(pos[0]) && Number.isFinite(pos[1])
      ? { x: pos[0] as number, y: pos[1] as number } : undefined;
    const classType = stringValue(rawNode.class_type) || stringValue(rawNode.type);
    return [{ id, title: stringValue(rawNode.title) || classType || `Node ${id}`, classType, inputs, mappingKeys: labels.get(id) || [], position }];
  });
  return { nodes, edges };
}

export function parseWorkflowGraph(workflow: unknown, mapping?: unknown): WorkflowGraph | null {
  let value = workflow;
  if (typeof value === 'string') {
    try { value = JSON.parse(value); } catch { return null; }
  }
  if (!isRecord(value)) return null;
  return Array.isArray(value.nodes) ? parseUiWorkflow(value, mapping) : parseApiWorkflow(value, mapping);
}
