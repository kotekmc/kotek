"""
ATM10 Dashboard - Script de synchronisation (Version 2.0)
========================================================
- Extraction des Chunks chargés
- Fix FTB Quests & Iron's Spells
"""

import paramiko
import json
import os
import time
import getpass
import sys
import re
from datetime import datetime

try:
    from mcrcon import MCRcon
    RCON_AVAILABLE = True
except ImportError:
    RCON_AVAILABLE = False

# =============================================
# CONFIGURATION
# =============================================
SFTP_HOST     = "srv01.uniheberg.fr"
SFTP_PORT     = 2022
SFTP_USER     = "rafael.strummiello@gmail.com.dcc7d524"
RCON_HOST     = "srv01.uniheberg.fr"
RCON_PORT     = 25575
RCON_PASSWORD = "" # À saisir au lancement
MINECRAFT_PORT = 25505
REMOTE_STATS_PATH = "world/stats"
REMOTE_ADVANCEMENTS_PATH = "world/advancements"
REMOTE_FTB_TEAMS_PATH = "world/data/ftbteams"
OUTPUT_FILE = "data.json"

BOSS_NAMES = {
    "minecraft:ender_dragon": {"name": "Ender Dragon", "icon": "🐉"},
    "minecraft:wither": {"name": "Wither", "icon": "💀"},
    "minecraft:warden": {"name": "Warden", "icon": "🌑"},
    "cataclysm:the_harbinger": {"name": "The Harbinger", "icon": "⚡"},
    "cataclysm:netherite_monstrosity": {"name": "Netherite Monstrosity", "icon": "🔩"},
    "cataclysm:the_leviathan": {"name": "The Leviathan", "icon": "🌊"},
    "cataclysm:ancient_remnant": {"name": "Ancient Remnant", "icon": "🦴"},
    "cataclysm:ender_golem": {"name": "Ender Guardian", "icon": "🌀"},
    "cataclysm:ignis": {"name": "Ignis", "icon": "🔥"},
    "cataclysm:avaricia": {"name": "Avaricia", "icon": "💰"},
    "cataclysm:necronomicon": {"name": "Necronomicon", "icon": "📖"},
    "cataclysm:nameless_one": {"name": "The Nameless One", "icon": "👁️"},
    "twilightforest:naga": {"name": "Naga", "icon": "🐍"},
    "twilightforest:twilight_lich": {"name": "Twilight Lich", "icon": "🧙"},
    "twilightforest:hydra": {"name": "Hydra", "icon": "🔱"},
    "twilightforest:ur_ghast": {"name": "Ur-Ghast", "icon": "👻"},
    "twilightforest:snow_queen": {"name": "Snow Queen", "icon": "❄️"},
    "twilightforest:alpha_yeti": {"name": "Alpha Yeti", "icon": "🏔️"},
    "twilightforest:minoshroom": {"name": "Minoshroom", "icon": "🍄"},
    "twilightforest:knight_phantom": {"name": "Knight Phantom", "icon": "⚔️"},
    "aether:slider": {"name": "Slider (Bronze)", "icon": "🟫"},
    "aether:valkyrie_queen": {"name": "Valkyrie Queen", "icon": "🗡️"},
    "aether:sun_spirit": {"name": "Sun Spirit", "icon": "☀️"},
    "blue_skies:summoner": {"name": "Summoner", "icon": "🔮"},
    "blue_skies:alchemist": {"name": "Alchemist", "icon": "⚗️"},
    "blue_skies:starlit_crusher": {"name": "Starlit Crusher", "icon": "⭐"},
    "blue_skies:arachnarch": {"name": "Arachnarch", "icon": "🕷️"},
    "ars_nouveau:wilden_chimera": {"name": "Wilden Chimera", "icon": "🦁"},
}

def parse_player_stats(stats_json, adv_json, uuid):
    result = {
        "uuid": uuid,
        "playtime_ticks": 0,
        "mobs_killed": 0,
        "deaths": 0,
        "chunks_loaded": 0, # Nouvelle stat d'exploration
        "bosses": [],
        "ftb_quests_done": 0,
        "ftb_quests_total": 0,
        "spells": [],
        "stats": {}
    }

    if stats_json:
        stats = stats_json.get("stats", {})
        result["stats"] = stats
        custom = stats.get("minecraft:custom", {})
        result["playtime_ticks"] = custom.get("minecraft:play_time", 0) or custom.get("minecraft:play_one_minute", 0)
        result["deaths"] = custom.get("minecraft:deaths", 0)
        result["chunks_loaded"] = custom.get("minecraft:chunk_loaded", 0) # Extraction stat Exploration
        
        killed = stats.get("minecraft:killed", {})
        result["mobs_killed"] = sum(killed.values())
        for mob_id, info in BOSS_NAMES.items():
            if killed.get(mob_id, 0) > 0:
                result["bosses"].append({"name": info["name"], "icon": info["icon"], "count": killed[mob_id]})

    if adv_json:
        # Fix FTB Quests
        ftb_keys = [k for k in adv_json.keys() if k.startswith("ftbquests:")]
        result["ftb_quests_done"] = sum(1 for k in ftb_keys if adv_json[k].get("done"))
        result["ftb_quests_total"] = len(ftb_keys)

        # Fix Iron's Spells : Extraction du niveau via les critères
        spells_list = []
        for adv_key, adv_val in adv_json.items():
            if adv_key.startswith("irons_spellbooks:") and adv_val.get("done"):
                # Nettoyage de l'ID pour correspondre au JS du site
                s_id = adv_key.replace("spells/", "") if "spells/" in adv_key else adv_key
                level = 1
                criteria = adv_val.get("criteria", {})
                for crit_key in criteria:
                    match = re.search(r'level_(\d+)', crit_key)
                    if match: level = max(level, int(match.group(1)))
                spells_list.append({"id": s_id, "level": level})
        result["spells"] = spells_list

    return result

def ticks_to_human(ticks):
    seconds = ticks // 20
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days > 0: return f"{days}j {hours % 24}h"
    return f"{hours}h {minutes % 60}min" if hours > 0 else f"{minutes}min"

def get_rcon_data(rcon_pass):
    data = {"online_players": [], "online": False}
    if not RCON_AVAILABLE or not rcon_pass: return data
    try:
        with MCRcon(RCON_HOST, rcon_pass, port=RCON_PORT) as mcr:
            data["online"] = True
            resp = mcr.command("list")
            if "players online:" in resp:
                data["online_players"] = [n.strip() for n in resp.split("players online:")[-1].split(",") if n.strip()]
    except Exception: pass
    return data

def run_sync(sftp_pass, rcon_pass):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Sync...")
    rcon_data = get_rcon_data(rcon_pass)
    players_data = {}
    usercache = {}

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=sftp_pass)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        try:
            with sftp.open("usercache.json") as f:
                for e in json.load(f): usercache[e["uuid"].replace("-","")] = e["name"]
        except Exception: pass

        stat_files = sftp.listdir(REMOTE_STATS_PATH)
        for fname in stat_files:
            if not fname.endswith(".json"): continue
            uuid = fname.replace(".json","").replace("-","")
            with sftp.open(f"{REMOTE_STATS_PATH}/{fname}") as f: s_json = json.load(f)
            try:
                with sftp.open(f"{REMOTE_ADVANCEMENTS_PATH}/{fname}") as f: a_json = json.load(f)
            except: a_json = None
            
            p_stats = parse_player_stats(s_json, a_json, uuid)
            p_stats["name"] = usercache.get(uuid, uuid[:8])
            p_stats["playtime_human"] = ticks_to_human(p_stats["playtime_ticks"])
            p_stats["kd"] = round(p_stats["mobs_killed"] / max(p_stats["deaths"], 1), 1)
            players_data[uuid] = p_stats
        
        # FTB Teams
        teams_map = {}
        try:
            for tf in sftp.listdir(REMOTE_FTB_TEAMS_PATH):
                if not tf.endswith(".snbt"): continue
                with sftp.open(f"{REMOTE_FTB_TEAMS_PATH}/{tf}") as f:
                    content = f.read().decode("utf-8", errors="replace")
                    name_match = re.search(r'display_name:\s*"([^"]+)"', content)
                    m_match = re.search(r'members:\s*\[([^\]]*)\]', content, re.DOTALL)
                    if name_match and m_match:
                        team_n = name_match.group(1)
                        for u in re.findall(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', m_match.group(1)):
                            teams_map[u.replace("-","")] = team_n
        except: pass
        
        for u, p in players_data.items(): p["team"] = teams_map.get(u)
        sftp.close()
        transport.close()
    except Exception as e: print(f"Erreur SFTP: {e}")

    output = {
        "updated_at": datetime.now().isoformat(),
        "server": {"online": rcon_data["online"], "host": f"{SFTP_HOST}:{MINECRAFT_PORT}"},
        "players": list(players_data.values())
    }
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f: json.dump(output, f, indent=2)
    print("Done.")

if __name__ == "__main__":
    p_sftp = getpass.getpass("Pass SFTP: ")
    run_sync(p_sftp, "")