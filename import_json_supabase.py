import json
import streamlit as st
from supabase import create_client, Client

# --- Configuration Supabase ---
SUPABASE_URL = "https://xxxxxx.supabase.co"  # ton URL
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR..."  # ta clé publique
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Interface Streamlit ---
st.title("📂 Import JSON vers Supabase")

uploaded_file = st.file_uploader("Choisis un fichier JSON", type=["json"])

if uploaded_file is not None:
    try:
        data = json.load(uploaded_file)
        st.success("✅ Fichier chargé avec succès !")

        # Affiche un aperçu du JSON
        st.json(data)

        if st.button("🚀 Importer dans Supabase"):
            # Exemple : insertion des données principales
            rencontre = data["data"]["Rencontre"]

            # Insertion de la rencontre
            response = supabase.table("rencontres").insert({
                "id": rencontre["id"],
                "numero": rencontre["numero"],
                "dateOfficielle": rencontre["dateOfficielle"],
                "etatMixte": rencontre["etatMixte"],
                "scoreValide": rencontre["scoreValide"],
                "nom_journee": rencontre["Journee"]["nom"]
            }).execute()

            # Insertion des joueurs locaux
            for joueur in rencontre["EquipeLocal"]:
                supabase.table("joueurs").insert({
                    "id": joueur["id"],
                    "numero": joueur["numero"],
                    "nom": joueur["Personne"]["nom"],
                    "prenom": joueur["Personne"]["prenom"],
                    "equipe": "local",
                    "rencontre_id": rencontre["id"]
                }).execute()

            # Insertion des joueurs visiteurs
            for joueur in rencontre["EquipeVisiteur"]:
                supabase.table("joueurs").insert({
                    "id": joueur["id"],
                    "numero": joueur["numero"],
                    "nom": joueur["Personne"]["nom"],
                    "prenom": joueur["Personne"]["prenom"],
                    "equipe": "visiteur",
                    "rencontre_id": rencontre["id"]
                }).execute()

            st.success("✅ Données importées avec succès dans Supabase !")

    except Exception as e:
        st.error(f"Erreur lors du traitement du fichier : {e}")
