import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

// Execute the real component handlers without React mounting or network I/O.
function loadHandler(file, name, globals) {
  const source = readFileSync(new URL(`../src/pages/ChapterGenerate/components/${file}`, import.meta.url), 'utf8');
  const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let initializer;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(ast) === name) initializer = node.initializer.getText(ast);
    ts.forEachChild(node, visit);
  }
  visit(ast);
  assert.ok(initializer, `${name} exists`);
  const js = ts.transpileModule(`const handler = ${initializer};`, {
    compilerOptions: { target: ts.ScriptTarget.ES2022 },
  }).outputText;
  return vm.runInNewContext(js + '\nhandler', globals);
}

function readyEvent(id, order, overrides = {}) {
  return Object.freeze({
    id, shotId: 'shot-id', order, type: 'DIALOGUE',
    voiceOwnerCharacterId: 'wolf-voice-id', voiceOwnerName: 'Wolf',
    visibleSpeakerCharacterId: 'wolf-speaker-id', visibleSpeakerName: 'Wolf',
    requiresVisibleLipsync: true, text: 'Stay with the pack.',
    emotionPrompt: 'Quiet', pauseAfter: 'SHORT', ttsStatus: 'READY',
    currentTtsAsset: Object.freeze({
      id: `tts-${id}`, audioEventId: id, audioUrl: `/audio/${id}.wav`,
      durationSeconds: 2.5, revision: 1, status: 'READY',
    }),
    ...overrides,
  });
}

test('adding narration after an existing order 1 yields [1, 2] and preserves READY dialogue', () => {
  const existing = readyEvent('dialogue-id', 1);
  let next;
  const add = loadHandler('ShotForm.tsx', 'addAudioEvent', {
    audioEvents: Object.freeze([existing]), shotData: { id: 'shot-id' },
    setAudioEvents: value => { next = value; },
  });
  add('NARRATION');
  assert.deepEqual(Array.from(next, event => event.order), [1, 2]);
  assert.equal(next[0], existing);
  assert.match(next[1].id, /^local-/);
  assert.equal(next[1].shotId, existing.shotId);
  assert.equal(next[1].type, 'NARRATION');
  assert.equal(next[1].voiceOwnerName, '\u65c1\u767d');
  assert.equal(next[1].visibleSpeakerName, null);
  assert.equal(next[1].requiresVisibleLipsync, false);
  assert.equal(next[1].text, '');
  assert.equal(next[1].ttsStatus, 'NOT_GENERATED');
});

test('deleting first, middle, or last event reindexes from 1 without changing survivors', () => {
  const events = Object.freeze([readyEvent('first', 1), readyEvent('middle', 2), readyEvent('last', 3)]);
  for (const index of [0, 1, 2]) {
    let next;
    const remove = loadHandler('ShotForm.tsx', 'removeAudioEvent', {
      audioEvents: events, setAudioEvents: value => { next = value; },
    });
    remove(index);
    assert.deepEqual(JSON.parse(JSON.stringify(next)), events
      .filter((_, i) => i !== index)
      .map((event, i) => ({ ...event, order: i + 1 })));
  }
});

test('saving legacy [1, 1] serializes UI order and retains IDs, text, owners, and READY assets', async () => {
  const events = Object.freeze([
    readyEvent('z-dialogue-id', 1),
    readyEvent('a-narration-id', 1, {
      type: 'NARRATION', voiceOwnerCharacterId: 'narrator-id', voiceOwnerName: '\u65c1\u767d',
      visibleSpeakerCharacterId: null, visibleSpeakerName: null, requiresVisibleLipsync: false,
      text: 'The wolves disappeared into the forest.', emotionPrompt: 'Calm', pauseAfter: 'NONE',
    }),
  ]);
  let request;
  const saving = [], completed = [], messages = [];
  const save = loadHandler('ShotSplitTab.tsx', 'saveShotsData', {
    novelId: 'novel-id', chapterId: 'chapter-id', t: key => key,
    setIsSaving: value => saving.push(value), saveChapterResources: async () => {},
    shotsApi: { batchUpdateShots: async (novelId, chapterId, shots) => {
      request = JSON.parse(JSON.stringify({ novelId, chapterId, shots }));
      return { success: true, data: { updated_count: shots.length } };
    } },
    markTabComplete: tab => completed.push(tab),
    toast: { success: message => messages.push(message), error: message => messages.push(message) },
    console: { log() {}, error() {} },
  });
  await save([{ id: 'shot-id', duration: 5, audioEvents: events }, { id: 'empty-shot-id', duration: 5 }]);
  assert.equal(request.novelId, 'novel-id');
  assert.equal(request.chapterId, 'chapter-id');
  assert.equal(request.shots[0].id, 'shot-id');
  assert.deepEqual(request.shots[0].audio_events, events.map((event, i) => ({ ...event, order: i + 1 })));
  assert.deepEqual(request.shots[1].audio_events, []);
  assert.deepEqual(events.map(event => event.order), [1, 1]);
  assert.deepEqual(saving, [true, false]);
  assert.deepEqual(completed, [0]);
  assert.deepEqual(messages, ['chapterGenerate.shotSaveSuccess']);
});

test('layout save used by the visible editor button and shortcut preserves contiguous 1-based audio order', async () => {
  const events = Object.freeze([readyEvent('first', 1), readyEvent('second', 1), readyEvent('third', 9)]);
  const shot = Object.freeze({ id: 'shot-id', duration: 10, estimatedDuration: 8, audioEvents: events });
  let request;
  const saving = [];
  const save = loadHandler('ChapterGenerateLayout.tsx', 'saveShotSplitData', {
    id: 'n', cid: 'c', isSavingShots: false, shots: [shot], t: key => key,
    setIsSavingShots: value => saving.push(value), saveChapterResources: async () => {},
    shotsApi: { batchUpdateShots: async (_n, _c, shots) => { request = shots; return { success: true }; } },
    markTabComplete() {}, toast: { success() {}, error: assert.fail }, console,
  });
  await save();
  assert.deepEqual(JSON.parse(JSON.stringify(request[0].audio_events)), events.map((event, i) => ({ ...event, order: i + 1 })));
  assert.equal(request[0].duration, 10);
  assert.equal(request[0].estimated_duration, 8);
  assert.deepEqual(events.map(event => event.order), [1, 1, 9]);
  assert.deepEqual(saving, [true, false]);
});
