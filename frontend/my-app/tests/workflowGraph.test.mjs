import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/components/workflowGraph.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ES2020, target: ts.ScriptTarget.ES2020 } });
const { parseWorkflowGraph } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`);

test('API workflow preserves input ports, literal parameters and mapped nodes', () => {
  const workflow = {
    '1': { class_type: 'VAELoader', inputs: { vae_name: 'model.safetensors' }, _meta: { title: 'Load VAE' } },
    '2': { class_type: 'VAEDecode', inputs: { vae: ['1', 0], samples: ['missing', 0], steps: 8 } },
  };
  const before = structuredClone(workflow);
  const graph = parseWorkflowGraph(workflow, { vae_node_id: '1', scale_value: '2' });
  assert.equal(graph.nodes.length, 2);
  assert.deepEqual(graph.edges, [{ id: '1:0->2:vae', source: '1', target: '2', output: 0, input: 'vae' }]);
  assert.deepEqual(graph.nodes[0].mappingKeys, ['vae_node_id']);
  assert.deepEqual(graph.nodes[1].mappingKeys, []);
  assert.equal(graph.nodes[1].inputs.find(input => input.name === 'steps').value, 8);
  assert.equal(graph.nodes[1].inputs.find(input => input.name === 'samples').source, undefined);
  assert.deepEqual(workflow, before);
});

test('saved UI workflow reads links, widget values and original positions', () => {
  const graph = parseWorkflowGraph({
    nodes: [
      { id: 3, type: 'LoadImage', pos: [12, 34], inputs: [], widgets_values_named: { image: 'ref.png' } },
      { id: 4, type: 'PreviewImage', pos: [420, 34], inputs: [{ name: 'images', link: 9 }] },
    ],
    links: [[9, 3, 0, 4, 0, 'IMAGE']],
  });
  assert.deepEqual(graph.edges, [{ id: '3:0->4:images', source: '3', target: '4', output: 0, input: 'images' }]);
  assert.deepEqual(graph.nodes[0].position, { x: 12, y: 34 });
  assert.equal(graph.nodes[0].inputs[0].value, 'ref.png');
});

test('all mapped keyframe controllers are marked in the graph', () => {
  const workflow = {
    '116': { class_type: 'MiniMaxH3CustomKeyframes', inputs: {} },
    '151': { class_type: 'MiniMaxH3CustomKeyframes', inputs: {} },
  };
  const graph = parseWorkflowGraph(workflow, {
    custom_keyframes_node_id: '116',
    custom_keyframes_node_ids: ['116', '151'],
  });
  assert.ok(graph.nodes.find(node => node.id === '116').mappingKeys.includes('custom_keyframes_node_ids'));
  assert.ok(graph.nodes.find(node => node.id === '151').mappingKeys.includes('custom_keyframes_node_ids'));
});

test('invalid JSON returns no graph and a real stored workflow parses', async () => {
  assert.equal(parseWorkflowGraph('{bad json'), null);
  const fixture = JSON.parse(await readFile(new URL('../../../backend/tests/fixtures/h3_continuation_workflow.json', import.meta.url), 'utf8'));
  const graph = parseWorkflowGraph(fixture.workflow_json, JSON.parse(fixture.node_mapping));
  assert.ok(graph.nodes.length > 20);
  assert.ok(graph.edges.some(edge => edge.target === '55' && edge.input === 'vae' && edge.source === '30'));
  assert.ok(graph.nodes.find(node => node.id === '55').mappingKeys.includes('reference_to_video_node_id'));
});
