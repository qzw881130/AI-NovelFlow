import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import test from 'node:test';
import ts from 'typescript';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
const require=createRequire(import.meta.url);
const url=s=>`data:text/javascript;base64,${Buffer.from(s).toString('base64')}`;
async function component(name, exportName=name){
 let source=ts.transpileModule(await readFile(new URL(`../src/pages/ChapterGenerate/components/${name}.tsx`,import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ES2020,target:ts.ScriptTarget.ES2020,jsx:ts.JsxEmit.ReactJSX}}).outputText;
 source=source.replace(/from ['"]react\/jsx-runtime['"]/g,`from ${JSON.stringify(pathToFileURL(require.resolve('react/jsx-runtime')).href)}`)
 .replace(/from ['"]react['"]/g,`from ${JSON.stringify(pathToFileURL(require.resolve('react')).href)}`)
 .replace(/from ['"]\.\.\/\.\.\/\.\.\/api\/shots['"]/g,`from ${JSON.stringify(url('export const shotsApi={};'))}`);
 return (await import(url(source)))[exportName];
}
const ShotAutoGeneration=await component('ShotAutoGeneration');
const ClipPlaybackButtons=await component('ClipPlaybackButtons');
const clipPlaybackErrorMessage=await component('ClipPlaybackButtons','clipPlaybackErrorMessage');
test('missing old receipts are distinguished from invalid provenance and transient reads',()=>{
 assert.match(clipPlaybackErrorMessage('RAW_CLIP_RECEIPT_UNAVAILABLE'), /旧任务缺少/);
 assert.match(clipPlaybackErrorMessage('CLIP_PLAYBACK_RECEIPT_MISMATCH'), /不一致，已停止读取/);
 assert.match(clipPlaybackErrorMessage('RAW_CLIP_FRAME_COUNT_MISMATCH'), /帧数校验未通过/);
 assert.match(clipPlaybackErrorMessage('network failure'), /稍后重试/);
});
test('automatic entry exists even before a clip plan; rendering never starts tasks',()=>{
 const html=renderToStaticMarkup(React.createElement(ShotAutoGeneration,{novelId:'n',chapterId:'c',shotId:'s'}));
 assert.ok(html.includes('自动生成整个 Shot'));assert.ok(!html.includes('disabled='));
});
test('playback exposes independent and cumulative entry points',()=>{
 const html=renderToStaticMarkup(React.createElement(ClipPlaybackButtons,{novelId:'n',chapterId:'c',shotId:'s',clip:{clip_index:2},ready:true,onPreview(){}}));
 assert.ok(html.includes('播放本片段'));assert.ok(html.includes('播放累计视频'));
});
test('saved review provenance labels historical previews after reload while original playback takes priority',()=>{
 const props={novelId:'n',chapterId:'c',shotId:'s',clip:{clip_index:3},ready:true,onPreview(){}};
 const review=renderToStaticMarkup(React.createElement(ClipPlaybackButtons,{...props,playback:{independent_url:null,review_url:'/review.mp4'}}));
 assert.ok(review.includes('播放片段预览（累计截取）'));
 assert.ok(review.includes('不是原始单段'));
 const original=renderToStaticMarkup(React.createElement(ClipPlaybackButtons,{...props,playback:{independent_url:'/raw.mp4',review_url:'/review.mp4'}}));
 assert.ok(original.includes('播放本片段'));
 assert.ok(!original.includes('原始单段缺失'));
});
