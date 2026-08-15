-- ScumBot — server-side UE4SS mod, Gegenstueck zum Python-Discord-Bot.
--
-- Verbindet den Discord-Bot mit dem laufenden Spiel: Taxi ("!taxi <ziel>" im
-- Chat), Shop-/Tagespaket-/Quest-/Briefkasten-Auslieferung, Admin-Konsole,
-- Item/Geld/Ruhm vergeben, Absprungkisten spawnen, Live-Positionen fuer die
-- Webkarte - alles per Datei-basierter Kommandoschnittstelle (commands.txt),
-- die der Python-Bot beschreibt und dieser Mod periodisch abarbeitet.
--
-- Enable: in ue4ss\Mods\mods.txt die Zeile   ScumBot : 1   hinzufuegen
-- (NIEMALS eine enabled.txt anlegen, die ueberschreibt mods.txt stillschweigend).
-- In ue4ss\UE4SS-settings.ini muessen HookProcessInternal=1 und
-- HookProcessLocalScriptFunction=1 gesetzt sein, sonst feuert der Chat-Hook nicht.

local ModName = "ScumBot"

-- Eigenen Ordner automatisch ermitteln (funktioniert auf jedem Laufwerk/Pfad)
local MOD_DIR
do
    local src = ((debug and debug.getinfo) and debug.getinfo(1, "S").source) or ""
    MOD_DIR = (src:gsub("^@", "")):match("^(.*)[/\\][^/\\]+[/\\][^/\\]+$")
end
local LOGFILE = MOD_DIR .. [[\ScumBot.log]]
local COMMANDS_FILE = MOD_DIR .. [[\commands.txt]]
local LIVE_POSITIONS_FILE = MOD_DIR .. [[\live_positions.txt]]
local VEHICLE_POSITIONS_FILE = MOD_DIR .. [[\vehicle_positions.txt]]
local ITEM_CHECK_RESULTS_FILE = MOD_DIR .. [[\item_check_results.txt]]

local function ts() return os.date("%Y-%m-%d %H:%M:%S") end
local function log(m)
    local line = "[" .. ModName .. "] " .. ts() .. " " .. tostring(m)
    print(line .. "\n")
    local f = io.open(LOGFILE, "a"); if f then f:write(line .. "\n"); f:close() end
end

do local f = io.open(LOGFILE, "w"); if f then f:write("===== " .. ModName .. " started :: " .. ts() .. " =====\n"); f:close() end end

-- ===================== TAXI-ZIELE =====================
-- Trag hier deine Fahrtziele ein: Name (klein geschrieben, wie im Chat getippt)
-- -> {X, Y, Z}. Muss mit config.TAXI_DESTINATIONS im Python-Bot uebereinstimmen!
local DESTINATIONS = {
    ["händler z3"] = { X = 24345.7298, Y = -674956.6459, Z = 5000 },
    ["händler a0"] = { X = -615444.9001, Y = -555564.8473, Z = 5000 },
    ["händler c2"] = { X = -152610.9187, Y = 290780.4085, Z = 5000 },
    ["händler b4"] = { X = 568791.2967, Y = -225382.5923, Z = 5000 },
    ["bunker b3"]  = { X = 148367.9779, Y = 553321.3426, Z = 5000 },
    ["bunker d0"]  = { X = -885484.008, Y = 597205.3267, Z = 5000 },
    ["bunker c1"]  = { X = -396972.1067, Y = 207721.8126, Z = 5000 },
    ["bunker b4"]  = { X = 434801.9531, Y = -6324.6462, Z = 5000 },
    ["bunker b0"]  = { X = -816553.5265, Y = -98097.9908, Z = 5000 },
    ["bunker a2"]  = { X = -27830.2734, Y = -330695.5314, Z = 5000 },
    ["bunker z2"]  = { X = -212385.7485, Y = -640491.4066, Z = 5000 },
    ["bunker z0"]  = { X = -715118.5547, Y = -789904.6922, Z = 5000 },
}

-- ===================== HILFSFUNKTIONEN =====================
local function pcs(fn, d) local ok, v = pcall(fn); if ok and v ~= nil then return v end; return d end
local function isValid(o) return o ~= nil and pcs(function() return o:IsValid() end, false) end

local CHAT_SERVERMESSAGE = 6
local function sendChatTo(chan, ctrl, msg)
    if not chan or not ctrl then return end
    local ps = pcs(function() return ctrl.PlayerState end, nil)
    pcall(function() chan:Chat_Client_SendMessageToChat(msg, ps, {}, CHAT_SERVERMESSAGE, false) end)
end

-- Bodenhoehe: feste Hoehe 0 hat sich in der Praxis als zuverlaessig
-- herausgestellt (automatische Line-Trace-Erkennung hat nicht funktioniert
-- und wurde wieder entfernt).
local FALLBACK_Z = 0

local function findGroundZ(worldContext, x, y)
    return FALLBACK_Z
end

-- ===================== ADMIN-PRUEFUNG GEZIELT UEBERSCHREIBEN =====================
-- IsUserAdmin() entscheidet, ob ein Admin-Befehl ausgefuehrt werden darf.
-- Wir haken diese Funktion und ueberschreiben das Ergebnis NUR fuer den einen
-- Controller, den wir gerade gezielt "durchwinken" (waehrend Starter-Paket/Shop
-- ausgefuehrt wird) - fuer alle anderen Spieler/Momente bleibt die echte Pruefung
-- unveraendert aktiv.
local bypassAdminForCtrl = nil

local okAdminHook, errAdminHook = pcall(function()
    RegisterHook("/Script/SCUM.ConZPlayerController:IsUserAdmin",
        function(Context) end,  -- Pre-Hook: nichts zu tun
        function(Context, ReturnValue)
            local self = pcs(function() return Context:get() end, nil)
            if self and bypassAdminForCtrl and self == bypassAdminForCtrl then
                ReturnValue:set(true)
            end
        end
    )
end)
log(okAdminHook and "IsUserAdmin-Hook installiert." or ("IsUserAdmin-Hook FEHLGESCHLAGEN: " .. tostring(errAdminHook)))

-- Fuehrt fn() aus, waehrend IsUserAdmin() fuer 'ctrl' auf true gesetzt wird.
local function withTemporaryAdmin(ctrl, fn)
    bypassAdminForCtrl = ctrl
    local ok, err = pcall(fn)
    bypassAdminForCtrl = nil
    if not ok then
        log("withTemporaryAdmin FEHLER: " .. tostring(err))
    end
end

-- Fuehrt einen ECHTEN SCUM-Admin-Befehl aus (z.B. "SpawnItem Backpack_01 1"),
-- genau so, als haette ein Admin ihn selbst im Chat getippt - inklusive aller
-- eingebauten Eigenheiten (Boden-Snapping bei Teleport, korrektes Item-Spawnen etc).
-- Gefunden im UE4SS-Objekt-Dump: PlayerRpcChannel:Chat_Server_ProcessAdminCommand(commandText).
-- WICHTIG: OHNE fuehrendes '#' aufrufen - das entfernt der Client vermutlich schon,
-- bevor der eigentliche RPC-Aufruf passiert (daher "Unrecognized command" mit '#').
local function runAdminCommand(chan, commandText)
    if not chan then return false end
    local cleanText = commandText:gsub("^#", "")  -- fuehrendes '#' entfernen, falls vorhanden
    local ok, err = pcall(function()
        chan:Chat_Server_ProcessAdminCommand(cleanText)
    end)
    if ok then
        log("Admin-Befehl gesendet: '" .. cleanText .. "'")
    else
        log("Admin-Befehl FEHLGESCHLAGEN: " .. commandText .. " -> " .. tostring(err))
    end
    return ok
end

-- ===================== TAXI-BEFEHL =====================
local function handleTaxi(chan, ctrl, destName)
    destName = destName:lower():gsub("^%s+", ""):gsub("%s+$", "")
    local dest = DESTINATIONS[destName]
    if not dest then
        local names = {}
        for k in pairs(DESTINATIONS) do names[#names + 1] = k end
        sendChatTo(chan, ctrl, "[Taxi] Unbekanntes Ziel. Verfuegbar: " .. table.concat(names, ", "))
        return
    end

    local pawn = pcs(function() return ctrl:K2_GetPawn() end, nil)
    if not isValid(pawn) then
        sendChatTo(chan, ctrl, "[Taxi] Konnte deinen Charakter nicht finden, versuch's nochmal.")
        return
    end

    local ok, err = pcall(function()
        local groundZ = findGroundZ(pawn, dest.X, dest.Y)
        pawn:K2_SetActorLocation({ X = dest.X, Y = dest.Y, Z = groundZ }, false, {}, false)
    end)

    if ok then
        sendChatTo(chan, ctrl, "[Taxi] 🚕 Unterwegs nach " .. destName .. "!")
        log("Taxi: Spieler teleportiert nach " .. destName)
    else
        sendChatTo(chan, ctrl, "[Taxi] Teleport fehlgeschlagen, sag das bitte einem Admin.")
        log("Taxi FEHLER: " .. tostring(err))
    end
end

-- ===================== CHAT-HOOK =====================
local TARGET = "/Script/SCUM.PlayerRpcChannel:Chat_Server_BroadcastChatMessage"
local okHook, errHook = pcall(function()
    RegisterHook(TARGET, function(self, messageParam, channelParam)
        local msg = ""
        pcall(function() msg = messageParam:get():ToString() end)
        if type(msg) ~= "string" or msg == "" then return end

        local lower = msg:lower()
        if lower:sub(1, 6) ~= "!taxi " and lower ~= "!taxi" then return end

        local chan = pcs(function() return self:get() end, nil)
        local ctrl = chan and pcs(function() return chan:GetOuter() end, nil) or nil
        if not chan or not ctrl then return end

        local destName = msg:sub(7)
        if destName == "" then
            local names = {}
            for k in pairs(DESTINATIONS) do names[#names + 1] = k end
            sendChatTo(chan, ctrl, "[Taxi] Nutzung: !taxi <ziel>. Verfuegbar: " .. table.concat(names, ", "))
            return
        end
        handleTaxi(chan, ctrl, destName)
    end)
end)
log(okHook and "ready: '!taxi <ziel>' Chat-Trigger installiert." or ("Chat-Hook FEHLGESCHLAGEN: " .. tostring(errHook)))

-- ===================== BROADCAST AN ALLE (fuer Neustart-Warnungen) =====================
local function broadcastToAll(msg)
    local controllers = FindAllOf("PlayerController")
    if not controllers then return 0 end
    local count = 0
    for i = 1, #controllers do
        local ctrl = controllers[i]
        if isValid(ctrl) then
            local ps = pcs(function() return ctrl.PlayerState end, nil)
            if ps then
                -- Wir brauchen einen "channel" (RpcChannel) fuer den Versand.
                -- Der haengt am PlayerController selbst als Komponente.
                local chan = pcs(function() return ctrl.PlayerRpcChannel end, nil)
                if chan then
                    pcall(function()
                        chan:Chat_Client_SendMessageToChat(msg, ps, {}, CHAT_SERVERMESSAGE, false)
                    end)
                    count = count + 1
                end
            end
        end
    end
    return count
end

-- Sucht einen aktuell verbundenen Spieler anhand seines Ingame-Namens.
-- Gibt ctrl zurueck (oder nil falls nicht online). chan wird separat und
-- best-effort ermittelt, blockiert den Teleport aber NICHT mehr, falls es
-- fehlschlaegt (nur die Bestaetigungsnachricht faellt dann weg).
local function getPlayerName(ps)
    if not ps then return nil end
    -- Weg 1: Standard-UE-Funktion GetPlayerName() (haeufigster Fall)
    local n = pcs(function() return ps:GetPlayerName() end, nil)
    if type(n) == "string" and n ~= "" then return n end
    -- Weg 2: privates Feld direkt (falls die Funktion nicht existiert/fehlschlaegt)
    local raw = pcs(function() return ps.PlayerNamePrivate end, nil)
    if type(raw) == "string" and raw ~= "" then return raw end
    if raw then
        local s = pcs(function() return raw:ToString() end, nil)
        if type(s) == "string" and s ~= "" then return s end
    end
    -- Weg 3: oeffentliches Feld (falls doch vorhanden)
    local raw2 = pcs(function() return ps.PlayerName end, nil)
    if type(raw2) == "string" and raw2 ~= "" then return raw2 end
    if raw2 then
        local s2 = pcs(function() return raw2:ToString() end, nil)
        if type(s2) == "string" and s2 ~= "" then return s2 end
    end
    return nil
end

local function findPlayerByName(playerName)
    local controllers = FindAllOf("PlayerController")
    if not controllers then return nil, nil end
    local seenNames = {}
    for i = 1, #controllers do
        local ctrl = controllers[i]
        if isValid(ctrl) then
            local ps = pcs(function() return ctrl.PlayerState end, nil)
            local name = getPlayerName(ps)
            seenNames[#seenNames + 1] = tostring(name) .. (ps == nil and " (PlayerState=nil)" or "")
            if name == playerName then
                local chan = pcs(function() return ctrl:GetPlayerRpcChannel() end, nil)
                return ctrl, chan
            end
        end
    end
    log("DEBUG: Gesucht '" .. tostring(playerName) .. "', gefundene Namen: [" .. table.concat(seenNames, ", ") .. "]")
    return nil, nil
end

-- Entfernt alle aktuell existierenden Sentries/Mechs von der Karte.
-- ACHTUNG: Klassenname "BP_Sentry_C" ist eine Vermutung (typisches SCUM-Namensschema),
-- nicht aus Referenzcode bestaetigt - unbedingt testen!
local function destroySentries()
    local count = 0
    for _, className in ipairs({ "BP_Sentry_C", "Sentry_C", "BP_TurretSentry_C" }) do
        local list = FindAllOf(className)
        if list then
            for i = 1, #list do
                local actor = list[i]
                if isValid(actor) then
                    local ok = pcall(function() actor:K2_DestroyActor() end)
                    if ok then count = count + 1 end
                end
            end
        end
    end
    return count
end

-- Entfernt alle per SPAWN_DROP_MARKER erzeugten (oder echten Weltereignis-)
-- Absprungkisten - zum Aufraeumen nach einem Test.
local function destroyDropCrates()
    local count = 0
    local list = FindAllOf("BP_DropZoneCrate_C")
    if list then
        for i = 1, #list do
            local actor = list[i]
            if isValid(actor) then
                local ok = pcall(function() actor:K2_DestroyActor() end)
                if ok then count = count + 1 end
            end
        end
    end
    return count
end

-- ===================== SICHTBARE ABGABE-MARKIERUNG (Tote Briefkaesten) =====================
-- Spawnt eine echte SCUM-Absprungkiste (dieselbe Klasse, die bei Weltereignis-
-- Loot-Abwuerfen benutzt wird: Fallschirm, faellt von selbst zu Boden) an einer
-- festen Weltkoordinate, damit Spieler den Abgabeort SEHEN statt nur eine
-- unsichtbare GPS-Zone zu haben. Ueber GameplayStatics:BeginSpawningActorFromClass/
-- FinishSpawningActor (per UE4SS-Objekt-Dump bestaetigt vorhanden, deferred-
-- Spawn-Pattern) - EXPERIMENTELL, noch nicht live getestet.
local DROP_CRATE_CLASS_PATH = "/Game/ConZ_Files/GameEvents/DropZone/BP_DropZoneCrate.BP_DropZoneCrate_C"

local function spawnDropCrate(x, y, z)
    local statics = pcs(function() return StaticFindObject("/Script/Engine.Default__GameplayStatics") end, nil)
    if not isValid(statics) then
        return false, "GameplayStatics-CDO nicht gefunden"
    end
    local worldCtx = pcs(function() return FindFirstOf("World") end, nil)
    if not isValid(worldCtx) then
        -- Fallback: irgendeinen online Spieler-Controller als World-Kontext nehmen
        worldCtx = pcs(function() return FindFirstOf("ConZPlayerController") end, nil)
    end
    if not isValid(worldCtx) then
        return false, "Kein World-Kontext gefunden (niemand online?)"
    end
    local actorClass = pcs(function() return StaticFindObject(DROP_CRATE_CLASS_PATH) end, nil)
    if not isValid(actorClass) then
        return false, "Klasse BP_DropZoneCrate_C nicht gefunden"
    end
    local transform = {
        Translation = { X = x, Y = y, Z = z },
        Rotation = { Pitch = 0, Yaw = 0, Roll = 0 },
        Scale3D = { X = 1, Y = 1, Z = 1 },
    }
    local ok, actorOrErr = pcall(function()
        return statics:BeginSpawningActorFromClass(worldCtx, actorClass, transform, true, nil)
    end)
    if not ok or not isValid(actorOrErr) then
        return false, "BeginSpawningActorFromClass fehlgeschlagen: " .. tostring(actorOrErr)
    end
    local actor = actorOrErr
    local ok2, err2 = pcall(function()
        statics:FinishSpawningActor(actor, transform)
    end)
    if not ok2 then
        return false, "FinishSpawningActor fehlgeschlagen: " .. tostring(err2)
    end
    return true, "OK"
end

-- ===================== ITEM-ERKENNUNG (Tote Briefkaesten/Quests) =====================
-- Sucht freie (nicht angelegte/nicht im Inventar befindliche) Items einer
-- bestimmten Klasse innerhalb eines Radius um eine Koordinate. "Frei" wird
-- daran erkannt, dass _attachParentObject nicht gesetzt ist (kein Charakter/
-- Container haelt das Item gerade). Basiert auf der SCUM.Item-Basisklasse
-- (per UE4SS-Objekt-Dump bestaetigt vorhanden) - NICHT live im Spiel getestet.
-- Falls der Klassenname-Abgleich (itemId .. "_C") nicht zuverlaessig matcht,
-- bitte Rueckmeldung, dann passen wir das Suffix/Praefix an.
local function findNearbyFreeItems(itemClassName, x, y, z, radius)
    local matches = {}
    local items = FindAllOf("Item")
    if not items then return matches end
    for i = 1, #items do
        local item = items[i]
        if isValid(item) then
            local parent = pcs(function() return item._attachParentObject end, nil)
            local isFree = not isValid(parent)
            if isFree then
                local className = pcs(function() return item:GetClass():GetFName():ToString() end, nil)
                if className == itemClassName then
                    local loc = pcs(function() return item:K2_GetActorLocation() end, nil)
                    if loc then
                        -- Nur 2D-Abstand (X/Y) - Hoehe (Z) ist fuer die Naehe-Pruefung irrelevant
                        local dx, dy = loc.X - x, loc.Y - y
                        local dist = math.sqrt(dx * dx + dy * dy)
                        if dist <= radius then
                            matches[#matches + 1] = item
                        end
                    end
                end
            end
        end
    end
    return matches
end

-- ===================== STARTER-PAKET-ITEMS =====================
-- type "item" -> #SpawnItem <id> <amount>
-- type "vehicle" -> #SpawnVehicle <id> (kein amount-Parameter)
local STARTER_KIT_SPAWN_LIST = {
    { type = "vehicle", id = "BPC_MountainBike" },
    { type = "item", id = "Backpack_02_02", amount = 1 },
    { type = "item", id = "Military_Shirt_01", amount = 1 },
    { type = "item", id = "Jeans_01_03", amount = 1 },
    { type = "item", id = "Hiking_Boots_02", amount = 1 },
    { type = "item", id = "Baseball_Cap_01", amount = 1 },
    { type = "item", id = "1H_Hunter", amount = 1 },
    { type = "item", id = "2H_Baseball_Bat", amount = 1 },
    { type = "item", id = "MRE_Stew", amount = 2 },
    { type = "item", id = "Canteen", amount = 1 },
    { type = "item", id = "Emergency_Bandage_Big", amount = 1 },
    { type = "item", id = "Lock_Item_Basic", amount = 1 },
}

-- ===================== KOMMANDO-DATEI POLLEN =====================
-- Der Python-Bot haengt Zeilen an COMMANDS_FILE an:
--   ANNOUNCE|<Nachricht>                       -> an alle Spieler
--   TELEPORT|<Spielername>|<X>|<Y>|<Z>         -> per Discord ausgeloestes Taxi
--   DESTROY_SENTRIES|                          -> alle Sentries/Mechs entfernen
-- Wir lesen sie alle 3 Sekunden, verarbeiten sie und leeren die Datei danach.
LoopAsync(3000, function()
    local f = io.open(COMMANDS_FILE, "r")
    if f then
        local content = f:read("*a")
        f:close()
        if content and content ~= "" then
            for line in content:gmatch("[^\r\n]+") do
                local cmdType, payload = line:match("^([%u_]+)|(.*)$")
                if cmdType == "ANNOUNCE" and payload then
                    local n = broadcastToAll(payload)
                    log("ANNOUNCE an " .. n .. " Spieler gesendet: " .. payload)
                elseif cmdType == "DISCORD_CHAT" and payload then
                    local n = broadcastToAll("[Discord] " .. payload)
                    log("DISCORD_CHAT an " .. n .. " Spieler gesendet: " .. payload)
                elseif cmdType == "TELEPORT" and payload then
                    local name, xs, ys, zs = payload:match("^(.-)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)$")
                    if name then
                        local ctrl, chan = findPlayerByName(name)
                        if ctrl then
                            local pawn = pcs(function() return ctrl:K2_GetPawn() end, nil)
                            if isValid(pawn) then
                                local ok = pcall(function()
                                    local groundZ = findGroundZ(pawn, tonumber(xs), tonumber(ys))
                                    pawn:K2_SetActorLocation(
                                        { X = tonumber(xs), Y = tonumber(ys), Z = groundZ },
                                        false, {}, false
                                    )
                                end)
                                if ok then
                                    log("Discord-Taxi: " .. name .. " teleportiert nach " .. xs .. "," .. ys .. "," .. zs)
                                    -- Bestaetigung nur best-effort, blockiert den Teleport nicht
                                    if chan then sendChatTo(chan, ctrl, "[Taxi] 🚕 Von Discord aus teleportiert!") end
                                else
                                    log("Discord-Taxi FEHLER bei Teleport fuer " .. name)
                                end
                            else
                                log("Discord-Taxi: Pawn von '" .. name .. "' nicht gefunden.")
                            end
                        else
                            log("Discord-Taxi: Spieler '" .. name .. "' nicht online, ignoriert.")
                        end
                    end
                elseif cmdType == "DESTROY_SENTRIES" then
                    local n = destroySentries()
                    log("DESTROY_SENTRIES: " .. n .. " Sentries entfernt.")
                elseif cmdType == "DESTROY_DROP_CRATES" then
                    local n = destroyDropCrates()
                    log("DESTROY_DROP_CRATES: " .. n .. " Absprungkisten entfernt.")
                elseif cmdType == "DUMP_OBJECTS" then
                    local ok, err = pcall(function() DumpAllObjects() end)
                    log(ok and "DUMP_OBJECTS: UE4SS_ObjectDump.txt wird erzeugt (kann etwas dauern)..."
                           or ("DUMP_OBJECTS FEHLER: " .. tostring(err)))
                elseif cmdType == "ADMIN_CMD" and payload then
                    -- Format: Spielername|roher Befehlstext (ohne '#')
                    -- Wie BUY_ITEM/STARTER_KIT ueber withTemporaryAdmin ausgefuehrt,
                    -- damit das auch OHNE echten AdminUsers.ini-Eintrag (also ohne
                    -- AMP) funktioniert - der Aufrufer muss also kein echter Admin sein.
                    local name, rawCmd = payload:match("^(.-)|(.*)$")
                    if name and rawCmd then
                        local ctrl, chan = findPlayerByName(name)
                        if ctrl and chan then
                            withTemporaryAdmin(ctrl, function()
                                runAdminCommand(chan, rawCmd)
                            end)
                            log("ADMIN_CMD: '" .. rawCmd .. "' fuer " .. name .. " ausgefuehrt.")
                        else
                            log("ADMIN_CMD: Spieler '" .. name .. "' nicht online, ignoriert.")
                        end
                    end
                elseif cmdType == "STARTER_KIT" and payload then
                    local name = payload
                    local ctrl, chan = findPlayerByName(name)
                    if ctrl and chan then
                        withTemporaryAdmin(ctrl, function()
                            for _, entry in ipairs(STARTER_KIT_SPAWN_LIST) do
                                if entry.type == "vehicle" then
                                    runAdminCommand(chan, "#SpawnVehicle " .. entry.id)
                                else
                                    runAdminCommand(chan, "#SpawnItem " .. entry.id .. " " .. tostring(entry.amount or 1))
                                end
                            end
                        end)
                        sendChatTo(chan, ctrl, "[Starter-Paket] 🎒 Dein Starter-Paket ist da!")
                        log("STARTER_KIT: an " .. name .. " ausgegeben.")
                    else
                        log("STARTER_KIT: Spieler '" .. name .. "' nicht online, ignoriert.")
                    end
                elseif cmdType == "ITEM_CHECK" and payload then
                    -- Format: requestId|X|Y|Z|Radius|itemId|Menge|DryRun(0/1)
                    -- DryRun=1 prueft nur (zerstoert NICHTS) - fuer Faelle, in denen
                    -- erst ALLE Anforderungen erfuellt sein muessen, bevor irgendwas
                    -- verbraucht wird (z.B. Tote Briefkaesten mit mehreren Artikeln).
                    local requestId, xs, ys, zs, rs, itemId, amountS, dryRunS =
                        payload:match("^(.-)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)|(.-)|(%d+)|(%d)$")
                    if requestId then
                        local x, y, z = tonumber(xs), tonumber(ys), tonumber(zs)
                        local radius, amount = tonumber(rs), tonumber(amountS)
                        local dryRun = dryRunS == "1"
                        local ok, matches = pcall(findNearbyFreeItems, itemId .. "_C", x, y, z, radius)
                        local foundCount = (ok and matches) and #matches or 0
                        local success = ok and foundCount >= amount
                        if success and not dryRun then
                            for i = 1, amount do
                                pcall(function() matches[i]:K2_DestroyActor() end)
                            end
                        end
                        local f = io.open(ITEM_CHECK_RESULTS_FILE, "a")
                        if f then
                            f:write(requestId .. "|" .. tostring(success) .. "|" .. tostring(foundCount) .. "\n")
                            f:close()
                        end
                        log("ITEM_CHECK " .. requestId .. (dryRun and " (dry-run)" or "") .. ": " .. itemId ..
                            " x" .. amount .. " -> gefunden=" .. foundCount .. " erfolg=" .. tostring(success))
                    end
                elseif cmdType == "ITEM_SCAN" and payload then
                    -- DIAGNOSE: Format requestId|X|Y|Z|Radius - listet ALLE Item-Klassennamen
                    -- in der Naehe auf (frei oder angelegt), um den echten Klassennamen fuer
                    -- ITEM_CHECK zu ermitteln.
                    local requestId, xs, ys, zs, rs = payload:match("^(.-)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)$")
                    if requestId then
                        local x, y, z, radius = tonumber(xs), tonumber(ys), tonumber(zs), tonumber(rs)
                        local found = {}
                        pcall(function()
                            local items = FindAllOf("Item")
                            if items then
                                for i = 1, #items do
                                    local item = items[i]
                                    if isValid(item) then
                                        local loc = pcs(function() return item:K2_GetActorLocation() end, nil)
                                        if loc then
                                            -- Nur 2D-Abstand (X/Y), konsistent mit ITEM_CHECK - Z spielt keine Rolle
                                            local dx, dy = loc.X - x, loc.Y - y
                                            local dist = math.sqrt(dx * dx + dy * dy)
                                            if dist <= radius then
                                                local parent = pcs(function() return item._attachParentObject end, nil)
                                                local isFree = not isValid(parent)
                                                local className = pcs(function() return item:GetClass():GetFName():ToString() end, nil)
                                                found[#found + 1] = tostring(className) .. (isFree and ":frei" or ":angelegt") ..
                                                    ":" .. math.floor(dist) .. "m"
                                            end
                                        end
                                    end
                                end
                            end
                        end)
                        local f = io.open(ITEM_CHECK_RESULTS_FILE, "a")
                        if f then
                            f:write(requestId .. "|SCAN|" .. table.concat(found, ";") .. "\n")
                            f:close()
                        end
                        log("ITEM_SCAN " .. requestId .. ": " .. #found .. " Items in der Naehe gefunden.")
                    end
                elseif cmdType == "BUY_ITEM" and payload then
                    -- Format: Spielername|type|itemId|amount
                    local name, itemType, itemId, amount = payload:match("^(.-)|(.-)|(.-)|(%d+)$")
                    if name then
                        local ctrl, chan = findPlayerByName(name)
                        if ctrl and chan then
                            withTemporaryAdmin(ctrl, function()
                                if itemType == "vehicle" then
                                    runAdminCommand(chan, "#SpawnVehicle " .. itemId)
                                else
                                    runAdminCommand(chan, "#SpawnItem " .. itemId .. " " .. amount)
                                end
                            end)
                            sendChatTo(chan, ctrl, "[Shop] 🛒 Dein Kauf ist da!")
                            log("BUY_ITEM: " .. itemId .. " x" .. amount .. " an " .. name .. " ausgegeben.")
                        else
                            log("BUY_ITEM: Spieler '" .. name .. "' nicht online, ignoriert.")
                        end
                    end
                elseif cmdType == "GRANT_CURRENCY" and payload then
                    -- Format: Spielername|CurrencyType(1=Normal,2=Gold)|neuerKontostand
                    -- Setzt das Bankguthaben direkt am PlayerController (SetCurrencyBalanceRep),
                    -- damit es sofort im laufenden Spiel ankommt (die DB allein wird vom
                    -- Server waehrend der Session nicht neu eingelesen). Nur wirksam, wenn
                    -- der Spieler gerade online ist - die DB wurde vom Bot bereits aktualisiert.
                    local name, ctypeS, balanceS = payload:match("^(.-)|(%d+)|(%-?%d+)$")
                    if name then
                        local ctrl = findPlayerByName(name)
                        if ctrl then
                            local ok = pcall(function()
                                ctrl:SetCurrencyBalanceRep(tonumber(ctypeS), tonumber(balanceS))
                            end)
                            log("GRANT_CURRENCY: " .. name .. " Typ " .. ctypeS .. " -> " .. balanceS ..
                                " (" .. tostring(ok) .. ")")
                        else
                            log("GRANT_CURRENCY: Spieler '" .. name .. "' nicht online, nur DB aktualisiert.")
                        end
                    end
                elseif cmdType == "GRANT_FAME" and payload then
                    -- Format: Spielername|neuerRuhmwert
                    local name, valueS = payload:match("^(.-)|(%-?[%d.]+)$")
                    if name then
                        local ctrl = findPlayerByName(name)
                        if ctrl then
                            local ok = pcall(function()
                                ctrl:SetFamePoints(tonumber(valueS))
                            end)
                            log("GRANT_FAME: " .. name .. " -> " .. valueS .. " (" .. tostring(ok) .. ")")
                        else
                            log("GRANT_FAME: Spieler '" .. name .. "' nicht online, nur DB aktualisiert.")
                        end
                    end
                elseif cmdType == "SPAWN_DROP_MARKER" and payload then
                    -- Format: requestId|X|Y|Z (Z hoch ansetzen, z.B. 3000-5000,
                    -- damit die Kiste wie bei einem echten Loot-Abwurf per
                    -- Fallschirm zu Boden faellt statt im Terrain zu stecken)
                    local requestId, xs, ys, zs = payload:match("^(.-)|([%-%d.]+)|([%-%d.]+)|([%-%d.]+)$")
                    if requestId then
                        local x, y, z = tonumber(xs), tonumber(ys), tonumber(zs)
                        local ok, msg = spawnDropCrate(x, y, z)
                        log("SPAWN_DROP_MARKER " .. requestId .. ": " .. tostring(ok) .. " (" .. msg .. ")")
                        local f = io.open(ITEM_CHECK_RESULTS_FILE, "a")
                        if f then
                            f:write(requestId .. "|SPAWN|" .. tostring(ok) .. "|" .. msg .. "\n")
                            f:close()
                        end
                    end
                end
            end
            -- Datei leeren, damit Kommandos nicht mehrfach ausgefuehrt werden
            local wf = io.open(COMMANDS_FILE, "w")
            if wf then wf:close() end
        end
    end
    return false -- weiter loopen
end)

-- ===================== LIVE-POSITIONEN FUER DIE WEBKARTE =====================
-- Schreibt alle 8 Sekunden Name+Position aller verbundenen Spieler in eine
-- Datei, die die Webseite (webapp/app.py) periodisch ausliest.
-- Format je Zeile: Spielername|X|Y|Z
LoopAsync(8000, function()
    local ok, err = pcall(function()
        local controllers = FindAllOf("PlayerController")
        local lines = {}
        if controllers then
            for i = 1, #controllers do
                local ctrl = controllers[i]
                if isValid(ctrl) then
                    local ps = pcs(function() return ctrl.PlayerState end, nil)
                    local name = getPlayerName(ps)
                    local pawn = pcs(function() return ctrl:K2_GetPawn() end, nil)
                    if name and pawn and isValid(pawn) then
                        local loc = pcs(function() return pawn:K2_GetActorLocation() end, nil)
                        if loc then
                            lines[#lines + 1] = name .. "|" .. tostring(loc.X) .. "|" .. tostring(loc.Y) .. "|" .. tostring(loc.Z)
                        end
                    end
                end
            end
        end
        local f = io.open(LIVE_POSITIONS_FILE, "w")
        if f then
            f:write(table.concat(lines, "\n"))
            f:close()
        end
    end)
    if not ok then
        log("LIVE_POSITIONS FEHLER: " .. tostring(err))
    end
    return false -- weiter loopen
end)

-- ===================== FAHRZEUG-POSITIONEN FUER DIE WEBKARTE =====================
-- Schreibt alle 15 Sekunden Name+Position aller Fahrzeuge in eine Datei.
-- Format je Zeile: Fahrzeugname|X|Y|Z
LoopAsync(15000, function()
    local ok, err = pcall(function()
        local vehicles = FindAllOf("DcxWheeledVehicle")
        local lines = {}
        if vehicles then
            for i = 1, #vehicles do
                local v = vehicles[i]
                if isValid(v) then
                    local loc = pcs(function() return v:K2_GetActorLocation() end, nil)
                    local className = pcs(function() return v:GetClass():GetFName():ToString() end, nil)
                    if loc and className then
                        -- 'BPC_WolfsWagen_C' / 'BP_Pickup_01_A_C' -> lesbarer Name
                        local cleanName = className:gsub("^BPC?_", ""):gsub("_C$", ""):gsub("_", " ")
                        lines[#lines + 1] = cleanName .. "|" .. tostring(loc.X) .. "|" .. tostring(loc.Y) .. "|" .. tostring(loc.Z)
                    end
                end
            end
        end
        local f = io.open(VEHICLE_POSITIONS_FILE, "w")
        if f then
            f:write(table.concat(lines, "\n"))
            f:close()
        end
    end)
    if not ok then
        log("VEHICLE_POSITIONS FEHLER: " .. tostring(err))
    end
    return false -- weiter loopen
end)

log("=====================================================")
log(ModName .. " ist geladen. '!taxi <ziel>' im Chat testen.")
log("=====================================================")
