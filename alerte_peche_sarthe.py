#!/usr/bin/env python3
"""
Alerte Peche - Sarthe, Huisne, Vègre
Detection ADAPTATIVE des variations anormales de hauteur d'eau.
"""

import requests
import json
import os
import statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# ============================================================
# CONFIGURATION
# ============================================================

SUJETS_NTFY = {
    "sarthe": "alerte-peche-sarthe-72",
    "huisne": "alerte-peche-huisne-72",
    "vegre":  "alerte-peche-vegre-72",
}

STATIONS = {
    "M020061010": {"nom": "Sarthe a Beaumont", "riviere": "sarthe"},
    "M025061010": {"nom": "Sarthe a Neuville", "riviere": "sarthe"},
    "M027061020": {"nom": "Sarthe au Mans [Yssoir]", "riviere": "sarthe"},
    "M050061010": {"nom": "Sarthe a Spay", "riviere": "sarthe"},
    "M052061010": {"nom": "Sarthe a La Suze", "riviere": "sarthe"},
    "M063061010": {"nom": "Sarthe a Sable", "riviere": "sarthe"},
    "M037151030": {"nom": "Huisne a La Ferte-Bernard", "riviere": "huisne"},
    "M042151010": {"nom": "Huisne a Montfort-le-Gesnois", "riviere": "huisne"},
    "M044151010": {"nom": "Huisne au Mans [Pontlieue]", "riviere": "huisne"},
    "M058302010": {"nom": "Vegre a Asnieres", "riviere": "vegre"},
}

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
URL_API = "https://hubeau.eaufrance.fr/api/v2/hydrometrie/observations_tr"

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


def iso_to_dt(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def calculer_ecart_type_horaire(histo):
    """
    Calcule l'ecart-type des variations sur des fenetres glissantes de 6h.
    Plafonne le resultat pour eviter les aberrations.
    """
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


def main():
    print("=== Alerte Peche (adaptative) - Sarthe / Huisne / Vegre ===")
    paris = datetime.now(ZoneInfo("Europe/Paris"))
    print(f"Execution : {paris.strftime('%d/%m/%Y %H:%M')}\n")

    historique = charger_json(FICHIER_HISTORIQUE, {})
    alertes = charger_json(FICHIER_ALERTES, {})

    print("Recuperation des hauteurs d'eau...")
    hauteurs = recuperer_hauteurs(list(STATIONS.keys()))
    print(f"{len(hauteurs)} stations sur {len(STATIONS)} ont repondu\n")

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

        ecart_type = calculer_ecart_type_horaire(histo)
        if ecart_type is None:
            print(f"   Ecart-type : pas encore assez de mesures\n")
            continue
        print(f"   Ecart-type : {ecart_type:.2f} mm/h")

        # === MONTE E ===
        seuil_montee_mm = max(
            PLANCHER_ALERTE_MONTEE_MM,
            K_MONTEE * ecart_type * MONTEE_FENETRE_H,
        )
        var = calculer_variation(histo, MONTEE_FENETRE_H)
        if var and var["variation_mm"] >= seuil_montee_mm:
            if cooldown_ok(alertes, code, "montee"):
                ratio = var["variation_mm"] / max(K_MONTEE * ecart_type * MONTEE_FENETRE_H, 0.001)
                msg = (
                    f"{nom}\n\n"
                    f"L'eau monte anormalement : +{var['variation_mm']:.0f} mm "
                    f"en {var['heures_reelles']:.1f}h\n"
                    f"{var['avant']:.0f} -> {var['maintenant']:.0f} mm\n"
                    f"Variation {ratio:.1f}x plus forte que la normale\n\n"
                    f"Bon moment pour aller pecher !"
                )
                envoyer_notification(SUJETS_NTFY[riviere], f"Montee - {nom}", msg)
                alertes[f"{code}_montee"] = datetime.now().isoformat()
                print(f"   -> ALERTE MONTEE +{var['variation_mm']:.0f} mm (seuil {seuil_montee_mm:.0f})")
            else:
                print(f"   Montee detectee mais cooldown actif")
        else:
            if var:
                print(f"   Montee : {var['variation_mm']:+.0f} mm / seuil {seuil_montee_mm:.0f} mm")

        # === BAISSE ===
        seuil_baisse_mm = min(
            PLANCHER_ALERTE_BAISSE_MM,
            -K_BAISSE * ecart_type * BAISSE_FENETRE_H,
        )
        var_baisse = calculer_variation(histo, BAISSE_FENETRE_H)
        if var_baisse and var_baisse["variation_mm"] <= seuil_baisse_mm:
            if cooldown_ok(alertes, code, "baisse"):
                msg = (
                    f"{nom}\n\n"
                    f"L'eau baisse : {var_baisse['variation_mm']:.0f} mm "
                    f"en {var_baisse['heures_reelles']:.1f}h\n"
                    f"{var_baisse['avant']:.0f} -> {var_baisse['maintenant']:.0f} mm\n\n"
                    f"Le niveau revient a la normale, conditions ideales."
                )
                envoyer_notification(SUJETS_NTFY[riviere], f"Baisse - {nom}", msg)
                alertes[f"{code}_baisse"] = datetime.now().isoformat()
                print(f"   -> ALERTE BAISSE {var_baisse['variation_mm']:.0f} mm (seuil {seuil_baisse_mm:.0f})")
            else:
                print(f"   Baisse detectee mais cooldown actif")
        else:
            if var_baisse:
                print(f"   Baisse : {var_baisse['variation_mm']:+.0f} mm / seuil {seuil_baisse_mm:.0f} mm")

        print()

    sauvegarder_json(FICHIER_HISTORIQUE, historique)
    sauvegarder_json(FICHIER_ALERTES, alertes)
    print(f"Historique sauvegarde : {len(historique)} stations")
    print(f"Alertes recentes : {len(alertes)}")


if __name__ == "__main__":
    main()