/** ZET tovush dvigateli — barcha tovushlar Web Audio API bilan SINTEZ qilinadi.
 *
 * Tashqi audio fayl YO'Q — oscillator + envelope + filter kombinatsiyasi.
 * Har bir holat/buyruq mantiqiga mos alohida tovush (docs/10 §3.2 holat
 * mashinasi bilan sinxron):
 *
 *   wake            sleep → listening       yumshoq ko'tariluvchi ikki nota
 *   sleep           listening → sleep       pasayuvchi mayin ton
 *   listenStart     mikrofon ochildi        qisqa yorqin ping
 *   thinkingLoop    LLM ishlayapti          past chastotali "nafas" pad (loop)
 *   speak           javob kela boshladi     iliq qisqa akkord
 *   success         amal muvaffaqiyatli     major-uchlik arpejio
 *   error           xato                    past dissonant urilish
 *   approval        tasdiq so'raldi         diqqat ikki-ping (shoshilinch, lekin xavotirsiz)
 *   notification    fon xabari              mayin qo'ng'iroq
 *   tick            UI bosish/hover         juda qisqa "tik"
 *   killswitch      favqulodda to'xtatish   dramatik pasayuvchi signal
 *
 * Brauzer autoplay siyosati: AudioContext faqat birinchi foydalanuvchi
 * harakati (click/keydown)da yaratiladi. Ovoz yoqish/o'chirish holati
 * localStorage'da saqlanadi.
 */

type SoundName =
  | "wake"
  | "sleep"
  | "listenStart"
  | "speak"
  | "success"
  | "error"
  | "approval"
  | "notification"
  | "tick"
  | "killswitch";

const STORAGE_KEY = "zet.sound.enabled";

class SoundEngine {
  private ctx: AudioContext | null = null;
  private master: GainNode | null = null;
  private thinkingNodes: { osc: OscillatorNode; lfo: OscillatorNode; gain: GainNode } | null = null;
  private _enabled = true;

  constructor() {
    if (typeof window !== "undefined") {
      this._enabled = localStorage.getItem(STORAGE_KEY) !== "0";
    }
  }

  get enabled(): boolean {
    return this._enabled;
  }

  setEnabled(v: boolean): void {
    this._enabled = v;
    if (typeof window !== "undefined") {
      localStorage.setItem(STORAGE_KEY, v ? "1" : "0");
    }
    if (!v) this.stopThinking();
  }

  /** AudioContext'ni dangasa yaratish — faqat foydalanuvchi harakati ichida chaqiriladi. */
  private ensure(): AudioContext | null {
    if (typeof window === "undefined") return null;
    if (!this.ctx) {
      const AC = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (!AC) return null;
      this.ctx = new AC();
      this.master = this.ctx.createGain();
      this.master.gain.value = 0.35; // umumiy balandlik — nozik, bezovta qilmaydi
      this.master.connect(this.ctx.destination);
    }
    if (this.ctx.state === "suspended") void this.ctx.resume();
    return this.ctx;
  }

  /** Bitta nota: chastota, davomiylik, to'lqin turi, kechikish, balandlik. */
  private tone(
    freq: number,
    dur: number,
    opts: {
      type?: OscillatorType;
      delay?: number;
      gain?: number;
      glideTo?: number;
      filterFreq?: number;
    } = {},
  ): void {
    const ctx = this.ensure();
    if (!ctx || !this.master || !this._enabled) return;
    const { type = "sine", delay = 0, gain = 1, glideTo, filterFreq } = opts;
    const t0 = ctx.currentTime + delay;

    const osc = ctx.createOscillator();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, t0);
    if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, t0 + dur);

    const env = ctx.createGain();
    env.gain.setValueAtTime(0, t0);
    env.gain.linearRampToValueAtTime(gain, t0 + 0.012); // attack
    env.gain.exponentialRampToValueAtTime(0.001, t0 + dur); // decay

    let out: AudioNode = env;
    if (filterFreq) {
      const filter = ctx.createBiquadFilter();
      filter.type = "lowpass";
      filter.frequency.value = filterFreq;
      env.connect(filter);
      out = filter;
    }

    osc.connect(env);
    out.connect(this.master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.05);
  }

  play(name: SoundName): void {
    if (!this._enabled) return;
    switch (name) {
      case "wake":
        // Yumshoq ko'tarilish: C5 → G5 (uyg'onish tuyg'usi)
        this.tone(523, 0.28, { gain: 0.5, filterFreq: 2400 });
        this.tone(784, 0.42, { delay: 0.1, gain: 0.55, filterFreq: 2800 });
        break;
      case "sleep":
        // Pasayuvchi: G4 → C4 glide (tinchlanish)
        this.tone(392, 0.5, { glideTo: 262, gain: 0.4, filterFreq: 1600 });
        break;
      case "listenStart":
        // Yorqin qisqa ping — "eshityapman"
        this.tone(1318, 0.14, { gain: 0.35, filterFreq: 4000 });
        break;
      case "speak":
        // Iliq akkord: E4+A4 (javob boshlanishi)
        this.tone(330, 0.3, { gain: 0.3, type: "triangle" });
        this.tone(440, 0.3, { delay: 0.02, gain: 0.3, type: "triangle" });
        break;
      case "success":
        // Major arpejio: C5-E5-G5 (bajarildi!)
        this.tone(523, 0.16, { gain: 0.4 });
        this.tone(659, 0.16, { delay: 0.09, gain: 0.4 });
        this.tone(784, 0.3, { delay: 0.18, gain: 0.45 });
        break;
      case "error":
        // Past dissonant: A2 + Bb2 birga (xato, lekin vahima emas)
        this.tone(110, 0.4, { gain: 0.5, type: "triangle", filterFreq: 500 });
        this.tone(117, 0.4, { gain: 0.4, type: "triangle", filterFreq: 500 });
        break;
      case "approval":
        // Ikki ping — "diqqat, sendan qaror kutilyapti"
        this.tone(880, 0.14, { gain: 0.45 });
        this.tone(880, 0.2, { delay: 0.22, gain: 0.5 });
        break;
      case "notification":
        // Mayin qo'ng'iroq — A5, sekin so'nadi
        this.tone(880, 0.6, { gain: 0.3, filterFreq: 3200 });
        this.tone(1760, 0.4, { gain: 0.12, filterFreq: 4000 });
        break;
      case "tick":
        // Juda qisqa UI tik
        this.tone(2093, 0.04, { gain: 0.12, filterFreq: 5000 });
        break;
      case "killswitch":
        // Dramatik pasayish: A4 → A2 glide, ikki marta
        this.tone(440, 0.35, { glideTo: 110, gain: 0.6, type: "sawtooth", filterFreq: 900 });
        this.tone(440, 0.5, { delay: 0.4, glideTo: 110, gain: 0.6, type: "sawtooth", filterFreq: 700 });
        break;
    }
  }

  /** Thinking loop — past "nafas" pad. To'xtatish uchun stopThinking(). */
  startThinking(): void {
    const ctx = this.ensure();
    if (!ctx || !this.master || !this._enabled || this.thinkingNodes) return;

    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 98; // G2 — chuqur, deyarli sezilmas

    const gain = ctx.createGain();
    gain.gain.value = 0;

    // LFO — gain'ni sekin "nafas oldiradi" (0.4 Hz)
    const lfo = ctx.createOscillator();
    lfo.frequency.value = 0.4;
    const lfoGain = ctx.createGain();
    lfoGain.gain.value = 0.05;
    lfo.connect(lfoGain);
    lfoGain.connect(gain.gain);

    const t = ctx.currentTime;
    gain.gain.setValueAtTime(0, t);
    gain.gain.linearRampToValueAtTime(0.07, t + 0.8);

    osc.connect(gain);
    gain.connect(this.master);
    osc.start();
    lfo.start();
    this.thinkingNodes = { osc, lfo, gain };
  }

  stopThinking(): void {
    if (!this.thinkingNodes || !this.ctx) return;
    const { osc, lfo, gain } = this.thinkingNodes;
    const t = this.ctx.currentTime;
    gain.gain.cancelScheduledValues(t);
    gain.gain.setValueAtTime(gain.gain.value, t);
    gain.gain.linearRampToValueAtTime(0, t + 0.4);
    osc.stop(t + 0.5);
    lfo.stop(t + 0.5);
    this.thinkingNodes = null;
  }
}

/** Global singleton — butun ilova bitta dvigatel ishlatadi. */
export const sound = new SoundEngine();
export type { SoundName };
