"""
ATM10 Dashboard - Script de synchronisation
============================================
Ce script récupère les données de ton serveur UniHeberg via SFTP + RCON
et génère un fichier data.json lu par le site web.

Prérequis (installe une seule fois) :
  pip install paramiko mcrcon

Usage :
  python sync_atm10.py
  (ou via sync_atm10.bat pour l'automatiser)
"""

import paramiko
import json
import os
import time
import getpass
import sys
from datetime import datetime

try:
    from mcrcon import MCRcon
    RCON_AVAILABLE = True
except ImportError:
    RCON_AVAILABLE = False
    print("[AVERTISSEMENT] mcrcon non installé. Installe-le avec : pip install mcrcon")

# =============================================
# CONFIGURATION — modifie ces valeurs
# =============================================
SFTP_HOST     = "srv01.uniheberg.fr"
SFTP_PORT     = 2022
SFTP_USER     = "rafael.strummiello@gmail.com.dcc7d524"
# Le mot de passe SFTP est demandé au lancement (jamais stocké ici)

RCON_HOST     = "srv01.uniheberg.fr"
RCON_PORT     = 25575
RCON_PASSWORD = ""  # Laisse vide → sera demandé au lancement ou mis dans .env

MINECRAFT_PORT = 25505

# Chemin vers le dossier stats sur le serveur (Pterodactyl)
REMOTE_STATS_PATH = "world/stats"
REMOTE_ADVANCEMENTS_PATH = "world/advancements"

# Fichier de sortie lu par le site web
OUTPUT_FILE = "data.json"

# Noms des boss moddés ATM10 — IDs exacts Minecraft (namespace:entity_id)
BOSS_NAMES = {
    # Vanilla
    "minecraft:ender_dragon":              {"name": "Ender Dragon",          "icon": "🐉"},
    "minecraft:wither":                    {"name": "Wither",                "icon": "💀"},
    "minecraft:warden":                    {"name": "Warden",                "icon": "🌑"},
    # L'Ender's Cataclysm
    "cataclysm:the_harbinger":             {"name": "The Harbinger",         "icon": "⚡"},
    "cataclysm:netherite_monstrosity":     {"name": "Netherite Monstrosity", "icon": "🔩"},
    "cataclysm:the_leviathan":             {"name": "The Leviathan",         "icon": "🌊"},
    "cataclysm:ancient_remnant":           {"name": "Ancient Remnant",       "icon": "🦴"},
    "cataclysm:ender_golem":               {"name": "Ender Guardian",        "icon": "🌀"},
    "cataclysm:ignis":                     {"name": "Ignis",                 "icon": "🔥"},
    "cataclysm:avaricia":                  {"name": "Avaricia",              "icon": "💰"},
    "cataclysm:necronomicon":              {"name": "Necronomicon",          "icon": "📖"},
    "cataclysm:nameless_one":              {"name": "The Nameless One",      "icon": "👁️"},
    # Twilight Forest
    "twilightforest:naga":                 {"name": "Naga",                  "icon": "🐍"},
    "twilightforest:twilight_lich":        {"name": "Twilight Lich",         "icon": "🧙"},
    "twilightforest:hydra":                {"name": "Hydra",                 "icon": "🔱"},
    "twilightforest:ur_ghast":             {"name": "Ur-Ghast",              "icon": "👻"},
    "twilightforest:snow_queen":           {"name": "Snow Queen",            "icon": "❄️"},
    "twilightforest:alpha_yeti":           {"name": "Alpha Yeti",            "icon": "🏔️"},
    "twilightforest:minoshroom":           {"name": "Minoshroom",            "icon": "🍄"},
    "twilightforest:knight_phantom":       {"name": "Knight Phantom",        "icon": "⚔️"},
    # The Aether
    "aether:slider":                       {"name": "Slider (Bronze)",       "icon": "🟫"},
    "aether:valkyrie_queen":               {"name": "Valkyrie Queen",        "icon": "🗡️"},
    "aether:sun_spirit":                   {"name": "Sun Spirit",            "icon": "☀️"},
    # Blue Skies
    "blue_skies:summoner":                 {"name": "Summoner",              "icon": "🔮"},
    "blue_skies:alchemist":                {"name": "Alchemist",             "icon": "⚗️"},
    "blue_skies:starlit_crusher":          {"name": "Starlit Crusher",       "icon": "⭐"},
    "blue_skies:arachnarch":               {"name": "Arachnarch",            "icon": "🕷️"},
    # Ars Nouveau
    "ars_nouveau:wilden_chimera":          {"name": "Wilden Chimera",        "icon": "🦁"},
}

# Chemins FTB Teams — données stockées dans world/data/ftbteams/
REMOTE_FTB_TEAMS_PATH = "world/data/ftbteams"
# Chemin FTB Quests — progression par équipe
REMOTE_FTB_QUESTS_PATH = "world/ftbquests"
# Config quêtes (définition des quêtes — pour compter le total)
REMOTE_FTB_QUESTS_CONFIG = "config/ftbquests/quests"
# =============================================

def load_env():
    """Charge .env si présent pour éviter de retaper les mots de passe"""
    env = {}
    if os.path.exists(".env"):
        with open(".env") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env

def get_credentials(env):
    """Récupère les mots de passe depuis .env, variables d'environnement OS, ou les demande"""
    # Priorité : variable d'environnement OS (GitHub Actions) > .env > saisie manuelle
    import os as _os
    sftp_pass = _os.environ.get("SFTP_PASSWORD") or env.get("SFTP_PASSWORD") or getpass.getpass("Mot de passe SFTP : ")
    rcon_pass = env.get("RCON_PASSWORD") or RCON_PASSWORD or ""
    return sftp_pass, rcon_pass

def get_rcon_data(rcon_pass):
    """Récupère les données en direct via RCON"""
    data = {
        "online_players": [],
        "tps": None,
        "online": False
    }
    if not RCON_AVAILABLE:
        return data
    try:
        with MCRcon(RCON_HOST, rcon_pass, port=RCON_PORT) as mcr:
            data["online"] = True
            # Joueurs en ligne
            resp = mcr.command("list")
            # Format: "There are X of a max of Y players online: name1, name2"
            if "players online:" in resp:
                names_part = resp.split("players online:")[-1].strip()
                data["online_players"] = [n.strip() for n in names_part.split(",") if n.strip()]
            # TPS
            try:
                tps_resp = mcr.command("forge tps")
                # Cherche "Mean TPS: XX.XX"
                for line in tps_resp.split("\n"):
                    if "Mean TPS" in line or "Overall" in line:
                        parts = line.split(":")
                        if len(parts) > 1:
                            val = parts[-1].strip().split()[0]
                            data["tps"] = float(val)
                            break
            except Exception:
                pass
    except Exception as e:
        print(f"[RCON] Connexion impossible : {e}")
    return data

def parse_player_stats(stats_json, adv_json, uuid):
    """Parse les fichiers stats et advancements d'un joueur"""
    result = {
        "uuid": uuid,
        "playtime_ticks": 0,
        "mobs_killed": 0,
        "deaths": 0,
        "bosses": [],
        "advancements_done": 0,
        "advancements_total": 0,
        "ores_mined": 0,
        "crafts_done": 0,
        "chunks_explored": 0,
        "stats": {},
    }

    # Stats
    if stats_json:
        stats = stats_json.get("stats", {})
        # Exporter les stats brutes pour le site (minerais, crafts, boss détaillés)
        result["stats"] = stats

        # Temps de jeu (en ticks, 20 ticks = 1 seconde)
        custom = stats.get("minecraft:custom", {})
        result["playtime_ticks"] = custom.get("minecraft:play_time", 0) or custom.get("minecraft:play_one_minute", 0)
        # Morts
        result["deaths"] = custom.get("minecraft:deaths", 0)
        # Mobs tués
        killed = stats.get("minecraft:killed", {})
        result["mobs_killed"] = sum(killed.values())
        # Boss moddés
        for mob_id, boss_info in BOSS_NAMES.items():
            count = killed.get(mob_id, 0)
            if count > 0:
                result["bosses"].append({
                    "name": boss_info["name"],
                    "icon": boss_info["icon"],
                    "count": count
                })
        # Minerais minés
        mined = stats.get("minecraft:mined", {})
        ore_keywords = ["ore", "raw_iron", "raw_copper", "raw_gold", "ancient_debris",
                        "nether_quartz", "coal", "lapis", "redstone", "diamond", "emerald",
                        "allthemodium", "vibranium", "unobtainium", "osmium", "tin",
                        "lead", "silver", "nickel", "zinc", "uranium", "certus", "fluorite"]
        result["ores_mined"] = sum(
            v for k, v in mined.items()
            if any(kw in k for kw in ore_keywords)
        )
        # Crafts réalisés
        crafted = stats.get("minecraft:crafted", {})
        result["crafts_done"] = sum(crafted.values())

        # Chunks explorés — stat native Minecraft
        result["chunks_explored"] = custom.get("minecraft:chunks_loaded", 0)

        # Iron's Spells 'n Spellbooks — sorts débloqués via advancements
        # Les advancements du mod ont la forme : irons_spellbooks:spells/<spell_id>/obtained
        # On collecte les sorts depuis adv_json (passé en argument)
        spells_list = []
        # On les extrait séparément dans parse_player_stats via adv_json
        result["spells"] = spells_list  # sera rempli après via advancements

    # Advancements — source pour Iron's Spells ET FTB Quests ET progression générale
    if adv_json:
        # Advancements génériques Minecraft
        done = sum(1 for v in adv_json.values() if isinstance(v, dict) and v.get("done") is True)
        total = len([v for v in adv_json.values() if isinstance(v, dict) and "done" in v])
        result["advancements_done"] = done
        result["advancements_total"] = max(total, 1)

        # ── Iron's Spells : sorts débloqués ──
        # Les advancements de VRAIS SORTS ont EXACTEMENT la forme :
        #   "irons_spellbooks:spells/<spell_name>"
        # Ex: "irons_spellbooks:spells/fireball", "irons_spellbooks:spells/ice_lance"
        # Les achievements génériques du mod (ink_root, make_inscription_table…) ont la forme
        #   "irons_spellbooks:irons_spellbooks/<achievement>" → on les IGNORE
        spells_list = []
        import re as _re
        for adv_key, adv_val in adv_json.items():
            if not isinstance(adv_val, dict):
                continue
            if not adv_val.get("done", False):
                continue
            # Uniquement les advancements de la catégorie "spells/"
            if not adv_key.startswith("irons_spellbooks:spells/"):
                continue
            # Extraire le nom du sort : "irons_spellbooks:spells/fireball" → "irons_spellbooks:fireball"
            spell_name = adv_key.split("irons_spellbooks:spells/", 1)[1].split("/")[0]
            spell_id = f"irons_spellbooks:{spell_name}"

            # Chercher le niveau dans les critères (ex: "level_5": {"done": true})
            level = 1
            criteria = adv_val.get("criteria", {})
            for crit_key, crit_val in criteria.items():
                if not isinstance(crit_val, dict) or not crit_val.get("done", False):
                    continue
                m = _re.search(r'level[_\s]?(\d+)', crit_key, _re.IGNORECASE)
                if m:
                    lvl = int(m.group(1))
                    if lvl > level:
                        level = lvl

            spells_list.append({"id": spell_id, "level": level})

        result["spells"] = spells_list
        if spells_list:
            print(f"    → {len(spells_list)} sorts Iron's Spells trouvés pour {uuid}")

        # ── FTB Quests : progression ──
        # FTB Quests NE stocke PAS sa progression dans les advancements Minecraft.
        # Elle est dans world/ftbquests/data/<uuid>.snbt (ou .json selon la version).
        # On remet ftb_quests_done/total à 0 ici ; ils seront remplis dans run_sync()
        # après lecture des fichiers ftbquests séparés.
        result["ftb_quests_done"] = 0
        result["ftb_quests_total"] = 0

    return result

def ticks_to_human(ticks):
    """Convertit des ticks Minecraft en texte lisible"""
    seconds = ticks // 20
    minutes = seconds // 60
    hours = minutes // 60
    days = hours // 24
    if days > 0:
        return f"{days}j {hours % 24}h"
    elif hours > 0:
        return f"{hours}h {minutes % 60}min"
    else:
        return f"{minutes}min"

def get_player_name_from_uuid(uuid):
    """Tente de récupérer le pseudo depuis usercache.json (chargé séparément)"""
    return uuid[:8]  # fallback

def run_sync(sftp_pass, rcon_pass):
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Synchronisation en cours...")

    # 1. Données RCON (joueurs en ligne, TPS)
    rcon_data = get_rcon_data(rcon_pass)
    print(f"  → Serveur {'EN LIGNE' if rcon_data['online'] else 'HORS LIGNE'}")
    print(f"  → Joueurs en ligne : {rcon_data['online_players']}")

    # 2. Données SFTP (fichiers stats joueurs)
    players_data = {}
    usercache = {}

    try:
        transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport.connect(username=SFTP_USER, password=sftp_pass)
        sftp = paramiko.SFTPClient.from_transport(transport)
        print(f"  → Connecté en SFTP")

        # Charger usercache.json (pseudo ↔ UUID)
        try:
            with sftp.open("usercache.json") as f:
                cache = json.load(f)
                for entry in cache:
                    uid = entry.get("uuid", "").replace("-", "")
                    usercache[uid] = entry.get("name", uid[:8])
        except Exception:
            print("  → usercache.json non trouvé, utilisation des UUIDs")

        # Lister les fichiers stats
        try:
            stat_files = sftp.listdir(REMOTE_STATS_PATH)
        except Exception:
            stat_files = []
            print(f"  → Dossier stats introuvable : {REMOTE_STATS_PATH}")

        for fname in stat_files:
            if not fname.endswith(".json"):
                continue
            uuid = fname.replace(".json", "").replace("-", "")
            try:
                with sftp.open(f"{REMOTE_STATS_PATH}/{fname}") as f:
                    stats_json = json.load(f)
            except Exception:
                stats_json = None

            # Advancements
            adv_json = None
            try:
                adv_path = f"{REMOTE_ADVANCEMENTS_PATH}/{fname}"
                with sftp.open(adv_path) as f:
                    adv_json = json.load(f)
            except Exception:
                pass

            player_stats = parse_player_stats(stats_json, adv_json, uuid)
            player_stats["name"] = usercache.get(uuid, uuid[:8])
            player_stats["online"] = player_stats["name"] in rcon_data["online_players"]
            player_stats["playtime_human"] = ticks_to_human(player_stats["playtime_ticks"])
            kd = player_stats["mobs_killed"] / max(player_stats["deaths"], 1)
            player_stats["kd"] = round(kd, 1)
            players_data[uuid] = player_stats
            print(f"  → Joueur chargé : {player_stats['name']}")

        sftp.close()
        transport.close()

    except Exception as e:
        print(f"  [SFTP] Erreur : {e}")

    # 3. Lire la progression FTB Quests (world/ftbquests/data/<uuid>.snbt)
    # FTB Quests stocke la progression de chaque joueur dans un fichier SNBT individuel.
    # Structure typique d'une entrée : { id: "QUEST_ID", completed: [{ player: "UUID", ... }] }
    # Le nombre total de quêtes vient du dossier config/ftbquests/quests/*.snbt
    try:
        transport2 = paramiko.Transport((SFTP_HOST, SFTP_PORT))
        transport2.connect(username=SFTP_USER, password=sftp_pass)
        sftp2 = paramiko.SFTPClient.from_transport(transport2)

        import re

        # ── Compter le total de quêtes depuis la config ──
        quest_total = 0
        try:
            config_files = sftp2.listdir(REMOTE_FTB_QUESTS_CONFIG)
            for cf in config_files:
                if not cf.endswith(".snbt"):
                    continue
                try:
                    with sftp2.open(f"{REMOTE_FTB_QUESTS_CONFIG}/{cf}") as f:
                        content = f.read().decode("utf-8", errors="replace")
                    # Chaque quête a un champ "id:" à la racine du bloc
                    quest_total += len(re.findall(r'\bquests\s*:\s*\[', content))
                    # Méthode alternative : compter les blocs quest individuels
                    quest_total += len(re.findall(r'\{\s*id\s*:\s*"[0-9A-F]+"', content))
                except Exception:
                    pass
            print(f"  → FTB Quests total (config) : {quest_total} quêtes trouvées")
        except Exception as e:
            print(f"  → FTB Quests config introuvable ({e})")

        # ── Lire la progression par joueur ──
        ftb_quests_done_map = {}  # uuid_sans_tirets → nb quêtes complétées
        try:
            quest_data_files = sftp2.listdir(REMOTE_FTB_QUESTS_PATH + "/data")
            for qf in quest_data_files:
                if not (qf.endswith(".snbt") or qf.endswith(".json")):
                    continue
                uuid_raw = qf.replace(".snbt", "").replace(".json", "")
                uuid_clean = uuid_raw.replace("-", "")
                try:
                    with sftp2.open(f"{REMOTE_FTB_QUESTS_PATH}/data/{qf}") as f:
                        content = f.read().decode("utf-8", errors="replace")
                    # Compter les quêtes complétées : cherche les blocs "completed" non vides
                    # Format SNBT : completed: [{ player: "UUID", time: 123 }]
                    completed_blocks = re.findall(r'completed\s*:\s*\[([^\]]+)\]', content)
                    done_count = sum(1 for b in completed_blocks if b.strip())
                    ftb_quests_done_map[uuid_clean] = done_count
                    print(f"  → FTB Quests {uuid_clean[:8]}: {done_count} complétées")
                except Exception as e:
                    print(f"  → Erreur lecture quêtes {qf}: {e}")
        except Exception as e:
            print(f"  → FTB Quests data introuvable ({e})")

        sftp2.close()
        transport2.close()

        # Injecter les données FTB Quests dans chaque joueur
        for uuid, pdata in players_data.items():
            pdata["ftb_quests_done"] = ftb_quests_done_map.get(uuid, 0)
            pdata["ftb_quests_total"] = quest_total if quest_total > 0 else 0

    except Exception as e:
        print(f"  [FTB Quests] Erreur : {e}")

    # 4. Assemblage du JSON final
    output = {
        "updated_at": datetime.now().isoformat(),
        "server": {
            "online": rcon_data["online"],
            "tps": rcon_data.get("tps"),
            "online_players": rcon_data["online_players"],
            "online_count": len(rcon_data["online_players"]),
            "host": f"{SFTP_HOST}:{MINECRAFT_PORT}",
        },
        "players": list(players_data.values()),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  ✅ data.json généré ({len(players_data)} joueurs)")
    return output

def main():
    print("=" * 50)
    print("  ATM10 Dashboard — Synchronisation")
    print("=" * 50)

    env = load_env()
    sftp_pass, rcon_pass = get_credentials(env)

    # Mode GitHub Actions : une seule sync puis exit
    if "--auto-once" in sys.argv:
        print("\nMode GitHub Actions — sync unique")
        run_sync(sftp_pass, rcon_pass)
        return

    # Mode automatique continu (--auto)
    auto_mode = "--auto" in sys.argv
    interval = 60  # secondes entre chaque sync

    if auto_mode:
        print(f"\nMode automatique — sync toutes les {interval}s (Ctrl+C pour arrêter)\n")
        while True:
            try:
                run_sync(sftp_pass, rcon_pass)
                time.sleep(interval)
            except KeyboardInterrupt:
                print("\nArrêt.")
                break
    else:
        run_sync(sftp_pass, rcon_pass)
        print("\nPour synchroniser en continu : python sync_atm10.py --auto")

if __name__ == "__main__":
    main()
