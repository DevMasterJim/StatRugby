import streamlit as st
import requests
import json

# --- Connexion Supabase via API REST ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# --- Interface Streamlit ---
st.title("📥 Import JSON Rugby vers Supabase")

uploaded_file = st.file_uploader("Choisis un fichier JSON de match", type=["json"])

if uploaded_file is not None:
    try:
        data = json.load(uploaded_file)
        st.json(data)

        rencontre = data["data"]["Rencontre"]
        equipes_data = [rencontre["CompetitionEquipeLocale"], rencontre["CompetitionEquipeVisiteuse"]]

        equipe_ids = {}

        # --- 1️⃣ Insérer les équipes ---
        for equipe in equipes_data:
            nom = equipe["Nom"]

            # Vérifier si l'équipe existe déjà
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/equipes",
                headers=headers,
                params={"nom": f"eq.{nom}"}
            )
            if resp.status_code != 200:
                st.error(f"Erreur GET équipes : {resp.status_code}")
                continue

            results = resp.json()
            if results:
                equipe_ids[nom] = results[0]["id"]
            else:
                # Création de l'équipe
                resp_post = requests.post(
                    f"{SUPABASE_URL}/rest/v1/equipes",
                    headers=headers,
                    json={"nom": nom}
                )
                if resp_post.status_code in [200, 201]:
                    equipe_ids[nom] = resp_post.json()[0]["id"] if resp_post.json() else None
                    st.success(f"Équipe '{nom}' ajoutée")
                else:
                    st.error(f"Erreur POST équipe '{nom}' : {resp_post.text}")

        # --- 2️⃣ Insérer la journée ---
        journee_data = {
            "equipe_id": equipe_ids[rencontre["Equipe"]["Nom"]],
            "numero": rencontre.get("Numero", ""),
            "date": rencontre.get("Date", ""),
            "adversaire": rencontre["Adversaire"]["Nom"],
            "score_dom": rencontre.get("Score", 0),
            "points_marques_1p1": rencontre.get("Points_1P1", 0),
            "points_marques_2p1": rencontre.get("Points_2P1", 0),
            "points_marques_1p2": rencontre.get("Points_1P2", 0),
            "points_marques_2p2": rencontre.get("Points_2P2", 0)
        }

        resp_journee = requests.post(
            f"{SUPABASE_URL}/rest/v1/journees",
            headers=headers,
            json=journee_data
        )
        if resp_journee.status_code in [200, 201]:
            journee_id = resp_journee.json()[0]["id"]
            st.success("Journée ajoutée")
        else:
            st.error(f"Erreur POST journée : {resp_journee.text}")
            journee_id = None

        # --- 3️⃣ Insérer les joueurs et points ---
        for joueur in rencontre["Equipe"]["Joueurs"]:
            # Vérifier si joueur existe déjà
            resp = requests.get(
                f"{SUPABASE_URL}/rest/v1/joueurs",
                headers=headers,
                params={"nom": f"eq.{joueur['Nom']}", "prenom": f"eq.{joueur['Prenom']}"}
            )
            results = resp.json() if resp.status_code == 200 else []
            joueur_id = None
            if results:
                joueur_id = results[0]["id"]
            else:
                # Création du joueur
                joueur_data = {
                    "nom": joueur["Nom"],
                    "prenom": joueur["Prenom"],
                    "equipe_id": equipe_ids[rencontre["Equipe"]["Nom"]]
                }
                resp_post = requests.post(
                    f"{SUPABASE_URL}/rest/v1/joueurs",
                    headers=headers,
                    json=joueur_data
                )
                if resp_post.status_code in [200, 201]:
                    joueur_id = resp_post.json()[0]["id"] if resp_post.json() else None

            if not joueur_id:
                st.error(f"Impossible d'ajouter le joueur {joueur['Nom']}")
                continue

            # --- Présence joueur ---
            presence_data = {
                "joueur_id": joueur_id,
                "journee_id": journee_id,
                "presence": joueur.get("Presence", "Absent"),
                "entree_minute": joueur.get("EntreeMinute", 0),
                "sortie_minute": joueur.get("SortieMinute", 0)
            }
            requests.post(f"{SUPABASE_URL}/rest/v1/presence_joueurs", headers=headers, json=presence_data)

            # --- Points marqués joueur ---
            for point in joueur.get("PointsMarques", []):
                point_data = {
                    "joueur_id": joueur_id,
                    "journee_id": journee_id,
                    "type": point["Type"],
                    "minute": point["Minute"],
                    "nb_points": point["Points"]
                }
                requests.post(f"{SUPABASE_URL}/rest/v1/points_marques_joueur", headers=headers, json=point_data)

        # --- 4️⃣ Points encaissés par période ---
        for pe in rencontre.get("PointsEncaisse", []):
            pe_data = {
                "journee_id": journee_id,
                "periode": pe.get("Periode", ""),
                "type": pe.get("Type", ""),
                "type_joueur": pe.get("TypeJoueur", ""),
                "nb_points": pe.get("Points", 0),
                "adversaire": pe.get("Adversaire", "")
            }
            requests.post(f"{SUPABASE_URL}/rest/v1/points_encaisse", headers=headers, json=pe_data)

        st.success("✅ Import JSON complet terminé !")

    except Exception as e:
        st.error(f"Erreur générale : {e}")
