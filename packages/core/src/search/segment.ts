export function segmentForFts(text: string, locale = 'zh-CN'): string {
  return [...new Intl.Segmenter(locale, { granularity: 'word' }).segment(text.normalize('NFC'))]
    .filter((part) => part.isWordLike).map((part) => part.segment).join(' ');
}
