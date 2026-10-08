// Tiny synthesized sound effects (no audio files needed).
type Sfx = 'draw' | 'discard' | 'select' | 'error' | 'win' | 'lose' | 'turn';

let ctx: AudioContext | null = null;
let muted = readMuted();

// Reads the saved mute setting (defaults to sound on).
function readMuted(): boolean {
  try {
    return localStorage.getItem('smart-rummy-muted') === '1';
  } catch {
    return false;
  }
}

// True if sound effects are currently muted.
export function isMuted() {
  return muted;
}

// Mutes or unmutes sound and remembers the choice.
export function setMuted(value: boolean) {
  muted = value;
  try {
    localStorage.setItem('smart-rummy-muted', value ? '1' : '0');
  } catch {
    /* storage unavailable: keep in memory only */
  }
}

// Plays a short synthesised tone.
function tone(freq: number, start: number, dur: number, type: OscillatorType = 'sine', gain = 0.08) {
  if (!ctx) return;
  const osc = ctx.createOscillator();
  const g = ctx.createGain();
  osc.type = type;
  osc.frequency.value = freq;
  g.gain.setValueAtTime(0, ctx.currentTime + start);
  g.gain.linearRampToValueAtTime(gain, ctx.currentTime + start + 0.01);
  g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + start + dur);
  osc.connect(g).connect(ctx.destination);
  osc.start(ctx.currentTime + start);
  osc.stop(ctx.currentTime + start + dur + 0.02);
}

// Plays a short burst of filtered noise (a card swish).
function noise(dur: number, gain = 0.05) {
  if (!ctx) return;
  const len = Math.floor(ctx.sampleRate * dur);
  const buf = ctx.createBuffer(1, len, ctx.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = (Math.random() * 2 - 1) * (1 - i / len);
  const src = ctx.createBufferSource();
  const g = ctx.createGain();
  const f = ctx.createBiquadFilter();
  f.type = 'bandpass';
  f.frequency.value = 2200;
  g.gain.value = gain;
  src.buffer = buf;
  src.connect(f).connect(g).connect(ctx.destination);
  src.start();
}

// Plays a named sound effect unless muted.
export function play(sfx: Sfx) {
  if (muted) return;
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') void ctx.resume();
  } catch {
    return;
  }
  switch (sfx) {
    case 'draw':
    case 'discard':
      noise(sfx === 'draw' ? 0.09 : 0.12, 0.09);
      break;
    case 'select':
      tone(880, 0, 0.05, 'triangle', 0.03);
      break;
    case 'turn':
      tone(660, 0, 0.12, 'sine', 0.05);
      tone(880, 0.1, 0.16, 'sine', 0.05);
      break;
    case 'error':
      tone(220, 0, 0.18, 'square', 0.03);
      break;
    case 'win':
      [523, 659, 784, 1046].forEach((f, i) => tone(f, i * 0.12, 0.3, 'triangle', 0.06));
      break;
    case 'lose':
      [392, 330, 262].forEach((f, i) => tone(f, i * 0.16, 0.3, 'sine', 0.05));
      break;
  }
}
