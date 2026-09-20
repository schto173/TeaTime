-- Tea Time v0.2
--
-- Watches for the "Welcoming Campfire" buff and reports JOIN / BEAT / LEAVE
-- events to Logs\General.log through C_Log, where the Tea Time Mumble plugin
-- (or tools/teatime_companion.py) picks them up.
--
-- Why the padding: the client buffers General.log (~50 KB) and only writes it
-- out when the buffer fills. Each event is therefore followed by enough
-- filler lines to push it to disk. Each log message is cut at ~4 KB, so
-- 14 filler lines of 4000 characters (~56 KB) always flush the event.
-- Every event costs roughly 57 KB of disk writes, so events are kept rare.

-- 1229739 is the 60 s "Welcoming Campfire" buff you get while sitting.
-- (1283391 is "Campfire nearby", the buff for standing next to a fire; it is
-- deliberately not used.) If SIT_BUFF_ID is nil the buff is matched by its
-- English name instead.
local SIT_BUFF_ID   = 1229739
local SIT_BUFF_NAME = "Welcoming Campfire"
local BEAT_SECONDS = 30       -- heartbeat interval while seated
local MIN_GAP      = 3        -- minimum seconds between heartbeat writes
local PAD_LINES    = 14
local PAD          = string.rep("x", 4000)

local seated   = false
local ticker   = nil
local lastEmit = 0
local verbose  = false

local function num(n, f)
    if n == nil then return "-" end
    return string.format(f or "%.1f", n)
end

-- Line format (one line, space separated):
-- TEATIME_E v2 <KIND> <mapID> <instanceID> <x> <y> <facing> <name>
-- x/y are world yards. UnitPosition returns y first, then x.
-- The name goes last because character names can contain spaces.
local function emit(kind)
    local y, x, _, inst = UnitPosition("player")
    local facing = GetPlayerFacing()
    local map = C_Map.GetBestMapForUnit("player")
    local name = (UnitName("player"))

    local line = string.format("TEATIME_E v2 %s %s %s %s %s %s %s",
        kind, map or "-", inst or "-",
        num(x), num(y), num(facing, "%.2f"), name or "-")

    C_Log.LogMessage(line)
    for _ = 1, PAD_LINES do
        C_Log.LogMessage("TEATIME_PAD " .. PAD)
    end

    lastEmit = GetTime()
    if verbose then print("|cffffd100TeaTime|r", line) end
end

local function hasCampfire()
    if SIT_BUFF_ID then
        return C_UnitAuras.GetPlayerAuraBySpellID(SIT_BUFF_ID) ~= nil
    end
    for i = 1, 40 do
        local a = C_UnitAuras.GetAuraDataByIndex("player", i, "HELPFUL")
        if not a then return false end
        if a.name == SIT_BUFF_NAME then return true end
    end
    return false
end

local function listAuras()
    print("|cffffd100TeaTime|r buffs on you:")
    for i = 1, 40 do
        local a = C_UnitAuras.GetAuraDataByIndex("player", i, "HELPFUL")
        if not a then break end
        print(i, a.name, a.spellId)
    end
end

-- The 60 s buff drops off and comes back while you stay seated, with a gap
-- of a few seconds. So a missing buff only counts as standing up if it is
-- still missing after GRACE seconds. Change it live: /teatime grace <seconds>
local GRACE = 15
local missingToken = 0
local waiting = false
local present = false
local goneAt = nil

local function startBeat()
    ticker = C_Timer.NewTicker(BEAT_SECONDS, function()
        if seated and (GetTime() - lastEmit) >= MIN_GAP then
            emit("BEAT")
        end
    end)
end

local function reallyLeft()
    seated = false
    waiting = false
    if ticker then ticker:Cancel() ticker = nil end
    emit("LEAVE")
end

local function update()
    local now = hasCampfire()

    -- verbose: report every disappear/appear together with the gap length
    if now ~= present then
        present = now
        if now then
            if verbose and goneAt then
                print(string.format("|cffffd100TeaTime|r buff back after %.1fs", GetTime() - goneAt))
            end
        else
            goneAt = GetTime()
            if verbose then print("|cffffd100TeaTime|r buff gone") end
        end
    end

    if now then
        if waiting then
            waiting = false
            missingToken = missingToken + 1  -- cancels the pending check
        end
        if not seated then
            seated = true
            emit("JOIN")
            startBeat()
        end
    elseif seated and not waiting then
        waiting = true
        missingToken = missingToken + 1
        local token = missingToken
        C_Timer.After(GRACE, function()
            if waiting and token == missingToken and not hasCampfire() then
                reallyLeft()
            end
        end)
    end
end

local frame = CreateFrame("Frame")
frame:RegisterUnitEvent("UNIT_AURA", "player")
frame:RegisterEvent("PLAYER_ENTERING_WORLD")
frame:SetScript("OnEvent", update)

SLASH_TEATIME1 = "/teatime"
SlashCmdList["TEATIME"] = function(msg)
    msg = (msg or ""):lower()
    if msg == "test" then
        emit("TEST")
    elseif msg:match("^grace%s+%d") then
        GRACE = tonumber(msg:match("^grace%s+([%d%.]+)")) or GRACE
        print("|cffffd100TeaTime|r grace set to " .. GRACE .. "s")
    elseif msg == "auras" then
        listAuras()
    elseif msg == "verbose" then
        verbose = not verbose
        print("|cffffd100TeaTime|r verbose " .. (verbose and "on" or "off"))
    else
        print("|cffffd100TeaTime|r seated=" .. tostring(seated)
            .. " grace=" .. GRACE .. "s"
            .. "  /teatime test | verbose | auras | grace <s>")
    end
end
