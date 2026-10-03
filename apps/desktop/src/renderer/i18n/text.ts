import zh from './zh-CN.json';
import en from './en.json';
export type Text = (key: string) => string;
export function translator(locale: 'zh-CN' | 'en'): Text {
  const source: Record<string, string> = locale === 'zh-CN' ? zh : en;
  return (key) => source[key] ?? source['common.error.unknown'] ?? key;
}
