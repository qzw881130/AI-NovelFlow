export interface CodePointRange {start:number;end:number}

export function sourceOwnershipRanges(shot:any):CodePointRange[] {
  const proof=shot?.source;
  const contract=proof?.sourceContract ?? shot?.sourceContract;
  if (contract?.ownership_range) return [contract.ownership_range];
  const ranges=proof?.sourceRanges ?? proof?.source_ranges ?? shot?.sourceRanges ?? shot?.source_ranges;
  if (Array.isArray(ranges) && ranges.length) return ranges;
  const start=proof?.sourceStart ?? proof?.source_start ?? shot?.sourceStart ?? shot?.source_start;
  const end=proof?.sourceEnd ?? proof?.source_end ?? shot?.sourceEnd ?? shot?.source_end;
  return Number.isFinite(start) && Number.isFinite(end) ? [{start,end}] : [];
}

export function normalizeCodePointRanges(content:string,ranges:CodePointRange[]) {
  const length=Array.from(content).length;
  return ranges.map(range=>({
    start:Math.max(0,Math.min(length,Number(range.start))),
    end:Math.max(0,Math.min(length,Number(range.end))),
  })).filter(range=>range.end>range.start).sort((a,b)=>a.start-b.start);
}

export function codePointSlice(content:string,start:number,end?:number) {
  return Array.from(content).slice(start,end).join('');
}
