import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

function load(relative) {
  const source=readFileSync(new URL(`../src/${relative}`,import.meta.url),'utf8');
  const exports={};
  vm.runInNewContext(ts.transpileModule(source,{
    compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022},
  }).outputText,{exports,require:()=>({})});
  return exports;
}

const ownership=load('utils/sourceOwnership.ts');
const revisions=load('api/shotRevision.ts');
const plain=value=>JSON.parse(JSON.stringify(value));

test('server code-point ownership includes a leading emoji without UTF-16 drift',()=>{
  const content='🐺刘备在桃园站定。';
  assert.equal(Array.from(content).length,9);
  assert.equal(ownership.codePointSlice(content,0,9),'🐺刘备在桃园站定。');
  assert.equal(ownership.codePointSlice(content,6,9),'站定。');
  assert.deepEqual(plain(ownership.normalizeCodePointRanges(content,[{start:0,end:9}])),[{start:0,end:9}]);
});

test('highlighting prefers signed ownership and retains a zero-start legacy fallback',()=>{
  const contract={ownership_range:{start:0,end:9,text:'🐺刘备在桃园站定。'}};
  assert.deepEqual(plain(ownership.sourceOwnershipRanges({source:{sourceContract:contract,sourceRanges:[{start:1,end:2}]}})),
    [{start:0,end:9,text:'🐺刘备在桃园站定。'}]);
  assert.deepEqual(plain(ownership.sourceOwnershipRanges({sourceStart:0,sourceEnd:9})),[{start:0,end:9}]);
});

test('revision projection rejects provenance instead of silently dropping it',()=>{
  const base={id:'shot',sourceRevision:0,description:'accepted'};
  assert.deepEqual(plain(revisions.shotRevisionPatch(base)),{id:'shot',expected_revision:0,description:'accepted'});
  for (const field of ['sourceContract','source_citations','sourceOwnership','source_evidence','source_ranges',
    'citation_evidence','citationRanges','ownership_evidence','ownershipRange','sourceStart','source_run_id',
    'sourceRunId','runId','evidence','ranges','bindings','offsetUnit','sourceSeal']) {
    assert.throws(()=>revisions.shotRevisionPatch({...base,[field]:{tampered:true}}),/SHOT_REVISION_PROTECTED_FIELD/);
  }
});

test('product split and source panel declare ownership v2 explicitly',()=>{
  const action=readFileSync(new URL('../src/pages/ChapterGenerate/stores/slices/chapterActionsSlice.ts',import.meta.url),'utf8');
  const panel=readFileSync(new URL('../src/pages/ChapterGenerate/components/ShotSourcePanel.tsx',import.meta.url),'utf8');
  assert.match(action,/sourceContractVersion=chapter-shot-ownership-v2/);
  assert.match(panel,/连续归属/);
  assert.match(panel,/引用证据/);
});
