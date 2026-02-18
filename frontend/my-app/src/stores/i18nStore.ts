import { create } from 'zustand';
import { translations, type Language, type Translations } from '../i18n';

export type { Language };

const STORAGE_KEY = 'novelflow-language';
const TIMEZONE_KEY = 'novelflow-timezone';

// 从 localStorage 获取保存的语言
const getStoredLanguage = (): Language => {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored && stored in translations) {
      return stored as Language;
    }
  } catch {
    // localStorage 不可用
  }
  return 'zh-CN';
};

// 保存语言到 localStorage
const storeLanguage = (language: Language) => {
  try {
    localStorage.setItem(STORAGE_KEY, language);
  } catch {
    // localStorage 不可用
  }
};

// 从 localStorage 获取保存的时区
const getStoredTimezone = (): string => {
  try {
    const stored = localStorage.getItem(TIMEZONE_KEY);
    if (stored) {
      return stored;
    }
  } catch {
    // localStorage 不可用
  }
  return 'Asia/Shanghai';
};

// 保存时区到 localStorage
const storeTimezone = (timezone: string) => {
  try {
    localStorage.setItem(TIMEZONE_KEY, timezone);
  } catch {
    // localStorage 不可用
  }
};

// 翻译函数类型
type TFunction = (key: string, params?: Record<string, string | number> & { defaultValue?: string }) => string;

interface I18nState {
  language: Language;
  timezone: string;
  setLanguage: (language: Language) => void;
  setTimezone: (timezone: string) => void;
  t: TFunction;
}

// 获取嵌套对象的值
const getNestedValue = (obj: any, path: string): string | undefined => {
  const keys = path.split('.');
  let value = obj;
  for (const key of keys) {
    if (value && typeof value === 'object' && key in value) {
      value = value[key];
    } else {
      return undefined; // 找不到翻译，返回 undefined
    }
  }
  return typeof value === 'string' ? value : undefined;
};

// 创建翻译函数
const createT = (translations: Translations) => {
  return (key: string, params?: Record<string, string | number> & { defaultValue?: string }): string => {
    // 提取 defaultValue
    const defaultValue = params?.defaultValue;
    
    let value = getNestedValue(translations, key);
    
    // 如果找不到翻译，使用 defaultValue 或原 key
    if (value === undefined) {
      value = defaultValue ?? key;
    }
    
    // 替换参数
    if (params && value) {
      Object.entries(params).forEach(([paramKey, paramValue]) => {
        if (paramKey !== 'defaultValue') {
          value = (value as string).replace(new RegExp(`{${paramKey}}`, 'g'), String(paramValue));
        }
      });
    }
    
    return value;
  };
};

export const useI18nStore = create<I18nState>((set, get) => ({
  language: getStoredLanguage(),
  timezone: getStoredTimezone(),
  t: createT(translations[getStoredLanguage()]) as TFunction,
  
  setLanguage: (language) => {
    storeLanguage(language);
    set({
      language,
      t: createT(translations[language]) as TFunction,
    });
  },
  
  setTimezone: (timezone) => {
    storeTimezone(timezone);
    set({ timezone });
  },
}));

// 兼容 react-i18next 的 useTranslation hook
export const useTranslation = () => {
  const { t, language, timezone, setLanguage, setTimezone } = useI18nStore();
  return { 
    t, 
    i18n: { 
      language, 
      timezone,
      changeLanguage: setLanguage,
      changeTimezone: setTimezone,
    } 
  };
};

// 语言选项
export const languageOptions = [
  { value: 'zh-CN', label: '简体中文' },
  { value: 'zh-TW', label: '繁體中文' },
  { value: 'en-US', label: 'English' },
  { value: 'ja-JP', label: '日本語' },
  { value: 'ko-KR', label: '한국어' },
] as const;

// 时区选项
export const timezoneOptions = [
  { value: 'Asia/Shanghai', labelKey: 'uiConfig.timezones.Asia/Shanghai' },
  { value: 'Asia/Hong_Kong', labelKey: 'uiConfig.timezones.Asia/Hong_Kong' },
  { value: 'Asia/Tokyo', labelKey: 'uiConfig.timezones.Asia/Tokyo' },
  { value: 'Asia/Seoul', labelKey: 'uiConfig.timezones.Asia/Seoul' },
  { value: 'America/New_York', labelKey: 'uiConfig.timezones.America/New_York' },
  { value: 'America/Los_Angeles', labelKey: 'uiConfig.timezones.America/Los_Angeles' },
  { value: 'Europe/London', labelKey: 'uiConfig.timezones.Europe/London' },
  { value: 'Europe/Paris', labelKey: 'uiConfig.timezones.Europe/Paris' },
  { value: 'Australia/Sydney', labelKey: 'uiConfig.timezones.Australia/Sydney' },
  { value: 'UTC', labelKey: 'uiConfig.timezones.UTC' },
] as const;
