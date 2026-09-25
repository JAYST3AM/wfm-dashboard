/* WFM Trader — calm, quiet interface sounds (WebAudio; no files, no network).

   Jay: "some calm and satisfying sounds for button clicks."

   - one delegated listener covers every button, nav pill, chip, tab, summary and [role=button]
   - each click is a soft two-part "tock" (sine + a whisper of triangle), low-passed so it never
     reads as a beep; navigation gets a slightly brighter one
   - per-element override: data-sfx="nav|press|toggle|soft|none"
   - explicit cues via window.sfx.play('done' | 'warn' | ...) for finished actions
   - the header ♪ button mutes it; the choice persists in localStorage
   - the AudioContext is created on the first real gesture (browser autoplay rules)
*/
(function () {
  'use strict';
  var KEY = 'wfm_sound';
  var enabled = true;
  try { enabled = localStorage.getItem(KEY) !== 'off'; } catch (e) {}

  var ctx = null, master = null;

  function ensure() {
    if (ctx) {
      if (ctx.state === 'suspended' && ctx.resume) ctx.resume();
      return ctx;
    }
    var AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    try {
      ctx = new AC();
      master = ctx.createGain();
      master.gain.value = 0.9;
      master.connect(ctx.destination);
    } catch (e) { ctx = null; return null; }
    return ctx;
  }

  /* One voice: low-passed sine, 8 ms attack, exponential tail. Quiet by design. */
  function voice(freq, dur, gain, type, delay, glideTo) {
    var t0 = ctx.currentTime + (delay || 0);
    var osc = ctx.createOscillator();
    var gainNode = ctx.createGain();
    var lp = ctx.createBiquadFilter();
    lp.type = 'lowpass';
    lp.frequency.value = 2200;
    lp.Q.value = 0.5;
    osc.type = type || 'sine';
    osc.frequency.setValueAtTime(freq, t0);
    if (glideTo) osc.frequency.exponentialRampToValueAtTime(glideTo, t0 + dur);
    gainNode.gain.setValueAtTime(0.0001, t0);
    gainNode.gain.exponentialRampToValueAtTime(gain, t0 + 0.008);
    gainNode.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
    osc.connect(lp);
    lp.connect(gainNode);
    gainNode.connect(master);
    osc.start(t0);
    osc.stop(t0 + dur + 0.03);
  }

  var RECIPES = {
    press: function () { voice(640, 0.07, 0.045, 'sine', 0, 500); voice(1280, 0.03, 0.010, 'triangle', 0.002); },
    nav: function () { voice(760, 0.06, 0.040, 'sine', 0, 620); voice(1520, 0.03, 0.009, 'triangle', 0.002); },
    toggle: function () { voice(680, 0.05, 0.034, 'sine'); voice(920, 0.06, 0.030, 'sine', 0.055); },
    soft: function () { voice(520, 0.07, 0.030, 'sine', 0, 440); },
    done: function () { [587, 784, 988].forEach(function (f, i) { voice(f, 0.13, 0.026, 'sine', i * 0.075); }); },
    warn: function () { voice(392, 0.20, 0.045, 'sine', 0, 320); }
  };

  function play(name) {
    if (!enabled) return false;
    if (!RECIPES[name]) name = 'press';
    if (!ensure()) return false;
    try { RECIPES[name](); return true; } catch (e) { return false; }
  }

  var SEL = 'button, .btn, .navpill, .chip, .tab, summary, [role="button"], .theme-item, .movedlink';

  function voiceFor(el) {
    var want = el.getAttribute ? el.getAttribute('data-sfx') : null;
    if (want) return want === 'none' ? null : want;
    if (el.closest && el.closest('.mainnav')) return 'nav';
    if (el.classList && (el.classList.contains('theme-item') || el.classList.contains('chip') ||
                         el.classList.contains('tab'))) return 'toggle';
    return 'press';
  }

  document.addEventListener('click', function (ev) {
    var el = ev.target && ev.target.closest ? ev.target.closest(SEL) : null;
    if (!el || el.disabled || el.getAttribute('aria-disabled') === 'true') return;
    if (el.id === 'soundBtn') return;          // the mute button plays its own cue when re-enabled
    var v = voiceFor(el);
    if (v) play(v);
  }, true);

  /* ---- header mute button ---- */
  function paint() {
    var b = document.getElementById('soundBtn');
    if (!b) return;
    b.classList.toggle('muted', !enabled);
    b.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    b.title = enabled ? 'Click sounds: on — click to mute' : 'Click sounds: muted — click to unmute';
    b.setAttribute('aria-label', enabled ? 'Click sounds (on)' : 'Click sounds (muted)');
  }

  function setEnabled(v) {
    enabled = !!v;
    try { localStorage.setItem(KEY, enabled ? 'on' : 'off'); } catch (e) {}
    paint();
    if (enabled) play('toggle');
  }

  document.addEventListener('click', function (ev) {
    if (ev.target && ev.target.closest && ev.target.closest('#soundBtn')) {
      setEnabled(!enabled);
    }
  }, true);

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', paint);
  } else {
    paint();
  }

  window.sfx = {
    play: play,
    toggle: function () { setEnabled(!enabled); },
    get enabled() { return enabled; }
  };
})();
