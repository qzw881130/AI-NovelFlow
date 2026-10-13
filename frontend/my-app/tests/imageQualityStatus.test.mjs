import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const { renderToStaticMarkup }=require('react-dom/server');
const React=require('react');
const compiled=await build({entryPoints:['src/pages/ChapterGenerate/components/ImageQualityStatus.tsx'],bundle:true,write:false,format:'cjs',platform:'node',external:['react','react/jsx-runtime'],jsx:'automatic',define:{'import.meta.env.VITE_API_URL':'undefined'}});
const mod={exports:{}};new Function('require','module','exports',compiled.outputFiles[0].text)(require,mod,mod.exports);
const {ImageQualityBadge,ImageQualitySummary,QUALITY_STATES}=mod.exports;
assert.deepEqual(QUALITY_STATES,['NOT_REVIEWED','PENDING','RUNNING','PASS','WARNING','REVIEW','FAIL','ERROR']);
for(const status of QUALITY_STATES){
 const markup=renderToStaticMarkup(React.createElement(ImageQualityBadge,{status}));
 assert.ok(markup.includes(`data-quality-status="${status}"`));
 assert.ok(!markup.includes('disabled'));
}
const markup=renderToStaticMarkup(React.createElement(ImageQualitySummary,{rows:[{qualityStatus:'FAIL'},{qualityStatus:'WARNING'},{qualityStatus:'NOT_REVIEWED'}],error:''}));
assert.ok(markup.includes('FAIL 1')&&markup.includes('WARNING 1')&&markup.includes('未评审 1'));
assert.ok(markup.includes('质量提醒不阻断视频生成'));
console.log('PASS: eight quality states, counts, no generation gate');
