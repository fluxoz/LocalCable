(function (global) {
  "use strict";

  var CHANNEL_COL = 132;
  var PX_PER_MIN = 14;
  var TICK_MINUTES = 30;
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
    programs: {},
    scrollEl: null,
    clockOffsetMs: 0,
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

  function parseTime(iso) {
    return new Date(iso).getTime();
  }

  function nowMs() {
    return Date.now() + state.clockOffsetMs;
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
    if (typeof document !== "undefined") {
      document.addEventListener("keydown", onKey);
    }
  }

  function onKey(event) {
    if (!state.schedule || !state.selectedId) return;
    var selected = state.programs[state.selectedId];
    if (!selected) return;
    var key = event.key;
    if (key === "Enter") {
      event.preventDefault();
      playProgram(state.selectedId);
      return;
    }
    var channels = state.schedule.channels || [];
    var chIndex = -1;
    var pIndex = -1;
    for (var c = 0; c < channels.length; c += 1) {
      var programs = channels[c].programs || [];
      for (var p = 0; p < programs.length; p += 1) {
        if (programs[p].id === state.selectedId) {
          chIndex = c;
          pIndex = p;
        }
      }
    }
    if (chIndex < 0) return;
    var next = null;
    if (key === "ArrowRight") {
      next = channels[chIndex].programs[pIndex + 1];
    } else if (key === "ArrowLeft") {
      next = channels[chIndex].programs[pIndex - 1];
    } else if (key === "ArrowDown" && channels[chIndex + 1]) {
      next = programAt(channels[chIndex + 1], parseTime(selected.start_time));
    } else if (key === "ArrowUp" && channels[chIndex - 1]) {
      next = programAt(channels[chIndex - 1], parseTime(selected.start_time));
    }
    if (next) {
      event.preventDefault();
      selectProgram(next.id);
    }
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
      empty.textContent = "No channels found. Add subfolders with video files to the media root.";
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

  function scrollNowIntoView() {
    if (!state.scrollEl || !state.schedule) return;
    var metrics = windowMetrics(state.schedule);
    var x = xFor(nowMs(), metrics);
    state.scrollEl.scrollLeft = Math.max(0, x - state.scrollEl.clientWidth * 0.28);
  }

  function selectDefault(schedule) {
    var channels = schedule.channels || [];
    var now = nowMs();
    for (var i = 0; i < channels.length; i += 1) {
      var hit = programAt(channels[i], now);
      if (hit) {
        selectProgram(hit.id);
        return;
      }
    }
    if (channels[0] && channels[0].programs && channels[0].programs[0]) {
      selectProgram(channels[0].programs[0].id);
    }
  }

  function selectProgram(id) {
    var program = (state.programs && state.programs[id]) || findProgram(id);
    if (!program) return;
    state.selectedId = id;
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

  function playProgram(id) {
    var program = (state.programs && state.programs[id]) || findProgram(id);
    if (!program) return;
    var status = $("footer-status");
    if (status) status.textContent = "Playing in mpv: " + program.title;
    if (typeof fetch !== "function") return;
    fetch("/api/play", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ program_id: id }),
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

  function loadSchedule() {
    if (typeof fetch !== "function") return;
    fetch("/api/schedule")
      .then(function (res) {
        if (!res.ok) throw new Error("schedule " + res.status);
        return res.json();
      })
      .then(function (data) {
        if (data && data.now) {
          var serverNow = new Date(data.now).getTime();
          if (!isNaN(serverNow)) state.clockOffsetMs = serverNow - Date.now();
        }
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
    if (typeof fetch === "function" && !skipAuto) loadSchedule();
    if (typeof setInterval === "function") setInterval(tick, 1000);
  }

  global.LocalCableGuide = {
    init: init,
    render: render,
    selectProgram: selectProgram,
    playProgram: playProgram,
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
