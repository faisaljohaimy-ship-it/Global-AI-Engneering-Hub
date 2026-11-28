// DOM engine helper, for motions made of real elements (controls, text, panels).
// build(root, ctx) creates the nodes once; apply(refs, state, ctx) sets their styles
// for one moment in time. Nothing animates by itself, so any frame can be shown.
let scopes = 0;

export function dom({ css, build, apply }) {
  return function setup(ctx) {
    const root = ctx.surface.element('div');
    scopes += 1;
    const scope = `hub-motion-scope-${scopes}`;
    root.className = scope;
    root.dir = ctx.rtl ? 'rtl' : 'ltr';
    root.style.cssText = 'position:absolute;inset:0;font:14px/1.4 system-ui,"Segoe UI","Noto Sans Arabic","DejaVu Sans",sans-serif;';
    if (css) {
      const style = root.ownerDocument.createElement('style');
      style.textContent = css.replaceAll(':scope', `.${scope}`);
      root.append(style);
    }
    const refs = build(root, ctx);
    return {
      render(state) {
        apply(refs, state, ctx);
      },
    };
  };
}

export const SVG = 'http://www.w3.org/2000/svg';

/** Create an SVG element with attributes. */
export function svg(document, tag, attributes = {}) {
  const node = document.createElementNS(SVG, tag);
  for (const [name, value] of Object.entries(attributes)) node.setAttribute(name, String(value));
  return node;
}
