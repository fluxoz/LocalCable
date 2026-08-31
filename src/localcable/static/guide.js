(function (global) {
  "use strict";

  var CHANNEL_COL = 132;
  var PX_PER_MIN = 14;
  var TICK_MINUTES = 30;
  var HUD_HIDE_MS = 4000;
  var SEEK_STEP = 10;
  var PALETTE = [
    "#2e8b6e",
    "#247a9e",
    "#3a9d5c",
    "#1e6b8a",
    "#2d9c8a",
    "#246b7a",
    "#3d8b5c",
    "#1a5f7a",
    "#2a7d9e",
    "#1f7a64",
  ];

  var state = {
    schedule: null,
    selectedId: null,
    selectedChannel: null,
    programs: {},
    scrollEl: null,
    clockOffsetMs: 0,
    digitBuf: "",
    digitTimer: null,
    watching: false,
    dashOn: false,
    dashPlayer: null,
    playerMode: "browser",
    startFrom: "live",
    crtOn: false,
    crtMode: "vhs",
    inpageFilter: "css",
    streamFilter: "off",
    packagedFrom: 0,
    programDuration: 0,
    hudTimer: null,
    hudPinned: false,
    seeking: false,
    previewId: null,
    previewTimer: null,
  };

  function $(id) {
    if (typeof document === "undefined") return null;
    return document.getElementById(id);
  }

  function colorFor(title) {
    var hash = 0;
    var text = title || "";
    for (var i = 0; i < text.length; i += 1) {
      hash = (hash * 31 + text.charCodeAt(i)) | 0;
    }
    return PALETTE[Math.abs(hash) % PALETTE.length];
  }

  function pad(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function formatClock(date) {
    var h = date.getHours();
    var m = date.getMinutes();
    var ampm = h >= 12 ? "pm" : "am";
    h = h % 12 || 12;
    return h + ":" + pad(m) + ampm;
  }

  function formatTick(date) {
    var h = date.getHours();
    var m = date.getMinutes();
    var suffix = h >= 12 ? "p" : "a";
    h = h % 12 || 12;
    if (m === 0) return h + ":00" + suffix;
    return h + ":" + pad(m) + suffix;
  }

  function formatRange(startIso, endIso) {
    var start = new Date(startIso);
    var end = new Date(endIso);
    return formatClock(start) + " – " + formatClock(end);
  }

  function formatDuration(seconds) {
    if (!isFinite(seconds) || seconds < 0) seconds = 0;
    var total = Math.floor(seconds);
    var h = Math.floor(total / 3600);
    var m = Math.floor((total % 3600) / 60);
    var s = total % 60;
    if (h > 0) return h + ":" + pad(m) + ":" + pad(s);
    return m + ":" + pad(s);
  }

  function parseTime(iso) {
    return new Date(iso).getTime();
  }

  function nowMs() {
    return Date.now();
  }

  function liveOffset(program) {
    if (!program) return 0;
    var start = parseTime(program.start_time);
    var end = parseTime(program.end_time);
    var elapsed = (nowMs() - start) / 1000;
    if (!(elapsed > 1)) return 0;
    var dur = Number(program.duration_seconds);
    if (!(dur > 0) && end > start) dur = (end - start) / 1000;
    if (!(dur > 2) || elapsed >= dur - 1) return 0;
    return elapsed;
  }

  function usesBrowser() {
    return state.playerMode === "browser" || state.playerMode === "both";
  }

  function usesMpv() {
    return state.playerMode === "mpv" || state.playerMode === "both";
  }

  function windowMetrics(schedule) {
    var start = parseTime(schedule.window_start);
    var end = parseTime(schedule.window_end);
    var width = ((end - start) / 60000) * PX_PER_MIN;
    return { start: start, end: end, width: Math.max(width, 1) };
  }

  function xFor(ms, metrics) {
    return ((ms - metrics.start) / 60000) * PX_PER_MIN;
  }

  function bindControls() {
    var play = $("play-button");
    if (play) {
      play.addEventListener("click", function () {
        if (state.selectedId) playProgram(state.selectedId);
      });
    }
    var earlier = $("scroll-earlier");
    var later = $("scroll-later");
    if (earlier) {
      earlier.addEventListener("click", function () {
        if (state.scrollEl) state.scrollEl.scrollLeft -= TICK_MINUTES * PX_PER_MIN;
      });
    }
    if (later) {
      later.addEventListener("click", function () {
        if (state.scrollEl) state.scrollEl.scrollLeft += TICK_MINUTES * PX_PER_MIN;
      });
    }
    bindHud();
    if (typeof document !== "undefined") {
      document.addEventListener("keydown", onKey, true);
      if (typeof window !== "undefined") {
        window.addEventListener("resize", parkStage);
        window.addEventListener("mousemove", onWatchPointer);
      }
    }
  }

  function bindHud() {
    var map = [
      ["hud-back", returnToGuide],
      ["hud-play", togglePlay],
      ["hud-restart", restartFromBeginning],
      ["hud-mute", toggleMute],
      ["hud-ch-down", function () { surfChannel(-1); }],
      ["hud-ch-up", function () { surfChannel(1); }],
      ["hud-info", toggleHudPin],
      ["hud-fs", toggleFullscreen],
    ];
    for (var i = 0; i < map.length; i += 1) {
      var el = $(map[i][0]);
      if (el) el.addEventListener("click", map[i][1]);
    }
    var crt = $("hud-crt");
    if (crt) {
      crt.checked = !!state.crtOn;
      crt.addEventListener("change", function () {
        state.crtOn = !!crt.checked;
        showHud();
        if (state.inpageFilter === "ntscrs") reloadStreamKeepingTime();
        else applyCrtClass();
      });
    }
    var seek = $("hud-seek");
    if (seek) {
      seek.addEventListener("input", function () {
        state.seeking = true;
        showHud();
      });
      seek.addEventListener("change", function () {
        var video = $("player");
        if (video && isFinite(video.duration) && video.duration > 0) {
          var span = Number(state.programDuration) || video.duration;
          var abs = (Number(seek.value) / 1000) * span;
          video.currentTime = Math.max(0, abs - (state.packagedFrom || 0));
        }
        state.seeking = false;
        showHud();
      });
    }
    var vol = $("hud-volume");
    if (vol) {
      vol.addEventListener("input", function () {
        var video = $("player");
        if (video) {
          video.volume = Number(vol.value) / 100;
          video.muted = video.volume === 0;
        }
        syncHudButtons();
        showHud();
      });
    }
    var video = $("player");
    if (video) {
      video.addEventListener("timeupdate", syncHudTime);
      video.addEventListener("play", syncHudButtons);
      video.addEventListener("pause", syncHudButtons);
      video.addEventListener("volumechange", syncHudButtons);
    }
    var stage = $("stage");
    if (stage) {
      stage.addEventListener("click", function (event) {
        if (event.target && event.target.closest && event.target.closest("#hud-row, #hud-seek, #hud-volume")) {
          return;
        }
        if (!state.watching) {
          if (state.dashOn) enterWatching(currentProgram());
          return;
        }
        togglePlay();
        showHud();
      });
    }
  }

  function onWatchPointer() {
    if (state.watching) showHud();
  }

  function isGuideKey(key) {
    return (
      key === "Escape" ||
      key === "Esc" ||
      key === "GoBack" ||
      key === "BrowserBack" ||
      key === "Backspace" ||
      key === "MediaGuide" ||
      key === "Guide" ||
      key === "ContextMenu" ||
      key === "Home"
    );
  }

  function isOkKey(key) {
    return key === "Enter" || key === " " || key === "Spacebar" || key === "Space" || key === "Select";
  }

  function isInfoKey(key) {
    return key === "i" || key === "I" || key === "Info" || key === "F1";
  }

  function digitFromKey(key, code) {
    if (key && key.length === 1 && key >= "0" && key <= "9") return key;
    if (key && key.indexOf("Digit") === 0 && key.length === 6) return key.slice(5);
    if (code && code.indexOf("Digit") === 0 && code.length === 6) return code.slice(5);
    if (code && code.indexOf("Numpad") === 0 && code.length === 7 && code.charAt(6) >= "0" && code.charAt(6) <= "9") {
      return code.charAt(6);
    }
    return null;
  }

  function onKey(event) {
    var key = event.key;
    if (state.watching && handleWatchKey(event)) return;
    if (isGuideKey(key)) {
      event.preventDefault();
      if (typeof event.stopPropagation === "function") event.stopPropagation();
      returnToGuide();
      return;
    }
    var digit = digitFromKey(key, event.code);
    if (digit) {
      event.preventDefault();
      typeChannelDigit(digit);
      return;
    }
    if (!state.schedule) return;
    if (isOkKey(key)) {
      event.preventDefault();
      if (state.digitBuf) {
        commitChannelDigits();
        return;
      }
      if (state.selectedId) playProgram(state.selectedId);
      return;
    }
    if (isInfoKey(key)) {
      event.preventDefault();
      if (typeof fetch === "function") {
        fetch("/api/remote", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "info" }),
        }).catch(function () {});
      }
      return;
    }
    var channels = state.schedule.channels || [];
    if (!channels.length) return;
    var chIndex = currentChannelIndex(channels);
    if (key === "ChannelUp" || key === "PageUp") {
      event.preventDefault();
      if (channels[chIndex + 1]) focusChannel(channels[chIndex + 1]);
      else if (channels[0]) focusChannel(channels[0]);
      return;
    }
    if (key === "ChannelDown" || key === "PageDown") {
      event.preventDefault();
      if (channels[chIndex - 1]) focusChannel(channels[chIndex - 1]);
      else if (channels[channels.length - 1]) focusChannel(channels[channels.length - 1]);
      return;
    }
    if (chIndex < 0) return;
    var selected = state.selectedId ? state.programs[state.selectedId] : null;
    var pIndex = -1;
    if (selected) {
      var programs = channels[chIndex].programs || [];
      for (var p = 0; p < programs.length; p += 1) {
        if (programs[p].id === state.selectedId) pIndex = p;
      }
    }
    if (key === "ArrowRight" && pIndex >= 0 && channels[chIndex].programs[pIndex + 1]) {
      event.preventDefault();
      selectProgram(channels[chIndex].programs[pIndex + 1].id);
      return;
    }
    if (key === "ArrowLeft" && pIndex > 0) {
      event.preventDefault();
      selectProgram(channels[chIndex].programs[pIndex - 1].id);
      return;
    }
    if (key === "ArrowDown" && channels[chIndex + 1]) {
      event.preventDefault();
      focusChannel(channels[chIndex + 1], selected ? parseTime(selected.start_time) : nowMs());
      return;
    }
    if (key === "ArrowUp" && channels[chIndex - 1]) {
      event.preventDefault();
      focusChannel(channels[chIndex - 1], selected ? parseTime(selected.start_time) : nowMs());
    }
  }

  function handleWatchKey(event) {
    var key = event.key;
    if (isGuideKey(key)) {
      event.preventDefault();
      returnToGuide();
      return true;
    }
    var digit = digitFromKey(key, event.code);
    if (digit) {
      event.preventDefault();
      typeChannelDigit(digit);
      return true;
    }
    if (isOkKey(key) || key === "MediaPlayPause" || key === "MediaPlay" || key === "MediaPause" || key === "k" || key === "K") {
      event.preventDefault();
      if (state.digitBuf) {
        commitChannelDigits();
        if (state.selectedId) playProgram(state.selectedId);
        return true;
      }
      togglePlay();
      showHud();
      return true;
    }
    if (isInfoKey(key)) {
      event.preventDefault();
      toggleHudPin();
      return true;
    }
    if (key === "ArrowLeft") {
      event.preventDefault();
      seekBy(-SEEK_STEP);
      showHud();
      return true;
    }
    if (key === "ArrowRight") {
      event.preventDefault();
      seekBy(SEEK_STEP);
      showHud();
      return true;
    }
    if (key === "ArrowUp") {
      event.preventDefault();
      bumpVolume(0.05);
      showHud();
      return true;
    }
    if (key === "ArrowDown") {
      event.preventDefault();
      bumpVolume(-0.05);
      showHud();
      return true;
    }
    if (key === "ChannelUp" || key === "PageUp") {
      event.preventDefault();
      surfChannel(1);
      return true;
    }
    if (key === "ChannelDown" || key === "PageDown") {
      event.preventDefault();
      surfChannel(-1);
      return true;
    }
    if (key === "m" || key === "M") {
      event.preventDefault();
      toggleMute();
      showHud();
      return true;
    }
    if (key === "f" || key === "F") {
      event.preventDefault();
      toggleFullscreen();
      return true;
    }
    return false;
  }

  function currentChannelIndex(channels) {
    var number = state.selectedChannel;
    if (number == null && state.selectedId && state.programs[state.selectedId]) {
      number = state.programs[state.selectedId].channel_number;
    }
    if (number == null) return 0;
    for (var i = 0; i < channels.length; i += 1) {
      if (channels[i].number === number) return i;
    }
    return 0;
  }

  function matchChannelBuf(buf) {
    var channels = (state.schedule && state.schedule.channels) || [];
    if (!buf || !channels.length) return null;
    var typed = parseInt(buf, 10);
    if (isNaN(typed)) return null;
    var prefixes = [];
    for (var i = 0; i < channels.length; i += 1) {
      if (channels[i].number === typed) return channels[i];
      if (String(channels[i].number).indexOf(buf) === 0) prefixes.push(channels[i]);
    }
    if (prefixes.length === 1) return prefixes[0];
    var closest = channels[0];
    var best = Math.abs(channels[0].number - typed);
    for (var c = 1; c < channels.length; c += 1) {
      var d = Math.abs(channels[c].number - typed);
      if (d < best) {
        best = d;
        closest = channels[c];
      }
    }
    return closest;
  }

  function maxChannelDigits() {
    var channels = (state.schedule && state.schedule.channels) || [];
    var width = 1;
    for (var i = 0; i < channels.length; i += 1) {
      var n = String(channels[i].number).length;
      if (n > width) width = n;
    }
    return width;
  }

  function typeChannelDigit(digit) {
    state.digitBuf += digit;
    if (state.digitTimer && typeof clearTimeout === "function") clearTimeout(state.digitTimer);
    var status = $("footer-status");
    if (status) status.textContent = "Channel " + state.digitBuf;
    var hit = matchChannelBuf(state.digitBuf);
    if (hit) focusChannel(hit);
    if (state.digitBuf.length >= maxChannelDigits()) {
      commitChannelDigits();
      return;
    }
    if (typeof setTimeout === "function") {
      state.digitTimer = setTimeout(commitChannelDigits, 1400);
    }
  }

  function commitChannelDigits() {
    if (state.digitTimer && typeof clearTimeout === "function") clearTimeout(state.digitTimer);
    state.digitTimer = null;
    var buf = state.digitBuf;
    state.digitBuf = "";
    if (!buf) return;
    var hit = matchChannelBuf(buf);
    if (hit) {
      focusChannel(hit);
      if (state.watching && state.selectedId) playProgram(state.selectedId);
    }
  }

  function highlightChannel(number) {
    state.selectedChannel = number;
    var cells = typeof document !== "undefined" ? document.querySelectorAll(".channel-cell.selected") : [];
    for (var i = 0; i < cells.length; i += 1) cells[i].classList.remove("selected");
    var cell = typeof document !== "undefined" ? document.querySelector('.channel-cell[data-channel="' + number + '"]') : null;
    if (cell) {
      cell.classList.add("selected");
      if (typeof cell.scrollIntoView === "function") cell.scrollIntoView({ block: "nearest" });
    }
  }

  function selectEmptyChannel(channel) {
    state.selectedId = null;
    highlightChannel(channel.number);
    var blocks = typeof document !== "undefined" ? document.querySelectorAll(".program.selected") : [];
    for (var i = 0; i < blocks.length; i += 1) blocks[i].classList.remove("selected");
    var title = $("detail-title");
    var chEl = $("detail-channel");
    var rating = $("detail-rating");
    var time = $("detail-time");
    var desc = $("detail-description");
    var play = $("play-button");
    if (title) title.textContent = channel.name || "No programming";
    if (chEl) chEl.textContent = channel.number != null ? channel.number + " " + (channel.name || "") : channel.name || "";
    if (rating) rating.textContent = "";
    if (time) time.textContent = "";
    if (desc) desc.textContent = "No programming";
    if (play) play.disabled = true;
    var status = $("footer-status");
    if (status) status.textContent = "Channel " + channel.number;
    showArt(channel.number != null ? "/art/channel/" + channel.number : "");
    cancelPreview();
    if (typeof fetch === "function") {
      fetch("/api/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: channel.number }),
      }).catch(function () {});
    }
  }

  function focusChannel(channel, atMs) {
    if (!channel) return;
    var hit = programAt(channel, atMs != null ? atMs : nowMs());
    if (hit) selectProgram(hit.id);
    else selectEmptyChannel(channel);
  }

  function programAt(channel, ms) {
    var programs = channel.programs || [];
    for (var i = 0; i < programs.length; i += 1) {
      var start = parseTime(programs[i].start_time);
      var end = parseTime(programs[i].end_time);
      if (start <= ms && ms < end) return programs[i];
    }
    return programs[0] || null;
  }

  function renderTimeAxis(schedule, metrics) {
    var axis = $("time-axis");
    if (!axis) return;
    axis.innerHTML = "";
    axis.style.width = metrics.width + "px";
    var start = new Date(metrics.start);
    var minutes = start.getMinutes();
    var delta = minutes % TICK_MINUTES === 0 ? 0 : TICK_MINUTES - (minutes % TICK_MINUTES);
    var cursor = new Date(metrics.start + delta * 60000);
    while (cursor.getTime() <= metrics.end) {
      var tick = document.createElement("div");
      tick.className = "tick";
      tick.style.left = xFor(cursor.getTime(), metrics) + "px";
      tick.style.width = TICK_MINUTES * PX_PER_MIN + "px";
      tick.textContent = formatTick(cursor);
      axis.appendChild(tick);
      cursor = new Date(cursor.getTime() + TICK_MINUTES * 60000);
    }
    var marker = document.createElement("div");
    marker.id = "now-tick";
    axis.appendChild(marker);
    var label = $("time-bar-label");
    if (label) {
      var now = new Date(nowMs());
      var winStart = new Date(schedule.window_start);
      var sameDay =
        now.getFullYear() === winStart.getFullYear() &&
        now.getMonth() === winStart.getMonth() &&
        now.getDate() === winStart.getDate();
      label.textContent = sameDay ? "Today" : winStart.toLocaleDateString();
    }
  }

  function renderRows(schedule, metrics) {
    var col = $("channel-column");
    var grid = $("program-grid");
    if (!col || !grid) return;
    var nowLine = $("now-line");
    col.innerHTML = "";
    grid.innerHTML = "";
    if (nowLine) grid.appendChild(nowLine);

    var channels = schedule.channels || [];
    if (!channels.length) {
      var empty = document.createElement("div");
      empty.className = "empty-guide";
      empty.textContent = "No channels found. Add subfolders to the media root (videos optional).";
      grid.appendChild(empty);
      return;
    }

    state.programs = {};
    var stripe = "repeating-linear-gradient(to right, transparent 0, transparent " +
      (TICK_MINUTES * PX_PER_MIN - 1) + "px, rgba(255,255,255,0.07) " +
      (TICK_MINUTES * PX_PER_MIN - 1) + "px, rgba(255,255,255,0.07) " +
      TICK_MINUTES * PX_PER_MIN + "px)";

    for (var i = 0; i < channels.length; i += 1) {
      var channel = channels[i];
      var cell = document.createElement("div");
      cell.className = "channel-cell";
      cell.setAttribute("data-channel", String(channel.number));
      var num = document.createElement("span");
      num.className = "ch-num";
      num.textContent = String(channel.number);
      var name = document.createElement("span");
      name.className = "ch-name";
      name.textContent = channel.name;
      cell.appendChild(num);
      cell.appendChild(name);
      col.appendChild(cell);

      var row = document.createElement("div");
      row.className = "grid-row";
      row.style.width = metrics.width + "px";
      row.style.backgroundImage = stripe;
      var programs = channel.programs || [];
      if (!programs.length) {
        var placeholder = document.createElement("div");
        placeholder.className = "program no-media";
        placeholder.setAttribute("data-channel", String(channel.number));
        placeholder.style.left = "0px";
        placeholder.style.width = metrics.width + "px";
        placeholder.textContent = "No programming";
        row.appendChild(placeholder);
      }
      for (var p = 0; p < programs.length; p += 1) {
        var program = programs[p];
        state.programs[program.id] = program;
        var start = parseTime(program.start_time);
        var end = parseTime(program.end_time);
        var left = xFor(start, metrics);
        var width = Math.max(((end - start) / 60000) * PX_PER_MIN, 2);
        var block = document.createElement("div");
        block.className = "program";
        block.id = "program-" + program.id;
        block.setAttribute("data-program-id", program.id);
        block.setAttribute("title", program.title);
        block.style.left = left + "px";
        block.style.width = width + "px";
        block.style.background = colorFor(program.title);
        block.textContent = program.title;
        block.addEventListener("click", onProgramClick);
        block.addEventListener("dblclick", onProgramDblClick);
        row.appendChild(block);
      }
      grid.appendChild(row);
    }
    grid.style.width = metrics.width + "px";
    grid.style.minHeight = channels.length * 42 + "px";
  }

  function onProgramClick(event) {
    var id = event.currentTarget.getAttribute("data-program-id");
    selectProgram(id);
  }

  function onProgramDblClick(event) {
    var id = event.currentTarget.getAttribute("data-program-id");
    selectProgram(id);
    playProgram(id);
  }

  function placeNowLine(schedule) {
    var line = $("now-line");
    if (!schedule) return;
    var metrics = windowMetrics(schedule);
    var x = xFor(nowMs(), metrics);
    if (line) {
      line.style.left = x + "px";
      line.style.height = Math.max((schedule.channels || []).length, 1) * 42 + "px";
    }
    var tick = $("now-tick");
    if (tick) tick.style.left = x + "px";
  }

  function gridScroller() {
    if (!state.scrollEl) state.scrollEl = $("grid-scroll");
    return state.scrollEl;
  }

  function scrollNowIntoView() {
    var scroller = gridScroller();
    if (!scroller || !state.schedule) return;
    var metrics = windowMetrics(state.schedule);
    var x = xFor(nowMs(), metrics);
    scroller.scrollLeft = Math.max(0, x - scroller.clientWidth * 0.28);
  }

  function scrollProgramIntoView(id) {
    var scroller = gridScroller();
    var program = (state.programs && state.programs[id]) || findProgram(id);
    if (!scroller || !program || !state.schedule) return;
    var metrics = windowMetrics(state.schedule);
    var x = xFor(parseTime(program.start_time), metrics);
    var width = Math.max(((parseTime(program.end_time) - parseTime(program.start_time)) / 60000) * PX_PER_MIN, 2);
    var viewW = scroller.clientWidth - CHANNEL_COL;
    if (!(viewW > 80)) viewW = 640;
    var pad = 28;
    if (x < scroller.scrollLeft + pad) {
      scroller.scrollLeft = Math.max(0, x - pad);
    } else if (x + width > scroller.scrollLeft + viewW - pad) {
      scroller.scrollLeft = Math.max(0, x + width - viewW + pad);
    }
    var cell = typeof document !== "undefined" ? document.querySelector(".channel-cell.selected") : null;
    if (cell && typeof cell.scrollIntoView === "function") {
      cell.scrollIntoView({ block: "nearest", inline: "nearest" });
    }
  }

  function selectDefault(schedule) {
    var channels = schedule.channels || [];
    if (!channels.length) return;
    var now = nowMs();
    for (var i = 0; i < channels.length; i += 1) {
      if (programAt(channels[i], now) || !(channels[i].programs || []).length) {
        focusChannel(channels[i], now);
        return;
      }
    }
    focusChannel(channels[0], now);
  }

  function selectProgram(id) {
    var program = (state.programs && state.programs[id]) || findProgram(id);
    if (!program) return;
    state.selectedId = id;
    if (program.channel_number != null) highlightChannel(program.channel_number);
    var blocks = typeof document !== "undefined" ? document.querySelectorAll(".program.selected") : [];
    for (var i = 0; i < blocks.length; i += 1) {
      blocks[i].classList.remove("selected");
    }
    var el = $("program-" + id);
    if (el) el.classList.add("selected");
    var title = $("detail-title");
    var channel = $("detail-channel");
    var rating = $("detail-rating");
    var time = $("detail-time");
    var desc = $("detail-description");
    var play = $("play-button");
    if (title) title.textContent = program.title || "";
    if (channel) {
      var chName = program.channel_name || "";
      var chNum = program.channel_number;
      channel.textContent = chNum != null ? chNum + " " + chName : chName;
    }
    if (rating) rating.textContent = program.rating || "No rating";
    if (time) time.textContent = formatRange(program.start_time, program.end_time);
    if (desc) {
      desc.textContent = program.description || "No description available.";
    }
    if (play) play.disabled = false;
    var status = $("footer-status");
    if (status) status.textContent = "Selected: " + program.title;
    showArt(program.art || "/art/" + id);
    scrollProgramIntoView(id);
    schedulePreview(program);
    if (typeof fetch === "function") {
      fetch("/api/select", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ program_id: id }),
      }).catch(function () {});
    }
    return program;
  }

  function findProgram(id) {
    if (!state.schedule) return null;
    var channels = state.schedule.channels || [];
    for (var i = 0; i < channels.length; i += 1) {
      var programs = channels[i].programs || [];
      for (var p = 0; p < programs.length; p += 1) {
        if (programs[p].id === id) {
          programs[p].channel_name = channels[i].name;
          programs[p].channel_number = channels[i].number;
          return programs[p];
        }
      }
    }
    return null;
  }

  function currentProgram() {
    if (!state.selectedId) return null;
    return state.programs[state.selectedId] || findProgram(state.selectedId);
  }

  function showArt(url) {
    var img = $("detail-art");
    var ph = document.querySelector(".thumb-placeholder");
    var overlay = $("video-overlay");
    var live = overlay && !overlay.hidden;
    if (!img) return;
    img.onload = null;
    img.onerror = null;
    if (!url) {
      img.removeAttribute("src");
      img.hidden = true;
      if (ph && !live) ph.hidden = false;
      return;
    }
    img.onload = function () {
      img.hidden = false;
      if (ph) ph.hidden = true;
    };
    img.onerror = function () {
      img.hidden = true;
      if (ph && !live) ph.hidden = false;
    };
    img.src = url;
  }

  function showVideoOverlay(program) {
    var overlay = $("video-overlay");
    if (!overlay || !program) return;
    overlay.hidden = false;
    var ph = document.querySelector(".thumb-placeholder");
    if (ph) ph.hidden = true;
    var title = $("video-overlay-title");
    var channel = $("video-overlay-channel");
    if (title) title.textContent = program.title || "";
    if (channel) {
      var chName = program.channel_name || "";
      var chNum = program.channel_number;
      channel.textContent = chNum != null && chNum !== "" ? chNum + " " + chName : chName;
    }
    var thumb = $("detail-thumb");
    if (thumb) thumb.classList.add("is-live");
    fillHudCopy(program);
  }

  function fillHudCopy(program) {
    if (!program) return;
    var title = $("hud-title");
    var channel = $("hud-channel");
    if (title) title.textContent = program.title || "";
    if (channel) {
      var chName = program.channel_name || "";
      var chNum = program.channel_number;
      channel.textContent = chNum != null && chNum !== "" ? chNum + " " + chName : chName;
    }
  }

  function parkStage() {
    var stage = $("stage");
    var thumb = $("detail-thumb");
    if (!stage) return;
    if (!state.dashOn) {
      stage.hidden = true;
      stage.classList.remove("is-on", "is-full");
      stage.removeAttribute("style");
      return;
    }
    stage.hidden = false;
    stage.classList.add("is-on");
    if (state.watching) {
      stage.classList.add("is-full");
      stage.removeAttribute("style");
      applyCrtClass();
      return;
    }
    stage.classList.remove("is-full");
    if (!thumb || typeof thumb.getBoundingClientRect !== "function") return;
    var r = thumb.getBoundingClientRect();
    stage.style.position = "fixed";
    stage.style.left = r.left + "px";
    stage.style.top = r.top + "px";
    stage.style.width = r.width + "px";
    stage.style.height = r.height + "px";
    stage.style.zIndex = "6";
    applyCrtClass();
  }

  function enterWatching(program) {
    state.watching = true;
    var video = $("player");
    if (video) video.muted = false;
    if (typeof document !== "undefined" && document.body) {
      document.body.classList.add("watching");
    }
    fillHudCopy(program || currentProgram());
    var badge = $("video-overlay-live");
    if (badge) badge.textContent = "On now";
    showHud();
    parkStage();
  }

  function leaveWatching() {
    state.watching = false;
    var video = $("player");
    if (video) video.muted = true;
    if (typeof document !== "undefined" && document.body) {
      document.body.classList.remove("watching");
    }
    hideHud(true);
    var badge = $("video-overlay-live");
    if (badge && state.dashOn) badge.textContent = "Preview";
    parkStage();
    if (typeof document !== "undefined" && document.fullscreenElement && typeof document.exitFullscreen === "function") {
      document.exitFullscreen().catch(function () {});
    }
  }

  function showHud() {
    var hud = $("hud");
    if (hud) hud.hidden = false;
    if (state.hudTimer && typeof clearTimeout === "function") clearTimeout(state.hudTimer);
    state.hudTimer = null;
    if (!state.watching) return;
    if (state.hudPinned) return;
    if (typeof setTimeout === "function") {
      state.hudTimer = setTimeout(function () {
        hideHud(false);
      }, HUD_HIDE_MS);
    }
  }

  function hideHud(force) {
    if (state.hudPinned && !force) return;
    var hud = $("hud");
    if (hud) hud.hidden = true;
  }

  function toggleHudPin() {
    state.hudPinned = !state.hudPinned;
    if (state.hudPinned) showHud();
    else showHud();
  }

  function syncHudButtons() {
    var video = $("player");
    var play = $("hud-play");
    var mute = $("hud-mute");
    var vol = $("hud-volume");
    if (video && play) play.textContent = video.paused ? "Play" : "Pause";
    if (video && mute) mute.textContent = video.muted || video.volume === 0 ? "Unmute" : "Mute";
    if (video && vol) vol.value = String(Math.round((video.muted ? 0 : video.volume) * 100));
  }

  function syncHudTime() {
    var video = $("player");
    var label = $("hud-time");
    var seek = $("hud-seek");
    if (!video) return;
    var cur = (video.currentTime || 0) + (state.packagedFrom || 0);
    var dur = Number(state.programDuration);
    if (!(dur > 0) && isFinite(video.duration)) dur = video.duration + (state.packagedFrom || 0);
    if (label) label.textContent = formatDuration(cur) + " / " + formatDuration(dur);
    if (seek && !state.seeking && dur > 0) seek.value = String(Math.round((cur / dur) * 1000));
  }

  function togglePlay() {
    var video = $("player");
    if (!video) return;
    if (video.paused) video.play().catch(function () {});
    else video.pause();
    syncHudButtons();
  }

  function toggleMute() {
    var video = $("player");
    if (!video) return;
    video.muted = !video.muted;
    syncHudButtons();
  }

  function bumpVolume(delta) {
    var video = $("player");
    if (!video) return;
    var next = Math.max(0, Math.min(1, (video.muted ? 0 : video.volume) + delta));
    video.muted = next === 0;
    video.volume = next;
    syncHudButtons();
  }

  function seekBy(seconds) {
    var video = $("player");
    if (!video || !isFinite(video.duration)) return;
    var next = Math.max(0, Math.min(video.duration, (video.currentTime || 0) + seconds));
    video.currentTime = next;
    syncHudTime();
  }

  function toggleFullscreen() {
    if (typeof document === "undefined") return;
    var stage = $("stage");
    if (!stage) return;
    if (document.fullscreenElement) {
      if (typeof document.exitFullscreen === "function") document.exitFullscreen().catch(function () {});
      return;
    }
    if (typeof stage.requestFullscreen === "function") {
      stage.requestFullscreen().catch(function () {});
    }
  }

  function surfChannel(delta) {
    var channels = (state.schedule && state.schedule.channels) || [];
    if (!channels.length) return;
    var idx = currentChannelIndex(channels);
    var next = channels[(idx + delta + channels.length) % channels.length];
    if (!next) return;
    var hit = programAt(next, nowMs());
    if (hit) playProgram(hit.id);
    else focusChannel(next);
  }

  function returnToGuide() {
    if (state.watching) leaveWatching();
    var status = $("footer-status");
    if (status) status.textContent = "Guide";
    parkStage();
  }

  function cancelPreview() {
    if (state.previewTimer && typeof clearTimeout === "function") clearTimeout(state.previewTimer);
    state.previewTimer = null;
    if (state.watching) return;
    state.previewId = null;
    if (!state.dashOn) return;
    var video = $("player");
    if (video) {
      try {
        video.pause();
      } catch (err) {}
    }
    state.dashOn = false;
    parkStage();
  }

  function schedulePreview(program) {
    if (state.watching || !program) return;
    if (state.previewId === program.id && state.dashOn) return;
    if (state.previewTimer && typeof clearTimeout === "function") clearTimeout(state.previewTimer);
    if (typeof setTimeout !== "function") {
      loadPreview(program);
      return;
    }
    state.previewTimer = setTimeout(function () {
      loadPreview(program);
    }, 400);
  }

  function applyStreamBody(program, body, muted) {
    state.dashOn = true;
    state.programDuration = Number(body.duration_seconds || program.duration_seconds || 0);
    state.packagedFrom = body.packaged_from_offset ? Number(body.offset_seconds || 0) : 0;
    state.streamFilter = body.filter || activeFilter();
    var box = $("hud-crt");
    if (box && state.inpageFilter === "ntscrs") box.checked = state.streamFilter !== "off";
    var video = $("player");
    if (video) video.muted = !!muted;
    var stage = $("stage");
    if (stage) {
      stage.hidden = false;
      stage.classList.add("is-on");
    }
    if (body.protocol === "file" && body.url) {
      attachFile(body.url, body.offset_seconds || 0);
    } else {
      var seek = body.packaged_from_offset ? 0 : Number(body.offset_seconds || 0);
      attachDash(body.manifest || body.url, seek);
    }
    showVideoOverlay(program);
    var badge = $("video-overlay-live");
    if (badge) badge.textContent = state.watching ? "On now" : "Preview";
    parkStage();
    applyCrtClass();
  }

  function loadPreview(program) {
    if (!program || state.watching) return;
    if (state.previewId === program.id && state.dashOn) return;
    state.previewId = program.id;
    if (typeof fetch !== "function") return;
    fetch("/api/preview/" + encodeURIComponent(program.id))
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (body) {
        if (state.watching) return;
        if (!state.selectedId || state.selectedId !== program.id) return;
        if (!body || !body.ok) return;
        if (body.protocol === "file" && body.url) {
          body.offset_seconds = liveOffset(program);
          applyStreamBody(program, body, true);
          return;
        }
        showArt(body.art || program.art || "/art/" + program.id);
      })
      .catch(function () {});
  }

  function playMpv(id, fromStart) {
    if (typeof fetch !== "function") return;
    fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program_id: id, from_start: !!fromStart }),
    }).catch(function () {});
  }

  function attachDash(manifest, seekSeconds) {
    var video = $("player");
    if (!video) return;
    var seek = Number(seekSeconds || 0);
    if (typeof dashjs !== "undefined" && dashjs.MediaPlayer) {
      if (!state.dashPlayer) {
        state.dashPlayer = dashjs.MediaPlayer().create();
        state.dashPlayer.initialize(video, manifest, true);
      } else if (typeof state.dashPlayer.attachSource === "function") {
        state.dashPlayer.attachSource(manifest);
      } else {
        state.dashPlayer.reset();
        state.dashPlayer.initialize(video, manifest, true);
      }
      if (seek > 0 && state.dashPlayer) {
        var player = state.dashPlayer;
        var seekOnce = function () {
          try {
            if (dashjs.MediaPlayer.events) {
              player.off(dashjs.MediaPlayer.events.STREAM_INITIALIZED, seekOnce);
            }
          } catch (err) {}
          try {
            player.seek(seek);
          } catch (err2) {
            if (video) video.currentTime = seek;
          }
        };
        try {
          if (dashjs.MediaPlayer.events) {
            player.on(dashjs.MediaPlayer.events.STREAM_INITIALIZED, seekOnce);
          } else if (typeof setTimeout === "function") {
            setTimeout(seekOnce, 400);
          }
        } catch (err3) {
          if (typeof setTimeout === "function") setTimeout(seekOnce, 400);
        }
      }
    }
    video.play().catch(function () {});
    syncHudButtons();
  }

  function attachFile(url, seekSeconds) {
    var video = $("player");
    if (!video) return;
    if (state.dashPlayer && typeof state.dashPlayer.reset === "function") {
      try {
        state.dashPlayer.reset();
      } catch (err) {}
      state.dashPlayer = null;
    }
    var seek = Number(seekSeconds || 0);
    var onMeta = function () {
      video.removeEventListener("loadedmetadata", onMeta);
      if (seek > 0 && isFinite(video.duration)) {
        video.currentTime = Math.min(seek, Math.max(0, video.duration - 0.25));
      }
      video.play().catch(function () {});
    };
    video.addEventListener("loadedmetadata", onMeta);
    video.src = url;
    video.play().catch(function () {});
    syncHudButtons();
  }

  function activeFilter() {
    if (!state.crtOn) return "off";
    if (state.inpageFilter === "ntscrs") return state.crtMode || "vhs";
    return "off";
  }

  function applyCrtClass() {
    var stage = $("stage");
    if (!stage) return;
    stage.classList.remove("crt-ntsc", "crt-vhs");
    if (!state.crtOn || state.inpageFilter === "ntscrs") return;
    if (state.inpageFilter === "off") return;
    stage.classList.add(state.crtMode === "ntsc" ? "crt-ntsc" : "crt-vhs");
  }

  function streamPayload(program, fromStart, startSeconds) {
    var body = {
      program_id: program.id,
      from_start: !!fromStart,
      filter: activeFilter(),
    };
    if (startSeconds != null && startSeconds > 0) {
      body.from_start = false;
      body.start_seconds = startSeconds;
    }
    return body;
  }

  function playbackClockSeconds() {
    var video = $("player");
    var cur = (video && video.currentTime) || 0;
    return (state.packagedFrom || 0) + cur;
  }

  function reloadStreamKeepingTime() {
    var program = currentProgram();
    if (!program || !state.dashOn) return;
    startDash(program, false, playbackClockSeconds());
  }

  function startDash(program, fromStart, startSeconds) {
    var status = $("footer-status");
    if (typeof fetch !== "function") return;
    fetch("/api/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(streamPayload(program, fromStart, startSeconds)),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        if (!result.body || !result.body.ok) {
          var err = (result.body && (result.body.error || result.body.detail)) || "stream failed";
          if (status) status.textContent = "Could not play (" + err + ")";
          return;
        }
        state.dashOn = true;
        var stage = $("stage");
        if (stage) {
          stage.hidden = false;
          stage.classList.add("is-on");
        }
        applyStreamBody(program, result.body, false);
        if (status) status.textContent = "Playing: " + program.title;
      })
      .catch(function (err) {
        if (status) status.textContent = "Could not play (" + err + ")";
      });
  }

  function restartFromBeginning() {
    if (state.selectedId) playProgram(state.selectedId, true);
  }

  function playProgram(id, fromStart) {
    var program = (state.programs && state.programs[id]) || findProgram(id);
    if (!program) return;
    var status = $("footer-status");
    if (usesBrowser()) {
      enterWatching(program);
      if (status) status.textContent = "Playing: " + program.title;
      if (!fromStart && state.previewId === id && state.dashOn && state.streamFilter === activeFilter()) {
        var video = $("player");
        if (video) {
          video.muted = false;
          video.play().catch(function () {});
        }
        parkStage();
      } else {
        startDash(program, fromStart);
      }
      if (usesMpv()) playMpv(id, fromStart);
      return;
    }
    if (status) status.textContent = "Playing in mpv: " + program.title;
    if (typeof fetch !== "function") return;
    fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program_id: id, from_start: !!fromStart }),
    })
      .then(function (res) {
        return res.json().then(function (body) {
          return { ok: res.ok, body: body };
        });
      })
      .then(function (result) {
        if (!status) return;
        if (result.body && result.body.ok) {
          status.textContent = "Playing in mpv: " + program.title;
          showVideoOverlay(program);
        } else {
          var err = (result.body && (result.body.error || result.body.detail)) || "playback failed";
          status.textContent = "Could not play (" + err + ")";
        }
      })
      .catch(function (err) {
        if (status) status.textContent = "Could not play (" + err + ")";
      });
  }

  function tick() {
    var clock = $("clock");
    if (clock) clock.textContent = formatClock(new Date(nowMs()));
    if (state.schedule) placeNowLine(state.schedule);
    parkStage();
    syncHudTime();
  }

  function annotateChannels(schedule) {
    var channels = schedule.channels || [];
    for (var i = 0; i < channels.length; i += 1) {
      var programs = channels[i].programs || [];
      for (var p = 0; p < programs.length; p += 1) {
        programs[p].channel_name = channels[i].name;
        programs[p].channel_number = channels[i].number;
      }
    }
  }

  function render(schedule) {
    if (!schedule) return;
    state.schedule = schedule;
    annotateChannels(schedule);
    var metrics = windowMetrics(schedule);
    renderTimeAxis(schedule, metrics);
    renderRows(schedule, metrics);
    placeNowLine(schedule);
    selectDefault(schedule);
    scrollNowIntoView();
    var meta = $("footer-meta");
    if (meta) {
      meta.textContent = (schedule.channels || []).length + " channels";
    }
    tick();
  }

  function showEmpty(message) {
    var grid = $("program-grid");
    if (!grid) return;
    grid.innerHTML = "";
    var empty = document.createElement("div");
    empty.className = "empty-guide";
    empty.textContent = message;
    grid.appendChild(empty);
  }

  function applyUi(ui) {
    if (!ui) return;
    var label = $("header-label");
    var banner = ui.banner;
    if (label && banner != null) {
      banner = String(banner);
      label.textContent = banner;
      if (banner === "TV Listings") label.classList.add("with-mail");
      else label.classList.remove("with-mail");
    }
    if (ui.player) state.playerMode = String(ui.player);
    if (ui.start_from) state.startFrom = String(ui.start_from);
    if (ui.inpage_filter) state.inpageFilter = String(ui.inpage_filter);
    if (ui.filter) {
      var mode = String(ui.filter);
      if (mode === "ntsc" || mode === "vhs") {
        state.crtMode = mode;
        state.crtOn = true;
      } else {
        state.crtOn = false;
      }
      var box = $("hud-crt");
      if (box) box.checked = !!state.crtOn;
      applyCrtClass();
    }
  }

  function loadUi() {
    if (typeof fetch !== "function") return;
    fetch("/api/ui")
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(applyUi)
      .catch(function () {});
  }

  function loadSchedule() {
    if (typeof fetch !== "function") return;
    fetch("/api/schedule")
      .then(function (res) {
        if (!res.ok) throw new Error("schedule " + res.status);
        return res.json();
      })
      .then(function (data) {
        render(data);
      })
      .catch(function (err) {
        if (state.schedule) return;
        if (typeof console !== "undefined" && console.warn) {
          console.warn("LocalCable: schedule not loaded", err);
        }
        showEmpty("No schedule yet. Is the LocalCable server running?");
      });
  }

  function init(root) {
    state.root = root || (typeof document !== "undefined" ? document : null);
    state.scrollEl = $("grid-scroll");
    if (state.root) bindControls();
    tick();
    var skipAuto = global.LocalCableSkipAutoLoad === true;
    if (typeof fetch === "function" && !skipAuto) {
      loadUi();
      loadSchedule();
    }
    if (typeof setInterval === "function") setInterval(tick, 1000);
  }

  global.LocalCableGuide = {
    init: init,
    applyUi: applyUi,
    render: render,
    selectProgram: selectProgram,
    playProgram: playProgram,
    restartFromBeginning: restartFromBeginning,
    liveOffset: liveOffset,
    schedulePreview: schedulePreview,
    showArt: showArt,
    showVideoOverlay: showVideoOverlay,
    returnToGuide: returnToGuide,
    focusChannel: focusChannel,
    typeChannelDigit: typeChannelDigit,
    scrollProgramIntoView: scrollProgramIntoView,
    enterWatching: enterWatching,
    leaveWatching: leaveWatching,
    getState: function () {
      return state;
    },
  };

  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        init(document);
      });
    } else {
      init(document);
    }
  }
})(typeof window !== "undefined" ? window : this);
