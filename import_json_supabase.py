import json
import streamlit as st
from supabase import create_client, Client
from datetime import datetime

st.title("Import JSON Match → Supabase")

# === Configuration manuelle de la connexion ===
st.sidebar.header("🔐 Connexion Supabase")

supabase_url = st.sidebar.text_input("Supabase URL", placeholder="https://xxxx.supabase.co")
supabase_key = st.sidebar.text_input("Supabase API Key", placeholder="eyJhbGciOi...", type="password")

if not supabase_url or not supabase_key:
    st.warning("➡️ Renseigne ton URL et ta clé Supabase dans la barre latérale.")
    st.stop()

# Connexion
try:
    supabase: Client = create_client(supabase_url, supabase_key)
except Exception as e:
    st.error(f"Erreur de connexion Supabase : {e}")
    st.stop()

# === Chargement du fichier JSON ===
uploaded_file = st.file_uploader("Choisis un fichier JSON (un match)", type=["json"])

ACTION_POINTS = {
    "TRY": 5,
    "GOALPENALTY": 3,
    "PENALTY": 3,
    "CONVERSION": 2,
    "TRANSFORMATION": 2,
    "DROP": 3,
    "DROPGOAL": 3
}

def safe_get(d, *keys):
    cur = d
    for k in keys:
        if cur is None:
            return None
        cur = cur.get(k)
    return cur

def upsert_equipe(equipe_id: int, nom: str):
    res = supabase.table("equipes").select("id").eq("id", equipe_id).execute()
    if res.data:
        return equipe_id
    supabase.table("equipes").insert({"id": equipe_id, "nom": nom}).execute()
    return equipe_id

def find_journee(equipe_id: int, rencontre_id: int):
    res = supabase.table("journees").select("*").eq("equipe_id", equipe_id).eq("rencontre_id", rencontre_id).execute()
    return res.data[0] if res.data else None

def create_journee(equipe_id:int, rencontre_id:int, numero:str, date_iso:str, adversaire:str, score:int):
    payload = {
        "equipe_id": equipe_id,
        "rencontre_id": rencontre_id,
        "numero": numero,
        "date": date_iso,
        "adversaire": adversaire,
        "score_dom": score
    }
    res = supabase.table("journees").insert(payload).execute()
    return res.data[0]

def upsert_joueur(pid:int, nom:str, prenom:str):
    r = supabase.table("joueurs").select("id").eq("id", pid).execute()
    if r.data:
        return pid
    supabase.table("joueurs").insert({"id": pid, "nom": nom, "prenom": prenom}).execute()
    return pid

def insert_presence(joueur_id, journee_id, presence=None):
    supabase.table("presence_joueurs").insert({
        "joueur_id": joueur_id,
        "journee_id": journee_id,
        "presence": presence
    }).execute()

def insert_point_marque(joueur_id, journee_id, typ, minute, pts):
    supabase.table("points_marques_joueur").insert({
        "joueur_id": joueur_id,
        "journee_id": journee_id,
        "type": typ,
        "minute": minute,
        "nb_points": pts
    }).execute()

def insert_point_encaisse(journee_id, periode, typ, type_joueur, pts, adversaire):
    supabase.table("points_encaisse").insert({
        "journee_id": journee_id,
        "periode": periode,
        "type": typ,
        "type_joueur": type_joueur,
        "nb_points": pts,
        "adversaire": adversaire
    }).execute()

# === Import JSON ===
if uploaded_file:
    data = json.load(uploaded_file)
    st.json(data)

    if st.button("Importer vers Supabase"):
        try:
            rencontre = data["data"]["Rencontre"]
            rencontre_id = int(rencontre["id"])
            numero = safe_get(rencontre, "Journee", "nom")
            date_iso = rencontre.get("dateOfficielle") or rencontre.get("dateEffective")
            score_dom = safe_get(rencontre, "RencontreResultatLocale", "pointsDeMarque") or 0
            score_ext = safe_get(rencontre, "RencontreResultatVisiteuse", "pointsDeMarque") or 0

            eq_loc_id = int(safe_get(rencontre, "CompetitionEquipeLocale", "id"))
            eq_vis_id = int(safe_get(rencontre, "CompetitionEquipeVisiteuse", "id"))
            nom_loc = safe_get(rencontre, "CompetitionEquipeLocale", "nom") or "Local"
            nom_vis = safe_get(rencontre, "CompetitionEquipeVisiteuse", "nom") or "Visiteur"

            upsert_equipe(eq_loc_id, nom_loc)
            upsert_equipe(eq_vis_id, nom_vis)

            journee_loc = find_journee(eq_loc_id, rencontre_id) or create_journee(eq_loc_id, rencontre_id, numero, date_iso, nom_vis, score_dom)
            journee_vis = find_journee(eq_vis_id, rencontre_id) or create_journee(eq_vis_id, rencontre_id, numero, date_iso, nom_loc, score_ext)

            for side, key, eq_id, journee_row in [
                ("local", "EquipeLocal", eq_loc_id, journee_loc),
                ("visiteur", "EquipeVisiteur", eq_vis_id, journee_vis)
            ]:
                for m in rencontre.get(key, []):
                    pers = m.get("Personne", {})
                    pid = int(pers.get("id"))
                    nom, prenom = pers.get("nom"), pers.get("prenom")
                    upsert_joueur(pid, nom, prenom)
                    presence = "Titulaire" if int(m.get("position", 99)) <= 15 else "Remplaçant"
                    insert_presence(pid, journee_row["id"], presence)

            for act in rencontre.get("Actions", []):
                typ = act.get("type")
                pts = ACTION_POINTS.get(typ, 0)
                minute = act.get("minutes")
                periode = str(act.get("periode"))
                comp_eq_id = int(act.get("competitionEquipeId", 0))
                joueur = safe_get(act, "Joueur1", "Personne", "id")

                if not pts:
                    continue

                if joueur:
                    pid = int(joueur)
                    team = "local" if comp_eq_id == eq_loc_id else "visiteur"
                    jour_id = journee_loc["id"] if team == "local" else journee_vis["id"]
                    insert_point_marque(pid, jour_id, typ, minute, pts)
                    opp_jour_id = journee_vis["id"] if team == "local" else journee_loc["id"]
                    insert_point_encaisse(opp_jour_id, periode, typ, None, pts, nom_vis if team == "local" else nom_loc)
                else:
                    opp_jour_id = journee_vis["id"] if comp_eq_id == eq_loc_id else journee_loc["id"]
                    insert_point_encaisse(opp_jour_id, periode, typ, None, pts, nom_vis if comp_eq_id == eq_loc_id else nom_loc)

            st.success("✅ Import terminé avec succès !")

        except Exception as e:
            st.error(f"Erreur : {e}")
