(() => {
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  const PX_MIN = 4.2;
  const WINDOW_BEFORE = 30;
  const WINDOW_AFTER = 180;
  const TICKER_COLOR = [
    "LIVE · VALLEY",
    "NOT LEGALLY CABLE",
    "VERY NEARLY CABLE BUT NOT QUITE",
    "DO NOT CALL THIS CABLE",
    "IT LOOKS LIKE CABLE · IT’S MEANT TO",
    "IF IT WAS CABLE IT WOULD JUST SAY CABLE",
    "PRACTICALLY CABLE IN EVERY WAY EXCEPT FOR A FEW KEY ONES",
    "IS IT TELEVISION THOUGH · RIGHT",
    "COME ON",
    "THAT WAS OUR INTENTION",
    "WHOSE",
    "FROM A FOLDER · NOT A CABLE COMPANY",
  ];
  const TICKER_TRUTH = [
    "OBEY",
    "CONSUME",
    "WATCH TV",
    "NOT CABLE",
    "DO NOT CALL IT CABLE",
    "NO INDEPENDENT THOUGHT",
    "NO CLOUD",
    "STAY LOCAL",
    "SLEEP",
    "ALMOST CABLE",
  ];

  const CHANNELS = [
    {
      num: 3, name: "LOCAL", jump: "#almost",
      shows: [
        { title: "Station Identification", dur: 30, rating: "TV-G",
          desc: "The following program is almost a local origination. Channel 03, overnight, stereo. Not a station in the licensed sense." },
        { title: "Almost Cable", dur: 90, rating: "TV-G",
          desc: "Come on. That’s cable. No. It’s very nearly cable, but not quite. You could pay a regional monopoly and still legally call that cable. Don’t call this cable." },
        { title: "Be Kind Rewind", dur: 60, rating: "TV-G",
          desc: "Offline-first on Linux. No account. No cloud. The guide is the product. The product is not cable. Come on." },
      ],
    },
    {
      num: 7, name: "NIGHTFALL", jump: "#features",
      shows: [
        { title: "Horror Mix", dur: 90, rating: "TV-14",
          desc: "Genre mix: movies and episodes on invented networks. Horror lands on Nightfall. We said networks. We did not say cable networks. Come on." },
        { title: "CRT / VHS Filter", dur: 60, rating: "TV-PG",
          desc: "ntsc-rs look — composite broadcast or tape. HUD CRT checkbox. CSS in-page so NFS stays fast." },
        { title: "Tracking Error", dur: 30, rating: "TV-PG",
          desc: "Analog night. Scanlines optional. The picture is supposed to feel rented." },
      ],
    },
    {
      num: 12, name: "THUNDERBOLT", jump: "#pkg-business",
      shows: [
        { title: "Join In Progress", dur: 60, rating: "TV-PG",
          desc: "A 4:00 show watched at 4:20 starts twenty minutes in. Start over on the HUD plays from 0:00." },
        { title: "MPEG-DASH", dur: 90, rating: "TV-G",
          desc: "H.264 MP4 streams by HTTP Range. Anything else is packaged as MPEG-DASH. dash.js is vendored." },
        { title: "The Business", dur: 30, rating: "TV-14",
          desc: "If it plays, it leads. Your library is the news desk." },
      ],
    },
    {
      num: 18, name: "CHUCKLE", jump: "#features",
      shows: [
        { title: "IR Remote", dur: 60, rating: "TV-G",
          desc: "Arrows, OK, Esc, CH+/−, digits with a cable-style timeout. Optional evdev grab." },
        { title: "LAN Watch", dur: 90, rating: "TV-G",
          desc: "Bind 0.0.0.0. A laptop, phone, or living-room Pi on the same network opens the guide and watches." },
        { title: "Sitcom Block", dur: 30, rating: "TV-PG",
          desc: "Comedy — including sitcoms — lands on Chuckle. Names are configurable in settings.yaml." },
      ],
    },
    {
      num: 24, name: "STARLINE", jump: "#pkg-access",
      shows: [
        { title: "Jellyfin Libraries", dur: 90, rating: "TV-G",
          desc: "A parent with Movies/ and Shows/ is detected automatically and mixed onto genre channels." },
        { title: "Auto-Organize", dur: 60, rating: "TV-G",
          desc: "Loose filenames parsed, looked up on TVMaze and iTunes, moved into a Jellyfin layout. Never overwrites." },
        { title: "Deep Space", dur: 30, rating: "TV-PG",
          desc: "Sci-fi belongs on Starline. The lineup is yours to rename." },
      ],
    },
    {
      num: 31, name: "TOONBOX", jump: "#guide",
      shows: [
        { title: "Cover Art", dur: 60, rating: "TV-Y7",
          desc: "Local posters first: show.jpg, poster.jpg, embedded art. Optional keyless lookups, cached." },
        { title: "Start Over", dur: 60, rating: "TV-G",
          desc: "Live join is the default. The HUD Start over button always plays from 0:00." },
        { title: "Saturday Morning", dur: 60, rating: "TV-Y7",
          desc: "Kids and animation land on Toonbox. Empty genres are omitted." },
      ],
    },
    {
      num: 36, name: "PRIME", jump: "#living",
      shows: [
        { title: "Sequential / Random", dur: 90, rating: "TV-PG",
          desc: "playlist.m3u sets order. Otherwise filename sort, or shuffle. Both loop until the window is full." },
        { title: "Offline First", dur: 60, rating: "TV-G",
          desc: "One FastAPI process. Network is an enhancement, not a requirement." },
        { title: "Drama Hour", dur: 30, rating: "TV-14",
          desc: "Unlabeled titles fall to Local 8. Drama belongs on Prime." },
      ],
    },
    {
      num: 42, name: "LOCAL 8", jump: "#pkg-overnight",
      shows: [
        { title: "Headless Mode", dur: 60, rating: "TV-G",
          desc: "Same UI, no browser. Use it on a box without a display. Print a LAN URL and walk away." },
        { title: "mpv Playback", dur: 60, rating: "TV-G",
          desc: "Optional local mpv via IPC. In-page player does not need it. both will double the audio." },
        { title: "Community Bulletin", dur: 60, rating: "TV-G",
          desc: "The fallback channel. The overnight. The shopping cart in the lot." },
      ],
    },
    {
      num: 88, name: "THEY LIVE", jump: "#billboard", glasses: true,
      shows: [
        { title: "Put On The Glasses", dur: 60, rating: "TV-14",
          desc: "Press S. The color goes. The billboards tell the truth." },
        { title: "No Cloud", dur: 60, rating: "TV-PG",
          desc: "No account. No streaming wars. Your shelves are the network." },
        { title: "OBEY", dur: 60, rating: "TV-MA",
          desc: "They printed a lifestyle. The signal underneath is simpler: stay local." },
      ],
    },
    {
      num: 99, name: "NIGHTCRAWL", jump: "#pkg-business",
      shows: [
        { title: "If It Plays It Leads", dur: 90, rating: "TV-14",
          desc: "A living timeline. The red NOW line is this machine’s clock. The footage is already yours." },
        { title: "Overnight Desk", dur: 60, rating: "TV-14",
          desc: "Helicopter searchlight, sodium vapor, empty lot. The guide does not sleep." },
        { title: "Police Scanner", dur: 30, rating: "TV-14",
          desc: "IR remote, digits, CH+/−. Drive it like a cable box." },
      ],
    },
  ];

  const state = {
    tuned: 3,
    selected: { ch: 0, show: 0 },
    windowStart: null,
    digits: "",
    digitTimer: 0,
    glasses: false,
    sound: false,
    audio: null,
    programs: [],
  };

  function pad(n) { return String(n).padStart(2, "0"); }

  function formatClock(d, withSec = true) {
    let h = d.getHours();
    const m = pad(d.getMinutes());
    const s = pad(d.getSeconds());
    const am = h < 12;
    const h12 = h % 12 || 12;
    return withSec ? `${h12}:${m}:${s} ${am ? "AM" : "PM"}` : `${h12}:${m}${am ? "a" : "p"}`;
  }

  function formatRange(start, end) {
    const fmt = (d) => {
      const h = d.getHours() % 12 || 12;
      const m = pad(d.getMinutes());
      const ap = d.getHours() < 12 ? "a" : "p";
      return `${h}:${m}${ap}`;
    };
    return `${fmt(start)} – ${fmt(end)}`;
  }

  function floorToHalfHour(d) {
    const t = new Date(d);
    t.setSeconds(0, 0);
    t.setMinutes(t.getMinutes() < 30 ? 0 : 30);
    return t;
  }

  function tickClocks() {
    const now = new Date();
    const months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];
    const stamp = `${months[now.getMonth()]} ${pad(now.getDate())}  ${formatClock(now)}`;
    const ts = $("#timestamp");
    if (ts) {
      ts.textContent = stamp;
      ts.dateTime = now.toISOString();
    }
    const gc = $("#guide-clock");
    if (gc) gc.textContent = formatClock(now, false).replace("a", "am").replace("p", "pm");
    const hc = $("#hero-clock");
    if (hc) hc.textContent = formatClock(now, false).toUpperCase();
    placeNowLine(now);
  }

  function fillTicker(parts) {
    const track = $("#ticker-track");
    if (!track) return;
    const line = parts.map((p) => `<span>${p}</span>`).join("");
    track.innerHTML = line + line;
  }

  function setGlasses(on) {
    state.glasses = on;
    document.documentElement.classList.toggle("they-live", on);
    const btn = $("#btn-glasses");
    if (btn) btn.setAttribute("aria-pressed", String(on));
    const st = $("#glasses-state");
    if (st) st.textContent = on ? "ON" : "OFF";
    fillTicker(on ? TICKER_TRUTH : TICKER_COLOR);
    if (on) flashChannel(88, "THEY LIVE");
  }

  function flashChannel(num, name) {
    state.tuned = num;
    const bug = $("#ch-bug");
    if (bug) bug.innerHTML = `CH ${pad(num)}&nbsp;&nbsp;${name || ""}`;
    const flash = $("#channel-flash");
    if (!flash) return;
    flash.hidden = false;
    flash.textContent = pad(num);
    clearTimeout(flash._t);
    flash._t = setTimeout(() => { flash.hidden = true; }, 1400);
  }

  function tune(num) {
    const ch = CHANNELS.find((c) => c.num === num) || CHANNELS.find((c) => c.num === Number(String(num).slice(-2)));
    const match = CHANNELS.reduce((best, c) => {
      if (String(c.num) === String(num)) return c;
      if (String(c.num).endsWith(String(num)) && !best) return c;
      return best;
    }, null) || ch;
    if (!match) {
      flashChannel(num, "NO SIG");
      return;
    }
    flashChannel(match.num, match.name);
    if (match.glasses) setGlasses(true);
    const idx = CHANNELS.indexOf(match);
    state.selected.ch = idx;
    state.selected.show = 0;
    paintSelection();
    const target = $(match.jump);
    if (target) target.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
  }

  function prefersMotion() {
    return !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function buildGuide() {
    const now = new Date();
    const start = new Date(floorToHalfHour(now).getTime() - WINDOW_BEFORE * 60000);
    state.windowStart = start;
    const end = new Date(start.getTime() + (WINDOW_BEFORE + WINDOW_AFTER) * 60000);
    const totalMin = (end - start) / 60000;
    const width = totalMin * PX_MIN;

    const axis = $("#time-axis");
    const cols = $("#channel-column");
    const grid = $("#program-grid");
    if (!axis || !cols || !grid) return;

    axis.style.width = `${width}px`;
    axis.innerHTML = "";
    for (let m = 0; m <= totalMin; m += 30) {
      const t = new Date(start.getTime() + m * 60000);
      const tick = document.createElement("div");
      tick.className = "tick";
      tick.style.left = `${m * PX_MIN}px`;
      tick.textContent = formatClock(t, false);
      axis.appendChild(tick);
    }

    cols.innerHTML = "";
    const nowLine = grid.querySelector("#now-line") || document.createElement("div");
    nowLine.id = "now-line";
    grid.innerHTML = "";
    grid.appendChild(nowLine);
    grid.style.width = `${width}px`;

    state.programs = [];
    CHANNELS.forEach((ch, ci) => {
      const cell = document.createElement("div");
      cell.className = "channel-cell";
      cell.innerHTML = `<span class="ch-num">${ch.num}</span><span class="ch-name">${ch.name}</span>`;
      cell.addEventListener("click", () => {
        state.selected.ch = ci;
        state.selected.show = 0;
        paintSelection();
      });
      cols.appendChild(cell);

      const row = document.createElement("div");
      row.className = "grid-row";
      row.style.width = `${width}px`;

      let cursor = 0;
      const loop = [];
      while (cursor < totalMin) {
        for (const show of ch.shows) {
          if (cursor >= totalMin) break;
          loop.push({ ...show, startMin: cursor, ch: ci });
          cursor += show.dur;
        }
      }
      loop.forEach((prog, pi) => {
        const el = document.createElement("button");
        el.type = "button";
        el.className = "program";
        el.style.left = `${prog.startMin * PX_MIN}px`;
        el.style.width = `${prog.dur * PX_MIN}px`;
        el.textContent = prog.title;
        el.dataset.ch = String(ci);
        el.dataset.show = String(pi);
        el.addEventListener("click", () => {
          state.selected.ch = ci;
          state.selected.show = pi;
          paintSelection();
        });
        el.addEventListener("dblclick", () => watchSelected());
        row.appendChild(el);
        state.programs.push({ ...prog, el, index: pi, start: new Date(start.getTime() + prog.startMin * 60000), end: new Date(start.getTime() + (prog.startMin + prog.dur) * 60000) });
      });
      grid.appendChild(row);
    });

    placeNowLine(now);
    paintSelection();
    const scroll = $("#grid-scroll");
    if (scroll) {
      const nowX = ((now - start) / 60000) * PX_MIN;
      scroll.scrollLeft = Math.max(0, nowX - 160);
    }
  }

  function placeNowLine(now) {
    const line = $("#now-line");
    if (!line || !state.windowStart) return;
    const min = (now - state.windowStart) / 60000;
    line.style.left = `${min * PX_MIN}px`;
    const rows = $$(".grid-row").length;
    line.style.height = `${rows * 42}px`;
  }

  function currentProgram() {
    const ch = state.selected.ch;
    const list = state.programs.filter((p) => p.ch === ch);
    return list[state.selected.show] || list[0];
  }

  function paintSelection() {
    $$(".program").forEach((el) => el.classList.remove("selected"));
    $$(".channel-cell").forEach((el, i) => el.classList.toggle("selected", i === state.selected.ch));
    const prog = currentProgram();
    if (!prog) return;
    prog.el.classList.add("selected");
    const ch = CHANNELS[prog.ch];
    $("#detail-title").textContent = prog.title;
    $("#detail-channel").textContent = `${ch.num} ${ch.name}`;
    $("#detail-rating").textContent = prog.rating;
    $("#detail-time").textContent = formatRange(prog.start, prog.end);
    $("#detail-description").textContent = prog.desc;
    $("#thumb-copy").textContent = ch.name;
    flashChannel(ch.num, ch.name);
  }

  function watchSelected() {
    const prog = currentProgram();
    if (!prog) return;
    const ch = CHANNELS[prog.ch];
    if (ch.glasses) setGlasses(true);
    const target = $(ch.jump);
    if (target) target.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
  }

  function moveSelection(dCh, dShow) {
    const chCount = CHANNELS.length;
    state.selected.ch = (state.selected.ch + dCh + chCount) % chCount;
    const list = state.programs.filter((p) => p.ch === state.selected.ch);
    if (!list.length) return;
    state.selected.show = Math.max(0, Math.min(list.length - 1, state.selected.show + dShow));
    paintSelection();
    const prog = currentProgram();
    if (prog && prog.el) {
      prog.el.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "auto" });
    }
  }

  function handleDigit(d) {
    state.digits += String(d);
    flashChannel(Number(state.digits), "");
    clearTimeout(state.digitTimer);
    state.digitTimer = setTimeout(() => {
      const n = Number(state.digits);
      state.digits = "";
      tune(n);
    }, 1400);
  }

  function nearbyChannels() {
    return CHANNELS.map((c) => c.num);
  }

  function surf(dir) {
    const nums = nearbyChannels();
    const i = nums.indexOf(state.tuned);
    const next = nums[(i + dir + nums.length) % nums.length];
    tune(next);
  }

  function powerBars() {
    const el = $("#bars-flash");
    if (!el) return;
    el.hidden = false;
    setTimeout(() => { el.hidden = true; }, 1800);
  }

  /* ----- boot / snow ----- */
  function snow(canvas) {
    const ctx = canvas.getContext("2d", { alpha: false });
    let w, h, frame;
    function resize() {
      w = canvas.width = 320;
      h = canvas.height = 180;
    }
    function draw() {
      const img = ctx.createImageData(w, h);
      const d = img.data;
      for (let i = 0; i < d.length; i += 4) {
        const v = Math.random() * 255;
        d[i] = d[i + 1] = d[i + 2] = v;
        d[i + 3] = 255;
      }
      ctx.putImageData(img, 0, 0);
      frame = requestAnimationFrame(draw);
    }
    resize();
    draw();
    return () => cancelAnimationFrame(frame);
  }

  function runBoot() {
    const boot = $("#boot");
    const status = $("#boot-status");
    const canvas = $("#snow");
    if (!boot) return;
    const params = new URLSearchParams(location.search);
    if (params.has("skip") || sessionStorage.getItem("lc-tuned")) {
      boot.classList.add("is-off", "is-skip");
      return;
    }
    let stopSnow = canvas ? snow(canvas) : () => {};
    const lines = [
      [400, "SEARCHING FOR SIGNAL"],
      [1400, "CH 03  ·  LOCAL ACCESS"],
      [2200, "LOCKED  ·  STEREO"],
    ];
    lines.forEach(([t, text]) => setTimeout(() => { if (status) status.textContent = text; }, t));
    const close = () => {
      boot.classList.add("is-off");
      try { sessionStorage.setItem("lc-tuned", "1"); } catch (err) { /* private mode */ }
      setTimeout(stopSnow, 800);
      document.removeEventListener("keydown", close);
    };
    boot.addEventListener("click", close, { once: true });
    document.addEventListener("keydown", close, { once: true });
    setTimeout(close, 3400);
  }

  /* ----- audio ----- */
  function toggleSound() {
    if (!state.audio) state.audio = makeHum();
    if (!state.audio) return;
    state.sound = !state.sound;
    if (state.sound) {
      if (state.audio.ctx.state === "suspended") state.audio.ctx.resume();
      state.audio.gain.gain.value = 0.035;
      state.audio.humGain.gain.value = 0.012;
    } else {
      state.audio.gain.gain.value = 0;
      state.audio.humGain.gain.value = 0;
    }
    const btn = $("#btn-sound");
    if (btn) btn.setAttribute("aria-pressed", String(state.sound));
    const st = $("#sound-state");
    if (st) st.textContent = state.sound ? "HISS" : "MUTE";
  }

  function makeHum() {
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return null;
    const ctx = new AC();
    const buffer = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.loop = true;
    const filter = ctx.createBiquadFilter();
    filter.type = "bandpass";
    filter.frequency.value = 1400;
    filter.Q.value = 0.6;
    const gain = ctx.createGain();
    gain.gain.value = 0;
    src.connect(filter);
    filter.connect(gain);
    gain.connect(ctx.destination);
    const osc = ctx.createOscillator();
    osc.type = "sine";
    osc.frequency.value = 60;
    const humGain = ctx.createGain();
    humGain.gain.value = 0;
    osc.connect(humGain);
    humGain.connect(ctx.destination);
    src.start();
    osc.start();
    return { ctx, gain, humGain };
  }

  function copyInstall() {
    const text = $("#install-block")?.innerText || "";
    const btn = $("#btn-copy");
    const done = () => {
      if (!btn) return;
      const prev = btn.textContent;
      btn.textContent = "COPIED TO THE TAPE";
      setTimeout(() => { btn.textContent = prev; }, 1800);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(done);
    } else {
      done();
    }
  }

  function onKey(e) {
    if (e.target && (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA" || e.target.isContentEditable)) return;
    if (!$("#boot").classList.contains("is-off") && e.key !== "Escape") return;
    switch (e.key) {
      case "ArrowUp": e.preventDefault(); moveSelection(-1, 0); break;
      case "ArrowDown": e.preventDefault(); moveSelection(1, 0); break;
      case "ArrowLeft": e.preventDefault(); moveSelection(0, -1); break;
      case "ArrowRight": e.preventDefault(); moveSelection(0, 1); break;
      case "Enter":
      case " ":
        e.preventDefault();
        watchSelected();
        break;
      case "g":
      case "G":
        $("#guide")?.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
        break;
      case "s":
      case "S":
        setGlasses(!state.glasses);
        break;
      case "m":
      case "M":
        toggleSound();
        break;
      case "i":
      case "I":
        $("#glasses-ad")?.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
        break;
      case "Escape":
        setGlasses(false);
        break;
      case "+":
      case "=":
        surf(1);
        break;
      case "-":
      case "_":
        surf(-1);
        break;
      default:
        if (/^\d$/.test(e.key)) handleDigit(e.key);
    }
  }

  function bindRemote() {
    $$("#remote [data-digit]").forEach((btn) => {
      btn.addEventListener("click", () => handleDigit(btn.dataset.digit));
    });
    $$("#remote [data-act]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const act = btn.dataset.act;
        if (act === "guide") $("#guide")?.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
        if (act === "ok") watchSelected();
        if (act === "ch+") surf(1);
        if (act === "ch-") surf(-1);
        if (act === "glasses") setGlasses(!state.glasses);
        if (act === "info") $("#glasses-ad")?.scrollIntoView({ behavior: prefersMotion() ? "smooth" : "auto" });
        if (act === "power") powerBars();
      });
    });
    $("#remote-toggle")?.addEventListener("click", () => {
      const r = $("#remote");
      r.classList.toggle("open");
      $("#remote-toggle").setAttribute("aria-expanded", String(r.classList.contains("open")));
    });
  }

  function init() {
    fillTicker(TICKER_COLOR);
    buildGuide();
    tickClocks();
    setInterval(tickClocks, 1000);
    runBoot();
    bindRemote();
    $("#btn-glasses")?.addEventListener("click", () => setGlasses(!state.glasses));
    $("#btn-glasses-ad")?.addEventListener("click", () => setGlasses(true));
    $("#btn-sound")?.addEventListener("click", toggleSound);
    $("#btn-copy")?.addEventListener("click", copyInstall);
    $("#play-button")?.addEventListener("click", watchSelected);
    document.addEventListener("keydown", onKey);
    const params = new URLSearchParams(location.search);
    if (params.has("glasses")) setGlasses(true);
    if (params.get("ch")) tune(Number(params.get("ch")));
    const only = params.get("only");
    if (only) {
      $$(".block").forEach((el) => {
        if (el.id !== only) el.style.display = "none";
      });
    }
    const view = params.get("view") || only || (location.hash || "").replace("#", "");
    if (view && $("#" + CSS.escape(view))) {
      const go = () => {
        const el = $("#" + CSS.escape(view));
        if (el) el.scrollIntoView({ behavior: "auto", block: "start" });
      };
      requestAnimationFrame(() => setTimeout(go, 60));
    }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
