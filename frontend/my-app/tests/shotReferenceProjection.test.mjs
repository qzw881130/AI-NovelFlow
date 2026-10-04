import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from 'typescript';

const source = await readFile(new URL('../src/pages/ChapterGenerate/shotReferenceProjection.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { projectShotReferenceImages } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('merged task snapshots remain intact and expand only to bound supplemental resources', () => {
  const images = projectShotReferenceImages(
    [
      { label: '角色合并图', url: '/api/files/merged_characters/one.png' },
      { label: '场景图', url: '/api/files/scenes/gate.png' },
      { label: '道具合并图: 合并道具图', url: '/api/files/merged_props/one.png' },
    ],
    { characters: ['卫兵1', '骗子1'], props: ['宽边礼帽', '骗子木箱'] },
    [
      { name: '卫兵1', imageUrl: '/api/files/characters/guard.png' },
      { name: '骗子1', imageUrl: '/api/files/characters/trickster.png' },
      { name: '无关角色', imageUrl: '/api/files/characters/other.png' },
    ],
    [
      { name: '宽边礼帽', imageUrl: '/api/files/props/hat.png', existence: 'REAL' },
      { name: '骗子木箱', imageUrl: '/api/files/props/box.png', existence: 'REAL' },
      { name: '无关道具', imageUrl: '/api/files/props/other.png', existence: 'REAL' },
    ],
  );
  assert.deepEqual(images.map(({ label, url }) => [label, url]), [
    ['角色合并图', '/api/files/merged_characters/one.png'],
    ['角色：卫兵1', '/api/files/characters/guard.png'],
    ['角色：骗子1', '/api/files/characters/trickster.png'],
    ['场景图', '/api/files/scenes/gate.png'],
    ['道具合并图: 合并道具图', '/api/files/merged_props/one.png'],
    ['道具：宽边礼帽', '/api/files/props/hat.png'],
    ['道具：骗子木箱', '/api/files/props/box.png'],
  ]);
  assert.equal(images.filter(({ source }) => source === 'task').length, 3);
  assert.equal(images.filter(({ source }) => source === 'current_resource').length, 4);
});

test('direct references remain task snapshots and missing resources do not produce broken thumbnails', () => {
  const images = projectShotReferenceImages(
    [{ label: '角色合并图', url: '/merged_characters/one.png' }, { label: '场景图', url: '/scene.png' }],
    { characters: ['无图角色'], props: [] },
    [{ name: '无图角色', imageUrl: null }],
    [],
  );
  assert.deepEqual(images, [{ label: '角色合并图', url: '/merged_characters/one.png', source: 'task' }, { label: '场景图', url: '/scene.png', source: 'task' }]);
});


test('zero references and historical/malformed task data remain readable', () => {
  for (const input of [[], null, undefined]) assert.deepEqual(projectShotReferenceImages(input, undefined, [], []), []);
  assert.deepEqual(projectShotReferenceImages([null, {url:null}, {url:4}, {label:42,url:'/one.png'}], {}, [], []),
    [{label:'参考图',url:'/one.png',source:'task'}]);
});

test('projection preserves the task reference sequence without manufacturing authority', () => {
  const refs=[{label:'KF8',url:'/eight.png'},{label:'Picture 2',url:'/two.png'}, {label:'KF8',url:'/eight.png'}];
  const before=structuredClone(refs);
  const output=projectShotReferenceImages(refs,{characters:[],props:[]},[],[]);
  assert.deepEqual(output.map(({label,url})=>({label,url})),refs);
  for(const image of output) for(const field of ['picture','kind','required','capability','state_index','selected_temporal_target_ids'])
    assert.equal(field in image,false);
  assert.deepEqual(refs,before);
});

test('current fictional/unbound props are not supplemental resources and never erase history', () => {
  const refs=[{label:'道具合并图',url:'/merged_props/one.png'}];
  const out=projectShotReferenceImages(refs,{props:'["real","fiction"]'},[],[
    {name:'real',image_url:'/real.png'}, {name:'fiction',imageUrl:'/fiction.png',existence:'FICTIONAL_OR_NONEXISTENT'},
    {name:'other',imageUrl:'/other.png'}]);
  assert.deepEqual(out,[{label:'道具合并图',url:'/merged_props/one.png',source:'task'},
    {label:'道具：real',url:'/real.png',source:'current_resource'}]);
});
