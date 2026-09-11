import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

const source = readFileSync(new URL('../src/api/chapters.ts', import.meta.url), 'utf8');
const js = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;

function load(fetch) {
  const exports = {};
  vm.runInNewContext(js, {
    exports, fetch,
    require: () => ({ api: {}, API_BASE: '/api' }),
  });
  return exports.chapterApi;
}

test('downloads both formats as unchanged UTF-8 blobs using the chapter endpoint', async () => {
  for (const format of ['srt', 'ass']) {
    const content = '\ufeff字幕内容\n';
    const api = load(async url => {
      assert.equal(url, `/api/novels/novel%201/chapters/chapter%2F2/subtitles?format=${format}`);
      return new Response(content);
    });
    const result = await api.downloadSubtitles('novel 1', 'chapter/2', format);
    assert.deepEqual(new Uint8Array(await result.blob.arrayBuffer()), new TextEncoder().encode(content));
    assert.ok(result.filename.endsWith(`.${format}`));
  }
});

test('uses attachment filenames, preferring UTF-8 filename* over filename', async () => {
  const cases = [
    ['attachment; filename="chapter.srt"', 'chapter.srt'],
    ['attachment; filename=chapter.ass', 'chapter.ass'],
    ["attachment; filename=chapter.srt; filename*=UTF-8''%E7%AC%AC%E4%B8%80%E7%AB%A0.srt", '第一章.srt'],
    ["attachment; filename=safe.srt; filename*=UTF-8''bad%ZZ", 'safe.srt'],
    ['attachment; filename="../safe.srt"', 'safe.srt'],
    ['', 'chapter-c.srt'],
  ];
  for (const [header, filename] of cases) {
    const api = load(async () => new Response('subtitle', { headers: { 'Content-Disposition': header } }));
    assert.equal((await api.downloadSubtitles('n', 'c', 'srt')).filename, filename);
  }
});

test('surfaces backend merged-video validation errors without retrying or downloading fallback subtitles', async () => {
  for (const format of ['srt', 'ass']) {
    for (const detail of [
      '缺少章节成片，请先合并章节视频',
      '缺少成片渲染时间轴映射，请重新合并章节视频',
      '成片与音频快照元数据不匹配，请重新生成并合并章节视频',
      '仅支持 AudioDrive，旧数据不支持字幕导出',
    ]) {
      let requests = 0;
      const api = load(async url => {
        requests += 1;
        assert.equal(url, `/api/novels/n/chapters/c/subtitles?format=${format}`);
        return {
          ok: false,
          status: 409,
          json: async () => ({ detail }),
          blob: () => assert.fail('must not download an error response'),
        };
      });
      await assert.rejects(api.downloadSubtitles('n', 'c', format), { message: detail });
      assert.equal(requests, 1);
    }
  }
});

test('reports non-JSON server errors', async () => {
  const api = load(async () => new Response('Bad Gateway', { status: 502 }));
  await assert.rejects(api.downloadSubtitles('n', 'c', 'srt'), /字幕导出失败 \(502\)/);
});
