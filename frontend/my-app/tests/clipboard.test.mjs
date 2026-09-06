import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import ts from 'typescript';

function load(path, globals) {
  const exports = {};
  const source = readFileSync(new URL(path, import.meta.url), 'utf8');
  vm.runInNewContext(ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX },
  }).outputText, { exports, ...globals });
  return exports;
}

function fixture({ clipboard, result = true, throws = false, input = true } = {}) {
  let copies = 0;
  const children = [];
  class Element {
    focus(options) {
      assert.equal(options.preventScroll, true);
      document.activeElement = this;
    }
  }
  class Input extends Element {
    selectionStart = 2;
    selectionEnd = 5;
    selectionDirection = 'backward';
    setSelectionRange(start, end, direction) {
      this.selectionStart = start;
      this.selectionEnd = end;
      this.selectionDirection = direction;
    }
  }
  class Textarea extends Input {
    style = {};
    select() { selection.ranges = []; }
    remove() { children.splice(children.indexOf(this), 1); }
  }
  const range = { cloneRange() { return this; } };
  const selection = {
    ranges: [range],
    get rangeCount() { return this.ranges.length; },
    getRangeAt(index) { return this.ranges[index]; },
    removeAllRanges() { this.ranges = []; },
    addRange(value) { this.ranges.push(value); },
  };
  const original = input ? new Input() : new Element();
  const document = {
    activeElement: original,
    getSelection: () => selection,
    createElement(tag) { assert.equal(tag, 'textarea'); return new Textarea(); },
    body: { appendChild(node) { children.push(node); } },
    execCommand(command) {
      copies++;
      assert.equal(command, 'copy');
      assert.equal(children[0].value, 'task-full-id');
      assert.equal(document.activeElement, children[0]);
      assert.equal(children[0].selectionStart, 0);
      assert.equal(children[0].selectionEnd, 12);
      if (throws) throw new Error('Denied');
      return result;
    },
  };
  const { copyToClipboard } = load('../src/utils/clipboard.ts', {
    navigator: { clipboard }, document,
    HTMLElement: Element, HTMLInputElement: Input, HTMLTextAreaElement: Textarea,
  });
  return {
    copyToClipboard, document,
    get copies() { return copies; },
    restored() {
      assert.equal(children.length, 0);
      assert.equal(document.activeElement, original);
      assert.deepEqual(selection.ranges, [range]);
      if (input) {
        assert.equal(original.selectionStart, 2);
        assert.equal(original.selectionEnd, 5);
        assert.equal(original.selectionDirection, 'backward');
      }
    },
  };
}

test('modern clipboard succeeds without touching DOM and retains its receiver', async () => {
  const clipboard = { async writeText(text) {
    assert.equal(this, clipboard);
    assert.equal(text, 'task-full-id');
  } };
  const f = fixture({ clipboard });
  await f.copyToClipboard('task-full-id');
  assert.equal(f.copies, 0);
  f.restored();
});

test('HTTP fallback runs before returning, preserving input and document selection', async () => {
  for (const clipboard of [undefined, {}]) {
    const f = fixture({ clipboard });
    const pending = f.copyToClipboard('task-full-id');
    assert.equal(f.copies, 1);
    f.restored();
    await pending;
  }
});

test('denied async writes and synchronous API errors fall back', async () => {
  for (const writeText of [() => Promise.reject(new Error('Denied')), () => { throw new Error('Denied'); }]) {
    const f = fixture({ clipboard: { writeText }, input: false });
    await f.copyToClipboard('task-full-id');
    assert.equal(f.copies, 1);
    f.restored();
  }
});

test('false, throwing and missing execCommand reject and always clean up', async () => {
  for (const options of [{ result: false }, { throws: true }, { missing: true }]) {
    const f = fixture(options);
    if (options.missing) delete f.document.execCommand;
    await assert.rejects(f.copyToClipboard('task-full-id'));
    f.restored();
  }
});

test('TaskCard copy button has an accessible name and reports success or failure', async () => {
  for (const fail of [false, true]) {
    const messages = [];
    const copied = [];
    const jsx = (type, props) => ({ type, props });
    const { TaskCard } = load('../src/pages/Tasks/components/TaskCard.tsx', {
      require(name) {
        if (name === 'react/jsx-runtime') return { jsx, jsxs: jsx };
        if (name === 'lucide-react') return {};
        if (name.endsWith('/i18nStore')) return { useTranslation: () => ({ t: key => key }) };
        if (name.endsWith('/toastStore')) return { toast: {
          success: message => messages.push(['success', message]),
          error: message => messages.push(['error', message]),
        } };
        if (name.endsWith('/utils/clipboard')) return { copyToClipboard: async text => {
          copied.push(text);
          if (fail) throw new Error('Denied');
        } };
        if (name.endsWith('/utils')) return { formatUserFacingError: () => '' };
        throw new Error(`Unexpected import: ${name}`);
      },
    });
    const tree = TaskCard({
      task: { id: 'task-full-id', status: 'pending', type: 'shot_video' },
      getTaskDisplayName: () => '', getTaskTypeName: () => '',
      getStatusColor: () => '', getStatusIcon: () => null, getStatusText: () => '', formatDate: () => '',
    });
    function findCopy(node) {
      if (!node || typeof node !== 'object') return;
      if (node.type === 'button' && node.props['aria-label'] === 'common.copy tasks.taskId') return node;
      const children = node.props?.children;
      for (const child of Array.isArray(children) ? children : [children]) {
        const found = findCopy(child);
        if (found) return found;
      }
    }
    const button = findCopy(tree);
    assert.ok(button);
    assert.equal(button.props.type, 'button');
    assert.equal(button.props.title, button.props['aria-label']);
    await button.props.onClick();
    assert.deepEqual(copied, ['task-full-id']);
    assert.deepEqual(messages, [[fail ? 'error' : 'success', fail ? 'common.copyFailed' : 'common.copied']]);
  }
});
