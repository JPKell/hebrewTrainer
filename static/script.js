'use strict';

// ── Timer state ───────────────────────────────────────────────────────────────
let timerInterval   = null;
let totalSeconds    = 0;
let targetSeconds   = 0;   // set from plan — 0 means no target
let isRunning       = false;
let currentMode     = '';
let sessionSaved    = false;
let targetSatisfied = false;
let vowelScramble     = true;
let vowelGuideVisible = false;
let autoPlayIntervalId = null;
let autoPlayEnabled    = false;
let autoPlayDelayMs    = 1000;

// ── Recording state ──────────────────────────────────────────────────────────────────────────────
let mediaRecorder  = null;
let audioChunks    = [];
let isRecording    = false;
let recordingBlob  = null;

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatTime(s) {
  return String(Math.floor(s / 60)).padStart(2, '0') + ':' +
         String(s % 60).padStart(2, '0');
}

function updateDisplay() {
  const el = document.getElementById('timer-display');
  if (el) el.textContent = formatTime(totalSeconds);
  updateTargetUI();
}

function updateTargetUI() {
  const label = el('target-label');
  const bar   = el('target-bar');
  if (!label || !bar) return;

  if (!targetSeconds) {
    if (targetSatisfied) {
        label.textContent = '\u2713 Target reached';
      label.className   = 'font-medium tabular-nums text-emerald-400';
      bar.style.width   = '100%';
      bar.style.opacity = '0.6';
    }
    return;
  }

  const pct  = Math.min(100, Math.round(totalSeconds / targetSeconds * 100));
  bar.style.width = pct + '%';

  if (totalSeconds >= targetSeconds) {
    label.textContent = '\u2713 Target reached';
    label.className   = 'font-medium tabular-nums text-emerald-400';
    bar.style.opacity = '0.6';
  } else {
    const remaining = targetSeconds - totalSeconds;
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    label.textContent = (m > 0 ? m + 'm ' : '') + s + 's remaining';
    label.className   = 'font-medium tabular-nums text-gray-500';
    bar.style.opacity = '1';
  }
}

function el(id) { return document.getElementById(id); }

// ── Timer controls ────────────────────────────────────────────────────────────
function startTimer() {
  if (isRunning) return;
  isRunning = true;

  el('start-btn')?.classList.add('hidden');
  el('pause-btn')?.classList.remove('hidden');
  el('timer-display')?.classList.add('timer-active');

  const completeBtn = el('complete-btn');
  if (completeBtn) completeBtn.disabled = false;

  timerInterval = setInterval(() => {
    totalSeconds++;
    updateDisplay();
  }, 1000);
}

function pauseTimer() {
  if (!isRunning) return;
  isRunning = false;

  clearInterval(timerInterval);
  timerInterval = null;

  el('timer-display')?.classList.remove('timer-active');
  el('pause-btn')?.classList.add('hidden');

  const startBtn = el('start-btn');
  if (startBtn) {
    startBtn.textContent = 'Resume';
    startBtn.classList.remove('hidden');
  }
}

// ── Session completion ────────────────────────────────────────────────────────
async function completeSession() {
  if (sessionSaved) return;
  sessionSaved = true;
  stopAutoPlay();

  // Reveal the current item's answer in the translit box on session end
  const allItems = document.querySelectorAll('.drill-item');
  if (allItems.length && allItems[currentIndex]) {
    const label = el('translit-box')?.querySelector('p');
    if (label) label.textContent = 'Current item';
    const renderedText = allItems[currentIndex].querySelector('.hebrew-text')?.textContent.trim()
      || allItems[currentIndex].dataset.original || '';
    updateTranslitBox(renderedText);
  }

  // Stop mic and wait a tick for the final chunk to be assembled
  if (isRecording) {
    stopRecording();
    await new Promise(resolve => setTimeout(resolve, 400));
  }

  if (isRunning) { clearInterval(timerInterval); isRunning = false; }
  el('timer-display')?.classList.remove('timer-active');
  el('pause-btn')?.classList.add('hidden');
  el('start-btn')?.classList.add('hidden');

  const elapsed = totalSeconds;
  const minutes = Math.max(1, Math.round(totalSeconds / 60));
  const completeBtn = el('complete-btn');
  if (completeBtn) { completeBtn.disabled = true; completeBtn.textContent = 'Saving…'; }

  try {
    const res = await fetch('/complete', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ mode: currentMode, minutes, seconds: elapsed }),
    });
    const data = await res.json();

    if (data.success) {
      if (recordingBlob && data.session_id) {
        if (completeBtn) completeBtn.textContent = 'Uploading recording…';
        const form = new FormData();
        form.append('audio', recordingBlob, `session_${data.session_id}.webm`);
        await fetch(`/upload_recording/${data.session_id}`, { method: 'POST', body: form });
      }
      const statusEl = el('session-status');
      if (statusEl) {
        const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
        const ss = String(elapsed % 60).padStart(2, '0');
        statusEl.textContent =
          `✓ ${mm}:${ss} saved.` +
          (recordingBlob ? ' Recording uploaded.' : '') +
          ' Redirecting…';
        statusEl.classList.remove('hidden');
      }
      setTimeout(() => { window.location.href = data.redirect || '/'; }, 1400);
    }
  } catch (err) {
    console.error('Save error:', err);
    sessionSaved = false;
    if (completeBtn) { completeBtn.disabled = false; completeBtn.textContent = 'Complete Session'; }
    alert('Could not save session. Please try again.');
  }
}

// ── Drill navigation ──────────────────────────────────────────────────────────
let currentIndex = 0;

function updateTranslitBox(hebrewText) {
  const tBox = el('translit-box');
  const tTxt = el('translit-text');
  const tHeb = el('translit-prev-hebrew');
  if (!tBox) return;
  if (!hebrewText || !hebrewText.trim()) { tBox.classList.add('hidden'); return; }
  const translit = transliterate(hebrewText.trim());
  const hasContent = translit.replace(/[\u2019\s]/g, '').length > 0;
  if (!hasContent) { tBox.classList.add('hidden'); return; }
  if (tHeb) tHeb.textContent = hebrewText.trim();
  if (tTxt) tTxt.textContent = translit;
  tBox.classList.remove('hidden');
}

// ── Text-to-speech ────────────────────────────────────────────────────────────
function speakCurrent() {
  if (!window.speechSynthesis) return;
  const items = document.querySelectorAll('.drill-item');
  if (!items[currentIndex]) return;
  const text = (items[currentIndex].dataset.original || '').trim();
  // Skip section dividers (e.g. ── TITLE ──) and empty items
  if (!text || text.startsWith('\u2500')) return;

  window.speechSynthesis.cancel();

  const utter = new SpeechSynthesisUtterance(text);
  utter.lang = 'he-IL';
  utter.rate = 0.82; // slightly slower for learning

  const btn = el('speak-btn');
  if (btn) {
    btn.textContent = '🔊…';
    btn.disabled = true;
    const reset = () => { btn.textContent = '🔊'; btn.disabled = false; };
    utter.onend  = reset;
    utter.onerror = reset;
  }
  window.speechSynthesis.speak(utter);
}

function showItem(index) {
  const items = document.querySelectorAll('.drill-item');
  if (!items.length) return;
  hideVowelGuide();

  // Cancel any in-progress speech when navigating
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  const speakBtn = el('speak-btn');
  if (speakBtn) { speakBtn.textContent = '🔊'; speakBtn.disabled = false; }

  // Capture whichever item is currently visible — use the rendered text (may be scrambled)
  const visibleItem = Array.from(items).find(item => !item.classList.contains('hidden'));
  const prevText = visibleItem
    ? (visibleItem.querySelector('.hebrew-text')?.textContent.trim() || visibleItem.dataset.original || '')
    : null;

  items.forEach(item => item.classList.add('hidden'));

  // Wrap around — endless mode
  currentIndex = ((index % items.length) + items.length) % items.length;
  items[currentIndex].classList.remove('hidden');

  renderItemContent(currentIndex);
  updateTranslitBox(prevText);
}

function nextItem() {
  const items = document.querySelectorAll('.drill-item');
  if (!items.length) return;
  if (currentIndex >= items.length - 1) {
    shuffleItems(); // re-shuffle and restart from item 1
  } else {
    showItem(currentIndex + 1);
  }
  resetAutoPlayTimer();
}

function prevItem() { showItem(currentIndex - 1); resetAutoPlayTimer(); }

function shuffleItems() {
  const container = el('drill-items-container');
  if (!container) return;

  const items = Array.from(container.querySelectorAll('.drill-item'));

  // Fisher-Yates
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }
  items.forEach(item => container.appendChild(item));

  currentIndex = 0;
  showItem(0);
}

// ── Vowel scramble ────────────────────────────────────────────────────────────
// ── Transliteration ──────────────────────────────────────────────────────────
// Modern Israeli Pronunciation — simplified rule set for fluency training.
//
// Rules implemented:
//   Consonants  : see C table below; chet/khaf → "kh"
//   Dagesh kal  : ב→b  כ/ך→k  פ/ף→p  (dagesh chazak doubling ignored)
//   Shin/Sin    : shin-dot→"sh"  sin-dot→"s"
//   Vowels      : kamatz/patach→"a"  segol/tsere→"e"  hiriq→"i"
//                 holam/holam-male→"o"  qibbuts/shuruq→"u"
//                 hataf variants→their quality
//   Final He    : silent at word-end without mappiq (dagesh)
//   Vav mater   : וּ (shuruq)→"u"  וֹ (holam male)→"o"  (consonant suppressed)
//   Yod mater   : bare yod with no vowel after i/e vowel → suppressed
//   Alef / Ayin : silent (omitted)
//   Tav         : always "t" (no distinction with/without dagesh)
//   Qof         : "k" (same as kaf-with-dagesh)
//   Kamatz katan: treated as "a" (no distinction from kamatz gadol)
//
// Shva decision tree (Modern Israeli simplified, ~95% accuracy for training):
//   Evaluated top-down; first matching rule wins.
//   1. End of word (no following Hebrew consonant)             → Nach (silent)
//   2. Previous consonant had Nach-shva (two in a row → 2nd)  → Na (voiced "e")
//   3. Next consonant also has shva (first of two in a row)    → Nach (silent)
//   4. Word-initial (prevVowel === '')                         → Na (voiced "e")
//   5. After long vowel (kamatz, tsere, holam, shuruq)         → Na (voiced "e")
//   6. Default / after short vowel                             → Nach (silent)
function transliterate(text) {
  const DAGESH   = '\u05BC';
  const SHIN_DOT = '\u05C1';
  const SIN_DOT  = '\u05C2';
  const SHVA     = '\u05B0';

  // ── Consonant base values (default = soft / fricative form) ────────────────
  const C = {
    '\u05D0': '',    // א  Alef   — silent
    '\u05D1': 'v',   // ב  Vet    — soft default
    '\u05D2': 'g',   // ג  Gimel
    '\u05D3': 'd',   // ד  Dalet
    '\u05D4': 'h',   // ה  He
    '\u05D5': 'v',   // ו  Vav    — consonant form (mater handled separately)
    '\u05D6': 'z',   // ז  Zayin
    '\u05D7': 'kh',  // ח  Chet
    '\u05D8': 't',   // ט  Tet
    '\u05D9': 'y',   // י  Yod
    '\u05DA': 'kh',  // ך  Final Khaf — soft default
    '\u05DB': 'kh',  // כ  Khaf       — soft default
    '\u05DC': 'l',   // ל  Lamed
    '\u05DD': 'm',   // ם  Final Mem
    '\u05DE': 'm',   // מ  Mem
    '\u05DF': 'n',   // ן  Final Nun
    '\u05E0': 'n',   // נ  Nun
    '\u05E1': 's',   // ס  Samekh
    '\u05E2': '',    // ע  Ayin  — silent (Modern Israeli)
    '\u05E3': 'f',   // ף  Final Fe — soft default
    '\u05E4': 'f',   // פ  Fe       — soft default
    '\u05E5': 'ts',  // ץ  Final Tsadi
    '\u05E6': 'ts',  // צ  Tsadi
    '\u05E7': 'k',   // ק  Qof
    '\u05E8': 'r',   // ר  Resh
    '\u05E9': 'sh',  // ש  Shin (default; sin-dot overrides → 's')
    '\u05EA': 't',   // ת  Tav
  };

  // ── Dagesh kal: hardens ב→b  כ/ך→k  פ/ף→p ─────────────────────────────────
  // Dagesh chazak (gemination) is ignored per simplified Modern Israeli rules.
  const C_HARD = {
    '\u05D1': 'b',   // ב + dagesh
    '\u05DA': 'k',   // ך + dagesh
    '\u05DB': 'k',   // כ + dagesh
    '\u05E3': 'p',   // ף + dagesh
    '\u05E4': 'p',   // פ + dagesh
  };

  // ── Vowel diacritics ────────────────────────────────────────────────────────
  // Simplified Modern Israeli:
  //   kamatz / patach  →  a (kamatz = long, patach = short)
  //   segol  / tsere   →  e (tsere = long, segol = short)
  //   hiriq            →  i (short without yod)
  //   holam            →  o (long)
  //   qibbuts          →  u (short)
  //   hataf variants   →  their quality (ultra-short, treated as short)
  //   shva (U+05B0)    →  decided by the shva decision tree (see header)
  const V = {
    '\u05B7': 'a',   // patah      (short)
    '\u05B8': 'a',   // qamatz     (long — kamatz katan also treated as 'a')
    '\u05B5': 'e',   // tsere      (long)
    '\u05B6': 'e',   // segol      (short)
    '\u05B4': 'i',   // hiriq      (short)
    '\u05B9': 'o',   // holam      (long)
    '\u05BA': 'o',   // holam male (long, U+05BA)
    '\u05BB': 'u',   // qibbuts    (short)
    '\u05B1': 'e',   // hataf segol  (ultra-short → short)
    '\u05B2': 'a',   // hataf patah  (ultra-short → short)
    '\u05B3': 'o',   // hataf qamatz (ultra-short → short)
  };

  // Long vowel marks → Shva Na (pronounced) when they immediately precede a shva.
  // Shuruq (vav + dagesh) is also long but handled in the vav-mater branch.
  const LONG_V = new Set(['\u05B8', '\u05B5', '\u05B9', '\u05BA']);
  //                       kamatz    tsere     holam    holam-male

  // ── Helper: does the Hebrew consonant at chars[k] carry a shva? ───────────
  function consonantHasShva(k) {
    let m = k + 1;
    while (m < chars.length) {
      const mc = chars[m], mcp = mc.codePointAt(0);
      if (mcp >= 0x05B0 && mcp <= 0x05C7) {
        if (mc === SHVA) return true;
        m++;
      } else break;
    }
    return false;
  }

  const chars = [...text]; // spread by Unicode code point
  const out   = [];
  let i = 0;
  let prevVowel         = '';    // last emitted vowel ('a','e','i','o','u' or '')
  let prevVowelIsLong   = false; // was prevVowel from a long vowel?
  let prevWasSilentShva = false; // did the previous consonant end up with nach-shva?

  while (i < chars.length) {
    const ch = chars[i];
    const cp = ch.codePointAt(0);

    // ── Non-Hebrew: pass through (newline → space) ──────────────────────────
    if (cp < 0x05B0) {
      const emit = ch === '\n' ? ' ' : ch;
      out.push(emit);
      if (emit === ' ') {
        prevVowel         = '';    // reset all state at word boundary
        prevVowelIsLong   = false;
        prevWasSilentShva = false;
      }
      i++;
      continue;
    }

    // ── Orphaned combining marks (niqqud without a preceding consonant) ───────
    if (cp <= 0x05C7) { i++; continue; }

    // ── Hebrew consonants U+05D0–U+05EA ────────────────────────────────────
    if (cp >= 0x05D0 && cp <= 0x05EA) {
      let hasDagesh = false, hasShinDot = false, hasSinDot = false;
      let hasShva = false, vowel = '', vowelIsLong = false;
      let j = i + 1;

      // Collect all combining diacritics that immediately follow this letter
      while (j < chars.length) {
        const nc  = chars[j];
        const ncp = nc.codePointAt(0);
        if (ncp >= 0x05B0 && ncp <= 0x05C7) {
          if      (nc === DAGESH)   hasDagesh  = true;
          else if (nc === SHIN_DOT) hasShinDot = true;
          else if (nc === SIN_DOT)  hasSinDot  = true;
          else if (nc === SHVA)     hasShva    = true;
          else if (V[nc] && !vowel) { vowel = V[nc]; vowelIsLong = LONG_V.has(nc); }
          j++;
        } else break;
      }

      // ── Shva decision tree ───────────────────────────────────────────────
      if (hasShva && !vowel) {
        const nextCp      = j < chars.length ? chars[j].codePointAt(0) : 0;
        const nextIsHebrew = nextCp >= 0x05D0 && nextCp <= 0x05EA;
        if (!nextIsHebrew) {
          vowel = '';    // Rule 1: end of word → silent
        } else if (prevWasSilentShva) {
          vowel = 'e';   // Rule 2: second of two consecutive shevas → voiced
        } else if (consonantHasShva(j)) {
          vowel = '';    // Rule 3: first of two consecutive shevas → silent
        } else if (prevVowel === '') {
          vowel = 'e';   // Rule 4: word-initial → voiced
        } else if (prevVowelIsLong) {
          vowel = 'e';   // Rule 5: after long vowel → voiced
        } else {
          vowel = '';    // Rule 6: after short vowel → silent
        }
      }

      // Track for the consecutive-shva rule (Rule 2 / Rule 3 above)
      prevWasSilentShva = hasShva && vowel === '';

      // ── Final He (mater lectionis) ─────────────────────────────────────────
      // ה at word-end without a vowel or mappiq (dagesh) is silent in Modern
      // Israeli Hebrew (e.g. תּוֹרָה → tora, מִלָּה → mila).
      if (ch === '\u05D4' && !hasDagesh && !vowel) {
        const nextCp2 = j < chars.length ? chars[j].codePointAt(0) : 0;
        if (nextCp2 < 0x05D0 || nextCp2 > 0x05EA) { i = j; continue; }
      }

      // ── Vav as vowel carrier (mater lectionis) ────────────────────────────
      //   וּ Shuruq  (vav + dagesh, no independent vowel) → "u"  (long vowel)
      //   וֹ Holam male (vav + holam dot)                  → "o"  (long vowel)
      //   In both cases the vav consonant sound is suppressed.
      if (ch === '\u05D5') {
        if (hasDagesh && !vowel) {
          out.push('u');
          prevVowel = 'u'; prevVowelIsLong = true; prevWasSilentShva = false;
          i = j; continue;
        }
        if (vowel === 'o') {
          out.push('o');
          prevVowel = 'o'; prevVowelIsLong = true; prevWasSilentShva = false;
          i = j; continue;
        }
      }

      // ── Yod as mater lectionis ────────────────────────────────────────────
      //   Bare yod (no vowel of its own) after an i or e vowel → suppress.
      //   e.g. בֵּית: tsere + yod → "e" not "ey";  מִי: hiriq + yod → "i" not "iy"
      if (ch === '\u05D9' && !vowel && !hasDagesh &&
          (prevVowel === 'i' || prevVowel === 'e')) {
        i = j;
        continue;
      }

      // ── Resolve consonant sound ──────────────────────────────────────────
      let cons;
      if (ch === '\u05E9') {
        cons = hasSinDot ? 's' : 'sh';
      } else if (hasDagesh && C_HARD[ch]) {
        cons = C_HARD[ch];
      } else {
        cons = C[ch] ?? '';
      }

      out.push(cons, vowel);
      if (vowel) {
        prevVowel       = vowel;
        prevVowelIsLong = vowelIsLong;
      }
      // If vowel === '' prevVowel intentionally unchanged (bare consonant / silent shva)
      i = j;
      continue;
    }

    i++;
  }

  return out.join('')
    .replace(/\s+/g, ' ')
    .trim();
}


function renderItemContent(index) {
  const items = document.querySelectorAll('.drill-item');
  if (!items.length || index < 0 || index >= items.length) return;
  const textEl = items[index].querySelector('.hebrew-text');
  if (!textEl) return;
  const original = items[index].dataset.original || textEl.textContent.trim();
  if (vowelScramble && currentMode === 'letters') {
    const tokens = original.split(' ').filter(t => t.length > 0);
    for (let i = tokens.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [tokens[i], tokens[j]] = [tokens[j], tokens[i]];
    }
    textEl.textContent = tokens.join(' ');
  } else {
    textEl.textContent = original;
  }
}

function toggleVowelScramble() {
  vowelScramble = !vowelScramble;
  const btn = el('vowel-scramble-btn');
  if (btn) {
    btn.classList.toggle('bg-indigo-700',  vowelScramble);
    btn.classList.toggle('text-white',     vowelScramble);
    btn.classList.toggle('border-indigo-500', vowelScramble);
    btn.classList.toggle('bg-gray-800',    !vowelScramble);
    btn.classList.toggle('text-gray-400',  !vowelScramble);
    btn.classList.toggle('border-gray-700', !vowelScramble);
    btn.title = vowelScramble ? 'Vowel scramble ON — click to disable' : 'Scramble vowel order';
  }
  renderItemContent(currentIndex);
}

// ── Consonant auto-play ─────────────────────────────────────────────────────
function updateAutoPlayUI(enabled) {
  const btn = el('auto-play-btn');
  if (!btn) return;
  btn.textContent = enabled ? '⏸ Auto Play' : '▶ Auto Play';
  btn.classList.toggle('bg-rose-700', enabled);
  btn.classList.toggle('text-white', enabled);
  btn.classList.toggle('border-rose-500', enabled);
  btn.classList.toggle('bg-gray-800', !enabled);
  btn.classList.toggle('text-gray-400', !enabled);
  btn.classList.toggle('border-gray-700', !enabled);
  btn.title = enabled ? 'Auto-play is running — click to stop' : 'Auto-play random consonants';
}

function setAutoPlayDelay(seconds) {
  autoPlayDelayMs = Math.round(seconds * 1000);
  const label = el('auto-play-value');
  if (label) label.textContent = `${seconds.toFixed(1)}s`;
  if (autoPlayEnabled) startAutoPlay();
}

function showRandomItem() {
  const items = document.querySelectorAll('.drill-item');
  if (!items.length || items.length < 2) return;
  let nextIndex = currentIndex;
  while (nextIndex === currentIndex) {
    nextIndex = Math.floor(Math.random() * items.length);
  }
  showItem(nextIndex);
}

function startAutoPlay() {
  if (autoPlayIntervalId) clearInterval(autoPlayIntervalId);
  autoPlayEnabled = true;
  updateAutoPlayUI(true);
  autoPlayIntervalId = setInterval(showRandomItem, autoPlayDelayMs);
}

function stopAutoPlay() {
  if (autoPlayIntervalId) clearInterval(autoPlayIntervalId);
  autoPlayIntervalId = null;
  if (!autoPlayEnabled) return;
  autoPlayEnabled = false;
  updateAutoPlayUI(false);
}

function resetAutoPlayTimer() {
  if (!autoPlayEnabled) return;
  if (autoPlayIntervalId) clearInterval(autoPlayIntervalId);
  autoPlayIntervalId = setInterval(showRandomItem, autoPlayDelayMs);
}

function toggleAutoPlay() {
  if (autoPlayEnabled) stopAutoPlay();
  else startAutoPlay();
}

// ── Public init (called from drill.html inline script) ───────────────────────

// ── Recording ────────────────────────────────────────────────────────────────
async function startRecording() {
  try {
    // Mono 16 kHz speech — minimises file size while keeping voice intelligible
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, sampleRate: 16000, echoCancellation: true, noiseSuppression: true },
      video: false
    });
    audioChunks  = [];
    recordingBlob = null;
    // Prefer opus; fall back to plain webm. 16 kbps ≈ 120 KB/min (speech-quality)
    const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
      ? 'audio/webm;codecs=opus' : 'audio/webm';
    mediaRecorder = new MediaRecorder(stream, { mimeType, audioBitsPerSecond: 16000 });
    mediaRecorder.addEventListener('dataavailable', e => {
      if (e.data.size > 0) audioChunks.push(e.data);
    });
    mediaRecorder.addEventListener('stop', () => {
      recordingBlob = new Blob(audioChunks, { type: mimeType });
      stream.getTracks().forEach(t => t.stop());
    });
    mediaRecorder.start(500);
    isRecording = true;
    const btn = el('record-btn');
    if (btn) {
      btn.innerHTML = '⏺ Recording';
      btn.classList.remove('bg-gray-800', 'text-gray-400', 'border-gray-700');
      btn.classList.add('bg-red-900', 'text-red-300', 'border-red-700');
      btn.title = 'Recording — click to stop';
    }
    el('recording-indicator')?.classList.remove('hidden');
  } catch (err) {
    console.error('Mic error:', err);
    sessionSaved = false;
    alert('Microphone access is required to record. Please allow mic access and try again.');
  }
}

function stopRecording() {
  if (mediaRecorder && mediaRecorder.state !== 'inactive') mediaRecorder.stop();
  isRecording = false;
  const btn = el('record-btn');
  if (btn) {
    btn.innerHTML = '🎤 Record';
    btn.classList.remove('bg-red-900', 'text-red-300', 'border-red-700');
    btn.classList.add('bg-gray-800', 'text-gray-400', 'border-gray-700');
    btn.title = 'Record this session';
  }
  el('recording-indicator')?.classList.add('hidden');
}

function toggleRecording() {
  if (isRecording) stopRecording();
  else startRecording();
}

// Font toggle
function toggleFont() {
  const html = document.documentElement;
  const isModern = html.getAttribute('data-font') === 'modern';
  if (isModern) {
    html.removeAttribute('data-font');
    try { localStorage.setItem('hebrewFont', 'siddur'); } catch(e) {}
  } else {
    html.setAttribute('data-font', 'modern');
    try { localStorage.setItem('hebrewFont', 'modern'); } catch(e) {}
  }
  updateFontToggleBtn();
}

function updateFontToggleBtn() {
  const btn = el('font-toggle-btn');
  if (!btn) return;
  const isModern = document.documentElement.getAttribute('data-font') === 'modern';
  btn.textContent = isModern ? 'Aa Siddur' : 'Aa Modern';
  btn.title = isModern ? 'Switch to siddur (serif) font' : 'Switch to modern (sans-serif) font';
}

// Vowel guide
function toggleVowelGuide() {
  vowelGuideVisible = !vowelGuideVisible;
  const panel = el('vowel-guide-panel');
  if (panel) panel.classList.toggle('hidden', !vowelGuideVisible);
  const btn = el('vowel-guide-btn');
  if (btn) {
    btn.classList.toggle('bg-indigo-700',    vowelGuideVisible);
    btn.classList.toggle('text-white',        vowelGuideVisible);
    btn.classList.toggle('border-indigo-500', vowelGuideVisible);
    btn.classList.toggle('bg-gray-800',      !vowelGuideVisible);
    btn.classList.toggle('text-gray-400',    !vowelGuideVisible);
    btn.classList.toggle('border-gray-700',  !vowelGuideVisible);
  }
}

function hideVowelGuide() {
  if (!vowelGuideVisible) return;
  vowelGuideVisible = false;
  const panel = el('vowel-guide-panel');
  if (panel) panel.classList.add('hidden');
  const btn = el('vowel-guide-btn');
  if (btn) {
    btn.classList.remove('bg-indigo-700', 'text-white', 'border-indigo-500');
    btn.classList.add('bg-gray-800', 'text-gray-400', 'border-gray-700');
  }
}

function initDrill(mode, targetRemainingSeconds) {
  currentMode = mode;
  targetSatisfied = arguments.length > 2 ? !!arguments[2] : false;
  targetSeconds = (targetRemainingSeconds && targetRemainingSeconds > 0) ? targetRemainingSeconds : 0;
  updateDisplay();
  updateTargetUI();

  el('start-btn')?.addEventListener('click',    startTimer);
  el('pause-btn')?.addEventListener('click',    pauseTimer);
  el('complete-btn')?.addEventListener('click', completeSession);
  el('record-btn')?.addEventListener('click',   toggleRecording);
  el('vowel-guide-btn')?.addEventListener('click', toggleVowelGuide);
  el('speak-btn')?.addEventListener('click', speakCurrent);
  updateFontToggleBtn();

  if (['consonants', 'vowelfire', 'letters', 'words', 'phrases', 'prayer'].includes(mode)) {
    const slider = el('auto-play-slider');
    if (slider) {
      const initial = parseFloat(slider.value || '1.0');
      setAutoPlayDelay(initial);
      slider.addEventListener('input', () => {
        const value = parseFloat(slider.value || '1.0');
        setAutoPlayDelay(value);
        // Debounce save to server
        clearTimeout(slider._saveTimer);
        slider._saveTimer = setTimeout(() => {
          fetch('/api/save_interval', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode, seconds: value })
          }).catch(() => {});
        }, 600);
      });
    }
    el('auto-play-btn')?.addEventListener('click', toggleAutoPlay);
    updateAutoPlayUI(false);
  }

  // Show speak button only if browser supports Web Speech API
  if (window.speechSynthesis) {
    el('speak-btn')?.classList.remove('hidden');
  }

  // Tap / click the card to advance to the next item
  const container = el('drill-items-container');
  if (container) {
    container.style.cursor = 'pointer';
    container.addEventListener('click', e => {
      // Ignore clicks on interactive elements inside the card
      if (e.target.closest('button, a, input, select, textarea')) return;
      nextItem();
    });
  }

  // Auto-shuffle for modes where random order improves practice
  if (['words', 'phrases', 'prayer', 'consonants', 'vowelfire', 'letters'].includes(mode)) {
    shuffleItems();
  }
}

// ── Boot ──────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (document.querySelectorAll('.drill-item').length > 0) showItem(0);
});
// ── Keyboard navigation ───────────────────────────────────────────────────────────
document.addEventListener('keydown', e => {
  // Only active on drill pages with navigable items
  if (!currentMode || currentMode === 'siddur') return;
  if (!document.querySelectorAll('.drill-item').length) return;
  // Don't steal keys when focus is on a button / link / form element
  const tag = (document.activeElement || {}).tagName || '';
  if (['BUTTON', 'INPUT', 'TEXTAREA', 'SELECT', 'A'].includes(tag)) return;
  // Skip modifier combos (Ctrl+Z, Cmd+R …) and bare modifier / function keys
  if (e.ctrlKey || e.metaKey) return;
  const ignore = ['Tab', 'Escape', 'Shift', 'Control', 'Alt', 'Meta',
                  'F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','F11','F12'];
  if (ignore.includes(e.key)) return;

  e.preventDefault();
  if (e.key === 'Backspace') prevItem();
  else nextItem();
});