import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const backend = readFileSync(new URL('../../../backend/app/services/prompt_template_service.py', import.meta.url), 'utf8');
const styleBlock = backend.slice(backend.indexOf('SYSTEM_STYLE_TEMPLATES:'), backend.indexOf('SYSTEM_CHARACTER_PARSE_TEMPLATES:'));
const styles = [...styleBlock.matchAll(/"name": "([^"]+)",\s*"description": "([^"]+)"/g)]
  .map(([, name, description]) => ({ name, description }));

function load(file, imports = {}) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8');
  const exports = {};
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, require: name => imports[name] ?? require(name) });
  return exports;
}

const zhCN = load('../src/i18n/locales/zh-CN/settings.ts').default;
const enUS = load('../src/i18n/locales/en-US/settings.ts').default;
const dictionaries = {
  'zh-CN': zhCN,
  'zh-TW': load('../src/i18n/locales/zh-TW/settings.ts', { '../zh-CN/settings': { default: zhCN } }).default,
  'en-US': enUS,
  'ja-JP': load('../src/i18n/locales/ja-JP/settings.ts', { '../en-US/settings': { default: enUS } }).default,
  'ko-KR': load('../src/i18n/locales/ko-KR/settings.ts', { '../en-US/settings': { default: enUS } }).default,
};

test('all five locales cover the twelve builtin names and optimized descriptions', () => {
  assert.equal(styles.length, 12);
  assert.equal(new Set(styles.map(style => style.name)).size, 12);
  for (const [locale, dictionary] of Object.entries(dictionaries)) {
    const config = dictionary.promptConfig;
    assert.equal(new Set(styles.map(style => config.templateNames[style.name])).size, 12, locale);
    for (const style of styles) {
      assert.ok(config.templateNames[style.name], `${locale}: ${style.name}`);
      assert.ok(config.templateDescriptions[style.name]?.length > 20, `${locale}: ${style.name}`);
      if (locale === 'zh-CN') assert.equal(config.templateDescriptions[style.name], style.description);
    }
    for (const key of ['placeholderTipStyle', 'tipStyle', 'templatePlaceholderStyle']) {
      assert.ok(config[key], `${locale}: ${key}`);
      assert.doesNotMatch(config[key], /\{\w+\}|##STYLE##/);
    }
    assert.ok(config.types.styleDesc.includes(config.systemDefault), locale);
  }
  assert.equal(zhCN.promptConfig.systemDefault, '\u7cfb\u7edf\u9ed8\u8ba4');
});

for (const [locale, dictionary] of Object.entries(dictionaries)) {
  const requestedKeys = [];
  const t = key => {
    requestedKeys.push(key);
    return key.split('.').reduce((value, part) => value?.[part], dictionary) ?? key;
  };
  const imports = { '../../../stores/i18nStore': { useTranslation: () => ({ t }) } };
  const { EditModal } = load('../src/pages/PromptConfig/components/EditModal.tsx', imports);
  const { TemplateCard } = load('../src/pages/PromptConfig/components/TemplateCard.tsx', imports);
  const form = { name: 'My style', description: 'Rendering only', template: 'watercolor, transparent washes' };

  test(`${locale}: style editor shows raw rendering guidance instead of chapter variables`, () => {
    requestedKeys.length = 0;
    const html = renderToStaticMarkup(createElement(EditModal, {
      show: true, modalType: 'style', editingPrompt: null, form,
      setForm: () => {}, onClose: () => {}, onSave: () => {}, saving: false,
    }));
    for (const key of ['placeholderTipStyle', 'tipStyle', 'templatePlaceholderStyle']) {
      assert.ok(requestedKeys.includes(`promptConfig.${key}`));
    }
    for (const key of ['placeholderTipChapter', 'templatePlaceholderChapter', 'tipChapter', 'jsonStructureWarning']) {
      assert.ok(!requestedKeys.includes(`promptConfig.${key}`));
    }
    assert.ok(html.includes(form.template));
    assert.doesNotMatch(html, /\{wordCount\}|\{style\}|readonly=""/);
    assert.match(html, /type="submit"/);
  });

  test(`${locale}: builtin badge and read-only controls still reflect isSystem, not selection`, () => {
    for (const isSystem of [true, false]) {
      const template = { id: 'style-id', ...form, name: styles[0].name, type: 'style', isSystem, isActive: true };
      requestedKeys.length = 0;
      renderToStaticMarkup(createElement(TemplateCard, {
        template, type: 'style', onView: () => {}, onEdit: () => {}, onCopy: () => {}, onDelete: () => {},
        getDisplayName: item => isSystem ? dictionary.promptConfig.templateNames[item.name] : item.name,
        getDisplayDescription: item => isSystem ? dictionary.promptConfig.templateDescriptions[item.name] : item.description,
      }));
      assert.ok(requestedKeys.includes(`promptConfig.${isSystem ? 'systemDefault' : 'userCustom'}`));
      assert.equal(requestedKeys.includes('promptConfig.copyAsUser'), isSystem);
      assert.equal(requestedKeys.includes('common.edit'), !isSystem);
      assert.equal(requestedKeys.includes('common.delete'), !isSystem);
      const editor = renderToStaticMarkup(createElement(EditModal, {
        show: true, modalType: 'style', editingPrompt: template, form,
        setForm: () => {}, onClose: () => {}, onSave: () => {}, saving: false,
      }));
      assert.equal(editor.includes('readonly=""'), isSystem);
      assert.equal(editor.includes('type="submit"'), !isSystem);
    }
  });
}
