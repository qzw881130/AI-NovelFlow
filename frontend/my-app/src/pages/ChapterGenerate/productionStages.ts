export const STAGE={SPLIT:0,ASSETS:1,IMAGE:2,AUDIO:3,VIDEO:4} as const;
export const WORKFLOW_STATE_VERSION=2;

export function restoreProductionStages(value:unknown) {
  const raw=value&&typeof value==='object'?value as Record<string,unknown>:{};
  const current=Number.isInteger(raw.currentTab)?Number(raw.currentTab):0;
  const modern=raw.version===WORKFLOW_STATE_VERSION;
  const translate=(index:number)=>modern?index:index===0?0:index+1;
  const max=modern?4:3;
  const progress:Record<number,boolean>={};
  if(raw.tabProgress&&typeof raw.tabProgress==='object')for(const [key,flag] of Object.entries(raw.tabProgress)) {
    const index=Number(key);if(Number.isInteger(index)&&index>=0&&index<=max)progress[translate(index)]=flag===true;
  }
  delete progress[STAGE.ASSETS]; // Asset readiness always comes from a fresh backend check.
  return {currentTab:current>=0&&current<=max?translate(current):0,tabProgress:progress};
}
