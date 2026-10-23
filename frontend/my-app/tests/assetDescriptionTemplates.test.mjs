import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';
import ts from '../node_modules/typescript/lib/typescript.js';

const source = async path => readFile(new URL(`../src/${path}`, import.meta.url), 'utf8');
const hook = await source('pages/LLMLogs/hooks/useLLMLogsState.ts');
const configHook = await source('pages/PromptConfig/hooks/usePromptConfigState.ts');
const config = await source('pages/PromptConfig/index.tsx');
const types = await source('pages/PromptConfig/types.ts');
const modal = await source('pages/PromptConfig/components/EditModal.tsx');

async function loadModule(text) {
  const js = ts.transpileModule(text, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText;
  return import(`data:text/javascript;base64,${Buffer.from(js).toString('base64')}`);
}

async function loadLocale(locale, domain) {
  let text = await source(`i18n/locales/${locale}/${domain}.ts`);
  const inherited = text.match(/import (\w+) from '\.\.\/(zh-CN|en-US)\/(\w+)';/);
  if (inherited) {
    const { default: base } = await loadLocale(inherited[2], inherited[3]);
    text = text.replace(inherited[0], `const ${inherited[1]} = ${JSON.stringify(base)};`);
  }
  return loadModule(text);
}

function initializer(text, name) {
  const tree = ts.createSourceFile('source.tsx', text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  let found;
  function visit(node) {
    if (ts.isVariableDeclaration(node) && node.name.getText(tree) === name) found = node.initializer.getText(tree);
    ts.forEachChild(node, visit);
  }
  visit(tree);
  assert.ok(found, name);
  return found;
}

test('text templates have separate tabs in asset generation without replacing image types', async () => {
  const { categories } = await loadModule(`export const categories = ${initializer(config, 'CATEGORY_CONFIG')};`);
  assert.deepEqual(categories.asset_generation.types, ['character', 'scene', 'prop', 'scene_setting', 'prop_appearance']);
  for (const kind of ['scene_setting', 'prop_appearance']) {
    assert.ok(types.includes(`| '${kind}'`));
    assert.ok(configHook.includes(`'${kind}',`));
    assert.ok(configHook.includes(`${kind}: []`));
    assert.ok(configHook.includes(`${kind}: true`));
  }
  assert.match(modal, /!isAssetDescription && <span/);
  assert.match(modal, /isAssetDescription \? t\(assetDescriptionKey\)/);
});

test('both historical task IDs participate in asset-generation filtering', async () => {
  const { categories } = await loadModule(`export const categories = ${initializer(hook, 'TASK_CATEGORY_TYPES')};`);
  assert.ok(categories.asset_generation.includes('generate_scene_setting'));
  assert.ok(categories.asset_generation.includes('generate_prop_appearance'));
  assert.ok(categories.asset_generation.includes('generate_character_appearance'));
});

for (const locale of ['zh-CN', 'zh-TW', 'en-US', 'ja-JP', 'ko-KR']) {
  test(`${locale}: template tabs, names, descriptions and log labels are translated`, async () => {
    const { default: settings } = await loadLocale(locale, 'settings');
    const { default: logs } = await loadLocale(locale, 'logs');
    const translations = { ...settings, ...logs };
    const t = key => key.split('.').reduce((value, part) => value?.[part], translations) ?? key;
    const module = await loadModule(`
      export function labels(t) {
        const name = ${initializer(hook, 'getTaskTypeNameLabel')};
        const category = ${initializer(hook, 'getTaskTypeCategoryLabel')};
        return { name, category };
      }
    `);
    const labels = module.labels(t);
    for (const [task, key, templateName] of [
      ['generate_scene_setting', 'sceneSetting', '场景设定描述'],
      ['generate_prop_appearance', 'propAppearance', '道具外观描述'],
    ]) {
      assert.equal(labels.category(task), t('promptConfig.categories.assetGeneration'));
      assert.notEqual(labels.name(task), task);
      for (const path of [
        `promptConfig.types.${key}`, `promptConfig.types.${key}Desc`,
        `promptConfig.templateNames.${templateName}`, `promptConfig.templateDescriptions.${templateName}`,
      ]) {
        assert.notEqual(t(path), path);
        assert.ok(t(path).length > 0);
      }
    }
  });
}
