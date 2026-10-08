#!/usr/bin/env python3
"""
Alerte Peche - Sarthe, Huisne, Vègre
Detection ADAPTATIVE + page web + meteo + icones PNG
Version GitHub avec 3 sujets ntfy
"""

import requests
import json
import os
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from PIL import Image, ImageDraw

# ============================================================
# CONFIGURATION - 3 sujets depuis variables d'environnement
# ============================================================

SUJETS_NTFY = {
    "sarthe": os.environ.get("NTFY_TOPIC_SARTHE", "alerte-peche-sarthe-72"),
    "huisne": os.environ.get("NTFY_TOPIC_HUISNE", "alerte-peche-huisne-72"),
    "vegre":  os.environ.get("NTFY_TOPIC_VEGRE", "alerte-peche-vegre-72"),
}

STATIONS = {
    "M020061010": {"nom": "Sarthe a Beaumont", "riviere": "sarthe", "lat": 48.227, "lon": 0.117},
    "M025061010": {"nom": "Sarthe a Neuville", "riviere": "sarthe", "lat": 48.020, "lon": 0.190},
    "M027061020": {"nom": "Sarthe au Mans [Yssoir]", "riviere": "sarthe", "lat": 47.999, "lon": 0.184},
    "M050061010": {"nom": "Sarthe a Spay", "riviere": "sarthe", "lat": 47.925, "lon": 0.153},
    "M052061010": {"nom": "Sarthe a La Suze", "riviere": "sarthe", "lat": 47.887, "lon": 0.028},
    "M063061010": {"nom": "Sarthe a Sable", "riviere": "sarthe", "lat": 47.838, "lon": -0.333},
    "M037151030": {"nom": "Huisne a La Ferte-Bernard", "riviere": "huisne", "lat": 48.185, "lon": 0.656},
    "M042151010": {"nom": "Huisne a Montfort-le-Gesnois", "riviere": "huisne", "lat": 48.048, "lon": 0.407},
    "M044151010": {"nom": "Huisne au Mans [Pontlieue]", "riviere": "huisne", "lat": 47.982, "lon": 0.208},
    "M058302010": {"nom": "Vegre a Asnieres", "riviere": "vegre", "lat": 47.886, "lon": -0.402},
}

METEO_LAT = 48.006
METEO_LON = 0.199

MONTEE_FENETRE_H = 6
BAISSE_FENETRE_H = 12
K_MONTEE = 3.0
K_BAISSE = 3.0
PLANCHER_VARIATION_MM_H = 3.0
MAX_ECART_TYPE_MM_H = 10.0
PLANCHER_ALERTE_MONTEE_MM = 15
PLANCHER_ALERTE_BAISSE_MM = -15
MIN_MESURES_POUR_CALCUL = 6
COOLDOWN_ALERTE_H = 6
HISTORIQUE_MAX = 336

FICHIER_HISTORIQUE = "historique_hauteurs.json"
FICHIER_ALERTES = "alertes_peche.json"
DOSSIER_PUBLIC = "."
URL_API = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"
URL_METEO = "https://api.open-meteo.com/v1/forecast"

# ============================================================


def charger_json(fichier, defaut):
    if os.path.exists(fichier):
        try:
            with open(fichier, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return defaut
    return defaut


def sauvegarder_json(fichier, data):
    with open(fichier, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def creer_icones_png():
    """Genere les icones PNG 192x192 et 512x512 - poisson bleu."""
    for taille in (192, 512):
        img = Image.new("RGBA", (taille, taille), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        marge = taille // 16
        draw.rounded_rectangle(
            [marge, marge, taille - marge, taille - marge],
            radius=taille // 8,
            fill=(3, 105, 161, 255),
        )

        draw.ellipse(
            [int(taille * 0.22), int(taille * 0.35),
             int(taille * 0.72), int(taille * 0.65)],
            fill=(255, 255, 255, 255),
        )

        draw.polygon([
            (int(taille * 0.72), int(taille * 0.50)),
            (int(taille * 0.88), int(taille * 0.35)),
            (int(taille * 0.88), int(taille * 0.65)),
        ], fill=(255, 255, 255, 255))

        draw.ellipse(
            [int(taille * 0.30), int(taille * 0.45),
             int(taille * 0.38), int(taille * 0.53)],
            fill=(3, 105, 161, 255),
        )

        img.save(f"icon-{taille}.png")
        print(f"   Icone {taille}x{taille} generee")


def creer_manifest():
    manifest = {
        "name": "Alerte Peche Sarthe",
        "short_name": "Alerte Peche",
        "description": "Alertes peche en Sarthe - Huisne - Vegre",
        "start_url": "./",
        "display": "standalone",
        "background_color": "#ffffff",
        "theme_color": "#0369a1",
        "icons": [
            {"src": "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any maskable"},
        ],
    }
    with open("manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"   Manifest cree")


def envoyer_notification(sujet, titre, message):
    try:
        requests.post(
            f"https://ntfy.sh/{sujet}",
            data=message.encode("utf-8"),
            headers={
                "Title": titre.encode("utf-8"),
                "Priority": "max",
                "Tags": "fishing,water,rotating_light",
                "X-Priority": "1",
            },
            timeout=10,
        )
        print(f"   -> Notif envoyee sur {sujet} : {titre}")
    except Exception as e:
        print(f"   [ERREUR] Envoi notif : {e}")


def recuperer_hauteurs(codes):
    params = {
        "code_entite": ",".join(codes),
        "grandeur_hydro": "H",
        "size": 1000,
    }
    try:
        r = requests.get(URL_API, params=params, timeout=60)
        r.raise_for_status()
        data = r.json()
        resultats = {}
        for obs in data.get("data", []):
            code = obs.get("code_station")
            ts = obs.get("date_obs")
            val = obs.get("resultat_obs")
            if code and ts and val is not None:
                if code not in resultats or ts > resultats[code]["ts"]:
                    resultats[code] = {"ts": ts, "valeur": float(val)}
        return resultats
    except Exception as e:
        print(f"   [ERREUR] API : {e}")
        return {}


def recuperer_meteo():
    params = {
        "latitude": METEO_LAT,
        "longitude": METEO_LON,
        "current": "temperature_2m,precipitation,surface_pressure,wind_speed_10m,cloud_cover",
        "hourly": "precipitation",
        "forecast_days": 2,
        "timezone": "Europe/Paris",
    }
    try:
        r = requests.get(URL_METEO, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
        current = data.get("current", {})
        hourly = data.get("hourly", {})
        times = hourly.get("time", [])
        prec = hourly.get("precipitation", [])
        pluie_24h = 0.0
        now_iso = current.get("time", "")
        compteur = 0
        for i, t in enumerate(times):
            if t >= now_iso and i < len(prec):
                pluie_24h += prec[i] or 0
                compteur += 1
                if compteur >= 24:
                    break
        return {
            "temperature": current.get("temperature_2m"),
            "precipitation": current.get("precipitation", 0),
            "pression": current.get("surface_pressure"),
            "vent": current.get("wind_speed_10m"),
            "nuages": current.get("cloud_cover"),
            "pluie_24h": round(pluie_24h, 1),
        }
    except Exception as e:
        print(f"   [ERREUR] Meteo : {e}")
        return None


def iso_to_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def calculer_ecart_type_horaire(histo):
    if len(histo) < MIN_MESURES_POUR_CALCUL:
        return None

    variations_6h = []
    for i in range(len(histo)):
        ts_i = iso_to_dt(histo[i]["ts"])
        val_i = histo[i]["valeur"]
        ts_cible = ts_i - timedelta(hours=6)
        for j in range(i):
            ts_j = iso_to_dt(histo[j]["ts"])
            ecart_h = (ts_i - ts_j).total_seconds() / 3600
            if 5.5 <= ecart_h <= 6.5:
                delta = val_i - histo[j]["valeur"]
                variations_6h.append(delta)
                break

    if len(variations_6h) < 4:
        return None

    ecart_6h = statistics.stdev(variations_6h) if len(variations_6h) > 1 else 0.0
    ecart_horaire = ecart_6h / 6.0
    return max(PLANCHER_VARIATION_MM_H, min(ecart_horaire, MAX_ECART_TYPE_MM_H))


def calculer_variation(histo, fenetre_h):
    if len(histo) < 2:
        return None

    maintenant = histo[-1]
    ts_now = iso_to_dt(maintenant["ts"])
    ts_cible = ts_now - timedelta(hours=fenetre_h)

    meilleur = None
    meilleur_ecart = None
    for h in histo:
        ts_h = iso_to_dt(h["ts"])
        ecart = abs((ts_h - ts_cible).total_seconds())
        if meilleur_ecart is None or ecart < meilleur_ecart:
            meilleur_ecart = ecart
            meilleur = h

    if not meilleur:
        return None
    variation_mm = maintenant["valeur"] - meilleur["valeur"]
    heures_reelles = (ts_now - iso_to_dt(meilleur["ts"])).total_seconds() / 3600
    return {
        "variation_mm": variation_mm,
        "avant": meilleur["valeur"],
        "maintenant": maintenant["valeur"],
        "heures_reelles": heures_reelles,
    }


def cooldown_ok(alertes, code, type_alerte):
    cle = f"{code}_{type_alerte}"
    derniere = alertes.get(cle)
    if not derniere:
        return True
    try:
        ts = iso_to_dt(derniere)
        return (datetime.now(ts.tzinfo) - ts).total_seconds() > COOLDOWN_ALERTE_H * 3600
    except Exception:
        return True


def tendance(histo, nb_dernieres=6):
    if len(histo) < 3:
        return "stable"
    dernieres = histo[-nb_dernieres:]
    if len(dernieres) < 2:
        return "stable"
    delta = dernieres[-1]["valeur"] - dernieres[0]["valeur"]
    if delta > 5:
        return "montee"
    if delta < -5:
        return "baisse"
    return "stable"


def generer_page_html(stations_data, meteo, chemin="index.html"):
    paris = datetime.now(ZoneInfo("Europe/Paris"))
    date_heure = paris.strftime("%d/%m/%Y a %Hh%M")

    meteo_html = ""
    if meteo:
        temp = meteo.get("temperature", "?")
        pression = meteo.get("pression")
        vent = meteo.get("vent", "?")
        nuages = meteo.get("nuages", "?")
        pluie_24h = meteo.get("pluie_24h", 0)
        pression_txt = f"{pression:.0f} hPa" if pression else "?"

        if pluie_24h > 5:
            pluie_couleur = "#c00"
            pluie_msg = "Pluie importante prevue : l'eau devrait monter !"
        elif pluie_24h > 1:
            pluie_couleur = "#e80"
            pluie_msg = "Pluie moderee prevue"
        else:
            pluie_couleur = "#090"
            pluie_msg = "Pas de pluie significative prevue"

        meteo_html = f'''
        <div class="meteo">
            <h2>Meteo au Mans</h2>
            <div class="meteo-grid">
                <div class="meteo-item"><span class="label">Temperature</span><span class="valeur">{temp} C</span></div>
                <div class="meteo-item"><span class="label">Pression</span><span class="valeur">{pression_txt}</span></div>
                <div class="meteo-item"><span class="label">Vent</span><span class="valeur">{vent} km/h</span></div>
                <div class="meteo-item"><span class="label">Nuages</span><span class="valeur">{nuages} %</span></div>
            </div>
            <div class="pluie" style="color: {pluie_couleur};">
                <strong>Pluie 24h : {pluie_24h} mm</strong> - {pluie_msg}
            </div>
        </div>'''

    rivieres = {"sarthe": "La Sarthe", "huisne": "L'Huisne", "vegre": "La Vègre"}
    stations_html = ""
    for riv_key, riv_label in rivieres.items():
        stations_riv = [s for s in stations_data if s["riviere"] == riv_key]
        if not stations_riv:
            continue
        stations_html += f'<h2 class="riviere">{riv_label}</h2><div class="stations">'
        for s in sorted(stations_riv, key=lambda x: x["nom"]):
            tend = s.get("tendance", "stable")
            if tend == "montee":
                tend_class = "tend-montee"
                tend_txt = "EN MONTE"
                tend_icon = "↑"
            elif tend == "baisse":
                tend_class = "tend-baisse"
                tend_txt = "EN BAISSE"
                tend_icon = "↓"
            else:
                tend_class = "tend-stable"
                tend_txt = "STABLE"
                tend_icon = "="

            var_6h_txt = ""
            if s.get("variation_6h") is not None:
                v6 = s["variation_6h"]
                signe = "+" if v6 >= 0 else ""
                var_6h_txt = f'<div class="var">Variation 6h : <strong>{signe}{v6:.0f} mm</strong></div>'

            stations_html += f'''
            <div class="station {tend_class}">
                <div class="station-nom">{s["nom"]}</div>
                <div class="station-hauteur">{s["valeur"]:.0f} mm</div>
                <div class="station-tend">{tend_icon} {tend_txt}</div>
                {var_6h_txt}
                <div class="station-maj">Mesure : {s["ts"][:16].replace("T", " ")}</div>
            </div>'''
        stations_html += '</div>'

    html = f'''<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Alerte Peche Sarthe</title>
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="apple-touch-icon" href="icon-192.png">
<link rel="manifest" href="manifest.json">
<meta name="theme-color" content="#0369a1">
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif;
         margin: 0; padding: 16px; background: #f0f4f8; color: #222;
         display: flex; flex-direction: column; align-items: center; }}
  header, h2, .meteo, .stations, .date {{ width: 100%; max-width: 700px; }}
  .riviere {{ width: 100%; max-width: 700px; }}
  header {{ background: linear-gradient(135deg, #0369a1, #075985);
            color: white; padding: 20px; border-radius: 12px;
            margin-bottom: 16px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
  h1 {{ margin: 0; font-size: 1.4em; }}
  .compteur {{ margin-top: 8px; font-size: 1em; opacity: 0.95; }}
  h2 {{ font-size: 1.1em; color: #075985; margin: 20px 0 10px 0;
        border-bottom: 2px solid #075985; padding-bottom: 4px; }}
  .meteo {{ background: white; padding: 16px; border-radius: 10px;
            margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.08); }}
  .meteo h2 {{ margin-top: 0; }}
  .meteo-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 12px; }}
  .meteo-item {{ display: flex; flex-direction: column; padding: 6px;
                 background: #f0f4f8; border-radius: 6px; }}
  .meteo-item .label {{ font-size: 0.8em; color: #666; }}
  .meteo-item .valeur {{ font-size: 1.1em; font-weight: bold; color: #075985; }}
  .pluie {{ padding: 10px; border-radius: 6px; background: #f8f8f8;
            font-size: 0.95em; }}
  .riviere {{ color: #c00; border-bottom-color: #c00; }}
  .stations {{ display: grid; gap: 10px; grid-template-columns: 1fr; }}
  @media (min-width: 600px) {{
    .stations {{ grid-template-columns: 1fr 1fr; }}
  }}
  .station {{ background: white; padding: 14px; border-radius: 10px;
              box-shadow: 0 1px 4px rgba(0,0,0,0.08);
              border-left: 4px solid #ccc; }}
  .tend-montee {{ border-left-color: #c00; }}
  .tend-baisse {{ border-left-color: #090; }}
  .tend-stable {{ border-left-color: #888; }}
  .station-nom {{ font-weight: bold; font-size: 0.95em; }}
  .station-hauteur {{ font-size: 1.6em; font-weight: bold; color: #075985;
                      margin: 4px 0; }}
  .station-tend {{ font-size: 0.9em; font-weight: bold; color: #666; }}
  .tend-montee .station-tend {{ color: #c00; }}
  .tend-baisse .station-tend {{ color: #090; }}
  .var {{ font-size: 0.9em; color: #444; margin-top: 4px; }}
  .station-maj {{ font-size: 0.75em; color: #888; margin-top: 6px; }}
  .date {{ text-align: center; color: #888; font-size: 0.85em; margin: 20px 0; }}
</style>
</head>
<body>
<header>
  <h1>Alerte Peche - Sarthe</h1>
  <div class="compteur">10 stations surveillees</div>
</header>
{meteo_html}
{stations_html}
<div class="date">Derniere mise a jour : {date_heure}</div>
</body>
</html>'''

    with open(chemin, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"   Page HTML generee")


def main():
    print("=== Alerte Peche (adaptative) - Sarthe / Huisne / Vegre ===")
    paris = datetime.now(ZoneInfo("Europe/Paris"))
    print(f"Execution : {paris.strftime('%d/%m/%Y %H:%M')}\n")

    historique = charger_json(FICHIER_HISTORIQUE, {})
    alertes = charger_json(FICHIER_ALERTES, {})

    print("Recuperation des hauteurs d'eau...")
    hauteurs = recuperer_hauteurs(list(STATIONS.keys()))
    print(f"{len(hauteurs)} stations sur {len(STATIONS)} ont repondu")

    print("Recuperation de la meteo...")
    meteo = recuperer_meteo()
    if meteo:
        print(f"   Temp : {meteo.get('temperature')} C | Pression : {meteo.get('pression')} hPa")
    print()

    stations_data = []

    for code, info in STATIONS.items():
        nom = info["nom"]
        riviere = info["riviere"]
        print(f"[{nom}]")

        obs = hauteurs.get(code)
        if not obs:
            print("   Aucune donnee.\n")
            continue

        histo = historique.get(code, [])
        if not histo or histo[-1]["ts"] != obs["ts"]:
            histo.append(obs)
        if len(histo) > HISTORIQUE_MAX:
            histo = histo[-HISTORIQUE_MAX:]
        historique[code] = histo

        print(f"   Hauteur : {obs['valeur']:.0f} mm ({obs['ts']})")
        print(f"   Historique : {len(histo)} mesures")

        var_6h_mm = None
        ecart_type = calculer_ecart_type_horaire(histo)

        if ecart_type is not None:
            print(f"   Ecart-type : {ecart_type:.2f} mm/h")
            seuil_montee_mm = max(PLANCHER_ALERTE_MONTEE_MM, K_MONTEE * ecart_type * MONTEE_FENETRE_H)
            var = calculer_variation(histo, MONTEE_FENETRE_H)
            if var:
                var_6h_mm = var["variation_mm"]

            if var and var["variation_mm"] >= seuil_montee_mm:
                if cooldown_ok(alertes, code, "montee"):
                    msg = (
                        f"{nom}\n\n"
                        f"L'eau monte anormalement : +{var['variation_mm']:.0f} mm "
                        f"en {var['heures_reelles']:.1f}h\n"
                        f"{var['avant']:.0f} -> {var['maintenant']:.0f} mm\n\n"
                        f"Bon moment pour aller pecher !"
                    )
                    envoyer_notification(SUJETS_NTFY[riviere], f"Montee - {nom}", msg)
                    alertes[f"{code}_montee"] = datetime.now().isoformat()
                    print(f"   -> ALERTE MONTEE +{var['variation_mm']:.0f} mm")

            seuil_baisse_mm = min(PLANCHER_ALERTE_BAISSE_MM, -K_BAISSE * ecart_type * BAISSE_FENETRE_H)
            var_baisse = calculer_variation(histo, BAISSE_FENETRE_H)
            if var_baisse and var_baisse["variation_mm"] <= seuil_baisse_mm:
                if cooldown_ok(alertes, code, "baisse"):
                    msg = (
                        f"{nom}\n\n"
                        f"L'eau baisse : {var_baisse['variation_mm']:.0f} mm "
                        f"en {var_baisse['heures_reelles']:.1f}h\n\n"
                        f"Le niveau revient a la normale, conditions ideales."
                    )
                    envoyer_notification(SUJETS_NTFY[riviere], f"Baisse - {nom}", msg)
                    alertes[f"{code}_baisse"] = datetime.now().isoformat()
                    print(f"   -> ALERTE BAISSE {var_baisse['variation_mm']:.0f} mm")

        tend = tendance(histo, 6)
        stations_data.append({
            "code": code,
            "nom": nom,
            "riviere": riviere,
            "valeur": obs["valeur"],
            "ts": obs["ts"],
            "tendance": tend,
            "variation_6h": var_6h_mm,
        })
        print(f"   Tendance : {tend}\n")

    print("-> Generation de la page web...")
    generer_page_html(stations_data, meteo)

    print("-> Generation des icones...")
    creer_icones_png()
    creer_manifest()

    sauvegarder_json(FICHIER_HISTORIQUE, historique)
    sauvegarder_json(FICHIER_ALERTES, alertes)
    print(f"\nHistorique sauvegarde : {len(historique)} stations")
    print(f"Alertes recentes : {len(alertes)}")


if __name__ == "__main__":
    main()
