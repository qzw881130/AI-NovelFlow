import {createRequire} from 'node:module';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import test from 'node:test';
import {revisionStore,savedResponse} from './helpers/revision-harness.mjs';
const require=createRequire(import.meta.url);
const ts=require('typescript');
function handler(file,name,globals){
  const source=readFileSync(new URL('../src/'+file,import.meta.url),'utf8');
  const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let expression;
  function visit(node){
    if((ts.isVariableDeclaration(node)||ts.isPropertyAssignment(node))&&node.name?.getText(ast)===name)expression=node.initializer.getText(ast);
    ts.forEachChild(node,visit);
  }
  visit(ast);assert(expression,`${name} must exist`);
  return vm.runInNewContext(ts.transpileModule('const fn = '+expression,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText+'\nfn',globals);
}

test('F45: visible editor save uses real revision action/API projection and recovers the response',async()=>{
  const requests=[],errors=[];
  const globals={get:()=>({parsedData:{characters:[],scenes:[],props:[]}}),set(){},API_BASE:'/api',
    fetch:async()=>({ok:true,json:async()=>({success:true})}),console:{log(){},error(){}}};
  const saveResources=handler('pages/ChapterGenerate/stores/slices/dataSlice.ts','saveChapterResources',globals);
  const shots=[{id:'shot',sourceRevision:0,duration:5,audioEvents:[]}];
  const store=revisionStore({chapter:{id:'chapter',novelId:'book'},shots},async(url,options)=>{
    const body=JSON.parse(options.body);requests.push({url,body});return savedResponse(body.shots);
  });
  const save=handler('pages/ChapterGenerate/components/ChapterGenerateLayout.tsx','saveShotSplitData',{
    ...globals,id:'book',cid:'chapter',isSavingShots:false,shots,t:key=>key,
    setIsSavingShots(){},saveChapterResources:saveResources,useChapterGenerateStore:store,
    setShots(){},fetchShots:async()=>{},markTabComplete(){},toast:{success(){},error:m=>errors.push(m)},
  });
  await save();assert.equal(requests.length,1);assert.deepEqual(errors,[]);
  assert.equal(requests[0].url,'/api/novels/book/chapters/chapter/shots/batch');
  assert.equal(requests[0].body.shots[0].expected_revision,0);
  assert.equal(store.getState().shots[0].sourceRevision,1);
});
