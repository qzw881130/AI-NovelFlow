import {readFileSync} from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import ts from 'typescript';
import {createStore} from 'zustand/vanilla';

export function pureModule(file) {
  const source=readFileSync(new URL('../../src/'+file,import.meta.url),'utf8');
  const exports={};
  vm.runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports});
  return exports;
}

export function symbol(file,name,globals={}) {
  const source=readFileSync(new URL('../../src/'+file,import.meta.url),'utf8');
  const ast=ts.createSourceFile(file,source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let expression;
  function visit(node){
    if((ts.isVariableDeclaration(node)||ts.isPropertyAssignment(node))&&node.name?.getText(ast)===name)expression=node.initializer.getText(ast);
    if(ts.isFunctionDeclaration(node)&&node.name?.getText(ast)===name)expression=node.getText(ast).replace(/^export\s+/, '');
    ts.forEachChild(node,visit);
  }
  visit(ast);assert(expression,`${name} exists`);
  return vm.runInNewContext(ts.transpileModule('const fn = '+expression,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText+'\nfn',globals);
}

export function revisionStore(initial,fetch) {
  const revision=pureModule('api/shotRevision.ts');const {shotRevisionPatch}=revision;
  const imageTaskResponse=symbol('api/shots.ts','imageTaskResponse');
  const batchUpdateShots=symbol('api/shots.ts','batchUpdateShots',{fetch,shotRevisionPatch,imageTaskResponse});
  const create=symbol('pages/ChapterGenerate/stores/slices/dataSlice.ts','createDataSlice',{
    ...revision,shotsApi:{batchUpdateShots},API_BASE:'/api',assetResolutionsApi:{},console,
  });
  return createStore((set,get)=>({...create(set,get),shotImages:{},shotVideos:{},...initial}));
}

export function savedResponse(patches) {
  return {ok:true,json:async()=>({success:true,data:{updated_count:patches.length,
    shots:patches.map(p=>({...p,sourceRevision:p.expected_revision+1,audioEvents:p.audio_events}))}})};
}
