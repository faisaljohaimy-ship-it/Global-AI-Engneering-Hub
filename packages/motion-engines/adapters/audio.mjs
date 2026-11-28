// Feed a motion that reacts to sound from a Web Audio AnalyserNode. No audio is shipped
// or played by this package: the page supplies its own source and its own node.
//
//   const analyser = audioContext.createAnalyser();
//   source.connect(analyser);
//   const stop = connectAnalyser(instance, analyser, { bands: 16 });
//   ...
//   stop();   // hands the motion back to its own demonstration
export function connectAnalyser(instance, analyser, { bands = 16, view = globalThis } = {}) {
  const bins = new Uint8Array(analyser.frequencyBinCount);
  let frame = null;
  const read = () => {
    analyser.getByteFrequencyData(bins);
    const levels = [];
    const size = Math.max(1, Math.floor(bins.length / bands));
    for (let band = 0; band < bands; band += 1) {
      let sum = 0;
      for (let index = band * size; index < (band + 1) * size && index < bins.length; index += 1) sum += bins[index];
      levels.push(sum / size / 255);
    }
    instance.input({ levels });
    frame = view.requestAnimationFrame(read);
  };
  frame = view.requestAnimationFrame(read);
  return function stop() {
    if (frame !== null) view.cancelAnimationFrame(frame);
    frame = null;
    if (instance.state !== 'destroyed') instance.input(null);
  };
}
