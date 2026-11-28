// Canvas 2D engine helper. A motion supplies draw(g, state, ctx, data): g is already
// scaled so that one unit is one CSS pixel, and the frame is cleared to the background
// (or to transparent when the motion is a layer of a composition).
export function canvas2d({ init, draw, alpha = false }) {
  return function setup(ctx) {
    const { g } = ctx.surface.canvas2d({ alpha: alpha || ctx.transparent });
    const data = init ? init(ctx) : undefined;
    return {
      render(state) {
        g.setTransform(ctx.pixelRatio, 0, 0, ctx.pixelRatio, 0, 0);
        g.globalAlpha = 1;
        g.globalCompositeOperation = 'source-over';
        g.shadowBlur = 0;
        g.filter = 'none';
        if (ctx.transparent) g.clearRect(0, 0, ctx.width, ctx.height);
        else {
          g.fillStyle = ctx.css[0];
          g.fillRect(0, 0, ctx.width, ctx.height);
        }
        g.save();
        draw(g, state, ctx, data);
        g.restore();
      },
    };
  };
}
