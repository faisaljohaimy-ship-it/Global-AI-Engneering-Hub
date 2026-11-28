// React adapter. React is not a dependency of this package: pass your own.
//
//   import * as React from 'react';
//   import { createMotionComponent } from 'packages/motion-engines/adapters/react.mjs';
//   const Motion = createMotionComponent(React);
//   <Motion id="quantum-light-tunnel" options={{ quality: 'auto' }} playing />
//
// Only the motions a page actually renders are downloaded: the id is loaded on mount.
import { createMotion } from '../core/api.mjs';
import { load } from '../index.mjs';

export function createMotionComponent(React) {
  const { createElement, useEffect, useRef } = React;
  /**
   * Props: id or definition; options (create options; a new object re-creates the motion);
   * playing (default true); progress (0..1: when given, the motion is seeked instead of
   * played); className, style; onReady(instance); onError(error).
   */
  return function Motion({ id, definition, options, playing = true, progress, className, style, onReady, onError }) {
    const host = useRef(null);
    const live = useRef(null);
    const key = JSON.stringify(options ?? {});
    useEffect(() => {
      let cancelled = false;
      let instance = null;
      (async () => {
        try {
          const resolved = definition ?? (await load(id));
          if (cancelled) return;
          instance = await createMotion(resolved, { ...(options ?? {}), container: host.current });
          if (cancelled) {
            instance.destroy();
            return;
          }
          live.current = instance;
          if (Number.isFinite(progress)) instance.seek(progress);
          else if (playing) instance.play();
          onReady?.(instance);
        } catch (error) {
          if (!cancelled) onError?.(error);
        }
      })();
      return () => {
        cancelled = true;
        live.current = null;
        instance?.destroy();
      };
      // The motion is rebuilt when what it is, or how it is configured, changes.
    }, [id, definition, key]);
    useEffect(() => {
      const instance = live.current;
      if (!instance) return;
      if (Number.isFinite(progress)) {
        instance.pause();
        instance.seek(progress);
      } else if (playing) instance.state === 'paused' ? instance.resume() : instance.play();
      else instance.pause();
    }, [playing, progress]);
    return createElement('div', { ref: host, className, style, 'data-motion': id ?? definition?.id });
  };
}

/**
 * The same idea for a frame-driven renderer such as Remotion: the picture is a function
 * of the frame number, so a video render asks for exact frames.
 *   const Clip = createFrameComponent(React, { useCurrentFrame, useVideoConfig });   // hooks from 'remotion'
 *   <Clip id="quantum-singularity-reveal" />
 */
export function createFrameComponent(React, { useCurrentFrame, useVideoConfig }) {
  const { createElement, useEffect, useRef, useState } = React;
  return function MotionFrame({ id, definition, options, startFrame = 0 }) {
    const host = useRef(null);
    const [instance, setInstance] = useState(null);
    const frame = useCurrentFrame();
    const { fps, width, height } = useVideoConfig();
    const key = JSON.stringify(options ?? {});
    useEffect(() => {
      let cancelled = false;
      let made = null;
      (async () => {
        const resolved = definition ?? (await load(id));
        if (cancelled) return;
        made = await createMotion(resolved, { width, height, pixelRatio: 1, quality: 'high', reducedMotion: false, ...(options ?? {}), container: host.current });
        if (cancelled) made.destroy();
        else setInstance(made);
      })();
      return () => {
        cancelled = true;
        made?.destroy();
      };
    }, [id, definition, key, width, height]);
    useEffect(() => {
      instance?.render({ time: (Math.max(0, frame - startFrame) * 1000) / fps });
    }, [instance, frame, fps, startFrame]);
    return createElement('div', { ref: host, style: { width, height } });
  };
}
