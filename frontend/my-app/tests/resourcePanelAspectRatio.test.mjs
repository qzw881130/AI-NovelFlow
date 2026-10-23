import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

const componentUrl = new URL('../src/pages/ChapterGenerate/components/ResourcePanel.tsx', import.meta.url);
const source = await readFile(componentUrl, 'utf8');

test('shot resource thumbnails use the generated asset 17:11 ratio', () => {
  assert.match(source, /w-24 aspect-\[17\/11\]/);
  assert.doesNotMatch(source, /w-20 h-20/);
});

// Verify the rendered resource cards and the generated CSS, beyond a source regex.
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import ts from 'typescript';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';

globalThis.fetch = async () => assert.fail('Unexpected real network request');
const compiled = ts.transpileModule(source.replace(/^import[^;]+;\s*/gm, '').replace('export function', 'function')
  .replace(/^export default ResourcePanel;\s*/m, ''), {
  compilerOptions: { target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.None, jsx: ts.JsxEmit.React },
}).outputText;
const icon = () => React.createElement('svg');
const navigation = [];
const ResourcePanel = new Function('React', 'Users', 'MapPin', 'Package', 'RefreshCw', 'Eye',
  'useNavigate', 'useParams', 'useTranslation', `${compiled};return ResourcePanel;`)(
    React, icon, icon, icon, icon, icon, () => path => navigation.push(path), () => ({id:'novel'}), () => ({t:key=>key}));
const currentShot = { characters:['Alice'], scene:'Gate', props:['Hat'] };
const props = {
  currentShot, getCharacterImage: () => '/alice.png', getSceneImage: () => '/gate.png', getPropImage: () => '/hat.png',
};

function visit(element, fn) {
  if (Array.isArray(element)) return element.forEach(item => visit(item, fn));
  if (!React.isValidElement(element)) return;
  fn(element); visit(element.props.children, fn);
}

test('all rendered resource types use the 17:11 frame and preserve exact image previews', () => {
  const before = structuredClone(currentShot), previewed = [], frames = [], buttons = [];
  const tree = ResourcePanel({...props,onImageClick:url=>previewed.push(url)});
  visit(tree, element => {
    if(element.type==='div' && element.props.className?.includes('aspect-[17/11]')) frames.push(element);
    if(element.type==='button' && element.props.title==='common.viewLargeImage') buttons.push(element);
  });
  assert.equal(frames.length,3);assert.equal(buttons.length,3);
  for(const frame of frames) assert.match(frame.props.className,/w-24.*overflow-hidden.*flex-shrink-0/);
  const html = renderToStaticMarkup(tree);
  for(const url of ['/alice.png','/gate.png','/hat.png']) assert.ok(html.includes(`src="${url}"`));
  assert.equal((html.match(/object-cover/g)||[]).length,3);
  let stopped = 0;
  buttons.forEach(button => button.props.onClick({stopPropagation(){stopped++;}}));
  assert.equal(stopped,3);assert.deepEqual(previewed,['/alice.png','/gate.png','/hat.png']);
  assert.deepEqual(currentShot,before);assert.deepEqual(navigation,[]);
});

test('missing images keep bounded placeholders and empty resources render safely', () => {
  const html = renderToStaticMarkup(ResourcePanel({currentShot}));
  assert.equal((html.match(/aspect-\[17\/11\]/g)||[]).length,3);
  assert.doesNotMatch(html,/<img/);
  const empty = renderToStaticMarkup(ResourcePanel({currentShot:{}}));
  assert.match(empty,/chapterGenerate.noResourcesInShot/);assert.doesNotMatch(empty,/aspect-\[17\/11\]/);
});

test('Tailwind generates a fixed 17:11 frame and keeps cover cropping semantics', async () => {
  const {css} = await postcss([tailwindcss({content:[{raw:source,extension:'tsx'}],corePlugins:{preflight:false}})])
    .process('@tailwind utilities;',{from:undefined});
  assert.match(css,/aspect-ratio:\s*17\s*\/\s*11/);
  assert.match(css,/\.w-24\s*\{\s*width:\s*6rem/);
  assert.match(css,/\.object-cover\s*\{\s*object-fit:\s*cover/);
});
