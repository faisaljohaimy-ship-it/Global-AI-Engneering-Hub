// Text helpers for motions that animate words. Arabic letters join, and a letter changes
// shape as its neighbours arrive, so Arabic is animated by the word (or revealed with a
// moving mask), never letter by letter. Latin text may be animated by the grapheme.

const ARABIC = /[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]/;

export const isArabic = (text) => ARABIC.test(String(text));

/** User-perceived characters, so marks, ligatures and emoji are never split. */
export function graphemes(text, locale) {
  if (typeof Intl !== 'undefined' && Intl.Segmenter) {
    return Array.from(new Intl.Segmenter(locale, { granularity: 'grapheme' }).segment(String(text)), (part) => part.segment);
  }
  return Array.from(String(text));
}

/** Words, without the spaces between them. */
export function words(text) {
  return String(text).split(/\s+/u).filter(Boolean);
}

/**
 * The pieces a motion may move independently: words for joined scripts, graphemes
 * (spaces dropped) for the others. Each piece is { text, index, count }.
 */
export function units(text, locale) {
  const parts = isArabic(text) ? words(text) : graphemes(text, locale).filter((part) => part.trim());
  return parts.map((part, index) => ({ text: part, index, count: parts.length }));
}

/** CSS font shorthand with a stack that covers Arabic on common systems. */
export function font(sizePx, weight = 600) {
  return `${weight} ${sizePx}px "IBM Plex Sans Arabic","Noto Sans Arabic","Segoe UI",Tahoma,"DejaVu Sans",system-ui,sans-serif`;
}

/**
 * Lay out pieces of text along one line, centred on `centreX`, in reading order
 * (right to left when `rtl`). Returns [{ text, x, width }] where x is the centre of the piece.
 * `g` is a 2D context whose font is already set.
 */
export function layoutLine(g, pieces, { centreX, gap = 0, rtl = false }) {
  const widths = pieces.map((piece) => g.measureText(piece).width);
  const total = widths.reduce((sum, width) => sum + width, 0) + gap * Math.max(0, pieces.length - 1);
  let cursor = rtl ? centreX + total / 2 : centreX - total / 2;
  return pieces.map((piece, index) => {
    const width = widths[index];
    const x = rtl ? cursor - width / 2 : cursor + width / 2;
    cursor += (rtl ? -1 : 1) * (width + gap);
    return { text: piece, x, width };
  });
}
