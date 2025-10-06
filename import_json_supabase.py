# app.py
import json
import os
import math
from dotenv import load_dotenv
import streamlit as st
from supabase import create_client, Client
from datetime import datetime

load_dotenv()
SUPABASE_URL = os.getenv("https://fhkqflmfcejxoarbizkt.supabase.co")
SUPABASE_KEY = os.getenv("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZoa3FmbG1mY2VqeG9hcmJpemt0Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NTk3NDM3MjAsImV4cCI6MjA3NTMxOTcyMH0.2XxvHdI6nqNNDnbynTPULUbL-2lvS7JAsy3C8-dcsPE")
if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Il manque SUPABASE_URL ou SUPABASE_KEY dans le .env")
    st.stop()

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

st.title("Import JSON match → Supabase")
uploaded_file = st.file_uploader("Choisis un fichier JSON (un match)", type=["json"])

# mapping des types d'action vers pts
ACTION_POINTS = {
    "essais": 5,
    "butsPenalité": 3,
    "essaisDePenalité": 7,
    "butsAprèsEssai": 2,
    "dropGoals": 3
}

def safe_get(d, *keys):
    cur = d
    for k in keys:
        if cur is None:
            return None
        cur = cur.get(k)
    return cur

def upsert_equipe(equipe_external_id: int, nom: str):
    # On essaie d'insérer si absent (select first)
    res = supabase.table("equipes").select("id").eq("id", equipe_external_id).limit(1).execute()
    if res.data:
        return equipe_external_id
    # insert
    supabase.table("equipes").insert({"id": equipe_external_id, "nom": nom}).execute()
    return equipe_external_id

def find_journee(equipe_id: int, rencontre_id: int):
    res = supabase.table("journees").select("*").eq("equipe_id", equipe_id).eq("rencontre_id", rencontre_id).limit(1).execute()
    return res.data[0] if res.data else None

def create_journee(equipe_id:int, rencontre_id:int, numero:str, date_iso:str, adversaire:str, score_dom:int):
    payload = {
        "equipe_id": equipe_id,
        "rencontre_id": rencontre_id,
        "numero": numero,
        "date": date_iso,
        "adversaire": adversaire,
        "score_dom": score_dom
    }
    res = supabase.table("journees").insert(payload).execute()
    if res.error:
        st.error(f"Erreur insertion journee: {res.error}")
        return None
    return res.data[0]

def upsert_joueur(personne):
    # personne: dict with id, nom, prenom ; also number/position optional
    pid = int(personne.get("id"))
    nom = personne.get("nom")
    prenom = personne.get("prenom")
    # check existence
    r = supabase.table("joueurs").select("id").eq("id", pid).limit(1).execute()
    if r.data:
        return pid
    # insert minimal (user can update team later)
    supabase.table("joueurs").insert({
        "id": pid,
        "nom": nom,
        "prenom": prenom
    }).execute()
    return pid

def insert_presence(joueur_id, journee_id, presence=None, entree_min=None, sortie_min=None):
    payload = {
        "joueur_id": joueur_id,
        "journee_id": journee_id,
        "presence": presence,
        "entree_minute": entree_min,
        "sortie_minute": sortie_min
    }
    supabase.table("presence_joueurs").insert(payload).execute()

def insert_point_marque(joueur_id, journee_id, typ, minute, pts):
    payload = {
        "joueur_id": joueur_id,
        "journee_id": journee_id,
        "type": typ,
        "minute": minute,
        "nb_points": pts
    }
    supabase.table("points_marques_joueur").insert(payload).execute()

def insert_point_encaisse(journee_id, periode, typ, type_joueur, pts, adversaire):
    payload = {
        "journee_id": journee_id,
        "periode": periode,
        "type": typ,
        "type_joueur": type_joueur,
        "nb_points": pts,
        "adversaire": adversaire
    }
    supabase.table("points_encaisse").insert(payload).execute()

if uploaded_file is not None:
    raw = json.load(uploaded_file)
    st.json(raw)  # aperçu
    if st.button("Importer dans Supabase"):
        try:
            rencontre = raw["data"]["Rencontre"]
            rencontre_id = int(rencontre["id"])
            numero = safe_get(rencontre, "Journee", "nom") or rencontre.get("numero")
            date_iso = rencontre.get("dateOfficielle") or rencontre.get("dateEffective")
            date_iso = date_iso  # keep iso (Postgres timestamptz)
            # competition equipe ids (externe)
            comp_locale = safe_get(rencontre, "CompetitionEquipeLocale", "id")
            comp_visiteur = safe_get(rencontre, "CompetitionEquipeVisiteuse", "id")
            # noms équipes (si présents)
            nom_locale = safe_get(rencontre, "CompetitionEquipeLocale", "nom") or safe_get(rencontre, "CompetitionEquipeLocale", "Structure", "nom") or "LOCAL"
            nom_visiteur = safe_get(rencontre, "CompetitionEquipeVisiteuse", "nom") or safe_get(rencontre, "CompetitionEquipeVisiteuse", "Regroupement", "nom") or "VISITEUR"

            # scores extraits des résultats
            score_dom = safe_get(rencontre, "RencontreResultatLocale", "pointsDeMarque") or 0
            score_ext = safe_get(rencontre, "RencontreResultatVisiteuse", "pointsDeMarque") or 0

            # upsert equipes (ids are competitionEquipe ids if present, else fallback to generated negative)
            if comp_locale:
                equipe_locale_id = int(comp_locale)
            else:
                equipe_locale_id = -1  # fallback
            if comp_visiteur:
                equipe_visiteur_id = int(comp_visiteur)
            else:
                equipe_visiteur_id = -2

            upsert_equipe(equipe_locale_id, nom_locale)
            upsert_equipe(equipe_visiteur_id, nom_visiteur)

            # For each team create/find journee (one row per team per match)
            # local journee
            existing_local = find_journee(equipe_locale_id, rencontre_id)
            if existing_local:
                journee_local = existing_local
            else:
                journee_local = create_journee(equipe_locale_id, rencontre_id, numero, date_iso, nom_visiteur, int(score_dom))

            existing_vis = find_journee(equipe_visiteur_id, rencontre_id)
            if existing_vis:
                journee_vis = existing_vis
            else:
                journee_vis = create_journee(equipe_visiteur_id, rencontre_id, numero, date_iso, nom_locale, int(score_ext))

            # Insert players for both sides
            for side, key, equipe_id, journee_row in [
                ("local", "EquipeLocal", equipe_locale_id, journee_local),
                ("visiteur", "EquipeVisiteur", equipe_visiteur_id, journee_vis)
            ]:
                members = rencontre.get(key) or []
                for m in members:
                    personne = m.get("Personne") or {}
                    person_id = None
                    if personne.get("id"):
                        person_id = int(personne["id"])
                    else:
                        # fallback: construct an id from negative hash (not ideal)
                        person_id = -abs(hash(personne.get("nom","") + personne.get("prenom","")) % (10**9))

                    # upsert joueur (use external Personne.id)
                    upsert_joueur({"id": person_id, "nom": personne.get("nom"), "prenom": personne.get("prenom")})

                    # presence: we infer Titulaire si position number <=15 otherwise remplaçant (heuristique)
                    position = m.get("position")
                    presence = "Absent"
                    if position is not None:
                        try:
                            posint = int(position)
                            presence = "Titulaire" if posint <= 15 else "Remplaçant"
                        except:
                            presence = None

                    insert_presence(person_id, journee_row["id"], presence, None, None)

            # Process Actions => points and events
            actions = rencontre.get("Actions", [])
            for act in actions:
                typ = act.get("type")
                minute = act.get("minutes")
                periode_num = act.get("periode")  # integer 1 or 2 etc
                periode = None
                if periode_num == 1:
                    # can't determine 1P1 vs 2P1 from sample; we'll store period as "1" or "2"
                    periode = "1"
                elif periode_num == 2:
                    periode = "2"
                else:
                    periode = str(periode_num) if periode_num is not None else None

                competitionEquipeId = act.get("competitionEquipeId") or safe_get(act, "Equipe", "id")
                scoring_team = None
                if competitionEquipeId:
                    # competitionEquipeId corresponds to CompetitionEquipe id (same as CompetitionEquipeLocale.id above)
                    try:
                        competitionEquipeId = int(competitionEquipeId)
                        if competitionEquipeId == equipe_locale_id:
                            scoring_team = "local"
                        elif competitionEquipeId == equipe_visiteur_id:
                            scoring_team = "visiteur"
                    except:
                        pass

                # map scoring actions to points
                pts = 0
                if typ in ACTION_POINTS:
                    pts = ACTION_POINTS[typ]
                # special: GOALPENALTY or PENALTY -> 3 (already mapped)

                # If PLAYER involved -> attribute to joueur
                joueur1 = act.get("Joueur1")
                if joueur1 and joueur1.get("Personne"):
                    perso = joueur1["Personne"]
                    try:
                        pid = int(joueur1.get("id") or perso.get("id"))
                    except:
                        pid = None
                    if pid and pts > 0:
                        # determine journee_id of the joueur's team
                        # find whether pid is in local/visiteur teams; fallback: use scoring_team
                        # We'll check players lists
                        # search in local roster
                        def find_team_of_player(pid):
                            for m in rencontre.get("EquipeLocal", []):
                                if str(m.get("id")) == str(joueur1.get("id")) or (m.get("Personne") and str(m["Personne"].get("id"))==str(pid)):
                                    return "local"
                            for m in rencontre.get("EquipeVisiteur", []):
                                if str(m.get("id")) == str(joueur1.get("id")) or (m.get("Personne") and str(m["Personne"].get("id"))==str(pid)):
                                    return "visiteur"
                            return scoring_team

                        team = find_team_of_player(pid)
                        if team == "local":
                            jour_id = journee_local["id"]
                            adversaire_name = nom_visiteur
                        else:
                            jour_id = journee_vis["id"]
                            adversaire_name = nom_locale

                        # insert point marque
                        insert_point_marque(pid, jour_id, typ, minute, pts)
                        # insert point encaissé for the opponent
                        # opponent journee:
                        if team == "local":
                            opp_jour = journee_vis
                        else:
                            opp_jour = journee_local
                        # type_joueur unknown (Avant/Arriere) - we don't have mapping here, leave NULL
                        insert_point_encaisse(opp_jour["id"], f"{periode}", typ, None, pts, adversaire_name)

                else:
                    # no player attached but team scored (ex: penalty by team?), we still attribute to points_encaisse
                    if pts > 0 and scoring_team:
                        if scoring_team == "local":
                            opp_jour = journee_vis
                            adv = nom_visiteur
                        else:
                            opp_jour = journee_local
                            adv = nom_locale
                        insert_point_encaisse(opp_jour["id"], f"{periode}", typ, None, pts, adv)

            st.success("Import terminé ✅")
        except Exception as e:
            st.error(f"Erreur import: {e}")
