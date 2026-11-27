export function crossDissolveAtFrame(frame, durationFrames) {
  if (!Number.isInteger(frame) || !Number.isInteger(durationFrames) || durationFrames < 2) {
    throw new TypeError("frame and durationFrames must be integers; durationFrames >= 2");
  }
  const progress = Math.min(1, Math.max(0, frame / (durationFrames - 1)));
  return {outgoingOpacity: 1 - progress, incomingOpacity: progress};
}

export function crossDissolveSequence(durationFrames) {
  return Array.from({length: durationFrames}, (_, frame) => crossDissolveAtFrame(frame, durationFrames));
}
