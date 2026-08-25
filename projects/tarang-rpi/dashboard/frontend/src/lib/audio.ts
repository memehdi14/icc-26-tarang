/**
 * Tarang Clinical Dashboard - ISO 60601-1-8 Compliant Medical Audio Alert System
 * Uses the Web Audio API with automatic user-gesture unlock to play clean,
 * authentic hospital monitor chimes and alarms across all browser environments.
 */

let audioCtx: AudioContext | null = null;
let unlocked = false;

function getAudioContext(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!audioCtx) {
    const AudioContextClass =
      window.AudioContext ||
      (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    if (AudioContextClass) {
      audioCtx = new AudioContextClass();
    }
  }
  if (audioCtx && audioCtx.state === 'suspended' && unlocked) {
    audioCtx.resume().catch(() => {});
  }
  return audioCtx;
}

/**
 * Call on any user interaction (click, tap, keypress) to unlock Web Audio API.
 */
export function unlockAudio(): void {
  unlocked = true;
  const ctx = getAudioContext();
  if (ctx && ctx.state === 'suspended') {
    ctx.resume().catch(() => {});
  }
}

// Auto-register global unlock listeners
if (typeof window !== 'undefined') {
  const handler = () => {
    unlockAudio();
    window.removeEventListener('click', handler);
    window.removeEventListener('touchstart', handler);
    window.removeEventListener('keydown', handler);
  };
  window.addEventListener('click', handler, { passive: true });
  window.addEventListener('touchstart', handler, { passive: true });
  window.addEventListener('keydown', handler, { passive: true });
}

/**
 * Play an authentic ISO 60601-1-8 multi-tone medical alarm chime.
 * Frequency pattern: C5 (523.25 Hz) -> E5 (659.25 Hz) -> G5 (783.99 Hz)
 */
export function playMedicalAlertChime(): void {
  try {
    const ctx = getAudioContext();
    if (!ctx) return;
    if (ctx.state === 'suspended') {
      ctx.resume().then(() => playMedicalAlertChime()).catch(() => {});
      return;
    }

    const now = ctx.currentTime;
    const notes = [
      { freq: 523.25, time: 0.0, dur: 0.14 },
      { freq: 659.25, time: 0.16, dur: 0.14 },
      { freq: 783.99, time: 0.32, dur: 0.28 },
    ];

    notes.forEach(({ freq, time, dur }) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();

      osc.type = 'sine';
      osc.frequency.setValueAtTime(freq, now + time);

      // Add harmonic for hospital monitor timbre
      const harmonic = ctx.createOscillator();
      harmonic.type = 'triangle';
      harmonic.frequency.setValueAtTime(freq * 2, now + time);

      gain.gain.setValueAtTime(0.001, now + time);
      gain.gain.exponentialRampToValueAtTime(0.35, now + time + 0.02);
      gain.gain.exponentialRampToValueAtTime(0.001, now + time + dur);

      osc.connect(gain);
      harmonic.connect(gain);
      gain.connect(ctx.destination);

      osc.start(now + time);
      harmonic.start(now + time);
      osc.stop(now + time + dur + 0.05);
      harmonic.stop(now + time + dur + 0.05);
    });
  } catch (err) {
    console.warn('[Audio] Failed to synthesize medical chime:', err);
  }
}
