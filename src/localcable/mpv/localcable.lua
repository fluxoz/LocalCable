-- LocalCable mpv UI: Esc returns to the guide without changing the player
-- window. A cable-style info overlay is drawn on the video.

local utils = require "mp.utils"

local options = {
    url = os.getenv("LOCALCABLE_GUIDE_URL") or "http://127.0.0.1:8787",
    python = os.getenv("LOCALCABLE_PYTHON") or "python3",
    helper = os.getenv("LOCALCABLE_SHOW_GUIDE") or "",
    osd_path = os.getenv("LOCALCABLE_OSD_PATH") or "",
}

local info = {
    title = "",
    channel_name = "",
    channel_number = "",
    rating = "",
    description = "",
    time_range = "",
}

local banner_visible = false
local hide_timer = nil
local ov = nil
do
    local ok, result = pcall(mp.create_osd_overlay, "ass-events")
    if ok and result then
        ov = result
        ov.res_x = 1920
        ov.res_y = 1080
        ov.z = 100
    end
end

local function show_guide()
    if options.helper == nil or options.helper == "" then
        return
    end
    -- `run` is fire-and-forget and does not change playback or the window.
    mp.commandv("run", options.python, options.helper, options.url)
end

local function aesc(s)
    s = tostring(s or "")
    s = s:gsub("[{}\\]", "")
    s = s:gsub("\n", " ")
    return s
end

local function load_info()
    local path = options.osd_path
    if path == nil or path == "" then
        return
    end
    local f = io.open(path, "r")
    if not f then
        return
    end
    local raw = f:read("*a")
    f:close()
    if not raw or raw == "" then
        return
    end
    local data = utils.parse_json(raw)
    if type(data) ~= "table" then
        return
    end
    info.title = data.title or info.title
    info.channel_name = data.channel_name or ""
    info.channel_number = data.channel_number or ""
    info.rating = data.rating or ""
    info.description = data.description or ""
    info.time_range = data.time_range or ""
end

local function hide_banner()
    banner_visible = false
    if hide_timer then
        hide_timer:kill()
        hide_timer = nil
    end
    if not ov then
        return
    end
    ov.data = ""
    ov:update()
end

local function draw()
    if not banner_visible or not ov then
        return
    end
    local title = aesc(info.title)
    if title == "" then
        title = aesc(mp.get_property("media-title") or "")
    end
    local ch_num = aesc(info.channel_number)
    local ch_name = aesc(info.channel_name)
    local channel = (ch_num .. " " .. ch_name):gsub("^%s+", ""):gsub("%s+$", "")
    local rating = aesc(info.rating)
    local times = aesc(info.time_range)
    local desc = aesc(info.description)
    local pct = mp.get_property_number("percent-pos") or 0
    if pct < 0 then pct = 0 end
    if pct > 100 then pct = 100 end
    local bar_w = 1824
    local fill = math.floor(bar_w * pct / 100)

    local lines = {
        -- Translucent bottom banner (video shows through).
        "{\\an7\\bord0\\shad0\\p1\\c&H781E12&\\alpha&H30&}m 0 780 l 1920 780 l 1920 1080 l 0 1080{\\p0}",
        "{\\an7\\bord0\\shad0\\p1\\c&HAA5A1D&\\alpha&H50&}m 0 780 l 1920 780 l 1920 788 l 0 788{\\p0}",
        string.format("{\\an7\\pos(48,808)\\fs34\\b1\\bord2\\3c&H000000&\\c&HFFFFFF&}%s", channel),
        string.format("{\\an7\\pos(1872,808)\\an9\\fs28\\b0\\bord2\\3c&H000000&\\c&HE8F3FF&}%s", aesc(os.date("%I:%M%p"):gsub("^0", ""))),
        string.format("{\\an7\\pos(48,856)\\fs52\\b1\\bord2\\3c&H000000&\\c&HFFFFFF&}%s", title),
    }
    if rating ~= "" then
        lines[#lines + 1] = string.format(
            "{\\an7\\pos(1872,868)\\an9\\fs28\\b1\\bord2\\3c&H000000&\\c&HFFFFFF&}[%s]",
            rating
        )
    end
    if times ~= "" then
        lines[#lines + 1] = string.format(
            "{\\an7\\pos(48,920)\\fs28\\bord2\\3c&H000000&\\c&HB7D3F5&}%s",
            times
        )
    end
    if desc ~= "" then
        lines[#lines + 1] = string.format(
            "{\\an7\\pos(48,958)\\fs26\\bord2\\3c&H000000&\\c&HE6F0FF&}%s",
            desc
        )
    end
    -- Progress track + fill.
    lines[#lines + 1] = "{\\an7\\bord0\\shad0\\p1\\c&H0A2A55&\\alpha&H20&}m 48 1036 l 1872 1036 l 1872 1056 l 48 1056{\\p0}"
    if fill > 0 then
        local x2 = 48 + fill
        lines[#lines + 1] = string.format(
            "{\\an7\\bord0\\shad0\\p1\\c&H18C5F5&\\alpha&H00&}m 48 1036 l %d 1036 l %d 1056 l 48 1056{\\p0}",
            x2, x2
        )
    end
    if channel ~= "" then
        lines[#lines + 1] = string.format(
            "{\\an9\\pos(1872,36)\\fs32\\b1\\bord2\\3c&H000000&\\c&HFFFFFF&}%s",
            channel
        )
    end
    ov.data = table.concat(lines, "\n")
    ov:update()
end

local function show_banner(seconds)
    load_info()
    banner_visible = true
    if hide_timer then
        hide_timer:kill()
        hide_timer = nil
    end
    if seconds and seconds > 0 then
        hide_timer = mp.add_timeout(seconds, hide_banner)
    end
    draw()
end

local function toggle_banner()
    if banner_visible then
        hide_banner()
    else
        show_banner(0)
    end
end

mp.observe_property("percent-pos", "number", function()
    if banner_visible then
        draw()
    end
end)

mp.register_event("file-loaded", function()
    show_banner(7)
end)

mp.register_script_message("configure", function(url, python, helper)
    if url and url ~= "" then options.url = url end
    if python and python ~= "" then options.python = python end
    if helper and helper ~= "" then options.helper = helper end
end)

mp.register_script_message("info", function(payload)
    if payload and payload ~= "" then
        local data = utils.parse_json(payload)
        if type(data) == "table" then
            info.title = data.title or info.title
            info.channel_name = data.channel_name or info.channel_name
            info.channel_number = data.channel_number or info.channel_number
            info.rating = data.rating or info.rating
            info.description = data.description or info.description
            info.time_range = data.time_range or info.time_range
        end
    else
        load_info()
    end
    show_banner(7)
end)

local function remote(action, extra)
    if options.helper == nil or options.helper == "" then
        return
    end
    extra = extra or ""
    if extra ~= "" then
        mp.commandv("run", options.python, options.helper, options.url, action, extra)
    else
        mp.commandv("run", options.python, options.helper, options.url, action)
    end
end

local function bind_many(keys, name, fn)
    for i = 1, #keys do
        mp.add_forced_key_binding(keys[i], name .. "-" .. keys[i], fn)
    end
end

bind_many({"esc", "bs", "menu", "EPG", "GUIDE", "TV"}, "localcable-show-guide", show_guide)
bind_many({"i", "I"}, "localcable-info", toggle_banner)
mp.add_forced_key_binding("ENTER", "localcable-ok", toggle_banner)
mp.add_forced_key_binding("CHANNEL_UP", "localcable-ch-up", function() remote("channel-up") end)
mp.add_forced_key_binding("CHANNEL_DOWN", "localcable-ch-down", function() remote("channel-down") end)
for d = 0, 9 do
    local digit = tostring(d)
    mp.add_forced_key_binding(digit, "localcable-digit-" .. digit, function()
        remote("digit", digit)
    end)
end
