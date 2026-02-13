import { useState, useEffect, useRef } from 'react';
import { Check, AlertCircle, RotateCcw, AlignLeft, Maximize2, Minimize2, Search, ChevronUp, ChevronDown, X } from 'lucide-react';

interface JSONEditorProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
  height?: string;
}

export default function JSONEditor({ value, onChange, readOnly = false, height = '500px' }: JSONEditorProps) {
  const [error, setError] = useState<string | null>(null);
  const [isValid, setIsValid] = useState(true);
  const [isExpanded, setIsExpanded] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const lineNumbersRef = useRef<HTMLDivElement>(null);

  // 格式化 JSON
  const formatJSON = () => {
    try {
      const parsed = JSON.parse(value);
      const formatted = JSON.stringify(parsed, null, 2);
      onChange(formatted);
      setError(null);
      setIsValid(true);
    } catch (e: any) {
      setError(e.message);
      setIsValid(false);
    }
  };

  // 压缩 JSON
  const minifyJSON = () => {
    try {
      const parsed = JSON.parse(value);
      const minified = JSON.stringify(parsed);
      onChange(minified);
      setError(null);
      setIsValid(true);
    } catch (e: any) {
      setError(e.message);
      setIsValid(false);
    }
  };

  // 验证 JSON
  const validateJSON = (text: string) => {
    try {
      JSON.parse(text);
      setError(null);
      setIsValid(true);
      return true;
    } catch (e: any) {
      setError(e.message);
      setIsValid(false);
      return false;
    }
  };

  // 处理输入变化
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const newValue = e.target.value;
    onChange(newValue);
    validateJSON(newValue);
  };

  // 处理键盘事件（Tab 键缩进）
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (readOnly) return;
    
    if (e.key === 'Tab') {
      e.preventDefault();
      const target = e.target as HTMLTextAreaElement;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const newValue = value.substring(0, start) + '  ' + value.substring(end);
      onChange(newValue);
      
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 2;
      }, 0);
    }
  };

  // 高亮层 ref
  const highlightRef = useRef<HTMLPreElement>(null);

  // 搜索功能状态
  const [searchQuery, setSearchQuery] = useState('');
  const [searchMatches, setSearchMatches] = useState<number[]>([]);
  const [currentMatchIndex, setCurrentMatchIndex] = useState(-1);
  const [showSearch, setShowSearch] = useState(false);
  const textareaRefForSearch = useRef<HTMLTextAreaElement>(null);

  // 同步所有元素滚动位置
  const syncAllScroll = (scrollTop: number, scrollLeft: number) => {
    // 同步高亮层
    if (highlightRef.current) {
      highlightRef.current.scrollTop = scrollTop;
      highlightRef.current.scrollLeft = scrollLeft;
    }
    // 同步行号
    if (lineNumbersRef.current) {
      lineNumbersRef.current.scrollTop = scrollTop;
    }
  };

  // 执行搜索
  useEffect(() => {
    if (!searchQuery) {
      setSearchMatches([]);
      setCurrentMatchIndex(-1);
      return;
    }

    const matches: number[] = [];
    let index = value.toLowerCase().indexOf(searchQuery.toLowerCase());
    while (index !== -1) {
      matches.push(index);
      index = value.toLowerCase().indexOf(searchQuery.toLowerCase(), index + 1);
    }
    setSearchMatches(matches);
    setCurrentMatchIndex(matches.length > 0 ? 0 : -1);
  }, [searchQuery, value]);

  // 跳转到指定匹配位置
  const jumpToMatch = (matchIndex: number) => {
    if (matchIndex < 0 || matchIndex >= searchMatches.length) return;
    
    const position = searchMatches[matchIndex];
    const textarea = textareaRef.current;
    if (!textarea) return;

    // 计算行号并滚动到对应位置
    const textBeforeMatch = value.substring(0, position);
    const lineNumber = textBeforeMatch.split('\n').length;
    const lineHeight = 24; // leading-6 = 24px
    const scrollTop = (lineNumber - 1) * lineHeight - textarea.clientHeight / 2;
    
    textarea.scrollTop = Math.max(0, scrollTop);
    syncAllScroll(textarea.scrollTop, textarea.scrollLeft);
  };

  // 导航到上一个/下一个匹配
  const goToPrevMatch = () => {
    if (searchMatches.length === 0) return;
    const newIndex = currentMatchIndex > 0 ? currentMatchIndex - 1 : searchMatches.length - 1;
    setCurrentMatchIndex(newIndex);
    jumpToMatch(newIndex);
  };

  const goToNextMatch = () => {
    if (searchMatches.length === 0) return;
    const newIndex = currentMatchIndex < searchMatches.length - 1 ? currentMatchIndex + 1 : 0;
    setCurrentMatchIndex(newIndex);
    jumpToMatch(newIndex);
  };

  // 处理搜索框键盘事件
  const handleSearchKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      goToNextMatch();
    } else if (e.key === 'Escape') {
      setShowSearch(false);
      setSearchQuery('');
      textareaRef.current?.focus();
    }
  };

  // 全局键盘快捷键
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl/Cmd + F 打开搜索
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault();
        setShowSearch(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  // 处理 textarea 滚动
  const handleScroll = () => {
    if (!textareaRef.current) return;
    const { scrollTop, scrollLeft } = textareaRef.current;
    syncAllScroll(scrollTop, scrollLeft);
  };

  // 计算行号
  const lineNumbers = value.split('\n').map((_, i) => i + 1);

  // 语法高亮渲染（带搜索高亮）
  const renderHighlightedCode = () => {
    if (!value) return null;
    
    try {
      if (!searchQuery || searchMatches.length === 0) {
        // 无搜索时只显示语法高亮
        const tokens = tokenizeJSON(value);
        return tokens.map((token, i) => (
          <span key={i} className={getTokenClass(token.type)}>
            {token.value}
          </span>
        ));
      }

      // 有搜索时，显示搜索高亮
      const result: JSX.Element[] = [];
      let lastIndex = 0;
      
      // 按位置排序匹配项
      const sortedMatches = [...searchMatches].sort((a, b) => a - b);
      
      sortedMatches.forEach((matchPos, idx) => {
        // 匹配前的文本（带语法高亮）
        if (matchPos > lastIndex) {
          const beforeText = value.substring(lastIndex, matchPos);
          const tokens = tokenizeJSON(beforeText);
          tokens.forEach((token, ti) => (
            result.push(
              <span key={`${idx}-before-${ti}`} className={getTokenClass(token.type)}>
                {token.value}
              </span>
            )
          ));
        }
        
        // 匹配的文本（高亮显示）
        const matchText = value.substring(matchPos, matchPos + searchQuery.length);
        const isCurrent = idx === currentMatchIndex;
        result.push(
          <mark
            key={`match-${idx}`}
            className={`rounded px-0.5 ${isCurrent ? 'bg-yellow-400 text-black font-bold' : 'bg-yellow-700/50 text-yellow-200'}`}
          >
            {matchText}
          </mark>
        );
        
        lastIndex = matchPos + searchQuery.length;
      });
      
      // 最后一段文本
      if (lastIndex < value.length) {
        const afterText = value.substring(lastIndex);
        const tokens = tokenizeJSON(afterText);
        tokens.forEach((token, ti) => (
          result.push(
            <span key={`after-${ti}`} className={getTokenClass(token.type)}>
              {token.value}
            </span>
          )
        ));
      }
      
      return result;
    } catch {
      return <span className="text-red-400">{value}</span>;
    }
  };

  return (
    <div className={`border rounded-lg overflow-hidden bg-gray-900 ${isExpanded ? 'fixed inset-4 z-50' : ''}`}>
      {/* 隐藏滚动条样式 */}
      <style>{`
        .json-editor-hide-scrollbar::-webkit-scrollbar {
          display: none;
        }
      `}</style>
      {/* 工具栏 */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-800 border-b border-gray-700">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-400 font-mono">JSON</span>
          {isValid ? (
            <span className="flex items-center gap-1 text-xs text-green-400">
              <Check className="h-3 w-3" />
              有效
            </span>
          ) : (
            <span className="flex items-center gap-1 text-xs text-red-400">
              <AlertCircle className="h-3 w-3" />
              格式错误
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {!readOnly && (
            <>
              <button
                type="button"
                onClick={formatJSON}
                className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
                title="格式化 (Prettify)"
              >
                <AlignLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                onClick={minifyJSON}
                className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
                title="压缩 (Minify)"
              >
                <RotateCcw className="h-4 w-4" />
              </button>
            </>
          )}
          {!readOnly && (
            <button
              type="button"
              onClick={() => setShowSearch(!showSearch)}
              className={`p-1.5 rounded transition-colors ${showSearch ? 'text-white bg-gray-700' : 'text-gray-400 hover:text-white hover:bg-gray-700'}`}
              title="搜索 (Ctrl+F)"
            >
              <Search className="h-4 w-4" />
            </button>
          )}
          <button
            type="button"
            onClick={() => setIsExpanded(!isExpanded)}
            className="p-1.5 text-gray-400 hover:text-white hover:bg-gray-700 rounded transition-colors"
            title={isExpanded ? '缩小' : '全屏'}
          >
            {isExpanded ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
          </button>
        </div>
      </div>

      {/* 搜索框 */}
      {showSearch && (
        <div className="flex items-center gap-2 px-3 py-2 bg-gray-800 border-b border-gray-700">
          <Search className="h-4 w-4 text-gray-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleSearchKeyDown}
            placeholder="搜索..."
            className="flex-1 bg-gray-700 text-white text-sm px-2 py-1 rounded outline-none focus:ring-1 focus:ring-primary-500"
            autoFocus
          />
          {searchMatches.length > 0 && (
            <span className="text-xs text-gray-400">
              {currentMatchIndex + 1} / {searchMatches.length}
            </span>
          )}
          <button
            type="button"
            onClick={goToPrevMatch}
            disabled={searchMatches.length === 0}
            className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded disabled:opacity-30"
            title="上一个 (Shift+Enter)"
          >
            <ChevronUp className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={goToNextMatch}
            disabled={searchMatches.length === 0}
            className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded disabled:opacity-30"
            title="下一个 (Enter)"
          >
            <ChevronDown className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => { setShowSearch(false); setSearchQuery(''); }}
            className="p-1 text-gray-400 hover:text-white hover:bg-gray-700 rounded"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {/* 编辑器区域 */}
      <div className="relative flex" style={{ height: isExpanded ? `calc(100vh - ${showSearch ? '160px' : '120px'})` : height }}>
        {/* 行号 */}
        <div
          ref={lineNumbersRef}
          className="flex-shrink-0 w-12 py-3 bg-gray-800 text-right text-gray-500 font-mono text-sm select-none overflow-hidden scroll-smooth"
        >
          {lineNumbers.map((num) => (
            <div key={num} className="px-2 leading-6">
              {num}
            </div>
          ))}
        </div>

        {/* 编辑区域 */}
        <div className="flex-1 relative">
          {/* 背景高亮层 - pointerEvents-none 让鼠标事件穿透到 textarea */}
          <pre
            ref={highlightRef}
            className="absolute inset-0 m-0 p-3 font-mono text-sm leading-6 whitespace-pre-wrap break-all text-gray-300 overflow-auto json-editor-hide-scrollbar"
            aria-hidden="true"
            style={{ 
              pointerEvents: 'none',
              scrollbarWidth: 'none',
              msOverflowStyle: 'none'
            }}
          >
            {renderHighlightedCode()}
          </pre>

          {/* 输入层 */}
          <textarea
            ref={textareaRef}
            value={value}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onScroll={handleScroll}
            readOnly={readOnly}
            className="absolute inset-0 w-full h-full p-3 font-mono text-sm leading-6 bg-transparent text-transparent caret-white resize-none outline-none overflow-auto"
            spellCheck={false}
            autoComplete="off"
            autoCapitalize="off"
            style={{ tabSize: 2 }}
          />
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="px-3 py-2 bg-red-900/50 border-t border-red-700 text-red-200 text-xs">
          {error}
        </div>
      )}

      {/* 全屏遮罩关闭按钮 */}
      {isExpanded && (
        <div className="absolute top-4 right-4 z-10">
          <button
            type="button"
            onClick={() => setIsExpanded(false)}
            className="px-4 py-2 bg-gray-700 text-white rounded-lg hover:bg-gray-600 transition-colors"
          >
            关闭全屏
          </button>
        </div>
      )}
    </div>
  );
}

// 简单的 JSON 分词器
function tokenizeJSON(json: string): Array<{ type: string; value: string }> {
  const tokens: Array<{ type: string; value: string }> = [];
  let i = 0;

  while (i < json.length) {
    const char = json[i];

    // 字符串
    if (char === '"') {
      let value = char;
      i++;
      while (i < json.length && json[i] !== '"') {
        if (json[i] === '\\') {
          value += json[i];
          i++;
        }
        value += json[i];
        i++;
      }
      if (i < json.length) {
        value += json[i];
        i++;
      }
      tokens.push({ type: 'string', value });
      continue;
    }

    // 数字
    if (/[-\d]/.test(char)) {
      let value = '';
      while (i < json.length && /[-\d.eE+]/.test(json[i])) {
        value += json[i];
        i++;
      }
      tokens.push({ type: 'number', value });
      continue;
    }

    // 关键字
    if (/[a-z]/.test(char)) {
      let value = '';
      while (i < json.length && /[a-z]/.test(json[i])) {
        value += json[i];
        i++;
      }
      tokens.push({ type: 'keyword', value });
      continue;
    }

    // 标点符号
    if (/[{}[\]:,]/.test(char)) {
      tokens.push({ type: 'punctuation', value: char });
      i++;
      continue;
    }

    // 空白字符
    if (/\s/.test(char)) {
      let value = '';
      while (i < json.length && /\s/.test(json[i])) {
        value += json[i];
        i++;
      }
      tokens.push({ type: 'whitespace', value });
      continue;
    }

    // 其他字符
    tokens.push({ type: 'text', value: char });
    i++;
  }

  return tokens;
}

// 获取 token 样式类
function getTokenClass(type: string): string {
  switch (type) {
    case 'string':
      return 'text-green-400';
    case 'number':
      return 'text-amber-400';
    case 'keyword':
      return 'text-purple-400';
    case 'punctuation':
      return 'text-gray-400';
    case 'whitespace':
      return '';
    default:
      return 'text-gray-300';
  }
}
