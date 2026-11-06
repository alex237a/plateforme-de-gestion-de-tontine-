# Njangi+ : plateforme de gestion de plusieurs tontines (Flask et SQLite)
import csv
import io
import os
import re
import secrets
import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from functools import wraps

from flask import (Flask, Response, abort, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.security import check_password_hash, generate_password_hash

DOSSIER = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)
# La clé de session vient de l'environnement ; la valeur par défaut sert au développement
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "cle-de-developpement-a-changer")
app.config["BASE"] = os.path.join(DOSSIER, "projet.db")
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024

MODES = {"especes": "Espèces", "mobile_money": "Mobile Money"}
MOTIFS = {"retard": "Retard", "absence": "Absence"}
ROLES = {"membre": "Membre", "tresorier": "Trésorier", "president": "Président"}
PERIODICITES = {"hebdomadaire": "Hebdomadaire", "mensuelle": "Mensuelle"}
STATUTS_TONTINE = {"active": "Active", "terminee": "Terminée", "suspendue": "Suspendue"}
STATUTS_CYCLE = {"en_preparation": "En préparation", "en_cours": "En cours", "termine": "Terminé"}
STATUTS_ADHESION = {"en_attente": "En attente", "active": "Active", "quittee": "A quitté", "refusee": "Refusée"}
OPERATEURS = {"orange_money": "Orange Money", "mtn_momo": "MTN MoMo"}
STATUTS_PAIEMENT = {"en_attente": "En attente", "reussi": "Réussi", "echoue": "Échoué"}
DUREE_PAIEMENT = 10  # minutes avant qu'un paiement non confirmé expire
TYPES_EVENEMENT = {"mariage": "Mariage", "deuil": "Deuil", "naissance": "Naissance", "anniversaire": "Anniversaire",
                   "fete": "Fête", "autre": "Autre"}
CONTRIBUTION_MIN = 500
CONTRIBUTION_MAX = 5000000
COULEURS = {"vert": "Vert", "or": "Or", "turquoise": "Turquoise", "corail": "Corail", "prune": "Prune"}
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]
FORMAT_TELEPHONE = re.compile(r"^6\d{8}$")
FORMAT_DATE_HEURE = "%Y-%m-%d %H:%M:%S"
ALPHABET_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
# Limitation des essais de connexion : au plus 5 échecs par numéro (20 par adresse) en 10 minutes
ECHECS_MAX_TELEPHONE = 5
ECHECS_MAX_ADRESSE = 20
FENETRE_ECHECS = 10
# Empreinte factice : on la vérifie aussi quand le téléphone est inconnu,
# pour que la réponse prenne le même temps dans les deux cas
EMPREINTE_BIDON = generate_password_hash("code-bidon")


# ---------------------------------------------------------------- base de données

def obtenir_base():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["BASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def fermer_base(erreur):
    db = g.pop("db", None)
    if db is not None:
        db.close()


# ---------------------------------------------------------------- outils

def aujourdhui():
    return date.today()


def iso(jour):
    return jour.isoformat()


def lire_date(texte):
    """Renvoie une date à partir d'un texte AAAA-MM-JJ, ou None si le texte est faux."""
    try:
        return datetime.strptime(texte or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def ajouter_mois(depart, nombre):
    mois = depart.month - 1 + nombre
    annee = depart.year + mois // 12
    mois = mois % 12 + 1
    jour = min(depart.day, monthrange(annee, mois)[1])
    return date(annee, mois, jour)


def normaliser_telephone(texte):
    chiffres = re.sub(r"[\s.\-]", "", texte or "")
    for prefixe in ("+237", "00237", "237"):
        if chiffres.startswith(prefixe) and len(chiffres) > 9:
            chiffres = chiffres[len(prefixe):]
            break
    return chiffres


def maintenant():
    return datetime.now().strftime(FORMAT_DATE_HEURE)


@app.template_filter("fcfa")
def filtre_fcfa(valeur):
    return f"{int(valeur or 0):,}".replace(",", "\u00a0") + "\u00a0FCFA"


@app.template_filter("date_fr")
def filtre_date(valeur):
    jour = lire_date((valeur or "")[:10])
    if jour is None:
        return "—"
    return f"{jour.day} {MOIS[jour.month - 1]} {jour.year}"


@app.template_filter("horodatage")
def filtre_horodatage(valeur):
    texte = valeur or ""
    return f"{filtre_date(texte)} à {texte[11:16]}"


def generer_code_invitation(db):
    while True:
        code = "".join(secrets.choice(ALPHABET_CODE) for _ in range(8))
        if not db.execute("SELECT 1 FROM tontines WHERE code_invitation = ?", (code,)).fetchone():
            return code


def noter_action(db, id_tontine, action, detail):
    """Journal des actions : l'auteur vient toujours de la session."""
    db.execute("INSERT INTO journal_actions (tontine_id, utilisateur_id, action, detail) VALUES (?, ?, ?, ?)",
               (id_tontine, g.utilisateur["id"], action, detail))


def notifier(db, id_utilisateur, id_tontine, message):
    db.execute("INSERT INTO notifications (utilisateur_id, tontine_id, message) VALUES (?, ?, ?)",
               (id_utilisateur, id_tontine, message))


def notifier_gestionnaires(db, id_tontine, message):
    for ligne in db.execute("""SELECT utilisateur_id FROM adhesions
                               WHERE tontine_id = ? AND statut = 'active' AND role IN ('tresorier', 'president')""",
                            (id_tontine,)).fetchall():
        notifier(db, ligne["utilisateur_id"], id_tontine, message)


def neutraliser_csv(valeur):
    # Une cellule qui commence par = + - @ serait exécutée comme une formule par le tableur
    texte = str(valeur)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@") else texte


def reponse_csv(nom_fichier, entetes, lignes):
    sortie = io.StringIO()
    ecrivain = csv.writer(sortie, delimiter=";")
    ecrivain.writerow(entetes)
    for ligne in lignes:
        ecrivain.writerow([neutraliser_csv(valeur) for valeur in ligne])
    corps = "\ufeff" + sortie.getvalue()  # le BOM permet à Excel de lire les accents
    return Response(corps, mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{nom_fichier}"'})


def adresse_sure(adresse):
    # On n'accepte que les adresses du site, pour éviter une redirection vers l'extérieur
    return bool(adresse) and adresse.startswith("/") and not adresse.startswith("//") and "\\" not in adresse


def reponse_api_erreur(code, message):
    return jsonify(erreur=message), code


# ---------------------------------------------------------------- session, CSRF et droits

def jeton_csrf():
    if "csrf" not in session:
        session["csrf"] = secrets.token_hex(16)
    return session["csrf"]


def verifier_csrf():
    envoye = request.form.get("csrf") or request.headers.get("X-CSRF-Token", "")
    attendu = session.get("csrf", "")
    if not attendu or not secrets.compare_digest(envoye.encode(), attendu.encode()):
        abort(403)


@app.before_request
def preparer_requete():
    g.utilisateur = None
    g.tontine = None
    g.adhesion = None
    if request.endpoint in (None, "static"):
        return
    if request.method == "POST":
        verifier_csrf()
    id_utilisateur = session.get("utilisateur_id")
    if id_utilisateur:
        ligne = obtenir_base().execute(
            "SELECT id, nom, telephone, est_admin_plateforme, actif FROM utilisateurs WHERE id = ?",
            (id_utilisateur,)).fetchone()
        if ligne and ligne["actif"]:
            g.utilisateur = ligne
        else:
            suspendu = ligne is not None
            session.clear()
            if suspendu:
                flash("Ce compte est suspendu. Contactez l'administrateur de la plateforme.", "error")


@app.after_request
def ajouter_entetes(reponse):
    reponse.headers["X-Content-Type-Options"] = "nosniff"
    reponse.headers["X-Frame-Options"] = "DENY"
    reponse.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data:; form-action 'self'; "
        "frame-ancestors 'none'; base-uri 'self'")
    return reponse


@app.context_processor
def injecter_contexte():
    utilisateur = getattr(g, "utilisateur", None)
    tontine = getattr(g, "tontine", None)
    adhesion = getattr(g, "adhesion", None)
    nb_notifications = 0
    if utilisateur:
        nb_notifications = obtenir_base().execute(
            "SELECT COUNT(*) FROM notifications WHERE utilisateur_id = ? AND lue = 0",
            (utilisateur["id"],)).fetchone()[0]
    role = adhesion["role"] if adhesion else None
    return {
        "jeton_csrf": jeton_csrf, "utilisateur": utilisateur, "nb_notifications": nb_notifications,
        "est_admin_plateforme": bool(utilisateur and utilisateur["est_admin_plateforme"]),
        "tontine": tontine, "adhesion": adhesion,
        "gestionnaire": role in ("tresorier", "president"), "president": role == "president",
        "tontine_modifiable": bool(tontine and tontine["statut"] == "active"),
        "MODES": MODES, "MOTIFS": MOTIFS, "ROLES": ROLES, "PERIODICITES": PERIODICITES,
        "STATUTS_TONTINE": STATUTS_TONTINE, "STATUTS_CYCLE": STATUTS_CYCLE,
        "STATUTS_ADHESION": STATUTS_ADHESION, "COULEURS": COULEURS,
        "OPERATEURS": OPERATEURS, "STATUTS_PAIEMENT": STATUTS_PAIEMENT, "TYPES_EVENEMENT": TYPES_EVENEMENT,
        "aujourdhui": iso(aujourdhui()),
    }


def connexion_requise(vue):
    @wraps(vue)
    def enveloppe(*args, **kwargs):
        if g.utilisateur is None:
            if request.path.startswith("/api/"):
                return reponse_api_erreur(401, "Connexion requise.")
            flash("Connectez-vous pour accéder à cette page.", "info")
            return redirect(url_for("connexion", suivant=request.path))
        return vue(*args, **kwargs)
    return enveloppe


def admin_plateforme(vue):
    @wraps(vue)
    def enveloppe(*args, **kwargs):
        if not g.utilisateur["est_admin_plateforme"]:
            if request.path.startswith("/api/"):
                return reponse_api_erreur(403, "Accès refusé.")
            abort(403)
        return vue(*args, **kwargs)
    return connexion_requise(enveloppe)


def verifier_appartenance(id_tontine):
    """Charge la tontine et l'adhésion de l'utilisateur de la session.
    Si la tontine n'existe pas ou si l'utilisateur n'en est pas membre actif, on répond 404 :
    on ne révèle pas l'existence d'une tontine à quelqu'un qui n'en fait pas partie."""
    db = obtenir_base()
    tontine = db.execute("SELECT * FROM tontines WHERE id = ?", (id_tontine,)).fetchone()
    adhesion = db.execute("""SELECT * FROM adhesions WHERE tontine_id = ? AND utilisateur_id = ?
                             AND statut = 'active'""", (id_tontine, g.utilisateur["id"])).fetchone()
    if tontine is None or adhesion is None:
        abort(404)
    g.tontine = tontine
    g.adhesion = adhesion


def acces_tontine(roles=None, ecriture=True):
    """Fabrique les décorateurs d'accès à une tontine.
    roles : rôles autorisés dans CETTE tontine ; ecriture : les POST sont refusés si la tontine
    est suspendue ou terminée (lecture seule)."""
    def decorateur(vue):
        @wraps(vue)
        def enveloppe(id_tontine, **kwargs):
            verifier_appartenance(id_tontine)
            if roles and g.adhesion["role"] not in roles:
                abort(403)
            if ecriture and request.method == "POST" and g.tontine["statut"] != "active":
                message = f"Cette tontine est {STATUTS_TONTINE[g.tontine['statut']].lower()} : elle est en lecture seule."
                if request.path.startswith("/api/"):
                    return reponse_api_erreur(403, message)
                flash(message, "error")
                return redirect(url_for("tontine_accueil", id_tontine=id_tontine))
            return vue(id_tontine, **kwargs)
        return connexion_requise(enveloppe)
    return decorateur


membre_de_tontine = acces_tontine()
gestionnaire_de_tontine = acces_tontine(("tresorier", "president"))
president_de_tontine = acces_tontine(("president",))
president_meme_si_inactive = acces_tontine(("president",), ecriture=False)


# ---------------------------------------------------------------- cycles, séances, calculs métier

def cycle_ouvert(db, id_tontine):
    return db.execute("""SELECT * FROM cycles WHERE tontine_id = ? AND statut IN ('en_preparation', 'en_cours')
                         ORDER BY date_debut DESC LIMIT 1""", (id_tontine,)).fetchone()


def cycle_actuel(db, id_tontine):
    cycle = cycle_ouvert(db, id_tontine)
    if cycle:
        return cycle
    return db.execute("SELECT * FROM cycles WHERE tontine_id = ? ORDER BY date_debut DESC, id DESC LIMIT 1",
                      (id_tontine,)).fetchone()


def choisir_cycle(db, id_tontine):
    id_cycle = request.args.get("cycle", type=int)
    if id_cycle:
        cycle = db.execute("SELECT * FROM cycles WHERE id = ? AND tontine_id = ?", (id_cycle, id_tontine)).fetchone()
        if cycle:
            return cycle
    return cycle_actuel(db, id_tontine)


def charger_cycle_tontine(db, id_cycle):
    """Un cycle n'est visible que dans sa tontine : un autre identifiant donne un 404."""
    cycle = db.execute("SELECT * FROM cycles WHERE id = ? AND tontine_id = ?", (id_cycle, g.tontine["id"])).fetchone()
    if cycle is None:
        abort(404)
    return cycle


def charger_seance_tontine(db, id_seance):
    seance = db.execute("""SELECT s.* FROM seances s JOIN cycles c ON c.id = s.cycle_id
                           WHERE s.id = ? AND c.tontine_id = ?""", (id_seance, g.tontine["id"])).fetchone()
    if seance is None:
        abort(404)
    cycle = db.execute("SELECT * FROM cycles WHERE id = ?", (seance["cycle_id"],)).fetchone()
    return seance, cycle


def compter_membres(db, id_tontine):
    return db.execute("SELECT COUNT(*) FROM adhesions WHERE tontine_id = ? AND statut = 'active'",
                      (id_tontine,)).fetchone()[0]


def compter_presidents(db, id_tontine):
    return db.execute("""SELECT COUNT(*) FROM adhesions WHERE tontine_id = ? AND statut = 'active'
                         AND role = 'president'""", (id_tontine,)).fetchone()[0]


def lister_seances(db, cycle):
    """Séances d'un cycle avec le montant réellement collecté et l'état (passée, prochaine, à venir)."""
    auj = iso(aujourdhui())
    lignes = db.execute("""
        SELECT s.id, s.numero, s.date, s.beneficiaire_id, u.nom AS beneficiaire_nom,
               COALESCE((SELECT SUM(c.montant) FROM cotisations c WHERE c.seance_id = s.id), 0) AS collecte,
               (SELECT COUNT(*) FROM cotisations c WHERE c.seance_id = s.id) AS nb_payeurs
        FROM seances s
        LEFT JOIN adhesions a ON a.id = s.beneficiaire_id
        LEFT JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE s.cycle_id = ? ORDER BY s.numero""", (cycle["id"],)).fetchall()
    attendu = cycle["montant_cotisation"] * len(lignes)
    seances = []
    prochaine_trouvee = False
    for ligne in lignes:
        seance = dict(ligne)
        seance["attendu"] = attendu
        seance["passee"] = seance["date"] <= auj
        if seance["passee"]:
            seance["etat"] = "passee"
        elif not prochaine_trouvee:
            seance["etat"] = "prochaine"
            prochaine_trouvee = True
        else:
            seance["etat"] = "a_venir"
        seances.append(seance)
    return seances


def calculer_situation(db, cycle, id_adhesion=None):
    """Situation de chaque membre actif de la tontine du cycle.
    dû = (séances passées x cotisation) - total payé, plus les pénalités non payées.
    Rien n'est saisi à la main : tout vient des séances et des cotisations enregistrées."""
    auj = iso(aujourdhui())
    nb_passees = db.execute("SELECT COUNT(*) FROM seances WHERE cycle_id = ? AND date <= ?",
                            (cycle["id"], auj)).fetchone()[0]
    lignes = db.execute("""
        SELECT a.id, u.nom, u.telephone, a.role,
               COUNT(c.id) AS nb_payees,
               COALESCE(SUM(c.montant), 0) AS paye,
               COALESCE(SUM(CASE WHEN c.date_paiement <= s.date THEN 1 ELSE 0 END), 0) AS a_temps
        FROM adhesions a
        JOIN utilisateurs u ON u.id = a.utilisateur_id
        LEFT JOIN seances s ON s.cycle_id = :cycle AND s.date <= :auj
        LEFT JOIN cotisations c ON c.seance_id = s.id AND c.adhesion_id = a.id
        WHERE a.tontine_id = :tontine AND a.statut = 'active' AND (:adhesion IS NULL OR a.id = :adhesion)
        GROUP BY a.id ORDER BY u.nom""",
        {"cycle": cycle["id"], "auj": auj, "tontine": cycle["tontine_id"], "adhesion": id_adhesion}).fetchall()
    penalites = {ligne["adhesion_id"]: ligne for ligne in db.execute("""
        SELECT p.adhesion_id, SUM(p.montant) AS total,
               SUM(CASE WHEN p.payee = 0 THEN p.montant ELSE 0 END) AS non_payees
        FROM penalites p JOIN seances s ON s.id = p.seance_id
        WHERE s.cycle_id = ? GROUP BY p.adhesion_id""", (cycle["id"],))}
    situation = []
    for ligne in lignes:
        attendu = nb_passees * cycle["montant_cotisation"]
        manque = max(0, attendu - ligne["paye"])
        pen = penalites.get(ligne["id"])
        penalites_dues = pen["non_payees"] if pen else 0
        element = dict(ligne)
        element.update(
            nb_passees=nb_passees, attendu=attendu, manque=manque,
            seances_manquantes=nb_passees - ligne["nb_payees"],
            penalites_total=pen["total"] if pen else 0,
            penalites_dues=penalites_dues,
            montant_du=manque + penalites_dues,
            en_retard=manque > 0,
            taux=round(100 * ligne["a_temps"] / nb_passees) if nb_passees else None)
        situation.append(element)
    return situation


def montant_du_adhesion(db, id_tontine, id_adhesion):
    cycle = cycle_actuel(db, id_tontine)
    if cycle is None:
        return 0
    situation = calculer_situation(db, cycle, id_adhesion)
    return situation[0]["montant_du"] if situation else 0


def construire_statistiques(db, cycle):
    seances = lister_seances(db, cycle)
    situation = calculer_situation(db, cycle)
    return {
        "cycle": {"id": cycle["id"], "nom": cycle["nom"], "montant_cotisation": cycle["montant_cotisation"],
                  "nb_seances": len(seances), "nb_passees": sum(1 for s in seances if s["passee"])},
        "collecte_par_seance": [
            {"numero": s["numero"], "date": s["date"], "collecte": s["collecte"], "attendu": s["attendu"]}
            for s in seances if s["passee"]],
        "retards": sorted(
            [{"adhesion_id": m["id"], "nom": m["nom"], "seances_manquantes": m["seances_manquantes"],
              "cotisations_dues": m["manque"], "penalites_dues": m["penalites_dues"], "montant_du": m["montant_du"]}
             for m in situation if m["montant_du"] > 0],
            key=lambda m: -m["montant_du"]),
        "penalites_par_membre": sorted(
            [{"nom": m["nom"], "total": m["penalites_total"], "non_payees": m["penalites_dues"]}
             for m in situation if m["penalites_total"] > 0],
            key=lambda m: -m["total"]),
        "ponctualite": sorted(
            [{"nom": m["nom"], "a_temps": m["a_temps"], "seances_passees": m["nb_passees"], "taux": m["taux"]}
             for m in situation],
            key=lambda m: (-(m["taux"] if m["taux"] is not None else -1), m["nom"])),
    }


def etat_seance(db, seance, cycle):
    """Chiffres d'une séance, toujours recalculés à partir des cotisations enregistrées."""
    total, payeurs = db.execute(
        "SELECT COALESCE(SUM(montant), 0), COUNT(*) FROM cotisations WHERE seance_id = ?",
        (seance["id"],)).fetchone()
    nb_seances = db.execute("SELECT COUNT(*) FROM seances WHERE cycle_id = ?", (cycle["id"],)).fetchone()[0]
    retardataires = db.execute("""
        SELECT COUNT(*) FROM adhesions a WHERE a.tontine_id = ? AND a.statut = 'active'
        AND NOT EXISTS (SELECT 1 FROM cotisations c WHERE c.seance_id = ? AND c.adhesion_id = a.id)""",
        (cycle["tontine_id"], seance["id"])).fetchone()[0]
    return {"seance_id": seance["id"], "numero": seance["numero"], "date": seance["date"],
            "total_collecte": total, "attendu": cycle["montant_cotisation"] * nb_seances,
            "nb_payeurs": payeurs, "nb_retardataires": retardataires,
            "passee": seance["date"] <= iso(aujourdhui())}


def recalculer_total_seance(db, id_seance):
    db.execute("""UPDATE seances SET montant_total_collecte =
                  (SELECT COALESCE(SUM(montant), 0) FROM cotisations WHERE seance_id = ?)
                  WHERE id = ?""", (id_seance, id_seance))


def resumer_mes_tontines(db, id_utilisateur):
    """Une ligne par tontine de l'utilisateur : rôle, prochaine séance, montant dû, progression du cycle."""
    lignes = db.execute("""
        SELECT t.id, t.nom, t.couleur, t.statut, a.id AS id_adhesion, a.role
        FROM adhesions a JOIN tontines t ON t.id = a.tontine_id
        WHERE a.utilisateur_id = ? AND a.statut = 'active' ORDER BY t.nom""", (id_utilisateur,)).fetchall()
    resume = []
    for ligne in lignes:
        element = dict(ligne)
        element.update(cycle_nom=None, prochaine_numero=None, prochaine_date=None, du=0,
                       progression=0, tour_date=None)
        cycle = cycle_actuel(db, ligne["id"])
        if cycle:
            seances = lister_seances(db, cycle)
            situation = calculer_situation(db, cycle, ligne["id_adhesion"])
            prochaine = next((s for s in seances if s["etat"] == "prochaine"), None)
            mon_tour = next((s for s in seances if s["beneficiaire_id"] == ligne["id_adhesion"]), None)
            element.update(
                cycle_nom=cycle["nom"], du=situation[0]["montant_du"] if situation else 0,
                progression=round(100 * sum(1 for s in seances if s["passee"]) / len(seances)) if seances else 0,
                prochaine_numero=prochaine["numero"] if prochaine else None,
                prochaine_date=prochaine["date"] if prochaine else None,
                tour_date=mon_tour["date"] if mon_tour else None)
        element["verse"] = db.execute("SELECT COALESCE(SUM(montant), 0) FROM cotisations WHERE adhesion_id = ?",
                                      (ligne["id_adhesion"],)).fetchone()[0]
        resume.append(element)
    return resume


# ---------------------------------------------------------------- pages publiques et compte utilisateur

@app.route("/")
def accueil():
    db = obtenir_base()
    chiffres = {
        "tontines": db.execute("SELECT COUNT(*) FROM tontines WHERE statut != 'suspendue'").fetchone()[0],
        "membres": db.execute("SELECT COUNT(*) FROM utilisateurs WHERE actif = 1").fetchone()[0],
        "seances": db.execute("SELECT COUNT(*) FROM seances WHERE date <= ?", (iso(aujourdhui()),)).fetchone()[0],
        "collecte": db.execute("SELECT COALESCE(SUM(montant), 0) FROM cotisations").fetchone()[0],
    }
    return render_template("accueil.html", chiffres=chiffres)


def trop_d_echecs(db, telephone, adresse):
    limite = (datetime.now() - timedelta(minutes=FENETRE_ECHECS)).strftime(FORMAT_DATE_HEURE)
    db.execute("DELETE FROM tentatives_connexion WHERE date_tentative < ?", (limite,))
    par_telephone = db.execute("SELECT COUNT(*) FROM tentatives_connexion WHERE telephone = ?",
                               (telephone,)).fetchone()[0]
    par_adresse = db.execute("SELECT COUNT(*) FROM tentatives_connexion WHERE adresse_ip = ?",
                             (adresse,)).fetchone()[0]
    return par_telephone >= ECHECS_MAX_TELEPHONE or par_adresse >= ECHECS_MAX_ADRESSE


@app.route("/inscription", methods=["GET", "POST"])
def inscription():
    if g.utilisateur is not None:
        return redirect(url_for("mes_tontines"))
    valeurs = {"nom": "", "telephone": ""}
    if request.method == "POST":
        db = obtenir_base()
        nom = " ".join(request.form.get("nom", "").split())
        telephone = normaliser_telephone(request.form.get("telephone", ""))
        code = request.form.get("code", "")
        valeurs = {"nom": nom, "telephone": telephone}
        erreurs = []
        if not 2 <= len(nom) <= 80:
            erreurs.append("Le nom doit contenir entre 2 et 80 caractères.")
        if not FORMAT_TELEPHONE.match(telephone):
            erreurs.append("Le téléphone doit avoir 9 chiffres et commencer par 6 (exemple : 677123456).")
        elif db.execute("SELECT 1 FROM utilisateurs WHERE telephone = ?", (telephone,)).fetchone():
            erreurs.append("Un compte existe déjà avec ce numéro de téléphone.")
        if len(code) < 6:
            erreurs.append("Le code d'accès doit contenir au moins 6 caractères.")
        if code != request.form.get("confirmation", ""):
            erreurs.append("Les deux codes d'accès ne sont pas identiques.")
        if not erreurs:
            curseur = db.execute("""INSERT INTO utilisateurs (nom, telephone, code_acces, date_inscription)
                                    VALUES (?, ?, ?, ?)""",
                                 (nom, telephone, generate_password_hash(code), iso(aujourdhui())))
            db.commit()
            session.clear()
            session["utilisateur_id"] = curseur.lastrowid
            flash("Votre compte est créé. Créez une tontine ou rejoignez-en une.", "success")
            return redirect(url_for("mes_tontines"))
        for message in erreurs:
            flash(message, "error")
        return render_template("inscription.html", valeurs=valeurs), 400
    return render_template("inscription.html", valeurs=valeurs)


@app.route("/connexion", methods=["GET", "POST"])
def connexion():
    if g.utilisateur is not None:
        return redirect(url_for("mes_tontines"))
    suivant = request.values.get("suivant", "")
    if request.method == "POST":
        db = obtenir_base()
        telephone = normaliser_telephone(request.form.get("telephone", ""))
        code = request.form.get("code", "")
        adresse = request.remote_addr or "inconnue"
        if trop_d_echecs(db, telephone, adresse):
            db.commit()
            flash(f"Trop de tentatives échouées. Réessayez dans {FENETRE_ECHECS} minutes.", "error")
            return render_template("connexion.html", suivant=suivant), 429
        ligne = db.execute("SELECT * FROM utilisateurs WHERE telephone = ? AND actif = 1", (telephone,)).fetchone()
        empreinte = ligne["code_acces"] if ligne else EMPREINTE_BIDON
        if check_password_hash(empreinte, code) and ligne:
            db.execute("DELETE FROM tentatives_connexion WHERE telephone = ?", (telephone,))
            db.commit()
            session.clear()  # nouvelle session à chaque connexion
            session["utilisateur_id"] = ligne["id"]
            flash(f"Bienvenue {ligne['nom']}.", "success")
            return redirect(suivant if adresse_sure(suivant) else url_for("mes_tontines"))
        db.execute("INSERT INTO tentatives_connexion (telephone, adresse_ip, date_tentative) VALUES (?, ?, ?)",
                   (telephone, adresse, maintenant()))
        db.commit()
        flash("Téléphone ou code d'accès incorrect.", "error")
    return render_template("connexion.html", suivant=suivant)


@app.post("/deconnexion")
def deconnexion():
    session.clear()
    flash("Vous êtes déconnecté.", "info")
    return redirect(url_for("accueil"))


@app.get("/profil")
@connexion_requise
def profil():
    return render_template("profil.html", valeurs={"nom": g.utilisateur["nom"], "telephone": g.utilisateur["telephone"]})


@app.post("/profil")
@connexion_requise
def modifier_profil():
    db = obtenir_base()
    nom = " ".join(request.form.get("nom", "").split())
    telephone = normaliser_telephone(request.form.get("telephone", ""))
    erreurs = []
    if not 2 <= len(nom) <= 80:
        erreurs.append("Le nom doit contenir entre 2 et 80 caractères.")
    if not FORMAT_TELEPHONE.match(telephone):
        erreurs.append("Le téléphone doit avoir 9 chiffres et commencer par 6.")
    elif db.execute("SELECT 1 FROM utilisateurs WHERE telephone = ? AND id != ?",
                    (telephone, g.utilisateur["id"])).fetchone():
        erreurs.append("Ce numéro appartient déjà à un autre compte.")
    if erreurs:
        for message in erreurs:
            flash(message, "error")
        return render_template("profil.html", valeurs={"nom": nom, "telephone": telephone}), 400
    db.execute("UPDATE utilisateurs SET nom = ?, telephone = ? WHERE id = ?", (nom, telephone, g.utilisateur["id"]))
    db.commit()
    flash("Votre profil est à jour.", "success")
    return redirect(url_for("profil"))


@app.post("/profil/code")
@connexion_requise
def modifier_code():
    db = obtenir_base()
    ligne = db.execute("SELECT code_acces FROM utilisateurs WHERE id = ?", (g.utilisateur["id"],)).fetchone()
    nouveau = request.form.get("nouveau", "")
    if not check_password_hash(ligne["code_acces"], request.form.get("ancien", "")):
        flash("L'ancien code d'accès est incorrect.", "error")
    elif len(nouveau) < 6:
        flash("Le nouveau code doit contenir au moins 6 caractères.", "error")
    elif nouveau != request.form.get("confirmation", ""):
        flash("Les deux nouveaux codes ne sont pas identiques.", "error")
    else:
        db.execute("UPDATE utilisateurs SET code_acces = ? WHERE id = ?",
                   (generate_password_hash(nouveau), g.utilisateur["id"]))
        db.commit()
        flash("Votre code d'accès a été changé.", "success")
    return redirect(url_for("profil"))


@app.get("/notifications")
@connexion_requise
def notifications():
    lignes = obtenir_base().execute("""
        SELECT n.message, n.lue, n.date_creation, t.nom AS tontine_nom FROM notifications n
        LEFT JOIN tontines t ON t.id = n.tontine_id
        WHERE n.utilisateur_id = ? ORDER BY n.id DESC LIMIT 60""", (g.utilisateur["id"],)).fetchall()
    return render_template("notifications.html", lignes=lignes)


@app.post("/notifications/lues")
@connexion_requise
def marquer_notifications_lues():
    db = obtenir_base()
    db.execute("UPDATE notifications SET lue = 1 WHERE utilisateur_id = ?", (g.utilisateur["id"],))
    db.commit()
    return redirect(url_for("notifications"))


# ---------------------------------------------------------------- mes tontines, création, adhésion

@app.get("/mes-tontines")
@connexion_requise
def mes_tontines():
    db = obtenir_base()
    resume = resumer_mes_tontines(db, g.utilisateur["id"])
    attentes = db.execute("""SELECT t.nom, a.date_adhesion FROM adhesions a JOIN tontines t ON t.id = a.tontine_id
                             WHERE a.utilisateur_id = ? AND a.statut = 'en_attente' ORDER BY a.id DESC""",
                          (g.utilisateur["id"],)).fetchall()
    return render_template("mes_tontines.html", resume=resume, attentes=attentes)


def valider_tontine(formulaire, nb_membres_actuel=0):
    """Vérifie les champs d'une tontine ; renvoie les données propres et la liste des erreurs."""
    erreurs = []
    nom = " ".join(formulaire.get("nom", "").split())
    description = " ".join(formulaire.get("description", "").split())
    maximum = formulaire.get("nombre_max_membres", type=int)
    couleur = formulaire.get("couleur", "")
    mode = formulaire.get("adhesion", "")
    if not 2 <= len(nom) <= 80:
        erreurs.append("Le nom doit contenir entre 2 et 80 caractères.")
    if len(description) > 300:
        erreurs.append("La description ne doit pas dépasser 300 caractères.")
    if maximum is None or not 2 <= maximum <= 200:
        erreurs.append("Le nombre maximal de membres doit être compris entre 2 et 200.")
    elif maximum < nb_membres_actuel:
        erreurs.append(f"La tontine compte déjà {nb_membres_actuel} membres : le maximum ne peut pas être plus bas.")
    if couleur not in COULEURS:
        erreurs.append("Couleur invalide.")
    if mode not in ("libre", "validation"):
        erreurs.append("Choisissez le mode d'adhésion.")
    donnees = {"nom": nom, "description": description, "nombre_max_membres": maximum, "couleur": couleur,
               "adhesion": mode, "adhesion_libre": 1 if mode == "libre" else 0,
               "publique": 1 if formulaire.get("publique") else 0}
    return donnees, erreurs


@app.route("/tontines/nouvelle", methods=["GET", "POST"])
@connexion_requise
def tontine_nouvelle():
    valeurs = {"nom": "", "description": "", "nombre_max_membres": 25, "couleur": "vert",
               "adhesion": "validation", "publique": 0}
    if request.method == "POST":
        db = obtenir_base()
        donnees, erreurs = valider_tontine(request.form)
        if erreurs:
            for message in erreurs:
                flash(message, "error")
            return render_template("tontine_nouvelle.html", valeurs=donnees), 400
        curseur = db.execute("""INSERT INTO tontines (nom, description, createur_id, code_invitation, adhesion_libre,
                                publique, nombre_max_membres, couleur, date_creation)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                             (donnees["nom"], donnees["description"], g.utilisateur["id"],
                              generer_code_invitation(db), donnees["adhesion_libre"], donnees["publique"],
                              donnees["nombre_max_membres"], donnees["couleur"], iso(aujourdhui())))
        id_tontine = curseur.lastrowid
        # Le créateur devient président de sa tontine
        db.execute("""INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion)
                      VALUES (?, ?, 'president', 'active', ?)""", (id_tontine, g.utilisateur["id"], iso(aujourdhui())))
        noter_action(db, id_tontine, "Tontine créée", donnees["nom"])
        db.commit()
        flash("Votre tontine est créée. Partagez son code d'invitation pour inviter des membres.", "success")
        return redirect(url_for("tontine_accueil", id_tontine=id_tontine))
    return render_template("tontine_nouvelle.html", valeurs=valeurs)


def demander_adhesion(db, tontine, id_utilisateur):
    """Crée une adhésion (active ou en attente selon la tontine). Renvoie (succès, message)."""
    if tontine["statut"] != "active":
        return False, "Cette tontine n'accepte pas de nouveaux membres."
    if cycle_ouvert(db, tontine["id"]):
        return False, "Un cycle est en cours : les adhésions rouvrent à la fin du cycle."
    existante = db.execute("SELECT * FROM adhesions WHERE tontine_id = ? AND utilisateur_id = ?",
                           (tontine["id"], id_utilisateur)).fetchone()
    if existante and existante["statut"] == "active":
        return False, "Vous êtes déjà membre de cette tontine."
    if existante and existante["statut"] == "en_attente":
        return False, "Votre demande d'adhésion est déjà en attente de validation."
    if compter_membres(db, tontine["id"]) >= tontine["nombre_max_membres"]:
        return False, "Cette tontine a atteint son nombre maximal de membres."
    statut = "active" if tontine["adhesion_libre"] else "en_attente"
    if existante:
        db.execute("UPDATE adhesions SET statut = ?, role = 'membre', date_adhesion = ? WHERE id = ?",
                   (statut, iso(aujourdhui()), existante["id"]))
    else:
        db.execute("""INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion)
                      VALUES (?, ?, 'membre', ?, ?)""", (tontine["id"], id_utilisateur, statut, iso(aujourdhui())))
    if statut == "en_attente":
        notifier_gestionnaires(db, tontine["id"], f"{g.utilisateur['nom']} demande à rejoindre la tontine.")
    db.commit()
    return True, statut


@app.get("/rejoindre")
@connexion_requise
def rejoindre():
    db = obtenir_base()
    ouvertes = db.execute("""
        SELECT t.id, t.nom, t.description, t.couleur, t.adhesion_libre, t.nombre_max_membres,
               (SELECT COUNT(*) FROM adhesions a WHERE a.tontine_id = t.id AND a.statut = 'active') AS nb_membres
        FROM tontines t
        WHERE t.publique = 1 AND t.statut = 'active'
          AND NOT EXISTS (SELECT 1 FROM adhesions a WHERE a.tontine_id = t.id AND a.utilisateur_id = ?
                          AND a.statut IN ('active', 'en_attente'))
          AND NOT EXISTS (SELECT 1 FROM cycles c WHERE c.tontine_id = t.id AND c.statut IN ('en_preparation', 'en_cours'))
        ORDER BY t.nom""", (g.utilisateur["id"],)).fetchall()
    ouvertes = [t for t in ouvertes if t["nb_membres"] < t["nombre_max_membres"]]
    return render_template("rejoindre.html", ouvertes=ouvertes)


def finir_adhesion(db, tontine, succes, resultat):
    if not succes:
        flash(resultat, "error")
        return redirect(url_for("rejoindre"))
    if resultat == "active":
        flash(f"Bienvenue dans la tontine « {tontine['nom']} ».", "success")
        return redirect(url_for("tontine_accueil", id_tontine=tontine["id"]))
    flash(f"Votre demande pour « {tontine['nom']} » est envoyée : le bureau doit la valider.", "success")
    return redirect(url_for("mes_tontines"))


@app.post("/rejoindre")
@connexion_requise
def rejoindre_avec_code():
    db = obtenir_base()
    code = request.form.get("code", "").strip().upper()
    tontine = db.execute("SELECT * FROM tontines WHERE code_invitation = ?", (code,)).fetchone()
    if tontine is None:
        flash("Ce code d'invitation ne correspond à aucune tontine.", "error")
        return redirect(url_for("rejoindre"))
    succes, resultat = demander_adhesion(db, tontine, g.utilisateur["id"])
    return finir_adhesion(db, tontine, succes, resultat)


@app.post("/tontines/<int:id_tontine>/demander")
@connexion_requise
def demander_a_rejoindre(id_tontine):
    db = obtenir_base()
    # Seules les tontines visibles dans l'annuaire se rejoignent sans code
    tontine = db.execute("SELECT * FROM tontines WHERE id = ? AND publique = 1", (id_tontine,)).fetchone()
    if tontine is None:
        abort(404)
    succes, resultat = demander_adhesion(db, tontine, g.utilisateur["id"])
    return finir_adhesion(db, tontine, succes, resultat)


def a_deja_beneficie(db, id_adhesion, id_cycle):
    return db.execute("SELECT 1 FROM seances WHERE cycle_id = ? AND beneficiaire_id = ? AND date <= ?",
                      (id_cycle, id_adhesion, iso(aujourdhui()))).fetchone() is not None


@app.post("/tontines/<int:id_tontine>/quitter")
@membre_de_tontine
def quitter_tontine(id_tontine):
    db = obtenir_base()
    retour = redirect(url_for("tontine_accueil", id_tontine=id_tontine))
    # Tant que le cycle n'est pas terminé, personne ne part : le cycle compte sur tous ses membres
    cycle = cycle_ouvert(db, id_tontine)
    if cycle:
        if a_deja_beneficie(db, g.adhesion["id"], cycle["id"]):
            flash("Vous avez déjà reçu la cagnotte de ce cycle : vous devez rester dans la tontine jusqu'à la fin du cycle.", "error")
        else:
            flash("Un cycle est en cours : vous ne pouvez pas quitter la tontine avant sa fin.", "error")
        return retour
    if g.adhesion["role"] == "president" and compter_presidents(db, id_tontine) <= 1:
        flash("Vous êtes le dernier président : désignez un autre président avant de partir.", "error")
        return retour
    du = montant_du_adhesion(db, id_tontine, g.adhesion["id"])
    if du > 0:
        flash(f"Vous devez encore {filtre_fcfa(du)} : réglez vos sommes avant de quitter la tontine.", "error")
        return retour
    db.execute("UPDATE adhesions SET statut = 'quittee' WHERE id = ?", (g.adhesion["id"],))
    noter_action(db, id_tontine, "Départ", f"{g.utilisateur['nom']} a quitté la tontine")
    db.commit()
    flash(f"Vous avez quitté la tontine « {g.tontine['nom']} ».", "info")
    return redirect(url_for("mes_tontines"))


# ---------------------------------------------------------------- espace d'une tontine (tous les membres actifs)

def motif_recherche(q):
    protege = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{protege}%"


@app.get("/tontines/<int:id_tontine>")
@membre_de_tontine
def tontine_accueil(id_tontine):
    db = obtenir_base()
    cycle = cycle_actuel(db, id_tontine)
    donnees = {"cycle": cycle, "nb_membres": compter_membres(db, id_tontine), "nb_demandes": 0}
    if g.adhesion["role"] in ("tresorier", "president"):
        donnees["nb_demandes"] = db.execute("SELECT COUNT(*) FROM adhesions WHERE tontine_id = ? AND statut = 'en_attente'",
                                            (id_tontine,)).fetchone()[0]
    if cycle:
        seances = lister_seances(db, cycle)
        situation = calculer_situation(db, cycle, g.adhesion["id"])
        nb_passees = sum(1 for s in seances if s["passee"])
        donnees.update(
            seances=seances, moi=situation[0] if situation else None, nb_passees=nb_passees,
            progression=round(100 * nb_passees / len(seances)) if seances else 0,
            cagnotte=cycle["montant_cotisation"] * len(seances),
            prochaine=next((s for s in seances if s["etat"] == "prochaine"), None),
            mon_tour=next((s for s in seances if s["beneficiaire_id"] == g.adhesion["id"]), None))
    donnees["evenements"] = [e for e in lister_evenements(db, id_tontine) if e["accepte"]][:3]
    return render_template("tontine/accueil.html", **donnees)


def lire_contributions(db, id_adhesion):
    return db.execute("""
        SELECT e.id AS id_evenement, e.titre, c.montant, c.date_contribution, c.mode FROM contributions_evenement c
        JOIN evenements e ON e.id = c.evenement_id WHERE c.adhesion_id = ? ORDER BY c.id DESC LIMIT 30""",
        (id_adhesion,)).fetchall()


@app.get("/tontines/<int:id_tontine>/mon-espace")
@membre_de_tontine
def mon_espace(id_tontine):
    db = obtenir_base()
    cycle = cycle_actuel(db, id_tontine)
    if cycle is None:
        return render_template("tontine/mon_espace.html", cycle=None,
                               contributions=lire_contributions(db, g.adhesion["id"]))
    # Tout est filtré sur l'adhésion de la session
    id_adhesion = g.adhesion["id"]
    seances = lister_seances(db, cycle)
    situation = calculer_situation(db, cycle, id_adhesion)
    cotisations = db.execute("""
        SELECT s.numero, s.date AS date_seance, c.montant, c.date_paiement, c.mode
        FROM cotisations c JOIN seances s ON s.id = c.seance_id
        WHERE c.adhesion_id = ? AND s.cycle_id = ? ORDER BY s.numero""", (id_adhesion, cycle["id"])).fetchall()
    penalites = db.execute("""
        SELECT p.motif, p.montant, p.payee, s.numero
        FROM penalites p JOIN seances s ON s.id = p.seance_id
        WHERE p.adhesion_id = ? AND s.cycle_id = ? ORDER BY s.numero""", (id_adhesion, cycle["id"])).fetchall()
    moi = situation[0] if situation else None
    nb_passees = sum(1 for s in seances if s["passee"])
    contributions = lire_contributions(db, id_adhesion)
    return render_template(
        "tontine/mon_espace.html", cycle=cycle, seances=seances, moi=moi, cotisations=cotisations,
        penalites=penalites, nb_passees=nb_passees, contributions=contributions,
        mon_tour=next((s for s in seances if s["beneficiaire_id"] == id_adhesion), None),
        progression_cycle=round(100 * nb_passees / len(seances)) if seances else 0,
        progression_paiements=round(100 * moi["nb_payees"] / nb_passees) if moi and nb_passees else 0)


@app.get("/tontines/<int:id_tontine>/calendrier")
@membre_de_tontine
def calendrier(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    return render_template("tontine/calendrier.html", cycle=cycle, seances=lister_seances(db, cycle) if cycle else [])


@app.get("/tontines/<int:id_tontine>/transparence")
@membre_de_tontine
def transparence(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    seances = [s for s in lister_seances(db, cycle) if s["passee"]] if cycle else []
    statuts = {}
    if cycle:
        # Pour chaque séance passée : seulement payé ou non payé, ni montant, ni date, ni mode
        for ligne in db.execute("""
            SELECT s.id AS id_seance, u.nom, (c.id IS NOT NULL) AS paye
            FROM seances s CROSS JOIN adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
            LEFT JOIN cotisations c ON c.seance_id = s.id AND c.adhesion_id = a.id
            WHERE s.cycle_id = ? AND s.date <= ? AND a.tontine_id = ? AND (a.statut = 'active' OR c.id IS NOT NULL)
            ORDER BY s.numero, u.nom""", (cycle["id"], iso(aujourdhui()), id_tontine)):
            statuts.setdefault(ligne["id_seance"], []).append(ligne)
    return render_template("tontine/transparence.html", cycle=cycle, seances=seances, statuts=statuts)


@app.get("/tontines/<int:id_tontine>/membres")
@membre_de_tontine
def tontine_membres(id_tontine):
    q = request.args.get("q", "").strip()[:60]
    membres = obtenir_base().execute("""
        SELECT a.id, u.nom, u.telephone, a.role, a.date_adhesion FROM adhesions a
        JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE a.tontine_id = ? AND a.statut = 'active' AND u.nom LIKE ? ESCAPE '\\' ORDER BY u.nom""",
        (id_tontine, motif_recherche(q))).fetchall()
    return render_template("tontine/membres.html", membres=membres, q=q)


# ---------------------------------------------------------------- administration : tableau de bord et séances

@app.get("/tontines/<int:id_tontine>/admin")
@gestionnaire_de_tontine
def tontine_admin(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    donnees = {"cycle": cycle}
    if cycle:
        seances = lister_seances(db, cycle)
        situation = calculer_situation(db, cycle)
        donnees.update(
            attendu_seance=cycle["montant_cotisation"] * len(seances),
            total_collecte=sum(s["collecte"] for s in seances),
            nb_retardataires=sum(1 for m in situation if m["en_retard"]),
            penalites_impayees=sum(m["penalites_dues"] for m in situation),
            prochaine=next((s for s in seances if s["etat"] == "prochaine"), None))
    donnees["nb_demandes"] = db.execute("SELECT COUNT(*) FROM adhesions WHERE tontine_id = ? AND statut = 'en_attente'",
                                        (id_tontine,)).fetchone()[0]
    return render_template("tontine/admin/tableau_bord.html", **donnees)


def lister_membres_actifs(db, id_tontine):
    return db.execute("""SELECT a.id, u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                         WHERE a.tontine_id = ? AND a.statut = 'active' ORDER BY u.nom""", (id_tontine,)).fetchall()


@app.get("/tontines/<int:id_tontine>/admin/seances")
@gestionnaire_de_tontine
def liste_seances(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    seances = lister_seances(db, cycle) if cycle else []
    deja = {s["beneficiaire_id"] for s in seances if s["beneficiaire_id"]}
    return render_template("tontine/admin/seances.html", cycle=cycle, seances=seances, deja=deja,
                           membres=lister_membres_actifs(db, id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/seances/<int:id_seance>/beneficiaire")
@gestionnaire_de_tontine
def designer_beneficiaire(id_tontine, id_seance):
    db = obtenir_base()
    seance, cycle = charger_seance_tontine(db, id_seance)
    retour = redirect(url_for("liste_seances", id_tontine=id_tontine, cycle=cycle["id"]))
    if cycle["statut"] == "termine":
        flash("Ce cycle est terminé : on ne change plus les bénéficiaires.", "error")
        return retour
    brut = request.form.get("beneficiaire_id", "")
    passee = seance["date"] <= iso(aujourdhui())
    if brut == "":
        if passee:
            flash("On ne peut pas retirer le bénéficiaire d'une séance déjà passée.", "error")
            return retour
        nouveau, membre = None, None
    else:
        if not brut.isdigit():
            abort(400)
        nouveau = int(brut)
        # Le bénéficiaire doit être un membre actif de la même tontine
        membre = db.execute("""SELECT a.id, a.utilisateur_id, u.nom FROM adhesions a
                               JOIN utilisateurs u ON u.id = a.utilisateur_id
                               WHERE a.id = ? AND a.tontine_id = ? AND a.statut = 'active'""",
                            (nouveau, id_tontine)).fetchone()
        if membre is None:
            flash("Ce membre n'existe pas dans la tontine ou n'est pas actif.", "error")
            return retour
        if passee and seance["beneficiaire_id"] and seance["beneficiaire_id"] != nouveau:
            flash("Le bénéficiaire d'une séance passée ne peut plus être changé.", "error")
            return retour
        autre = db.execute("SELECT numero FROM seances WHERE cycle_id = ? AND beneficiaire_id = ? AND id != ?",
                           (cycle["id"], nouveau, id_seance)).fetchone()
        if autre:
            flash(f"{membre['nom']} bénéficie déjà de la séance n° {autre['numero']} dans ce cycle : "
                  "un membre ne reçoit la cagnotte qu'une fois par cycle.", "error")
            return retour
    try:
        db.execute("UPDATE seances SET beneficiaire_id = ? WHERE id = ?", (nouveau, id_seance))
        if membre:
            noter_action(db, id_tontine, "Bénéficiaire", f"Séance n° {seance['numero']} : {membre['nom']}")
            notifier(db, membre["utilisateur_id"], id_tontine,
                     f"Vous êtes bénéficiaire de la séance n° {seance['numero']} du {filtre_date(seance['date'])}.")
        else:
            noter_action(db, id_tontine, "Bénéficiaire", f"Séance n° {seance['numero']} : bénéficiaire retiré")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Ce membre est déjà bénéficiaire dans ce cycle.", "error")
        return retour
    flash(f"Bénéficiaire de la séance n° {seance['numero']} enregistré.", "success")
    return retour


# ---------------------------------------------------------------- administration : cotisations d'une séance

def lire_lignes_cotisations(db, id_tontine, id_seance):
    return db.execute("""
        SELECT a.id, u.nom, u.telephone, c.id AS cotisation_id, c.montant, c.date_paiement, c.mode
        FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
        LEFT JOIN cotisations c ON c.adhesion_id = a.id AND c.seance_id = ?
        WHERE a.tontine_id = ? AND (a.statut = 'active' OR c.id IS NOT NULL) ORDER BY u.nom""",
        (id_seance, id_tontine)).fetchall()


@app.get("/tontines/<int:id_tontine>/admin/seances/<int:id_seance>/cotisations")
@gestionnaire_de_tontine
def page_cotisations(id_tontine, id_seance):
    db = obtenir_base()
    seance, cycle = charger_seance_tontine(db, id_seance)
    passee = seance["date"] <= iso(aujourdhui())
    saisie = passee and cycle["statut"] == "en_cours" and g.tontine["statut"] == "active"
    return render_template("tontine/admin/cotisations.html", seance=seance, cycle=cycle, passee=passee, saisie=saisie,
                           lignes=lire_lignes_cotisations(db, id_tontine, id_seance),
                           etat=etat_seance(db, seance, cycle))


@app.post("/tontines/<int:id_tontine>/admin/seances/<int:id_seance>/cotisations")
@gestionnaire_de_tontine
def enregistrer_cotisations(id_tontine, id_seance):
    db = obtenir_base()
    seance, cycle = charger_seance_tontine(db, id_seance)
    retour = redirect(url_for("page_cotisations", id_tontine=id_tontine, id_seance=id_seance))
    if cycle["statut"] != "en_cours":
        flash("Le cycle n'est pas en cours : on ne peut pas enregistrer de cotisation.", "error")
        return retour
    if seance["date"] > iso(aujourdhui()):
        flash("Cette séance n'a pas encore eu lieu : on ne peut pas enregistrer de cotisation.", "error")
        return retour
    cochees = request.form.getlist("paye")
    if not cochees:
        flash("Cochez au moins un membre qui a payé.", "error")
        return retour
    erreurs, a_inserer, vus = [], [], set()
    for brut in cochees:
        if not brut.isdigit():
            abort(400)
        id_adhesion = int(brut)
        if id_adhesion in vus:
            continue
        vus.add(id_adhesion)
        # Le membre doit appartenir à CETTE tontine : un identifiant d'une autre tontine est refusé
        membre = db.execute("""SELECT a.id, a.utilisateur_id, u.nom FROM adhesions a
                               JOIN utilisateurs u ON u.id = a.utilisateur_id
                               WHERE a.id = ? AND a.tontine_id = ? AND a.statut = 'active'""",
                            (id_adhesion, id_tontine)).fetchone()
        if membre is None:
            erreurs.append(f"Le membre n° {id_adhesion} ne fait pas partie de cette tontine.")
            continue
        mode = request.form.get(f"mode_{id_adhesion}", "")
        jour = lire_date(request.form.get(f"date_{id_adhesion}", ""))
        montant = request.form.get(f"montant_{id_adhesion}", type=int)
        if mode not in MODES:
            erreurs.append(f"{membre['nom']} : mode de paiement invalide.")
        elif jour is None or jour > aujourdhui():
            erreurs.append(f"{membre['nom']} : la date de paiement est invalide ou dans le futur.")
        elif montant != cycle["montant_cotisation"]:
            erreurs.append(f"{membre['nom']} : le montant doit être de {filtre_fcfa(cycle['montant_cotisation'])}.")
        elif db.execute("SELECT 1 FROM cotisations WHERE seance_id = ? AND adhesion_id = ?",
                        (id_seance, id_adhesion)).fetchone():
            erreurs.append(f"{membre['nom']} a déjà cotisé pour cette séance.")
        else:
            a_inserer.append((id_seance, id_adhesion, cycle["montant_cotisation"], iso(jour), mode, membre["utilisateur_id"]))
    if erreurs:
        for message in erreurs:
            flash(message, "error")
        return retour
    try:
        db.executemany("""INSERT INTO cotisations (seance_id, adhesion_id, montant, date_paiement, mode)
                          VALUES (?, ?, ?, ?, ?)""", [ligne[:5] for ligne in a_inserer])
        recalculer_total_seance(db, id_seance)
        for ligne in a_inserer:
            notifier(db, ligne[5], id_tontine, f"Votre cotisation de la séance n° {seance['numero']} est enregistrée.")
        noter_action(db, id_tontine, "Cotisations", f"Séance n° {seance['numero']} : {len(a_inserer)} cotisation(s) enregistrée(s)")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Une des cotisations existe déjà pour cette séance : rien n'a été enregistré.", "error")
        return retour
    etat = etat_seance(db, seance, cycle)
    flash(f"{len(a_inserer)} cotisation(s) enregistrée(s). Total collecté : {filtre_fcfa(etat['total_collecte'])} "
          f"sur {filtre_fcfa(etat['attendu'])} attendus, {etat['nb_retardataires']} retardataire(s).", "success")
    return retour


# ---------------------------------------------------------------- administration : pénalités

@app.get("/tontines/<int:id_tontine>/admin/penalites")
@gestionnaire_de_tontine
def liste_penalites(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    penalites, seances = [], []
    if cycle:
        penalites = db.execute("""
            SELECT p.id, u.nom, s.numero, p.motif, p.montant, p.payee
            FROM penalites p JOIN seances s ON s.id = p.seance_id
            JOIN adhesions a ON a.id = p.adhesion_id JOIN utilisateurs u ON u.id = a.utilisateur_id
            WHERE s.cycle_id = ? ORDER BY p.payee, s.numero DESC, u.nom""", (cycle["id"],)).fetchall()
        seances = [s for s in lister_seances(db, cycle) if s["passee"]]
    return render_template("tontine/admin/penalites.html", cycle=cycle, penalites=penalites, seances=seances,
                           membres=lister_membres_actifs(db, id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/penalites/ajouter")
@gestionnaire_de_tontine
def ajouter_penalite(id_tontine):
    db = obtenir_base()
    retour = redirect(url_for("liste_penalites", id_tontine=id_tontine))
    id_adhesion = request.form.get("adhesion_id", type=int)
    id_seance = request.form.get("seance_id", type=int)
    motif = request.form.get("motif", "")
    membre = db.execute("""SELECT a.id, a.utilisateur_id, u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                           WHERE a.id = ? AND a.tontine_id = ? AND a.statut = 'active'""",
                        (id_adhesion, id_tontine)).fetchone()
    if membre is None or motif not in MOTIFS or id_seance is None:
        flash("Membre, séance ou motif invalide.", "error")
        return retour
    seance, cycle = charger_seance_tontine(db, id_seance)
    if seance["date"] > iso(aujourdhui()):
        flash("On ne peut pas sanctionner un membre pour une séance à venir.", "error")
        return retour
    montant = cycle["montant_penalite_" + motif]  # le montant vient du cycle, pas du formulaire
    if montant <= 0:
        flash("Le montant de cette pénalité est à 0 dans ce cycle.", "error")
        return retour
    try:
        db.execute("INSERT INTO penalites (adhesion_id, seance_id, motif, montant) VALUES (?, ?, ?, ?)",
                   (id_adhesion, id_seance, motif, montant))
        notifier(db, membre["utilisateur_id"], id_tontine,
                 f"Pénalité de {filtre_fcfa(montant)} ({MOTIFS[motif].lower()}) pour la séance n° {seance['numero']}.")
        noter_action(db, id_tontine, "Pénalité", f"{MOTIFS[motif]} de {membre['nom']} à la séance n° {seance['numero']}")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Cette pénalité existe déjà pour ce membre et cette séance.", "error")
        return retour
    flash(f"Pénalité de {filtre_fcfa(montant)} enregistrée pour {membre['nom']}.", "success")
    return redirect(url_for("liste_penalites", id_tontine=id_tontine, cycle=cycle["id"]))


@app.post("/tontines/<int:id_tontine>/admin/penalites/<int:id_penalite>/payer")
@gestionnaire_de_tontine
def payer_penalite(id_tontine, id_penalite):
    db = obtenir_base()
    ligne = db.execute("""SELECT p.id, p.payee, u.nom, s.numero, s.cycle_id FROM penalites p
                          JOIN adhesions a ON a.id = p.adhesion_id JOIN utilisateurs u ON u.id = a.utilisateur_id
                          JOIN seances s ON s.id = p.seance_id
                          WHERE p.id = ? AND a.tontine_id = ?""", (id_penalite, id_tontine)).fetchone()
    if ligne is None:
        abort(404)
    if ligne["payee"]:
        flash("Cette pénalité est déjà marquée payée.", "info")
    else:
        db.execute("UPDATE penalites SET payee = 1 WHERE id = ?", (id_penalite,))
        noter_action(db, id_tontine, "Pénalité payée", f"{ligne['nom']}, séance n° {ligne['numero']}")
        db.commit()
        flash(f"Pénalité de {ligne['nom']} marquée payée.", "success")
    return redirect(url_for("liste_penalites", id_tontine=id_tontine, cycle=ligne["cycle_id"]))


@app.post("/tontines/<int:id_tontine>/admin/penalites/montants")
@gestionnaire_de_tontine
def modifier_montants_penalites(id_tontine):
    db = obtenir_base()
    cycle = cycle_ouvert(db, id_tontine)
    retour = redirect(url_for("liste_penalites", id_tontine=id_tontine))
    if cycle is None:
        flash("Aucun cycle n'est ouvert : les montants se règlent à la création du cycle.", "error")
        return retour
    retard = request.form.get("retard", type=int)
    absence = request.form.get("absence", type=int)
    if any(v is None or not 0 <= v <= 100000 for v in (retard, absence)):
        flash("Chaque montant doit être compris entre 0 et 100 000 FCFA.", "error")
        return retour
    db.execute("UPDATE cycles SET montant_penalite_retard = ?, montant_penalite_absence = ? WHERE id = ?",
               (retard, absence, cycle["id"]))
    noter_action(db, id_tontine, "Paramètres", f"Pénalités du cycle : retard {retard} FCFA, absence {absence} FCFA")
    db.commit()
    flash("Montants des pénalités mis à jour pour le cycle en cours.", "success")
    return retour


# ---------------------------------------------------------------- administration : membres de la tontine

@app.get("/tontines/<int:id_tontine>/admin/membres")
@gestionnaire_de_tontine
def admin_membres(id_tontine):
    q = request.args.get("q", "").strip()[:60]
    membres = obtenir_base().execute("""
        SELECT a.id, u.nom, u.telephone, a.role, a.statut, a.date_adhesion FROM adhesions a
        JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE a.tontine_id = ? AND a.statut IN ('active', 'en_attente') AND u.nom LIKE ? ESCAPE '\\'
        ORDER BY (a.statut = 'en_attente') DESC, u.nom""", (id_tontine, motif_recherche(q))).fetchall()
    return render_template("tontine/admin/membres.html", membres=membres, q=q,
                           cycle_bloque=cycle_ouvert(obtenir_base(), id_tontine) is not None)


def charger_adhesion_tontine(db, id_adhesion, statut=None):
    """Une adhésion n'est accessible que dans sa propre tontine."""
    requete = """SELECT a.*, u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                 WHERE a.id = ? AND a.tontine_id = ?"""
    parametres = [id_adhesion, g.tontine["id"]]
    if statut:
        requete += " AND a.statut = ?"
        parametres.append(statut)
    adhesion = db.execute(requete, parametres).fetchone()
    if adhesion is None:
        abort(404)
    return adhesion


@app.post("/tontines/<int:id_tontine>/admin/membres/<int:id_adhesion>/valider")
@gestionnaire_de_tontine
def valider_adhesion(id_tontine, id_adhesion):
    db = obtenir_base()
    demande = charger_adhesion_tontine(db, id_adhesion, "en_attente")
    retour = redirect(url_for("admin_membres", id_tontine=id_tontine))
    if cycle_ouvert(db, id_tontine):
        flash("Un cycle est en cours : les adhésions rouvrent à la fin du cycle.", "error")
        return retour
    if compter_membres(db, id_tontine) >= g.tontine["nombre_max_membres"]:
        flash("Le nombre maximal de membres est atteint.", "error")
        return retour
    db.execute("UPDATE adhesions SET statut = 'active', date_adhesion = ? WHERE id = ?", (iso(aujourdhui()), id_adhesion))
    notifier(db, demande["utilisateur_id"], id_tontine, f"Votre demande pour « {g.tontine['nom']} » est acceptée.")
    noter_action(db, id_tontine, "Adhésion validée", demande["nom"])
    db.commit()
    flash(f"{demande['nom']} fait maintenant partie de la tontine.", "success")
    return retour


@app.post("/tontines/<int:id_tontine>/admin/membres/<int:id_adhesion>/refuser")
@gestionnaire_de_tontine
def refuser_adhesion(id_tontine, id_adhesion):
    db = obtenir_base()
    demande = charger_adhesion_tontine(db, id_adhesion, "en_attente")
    db.execute("UPDATE adhesions SET statut = 'refusee' WHERE id = ?", (id_adhesion,))
    notifier(db, demande["utilisateur_id"], id_tontine, f"Votre demande pour « {g.tontine['nom']} » est refusée.")
    noter_action(db, id_tontine, "Adhésion refusée", demande["nom"])
    db.commit()
    flash(f"La demande de {demande['nom']} est refusée.", "info")
    return redirect(url_for("admin_membres", id_tontine=id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/membres/<int:id_adhesion>/role")
@president_de_tontine
def changer_role(id_tontine, id_adhesion):
    db = obtenir_base()
    cible = charger_adhesion_tontine(db, id_adhesion, "active")
    nouveau = request.form.get("role", "")
    retour = redirect(url_for("admin_membres", id_tontine=id_tontine))
    if nouveau not in ROLES:
        flash("Rôle invalide.", "error")
    elif cible["role"] == "president" and nouveau != "president" and compter_presidents(db, id_tontine) <= 1:
        # Il doit toujours rester au moins un président
        flash("C'est le dernier président : nommez d'abord un autre président.", "error")
    elif nouveau == cible["role"]:
        flash("Ce membre a déjà ce rôle.", "info")
    else:
        db.execute("UPDATE adhesions SET role = ? WHERE id = ?", (nouveau, id_adhesion))
        notifier(db, cible["utilisateur_id"], id_tontine, f"Votre rôle dans « {g.tontine['nom']} » est maintenant : {ROLES[nouveau]}.")
        noter_action(db, id_tontine, "Rôle modifié", f"{cible['nom']} : {ROLES[nouveau]}")
        db.commit()
        flash(f"{cible['nom']} est maintenant {ROLES[nouveau].lower()}.", "success")
    return retour


@app.post("/tontines/<int:id_tontine>/admin/membres/<int:id_adhesion>/retirer")
@president_de_tontine
def retirer_membre(id_tontine, id_adhesion):
    db = obtenir_base()
    cible = charger_adhesion_tontine(db, id_adhesion, "active")
    retour = redirect(url_for("admin_membres", id_tontine=id_tontine))
    if id_adhesion == g.adhesion["id"]:
        flash("Pour partir vous-même, utilisez le bouton « Quitter la tontine ».", "error")
    elif cible["role"] == "president" and compter_presidents(db, id_tontine) <= 1:
        flash("C'est le dernier président : il ne peut pas être retiré.", "error")
    elif cycle_ouvert(db, id_tontine):
        flash("Un cycle est en cours : un membre ne peut être retiré qu'à la fin du cycle.", "error")
    else:
        db.execute("UPDATE adhesions SET statut = 'quittee' WHERE id = ?", (id_adhesion,))
        notifier(db, cible["utilisateur_id"], id_tontine, f"Vous avez été retiré de la tontine « {g.tontine['nom']} ».")
        noter_action(db, id_tontine, "Membre retiré", cible["nom"])
        db.commit()
        flash(f"{cible['nom']} a été retiré de la tontine.", "success")
    return retour


@app.post("/tontines/<int:id_tontine>/admin/invitation/regenerer")
@president_de_tontine
def regenerer_invitation(id_tontine):
    db = obtenir_base()
    db.execute("UPDATE tontines SET code_invitation = ? WHERE id = ?", (generer_code_invitation(db), id_tontine))
    noter_action(db, id_tontine, "Invitation", "Nouveau code d'invitation")
    db.commit()
    flash("Un nouveau code d'invitation est en place : l'ancien ne fonctionne plus.", "success")
    return redirect(url_for("admin_membres", id_tontine=id_tontine))


# ---------------------------------------------------------------- administration : cycles et tirage au sort

@app.get("/tontines/<int:id_tontine>/admin/cycles")
@gestionnaire_de_tontine
def liste_cycles(id_tontine):
    cycles = obtenir_base().execute("""
        SELECT c.*, COUNT(s.id) AS nb_seances,
               SUM(CASE WHEN s.beneficiaire_id IS NOT NULL THEN 1 ELSE 0 END) AS nb_designes,
               SUM(CASE WHEN s.date <= ? THEN 1 ELSE 0 END) AS nb_passees
        FROM cycles c LEFT JOIN seances s ON s.cycle_id = c.id WHERE c.tontine_id = ?
        GROUP BY c.id ORDER BY c.date_debut DESC, c.id DESC""", (iso(aujourdhui()), id_tontine)).fetchall()
    return render_template("tontine/admin/cycles.html", cycles=cycles)


@app.get("/tontines/<int:id_tontine>/admin/cycles/nouveau")
@president_meme_si_inactive
def formulaire_cycle(id_tontine):
    db = obtenir_base()
    valeurs = {"periodicite": "mensuelle", "date_debut": iso(aujourdhui()), "penalite_retard": 1000,
               "penalite_absence": 2000}
    return render_template("tontine/admin/cycle_form.html", valeurs=valeurs, nb_membres=compter_membres(db, id_tontine),
                           ouvert=cycle_ouvert(db, id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/cycles/nouveau")
@president_de_tontine
def creer_cycle(id_tontine):
    db = obtenir_base()
    nom = " ".join(request.form.get("nom", "").split())
    montant = request.form.get("montant", type=int)
    periodicite = request.form.get("periodicite", "")
    debut = lire_date(request.form.get("date_debut", ""))
    penalite_retard = request.form.get("penalite_retard", type=int)
    penalite_absence = request.form.get("penalite_absence", type=int)
    nb_membres = compter_membres(db, id_tontine)
    erreurs = []
    if cycle_ouvert(db, id_tontine):
        erreurs.append("Un cycle est déjà ouvert : terminez-le avant d'en créer un autre.")
    if not 2 <= len(nom) <= 80:
        erreurs.append("Le nom du cycle doit contenir entre 2 et 80 caractères.")
    if montant is None or not 1000 <= montant <= 5000000:
        erreurs.append("La cotisation doit être comprise entre 1 000 et 5 000 000 FCFA.")
    if periodicite not in PERIODICITES:
        erreurs.append("Périodicité invalide.")
    if debut is None:
        erreurs.append("La date de début est invalide.")
    if any(v is None or not 0 <= v <= 100000 for v in (penalite_retard, penalite_absence)):
        erreurs.append("Les pénalités doivent être comprises entre 0 et 100 000 FCFA.")
    if nb_membres < 2:
        erreurs.append("Il faut au moins deux membres actifs pour créer un cycle.")
    if erreurs:
        for message in erreurs:
            flash(message, "error")
        valeurs = {"nom": nom, "montant": request.form.get("montant", ""), "periodicite": periodicite,
                   "date_debut": request.form.get("date_debut", ""), "penalite_retard": request.form.get("penalite_retard", ""),
                   "penalite_absence": request.form.get("penalite_absence", "")}
        return render_template("tontine/admin/cycle_form.html", valeurs=valeurs, nb_membres=nb_membres,
                               ouvert=cycle_ouvert(db, id_tontine)), 400
    # Un tour par membre actif : le cycle compte autant de séances que de membres
    curseur = db.execute("""INSERT INTO cycles (tontine_id, nom, montant_cotisation, periodicite, date_debut,
                            montant_penalite_retard, montant_penalite_absence) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                         (id_tontine, nom, montant, periodicite, iso(debut), penalite_retard, penalite_absence))
    id_cycle = curseur.lastrowid
    for numero in range(1, nb_membres + 1):
        if periodicite == "hebdomadaire":
            jour = debut + timedelta(days=7 * (numero - 1))
        else:
            jour = ajouter_mois(debut, numero - 1)
        db.execute("INSERT INTO seances (cycle_id, numero, date) VALUES (?, ?, ?)", (id_cycle, numero, iso(jour)))
    noter_action(db, id_tontine, "Cycle créé", f"{nom} : {nb_membres} séances de {montant} FCFA")
    db.commit()
    flash(f"Le cycle « {nom} » est créé avec {nb_membres} séances. Tirez l'ordre des bénéficiaires, puis démarrez le cycle.", "success")
    return redirect(url_for("page_tirage", id_tontine=id_tontine, id_cycle=id_cycle))


@app.post("/tontines/<int:id_tontine>/admin/cycles/<int:id_cycle>/demarrer")
@president_de_tontine
def demarrer_cycle(id_tontine, id_cycle):
    db = obtenir_base()
    cycle = charger_cycle_tontine(db, id_cycle)
    retour = redirect(url_for("liste_cycles", id_tontine=id_tontine))
    sans_beneficiaire = db.execute("SELECT COUNT(*) FROM seances WHERE cycle_id = ? AND beneficiaire_id IS NULL",
                                   (id_cycle,)).fetchone()[0]
    if cycle["statut"] != "en_preparation":
        flash("Ce cycle n'est pas en préparation.", "error")
    elif sans_beneficiaire:
        flash(f"Il reste {sans_beneficiaire} séance(s) sans bénéficiaire : utilisez le tirage au sort.", "error")
    else:
        db.execute("UPDATE cycles SET statut = 'en_cours' WHERE id = ?", (id_cycle,))
        for membre in db.execute("SELECT utilisateur_id FROM adhesions WHERE tontine_id = ? AND statut = 'active'", (id_tontine,)):
            notifier(db, membre["utilisateur_id"], id_tontine, f"Le cycle « {cycle['nom']} » démarre.")
        noter_action(db, id_tontine, "Cycle démarré", cycle["nom"])
        db.commit()
        flash(f"Le cycle « {cycle['nom']} » est en cours.", "success")
    return retour


@app.post("/tontines/<int:id_tontine>/admin/cycles/<int:id_cycle>/terminer")
@president_de_tontine
def terminer_cycle(id_tontine, id_cycle):
    db = obtenir_base()
    cycle = charger_cycle_tontine(db, id_cycle)
    retour = redirect(url_for("liste_cycles", id_tontine=id_tontine))
    restantes = db.execute("SELECT COUNT(*) FROM seances WHERE cycle_id = ? AND date > ?",
                           (id_cycle, iso(aujourdhui()))).fetchone()[0]
    if cycle["statut"] != "en_cours":
        flash("Ce cycle n'est pas en cours.", "error")
    elif restantes:
        flash(f"Il reste {restantes} séance(s) à venir : le cycle ne peut pas encore se terminer.", "error")
    else:
        db.execute("UPDATE cycles SET statut = 'termine' WHERE id = ?", (id_cycle,))
        noter_action(db, id_tontine, "Cycle terminé", cycle["nom"])
        db.commit()
        flash(f"Le cycle « {cycle['nom']} » est terminé.", "success")
    return retour


@app.get("/tontines/<int:id_tontine>/admin/cycles/<int:id_cycle>/tirage")
@gestionnaire_de_tontine
def page_tirage(id_tontine, id_cycle):
    db = obtenir_base()
    cycle = charger_cycle_tontine(db, id_cycle)
    seances = lister_seances(db, cycle)
    return render_template("tontine/admin/tirage.html", cycle=cycle, seances=seances,
                           libres=sum(1 for s in seances if s["beneficiaire_id"] is None),
                           animation=request.args.get("anim") == "1")


@app.post("/tontines/<int:id_tontine>/admin/cycles/<int:id_cycle>/tirage")
@gestionnaire_de_tontine
def faire_tirage(id_tontine, id_cycle):
    db = obtenir_base()
    cycle = charger_cycle_tontine(db, id_cycle)
    retour = redirect(url_for("page_tirage", id_tontine=id_tontine, id_cycle=id_cycle))
    if cycle["statut"] == "termine":
        flash("Ce cycle est terminé.", "error")
        return retour
    libres = db.execute("SELECT id FROM seances WHERE cycle_id = ? AND beneficiaire_id IS NULL ORDER BY numero",
                        (id_cycle,)).fetchall()
    candidats = [ligne["id"] for ligne in db.execute("""
        SELECT id FROM adhesions WHERE tontine_id = ? AND statut = 'active' AND id NOT IN
        (SELECT beneficiaire_id FROM seances WHERE cycle_id = ? AND beneficiaire_id IS NOT NULL)""",
        (id_tontine, id_cycle))]
    if not libres:
        flash("Tous les bénéficiaires de ce cycle sont déjà désignés.", "error")
        return retour
    if len(candidats) < len(libres):
        flash("Il n'y a pas assez de membres actifs pour pourvoir toutes les séances restantes.", "error")
        return retour
    # secrets utilise le générateur du système : le tirage ne peut pas être prévu
    secrets.SystemRandom().shuffle(candidats)
    try:
        for seance, id_adhesion in zip(libres, candidats):
            db.execute("UPDATE seances SET beneficiaire_id = ? WHERE id = ?", (id_adhesion, seance["id"]))
        noter_action(db, id_tontine, "Tirage au sort", f"Cycle « {cycle['nom']} » : {len(libres)} bénéficiaire(s) tiré(s)")
        db.commit()
    except sqlite3.IntegrityError:
        db.rollback()
        flash("Le tirage a échoué : un membre serait bénéficiaire deux fois.", "error")
        return retour
    flash("Le tirage au sort est fait et enregistré.", "success")
    return redirect(url_for("page_tirage", id_tontine=id_tontine, id_cycle=id_cycle, anim=1))


# ---------------------------------------------------------------- administration : paramètres, journal, historique, exports

@app.get("/tontines/<int:id_tontine>/admin/parametres")
@president_meme_si_inactive
def page_parametres(id_tontine):
    t = g.tontine
    valeurs = {"nom": t["nom"], "description": t["description"], "nombre_max_membres": t["nombre_max_membres"],
               "couleur": t["couleur"], "adhesion": "libre" if t["adhesion_libre"] else "validation",
               "publique": t["publique"]}
    return render_template("tontine/admin/parametres.html", valeurs=valeurs, cycle_en_cours=cycle_ouvert(obtenir_base(), id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/parametres")
@president_de_tontine
def modifier_parametres(id_tontine):
    db = obtenir_base()
    donnees, erreurs = valider_tontine(request.form, compter_membres(db, id_tontine))
    if erreurs:
        for message in erreurs:
            flash(message, "error")
        return render_template("tontine/admin/parametres.html", valeurs=donnees,
                               cycle_en_cours=cycle_ouvert(db, id_tontine)), 400
    db.execute("""UPDATE tontines SET nom = ?, description = ?, adhesion_libre = ?, publique = ?,
                  nombre_max_membres = ?, couleur = ? WHERE id = ?""",
               (donnees["nom"], donnees["description"], donnees["adhesion_libre"], donnees["publique"],
                donnees["nombre_max_membres"], donnees["couleur"], id_tontine))
    noter_action(db, id_tontine, "Paramètres", "Paramètres de la tontine modifiés")
    db.commit()
    flash("Les paramètres de la tontine sont enregistrés.", "success")
    return redirect(url_for("page_parametres", id_tontine=id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/statut")
@president_meme_si_inactive
def changer_statut(id_tontine):
    db = obtenir_base()
    action = request.form.get("action", "")
    retour = redirect(url_for("page_parametres", id_tontine=id_tontine))
    statut = g.tontine["statut"]
    if action == "cloturer":
        if statut != "active":
            flash("Seule une tontine active peut être clôturée.", "error")
        elif cycle_ouvert(db, id_tontine):
            flash("Un cycle est encore ouvert : terminez-le avant de clôturer la tontine.", "error")
        else:
            db.execute("UPDATE tontines SET statut = 'terminee' WHERE id = ?", (id_tontine,))
            noter_action(db, id_tontine, "Clôture", "La tontine est terminée")
            db.commit()
            flash("La tontine est clôturée : elle est maintenant en lecture seule.", "success")
    elif action == "suspendre":
        if statut != "active":
            flash("Seule une tontine active peut être suspendue.", "error")
        else:
            db.execute("UPDATE tontines SET statut = 'suspendue', suspension_plateforme = 0 WHERE id = ?", (id_tontine,))
            noter_action(db, id_tontine, "Suspension", "Suspension volontaire par le président")
            db.commit()
            flash("La tontine est suspendue : elle est en lecture seule.", "info")
    elif action == "reactiver":
        if statut != "suspendue":
            flash("Cette tontine n'est pas suspendue.", "error")
        elif g.tontine["suspension_plateforme"]:
            flash("Cette tontine a été suspendue par l'administrateur de la plateforme : vous ne pouvez pas la réactiver.", "error")
        else:
            db.execute("UPDATE tontines SET statut = 'active' WHERE id = ?", (id_tontine,))
            noter_action(db, id_tontine, "Réactivation", "La tontine est de nouveau active")
            db.commit()
            flash("La tontine est de nouveau active.", "success")
    else:
        flash("Action inconnue.", "error")
    return retour


@app.get("/tontines/<int:id_tontine>/admin/journal")
@gestionnaire_de_tontine
def journal(id_tontine):
    lignes = obtenir_base().execute("""
        SELECT j.action, j.detail, j.date_action, u.nom FROM journal_actions j
        JOIN utilisateurs u ON u.id = j.utilisateur_id WHERE j.tontine_id = ?
        ORDER BY j.id DESC LIMIT 300""", (id_tontine,)).fetchall()
    return render_template("tontine/admin/journal.html", lignes=lignes)


@app.get("/tontines/<int:id_tontine>/admin/historique")
@gestionnaire_de_tontine
def historique(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    seances = lister_seances(db, cycle) if cycle else []
    return render_template("tontine/admin/historique.html", cycle=cycle, seances=seances,
                           situation=calculer_situation(db, cycle) if cycle else [],
                           total=sum(s["collecte"] for s in seances if s["passee"]),
                           attendu=sum(s["attendu"] for s in seances if s["passee"]))


@app.get("/tontines/<int:id_tontine>/admin/export/seance/<int:id_seance>.csv")
@gestionnaire_de_tontine
def exporter_seance(id_tontine, id_seance):
    db = obtenir_base()
    seance, cycle = charger_seance_tontine(db, id_seance)
    lignes = [[seance["numero"], seance["date"], m["nom"], m["telephone"],
               "Payé" if m["cotisation_id"] else "Non payé", m["montant"] or 0,
               m["date_paiement"] or "", MODES.get(m["mode"], "")]
              for m in lire_lignes_cotisations(db, id_tontine, id_seance)]
    return reponse_csv(f"cotisations_seance_{seance['numero']}.csv",
                       ["Séance", "Date de la séance", "Membre", "Téléphone", "Statut",
                        "Montant (FCFA)", "Date de paiement", "Mode"], lignes)


@app.get("/tontines/<int:id_tontine>/admin/export/membres.csv")
@gestionnaire_de_tontine
def exporter_membres(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    if cycle is None:
        abort(404)
    lignes = [[m["nom"], m["telephone"], ROLES[m["role"]], m["nb_passees"], m["nb_payees"], m["paye"],
               m["manque"], m["penalites_dues"], m["montant_du"],
               "" if m["taux"] is None else f"{m['taux']} %"]
              for m in calculer_situation(db, cycle)]
    return reponse_csv("situation_membres.csv",
                       ["Membre", "Téléphone", "Rôle", "Séances passées", "Cotisations payées",
                        "Total payé (FCFA)", "Cotisations manquantes (FCFA)", "Pénalités dues (FCFA)",
                        "Montant dû (FCFA)", "Ponctualité"], lignes)


# ---------------------------------------------------------------- administration de la plateforme

def statistiques_plateforme(db):
    """Chiffres globaux ; les cotisations ne sont lues qu'en total, jamais modifiées."""
    return {
        "tontines_actives": db.execute("SELECT COUNT(*) FROM tontines WHERE statut = 'active'").fetchone()[0],
        "tontines_total": db.execute("SELECT COUNT(*) FROM tontines").fetchone()[0],
        "utilisateurs": db.execute("SELECT COUNT(*) FROM utilisateurs WHERE actif = 1").fetchone()[0],
        "adhesions": db.execute("SELECT COUNT(*) FROM adhesions WHERE statut = 'active'").fetchone()[0],
        "total_collecte": db.execute("SELECT COALESCE(SUM(montant), 0) FROM cotisations").fetchone()[0],
        "plus_actives": [dict(l) for l in db.execute("""
            SELECT t.nom, COUNT(c.id) AS nb_cotisations, COALESCE(SUM(c.montant), 0) AS total
            FROM tontines t LEFT JOIN cycles cy ON cy.tontine_id = t.id
            LEFT JOIN seances s ON s.cycle_id = cy.id LEFT JOIN cotisations c ON c.seance_id = s.id
            GROUP BY t.id ORDER BY total DESC, t.nom LIMIT 5""")],
    }


@app.get("/plateforme")
@admin_plateforme
def plateforme_tableau_bord():
    return render_template("plateforme/tableau_bord.html", stats=statistiques_plateforme(obtenir_base()))


@app.get("/plateforme/tontines")
@admin_plateforme
def plateforme_tontines():
    q = request.args.get("q", "").strip()[:60]
    tontines = obtenir_base().execute("""
        SELECT t.id, t.nom, t.statut, t.suspension_plateforme, t.date_creation, t.couleur,
               (SELECT COUNT(*) FROM adhesions a WHERE a.tontine_id = t.id AND a.statut = 'active') AS nb_membres,
               (SELECT u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                WHERE a.tontine_id = t.id AND a.role = 'president' AND a.statut = 'active' ORDER BY a.id LIMIT 1) AS president,
               COALESCE((SELECT SUM(c.montant) FROM cotisations c JOIN seances s ON s.id = c.seance_id
                         JOIN cycles cy ON cy.id = s.cycle_id WHERE cy.tontine_id = t.id), 0) AS total
        FROM tontines t WHERE t.nom LIKE ? ESCAPE '\\' ORDER BY t.nom""", (motif_recherche(q),)).fetchall()
    return render_template("plateforme/tontines.html", tontines=tontines, q=q)


@app.get("/plateforme/utilisateurs")
@admin_plateforme
def plateforme_utilisateurs():
    q = request.args.get("q", "").strip()[:60]
    utilisateurs = obtenir_base().execute("""
        SELECT u.id, u.nom, u.telephone, u.date_inscription, u.actif, u.est_admin_plateforme,
               (SELECT COUNT(*) FROM adhesions a WHERE a.utilisateur_id = u.id AND a.statut = 'active') AS nb_tontines
        FROM utilisateurs u WHERE u.nom LIKE ? ESCAPE '\\' OR u.telephone LIKE ? ESCAPE '\\'
        ORDER BY u.nom""", (motif_recherche(q), motif_recherche(q))).fetchall()
    return render_template("plateforme/utilisateurs.html", utilisateurs=utilisateurs, q=q)


@app.post("/plateforme/tontines/<int:id_tontine>/suspendre")
@admin_plateforme
def plateforme_suspendre_tontine(id_tontine):
    db = obtenir_base()
    tontine = db.execute("SELECT * FROM tontines WHERE id = ?", (id_tontine,)).fetchone()
    if tontine is None:
        abort(404)
    if tontine["statut"] != "active":
        flash("Seule une tontine active peut être suspendue.", "error")
    else:
        db.execute("UPDATE tontines SET statut = 'suspendue', suspension_plateforme = 1 WHERE id = ?", (id_tontine,))
        noter_action(db, id_tontine, "Suspension", "Tontine suspendue par l'administrateur de la plateforme")
        for membre in db.execute("SELECT utilisateur_id FROM adhesions WHERE tontine_id = ? AND statut = 'active'", (id_tontine,)):
            notifier(db, membre["utilisateur_id"], id_tontine, "Cette tontine est suspendue par l'administrateur de la plateforme.")
        db.commit()
        flash(f"La tontine « {tontine['nom']} » est suspendue.", "success")
    return redirect(url_for("plateforme_tontines"))


@app.post("/plateforme/tontines/<int:id_tontine>/reactiver")
@admin_plateforme
def plateforme_reactiver_tontine(id_tontine):
    db = obtenir_base()
    tontine = db.execute("SELECT * FROM tontines WHERE id = ?", (id_tontine,)).fetchone()
    if tontine is None:
        abort(404)
    if tontine["statut"] != "suspendue":
        flash("Cette tontine n'est pas suspendue.", "error")
    else:
        db.execute("UPDATE tontines SET statut = 'active', suspension_plateforme = 0 WHERE id = ?", (id_tontine,))
        noter_action(db, id_tontine, "Réactivation", "Tontine réactivée par l'administrateur de la plateforme")
        db.commit()
        flash(f"La tontine « {tontine['nom']} » est de nouveau active.", "success")
    return redirect(url_for("plateforme_tontines"))


@app.post("/plateforme/utilisateurs/<int:id_utilisateur>/<action>")
@admin_plateforme
def plateforme_changer_compte(id_utilisateur, action):
    db = obtenir_base()
    cible = db.execute("SELECT * FROM utilisateurs WHERE id = ?", (id_utilisateur,)).fetchone()
    if cible is None or action not in ("suspendre", "reactiver"):
        abort(404)
    if cible["est_admin_plateforme"]:
        flash("Le compte d'un administrateur de la plateforme ne peut pas être suspendu.", "error")
    else:
        db.execute("UPDATE utilisateurs SET actif = ? WHERE id = ?", (0 if action == "suspendre" else 1, id_utilisateur))
        noter_action(db, None, "Compte " + ("suspendu" if action == "suspendre" else "réactivé"), cible["nom"])
        db.commit()
        flash(f"Le compte de {cible['nom']} est {'suspendu' if action == 'suspendre' else 'réactivé'}.", "success")
    return redirect(url_for("plateforme_utilisateurs"))


# ---------------------------------------------------------------- paiements par mobile money (simulation)

def generer_reference(db):
    while True:
        reference = "PAY" + "".join(secrets.choice(ALPHABET_CODE) for _ in range(9))
        if not db.execute("SELECT 1 FROM paiements WHERE reference = ?", (reference,)).fetchone():
            return reference


def expirer_paiements(db):
    """Un paiement non confirmé au bout de quelques minutes échoue."""
    limite = (datetime.now() - timedelta(minutes=DUREE_PAIEMENT)).strftime(FORMAT_DATE_HEURE)
    db.execute("""UPDATE paiements SET statut = 'echoue', motif_echec = ?
                  WHERE statut = 'en_attente' AND date_creation < ?""",
               ("Délai dépassé : le paiement n'a pas été confirmé.", limite))
    db.commit()


def paiement_en_attente(db, id_adhesion):
    return db.execute("SELECT * FROM paiements WHERE adhesion_id = ? AND statut = 'en_attente' ORDER BY id DESC LIMIT 1",
                      (id_adhesion,)).fetchone()


def sommes_dues(db, id_tontine, id_adhesion):
    """Ce que le membre peut régler en ligne : cotisations des séances passées sans paiement, pénalités non payées.
    Calculé par le serveur, jamais reçu du navigateur."""
    cycle = cycle_ouvert(db, id_tontine)
    if cycle is None or cycle["statut"] != "en_cours":
        return None, [], []
    cotisations = [dict(ligne, montant=cycle["montant_cotisation"]) for ligne in db.execute("""
        SELECT s.id AS seance_id, s.numero, s.date FROM seances s
        WHERE s.cycle_id = ? AND s.date <= ?
        AND NOT EXISTS (SELECT 1 FROM cotisations c WHERE c.seance_id = s.id AND c.adhesion_id = ?)
        ORDER BY s.numero""", (cycle["id"], iso(aujourdhui()), id_adhesion))]
    penalites = [dict(ligne) for ligne in db.execute("""
        SELECT p.id AS penalite_id, p.montant, p.motif, s.numero FROM penalites p JOIN seances s ON s.id = p.seance_id
        WHERE p.adhesion_id = ? AND p.payee = 0 AND s.cycle_id = ? ORDER BY s.numero""", (id_adhesion, cycle["id"]))]
    return cycle, cotisations, penalites


def charger_paiement(db, id_paiement):
    """Un paiement n'est visible que par le membre qui l'a lancé."""
    expirer_paiements(db)
    paiement = db.execute("SELECT * FROM paiements WHERE id = ? AND adhesion_id = ?",
                          (id_paiement, g.adhesion["id"])).fetchone()
    if paiement is None:
        abort(404)
    return paiement


def lignes_du_paiement(db, id_paiement):
    return db.execute("""
        SELECT l.type, l.montant, COALESCE(s.numero, ps.numero) AS numero, p.motif, ev.titre AS evenement
        FROM lignes_paiement l LEFT JOIN seances s ON s.id = l.seance_id
        LEFT JOIN penalites p ON p.id = l.penalite_id LEFT JOIN seances ps ON ps.id = p.seance_id
        LEFT JOIN evenements ev ON ev.id = l.evenement_id
        WHERE l.paiement_id = ? ORDER BY l.id""", (id_paiement,)).fetchall()


def echouer_paiement(db, id_paiement, motif):
    db.execute("UPDATE paiements SET statut = 'echoue', motif_echec = ?, date_confirmation = ? WHERE id = ?",
               (motif, maintenant(), id_paiement))
    db.commit()


def appliquer_paiement(db, paiement):
    """Transforme un paiement confirmé en cotisations payées et en pénalités réglées.
    Tout est revérifié ici : si une somme a déjà été réglée entre-temps, rien n'est enregistré."""
    cycle = cycle_ouvert(db, g.tontine["id"])
    lignes = db.execute("SELECT * FROM lignes_paiement WHERE paiement_id = ?", (paiement["id"],)).fetchall()
    try:
        # Le cycle ne compte que pour les cotisations et les pénalités, pas pour les événements
        if any(l["type"] != "evenement" for l in lignes) and (cycle is None or cycle["statut"] != "en_cours"):
            raise ValueError("Le cycle n'est plus en cours.")
        for ligne in lignes:
            if ligne["type"] == "evenement":
                evenement = db.execute("SELECT * FROM evenements WHERE id = ? AND tontine_id = ?",
                                       (ligne["evenement_id"], g.tontine["id"])).fetchone()
                if evenement is None or not evenement_ouvert(evenement):
                    raise ValueError("Cet événement n'accepte plus de contributions.")
                db.execute("""INSERT INTO contributions_evenement (evenement_id, adhesion_id, montant, date_contribution, mode, paiement_id)
                              VALUES (?, ?, ?, ?, 'mobile_money', ?)""",
                           (evenement["id"], paiement["adhesion_id"], ligne["montant"], iso(aujourdhui()), paiement["id"]))
            elif ligne["type"] == "cotisation":
                seance = db.execute("SELECT * FROM seances WHERE id = ? AND cycle_id = ?",
                                    (ligne["seance_id"], cycle["id"])).fetchone()
                if seance is None or seance["date"] > iso(aujourdhui()) or ligne["montant"] != cycle["montant_cotisation"]:
                    raise ValueError("Une des cotisations n'est plus valable.")
                db.execute("""INSERT INTO cotisations (seance_id, adhesion_id, montant, date_paiement, mode, paiement_id)
                              VALUES (?, ?, ?, ?, 'mobile_money', ?)""",
                           (seance["id"], paiement["adhesion_id"], ligne["montant"], iso(aujourdhui()), paiement["id"]))
                recalculer_total_seance(db, seance["id"])
            else:
                modifie = db.execute("""UPDATE penalites SET payee = 1, paiement_id = ?
                                        WHERE id = ? AND adhesion_id = ? AND payee = 0""",
                                     (paiement["id"], ligne["penalite_id"], paiement["adhesion_id"])).rowcount
                if modifie != 1:
                    raise ValueError("Une des pénalités est déjà réglée.")
        db.execute("UPDATE paiements SET statut = 'reussi', date_confirmation = ? WHERE id = ?", (maintenant(), paiement["id"]))
        libelle = OPERATEURS[paiement["operateur"]]
        notifier(db, g.utilisateur["id"], g.tontine["id"],
                 f"Paiement de {filtre_fcfa(paiement['montant'])} par {libelle} réussi (réf. {paiement['reference']}).")
        notifier_gestionnaires(db, g.tontine["id"],
                               f"{g.utilisateur['nom']} a réglé {filtre_fcfa(paiement['montant'])} par {libelle}.")
        noter_action(db, g.tontine["id"], "Paiement mobile", f"{g.utilisateur['nom']} : {paiement['montant']} FCFA, {libelle}, réf. {paiement['reference']}")
        db.commit()
        return True, ""
    except sqlite3.IntegrityError:
        db.rollback()
        message = "Une des sommes a déjà été réglée : rien n'a été prélevé."
    except ValueError as erreur:
        db.rollback()
        message = str(erreur)
    echouer_paiement(db, paiement["id"], message)
    return False, message


@app.route("/tontines/<int:id_tontine>/payer", methods=["GET", "POST"])
@membre_de_tontine
def payer(id_tontine):
    db = obtenir_base()
    expirer_paiements(db)
    attente = paiement_en_attente(db, g.adhesion["id"])
    if attente:
        flash("Vous avez déjà un paiement à confirmer.", "info")
        return redirect(url_for("page_paiement", id_tontine=id_tontine, id_paiement=attente["id"]))
    cycle, cotisations, penalites = sommes_dues(db, id_tontine, g.adhesion["id"])
    if request.method == "GET":
        return render_template("tontine/payer.html", cycle=cycle, cotisations=cotisations, penalites=penalites,
                               total=sum(c["montant"] for c in cotisations) + sum(p["montant"] for p in penalites))
    retour = redirect(url_for("payer", id_tontine=id_tontine))
    if cycle is None:
        flash("Aucun cycle n'est en cours : il n'y a rien à régler.", "error")
        return retour
    operateur = request.form.get("operateur", "")
    telephone = normaliser_telephone(request.form.get("telephone", ""))
    if operateur not in OPERATEURS:
        flash("Choisissez Orange Money ou MTN MoMo.", "error")
        return retour
    if not FORMAT_TELEPHONE.match(telephone):
        flash("Le numéro du compte de paiement doit avoir 9 chiffres et commencer par 6.", "error")
        return retour
    # On ne garde que les sommes que le serveur a lui-même calculées
    choix_c = set(request.form.getlist("cotisation"))
    choix_p = set(request.form.getlist("penalite"))
    lignes = [("cotisation", c["seance_id"], None, c["montant"]) for c in cotisations if str(c["seance_id"]) in choix_c]
    lignes += [("penalite", None, p["penalite_id"], p["montant"]) for p in penalites if str(p["penalite_id"]) in choix_p]
    if not lignes:
        flash("Cochez au moins une somme à régler.", "error")
        return retour
    curseur = db.execute("""INSERT INTO paiements (adhesion_id, operateur, telephone, montant, reference, date_creation)
                            VALUES (?, ?, ?, ?, ?, ?)""",
                         (g.adhesion["id"], operateur, telephone, sum(ligne[3] for ligne in lignes),
                          generer_reference(db), maintenant()))
    db.executemany("INSERT INTO lignes_paiement (paiement_id, type, seance_id, penalite_id, montant) VALUES (?, ?, ?, ?, ?)",
                   [(curseur.lastrowid,) + ligne for ligne in lignes])
    db.commit()
    return redirect(url_for("page_paiement", id_tontine=id_tontine, id_paiement=curseur.lastrowid))


@app.get("/tontines/<int:id_tontine>/paiements")
@membre_de_tontine
def mes_paiements(id_tontine):
    db = obtenir_base()
    expirer_paiements(db)
    paiements = db.execute("SELECT * FROM paiements WHERE adhesion_id = ? ORDER BY id DESC LIMIT 60",
                           (g.adhesion["id"],)).fetchall()
    return render_template("tontine/paiements.html", paiements=paiements)


@app.get("/tontines/<int:id_tontine>/paiements/<int:id_paiement>")
@membre_de_tontine
def page_paiement(id_tontine, id_paiement):
    db = obtenir_base()
    paiement = charger_paiement(db, id_paiement)
    limite = datetime.strptime(paiement["date_creation"], FORMAT_DATE_HEURE) + timedelta(minutes=DUREE_PAIEMENT)
    secondes = max(0, int((limite - datetime.now()).total_seconds()))
    return render_template("tontine/paiement.html", paiement=paiement, lignes=lignes_du_paiement(db, id_paiement),
                           secondes=secondes)


@app.post("/tontines/<int:id_tontine>/paiements/<int:id_paiement>/confirmer")
@membre_de_tontine
def confirmer_paiement(id_tontine, id_paiement):
    db = obtenir_base()
    paiement = charger_paiement(db, id_paiement)
    retour = redirect(url_for("page_paiement", id_tontine=id_tontine, id_paiement=id_paiement))
    if paiement["statut"] != "en_attente":
        flash("Ce paiement n'est plus en attente.", "info")
        return retour
    # Le code secret n'est jamais enregistré : la simulation vérifie seulement sa forme
    pin = request.form.get("pin", "")
    if not re.fullmatch(r"\d{4}", pin):
        flash("Le code secret comporte 4 chiffres.", "error")
        return retour
    if pin == "0000":
        echouer_paiement(db, id_paiement, "Solde insuffisant sur le compte (simulation avec le code 0000).")
        flash("Le paiement a échoué : solde insuffisant.", "error")
        return retour
    reussi, message = appliquer_paiement(db, paiement)
    flash("Paiement réussi : vos sommes sont réglées." if reussi else "Le paiement a échoué : " + message,
          "success" if reussi else "error")
    return retour


@app.post("/tontines/<int:id_tontine>/paiements/<int:id_paiement>/annuler")
@membre_de_tontine
def annuler_paiement(id_tontine, id_paiement):
    db = obtenir_base()
    paiement = charger_paiement(db, id_paiement)
    if paiement["statut"] == "en_attente":
        echouer_paiement(db, id_paiement, "Paiement annulé par le membre.")
        flash("Le paiement est annulé.", "info")
    return redirect(url_for("payer", id_tontine=id_tontine))


@app.get("/tontines/<int:id_tontine>/admin/paiements")
@gestionnaire_de_tontine
def admin_paiements(id_tontine):
    db = obtenir_base()
    expirer_paiements(db)
    paiements = db.execute("""
        SELECT p.*, u.nom FROM paiements p JOIN adhesions a ON a.id = p.adhesion_id
        JOIN utilisateurs u ON u.id = a.utilisateur_id WHERE a.tontine_id = ? ORDER BY p.id DESC LIMIT 200""",
        (id_tontine,)).fetchall()
    totaux = {ligne["operateur"]: ligne for ligne in db.execute("""
        SELECT p.operateur, COUNT(*) AS nb, SUM(p.montant) AS total FROM paiements p
        JOIN adhesions a ON a.id = p.adhesion_id WHERE a.tontine_id = ? AND p.statut = 'reussi'
        GROUP BY p.operateur""", (id_tontine,))}
    return render_template("tontine/admin/paiements.html", paiements=paiements, totaux=totaux)


@app.get("/api/tontines/<int:id_tontine>/paiements/<int:id_paiement>/statut")
@membre_de_tontine
def api_statut_paiement(id_tontine, id_paiement):
    paiement = charger_paiement(obtenir_base(), id_paiement)
    return jsonify(statut=paiement["statut"], reference=paiement["reference"], montant=paiement["montant"],
                   motif_echec=paiement["motif_echec"])


# ---------------------------------------------------------------- événements : contributions libres

def evenement_ouvert(evenement):
    """Un événement reçoit des contributions tant qu'il est ouvert et que sa date limite n'est pas dépassée."""
    if evenement["statut"] != "ouvert":
        return False
    return evenement["date_limite"] is None or evenement["date_limite"] >= iso(aujourdhui())


def lister_evenements(db, id_tontine, limite=100):
    lignes = db.execute("""
        SELECT e.*, u.nom AS concerne_nom,
               COALESCE((SELECT SUM(c.montant) FROM contributions_evenement c WHERE c.evenement_id = e.id), 0) AS total,
               (SELECT COUNT(DISTINCT c.adhesion_id) FROM contributions_evenement c WHERE c.evenement_id = e.id) AS nb_contributeurs
        FROM evenements e LEFT JOIN adhesions a ON a.id = e.concerne_id LEFT JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE e.tontine_id = ? ORDER BY (e.statut = 'ouvert') DESC, e.date_evenement DESC LIMIT ?""",
        (id_tontine, limite)).fetchall()
    evenements = []
    for ligne in lignes:
        element = dict(ligne)
        element["accepte"] = evenement_ouvert(ligne)
        element["pourcentage"] = min(100, round(100 * ligne["total"] / ligne["objectif"])) if ligne["objectif"] else None
        evenements.append(element)
    return evenements


def charger_evenement(db, id_evenement):
    """Un événement n'est visible que dans sa propre tontine."""
    for evenement in lister_evenements(db, g.tontine["id"]):
        if evenement["id"] == id_evenement:
            return evenement
    abort(404)


def valider_evenement(db, formulaire, id_tontine):
    erreurs = []
    titre = " ".join(formulaire.get("titre", "").split())
    description = " ".join(formulaire.get("description", "").split())
    type_evenement = formulaire.get("type", "")
    jour = lire_date(formulaire.get("date_evenement", ""))
    limite_texte = formulaire.get("date_limite", "")
    limite = lire_date(limite_texte) if limite_texte else None
    objectif_texte, suggere_texte = formulaire.get("objectif", ""), formulaire.get("montant_suggere", "")
    objectif = formulaire.get("objectif", type=int) if objectif_texte else None
    suggere = formulaire.get("montant_suggere", type=int) if suggere_texte else None
    concerne = formulaire.get("concerne_id", type=int) if formulaire.get("concerne_id") else None
    if not 2 <= len(titre) <= 80:
        erreurs.append("Le titre doit contenir entre 2 et 80 caractères.")
    if type_evenement not in TYPES_EVENEMENT:
        erreurs.append("Type d'événement invalide.")
    if len(description) > 500:
        erreurs.append("La description ne doit pas dépasser 500 caractères.")
    if jour is None:
        erreurs.append("La date de l'événement est invalide.")
    if limite_texte and (limite is None or (jour and limite > jour)):
        erreurs.append("La date limite est invalide ou après la date de l'événement.")
    if objectif_texte and (objectif is None or not 1000 <= objectif <= 100000000):
        erreurs.append("L'objectif doit être compris entre 1 000 et 100 000 000 FCFA.")
    if suggere_texte and (suggere is None or not CONTRIBUTION_MIN <= suggere <= CONTRIBUTION_MAX):
        erreurs.append(f"Le montant suggéré doit être compris entre {CONTRIBUTION_MIN} et {CONTRIBUTION_MAX} FCFA.")
    if concerne is not None and not db.execute(
            "SELECT 1 FROM adhesions WHERE id = ? AND tontine_id = ? AND statut = 'active'", (concerne, id_tontine)).fetchone():
        erreurs.append("Le membre concerné ne fait pas partie de la tontine.")
    donnees = {"titre": titre, "type": type_evenement, "description": description,
               "date_evenement": iso(jour) if jour else "", "date_limite": iso(limite) if limite else None,
               "objectif": objectif, "montant_suggere": suggere, "concerne_id": concerne}
    return donnees, erreurs


@app.get("/tontines/<int:id_tontine>/evenements")
@membre_de_tontine
def evenements(id_tontine):
    return render_template("tontine/evenements.html", evenements=lister_evenements(obtenir_base(), id_tontine))


@app.get("/tontines/<int:id_tontine>/evenements/<int:id_evenement>")
@membre_de_tontine
def page_evenement(id_tontine, id_evenement):
    db = obtenir_base()
    evenement = charger_evenement(db, id_evenement)
    contributions = db.execute("""
        SELECT c.montant, c.date_contribution, c.mode, u.nom, (c.adhesion_id = ?) AS la_mienne
        FROM contributions_evenement c JOIN adhesions a ON a.id = c.adhesion_id JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE c.evenement_id = ? ORDER BY c.id DESC""", (g.adhesion["id"], id_evenement)).fetchall()
    return render_template("tontine/evenement.html", evenement=evenement, contributions=contributions,
                           mon_total=sum(c["montant"] for c in contributions if c["la_mienne"]),
                           membres=lister_membres_actifs(db, id_tontine))


@app.post("/tontines/<int:id_tontine>/evenements/<int:id_evenement>/contribuer")
@membre_de_tontine
def contribuer_evenement(id_tontine, id_evenement):
    db = obtenir_base()
    evenement = charger_evenement(db, id_evenement)
    retour = redirect(url_for("page_evenement", id_tontine=id_tontine, id_evenement=id_evenement))
    expirer_paiements(db)
    attente = paiement_en_attente(db, g.adhesion["id"])
    if attente:
        flash("Vous avez déjà un paiement à confirmer.", "info")
        return redirect(url_for("page_paiement", id_tontine=id_tontine, id_paiement=attente["id"]))
    montant = request.form.get("montant", type=int)
    operateur = request.form.get("operateur", "")
    telephone = normaliser_telephone(request.form.get("telephone", ""))
    if not evenement_ouvert(evenement):
        flash("Cet événement n'accepte plus de contributions.", "error")
    elif montant is None or not CONTRIBUTION_MIN <= montant <= CONTRIBUTION_MAX:
        flash(f"Votre contribution doit être comprise entre {filtre_fcfa(CONTRIBUTION_MIN)} et {filtre_fcfa(CONTRIBUTION_MAX)}.", "error")
    elif operateur not in OPERATEURS:
        flash("Choisissez Orange Money ou MTN MoMo.", "error")
    elif not FORMAT_TELEPHONE.match(telephone):
        flash("Le numéro du compte de paiement doit avoir 9 chiffres et commencer par 6.", "error")
    else:
        curseur = db.execute("""INSERT INTO paiements (adhesion_id, operateur, telephone, montant, reference, date_creation)
                                VALUES (?, ?, ?, ?, ?, ?)""",
                             (g.adhesion["id"], operateur, telephone, montant, generer_reference(db), maintenant()))
        db.execute("INSERT INTO lignes_paiement (paiement_id, type, evenement_id, montant) VALUES (?, 'evenement', ?, ?)",
                   (curseur.lastrowid, id_evenement, montant))
        db.commit()
        return redirect(url_for("page_paiement", id_tontine=id_tontine, id_paiement=curseur.lastrowid))
    return retour


@app.get("/tontines/<int:id_tontine>/admin/evenements/nouveau")
@gestionnaire_de_tontine
def formulaire_evenement(id_tontine):
    valeurs = {"type": "mariage", "date_evenement": iso(aujourdhui())}
    return render_template("tontine/admin/evenement_form.html", valeurs=valeurs,
                           membres=lister_membres_actifs(obtenir_base(), id_tontine))


@app.post("/tontines/<int:id_tontine>/admin/evenements/nouveau")
@gestionnaire_de_tontine
def creer_evenement(id_tontine):
    db = obtenir_base()
    donnees, erreurs = valider_evenement(db, request.form, id_tontine)
    if erreurs:
        for message in erreurs:
            flash(message, "error")
        return render_template("tontine/admin/evenement_form.html", valeurs=donnees,
                               membres=lister_membres_actifs(db, id_tontine)), 400
    curseur = db.execute("""INSERT INTO evenements (tontine_id, titre, type, description, date_evenement, date_limite,
                            concerne_id, objectif, montant_suggere, cree_par, date_creation)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (id_tontine, donnees["titre"], donnees["type"], donnees["description"], donnees["date_evenement"],
                          donnees["date_limite"], donnees["concerne_id"], donnees["objectif"], donnees["montant_suggere"],
                          g.adhesion["id"], iso(aujourdhui())))
    for membre in db.execute("SELECT utilisateur_id FROM adhesions WHERE tontine_id = ? AND statut = 'active'", (id_tontine,)):
        notifier(db, membre["utilisateur_id"], id_tontine,
                 f"Nouvel événement : « {donnees['titre']} ». Contribution libre, chacun participe s'il le souhaite.")
    noter_action(db, id_tontine, "Événement créé", donnees["titre"])
    db.commit()
    flash("L'événement est créé : les membres sont prévenus.", "success")
    return redirect(url_for("page_evenement", id_tontine=id_tontine, id_evenement=curseur.lastrowid))


@app.post("/tontines/<int:id_tontine>/admin/evenements/<int:id_evenement>/statut")
@gestionnaire_de_tontine
def changer_statut_evenement(id_tontine, id_evenement):
    db = obtenir_base()
    evenement = charger_evenement(db, id_evenement)
    action = request.form.get("action", "")
    if action not in ("clore", "rouvrir"):
        abort(400)
    db.execute("UPDATE evenements SET statut = ? WHERE id = ?", ("clos" if action == "clore" else "ouvert", id_evenement))
    noter_action(db, id_tontine, "Événement " + ("clos" if action == "clore" else "rouvert"), evenement["titre"])
    db.commit()
    flash("L'événement est " + ("clos : il n'accepte plus de contributions." if action == "clore" else "rouvert."), "success")
    return redirect(url_for("page_evenement", id_tontine=id_tontine, id_evenement=id_evenement))


@app.post("/tontines/<int:id_tontine>/admin/evenements/<int:id_evenement>/contribution")
@gestionnaire_de_tontine
def enregistrer_contribution(id_tontine, id_evenement):
    """Le bureau note la contribution qu'un membre a remise en espèces."""
    db = obtenir_base()
    evenement = charger_evenement(db, id_evenement)
    retour = redirect(url_for("page_evenement", id_tontine=id_tontine, id_evenement=id_evenement))
    montant = request.form.get("montant", type=int)
    id_adhesion = request.form.get("adhesion_id", type=int)
    membre = db.execute("""SELECT a.id, a.utilisateur_id, u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                           WHERE a.id = ? AND a.tontine_id = ? AND a.statut = 'active'""", (id_adhesion, id_tontine)).fetchone()
    if not evenement_ouvert(evenement):
        flash("Cet événement n'accepte plus de contributions.", "error")
    elif membre is None:
        flash("Ce membre ne fait pas partie de la tontine.", "error")
    elif montant is None or not CONTRIBUTION_MIN <= montant <= CONTRIBUTION_MAX:
        flash(f"La contribution doit être comprise entre {filtre_fcfa(CONTRIBUTION_MIN)} et {filtre_fcfa(CONTRIBUTION_MAX)}.", "error")
    else:
        db.execute("""INSERT INTO contributions_evenement (evenement_id, adhesion_id, montant, date_contribution, mode, enregistre_par)
                      VALUES (?, ?, ?, ?, 'especes', ?)""", (id_evenement, id_adhesion, montant, iso(aujourdhui()), g.adhesion["id"]))
        notifier(db, membre["utilisateur_id"], id_tontine,
                 f"Votre contribution de {filtre_fcfa(montant)} à « {evenement['titre']} » est enregistrée. Merci.")
        noter_action(db, id_tontine, "Contribution", f"{membre['nom']} : {montant} FCFA en espèces pour « {evenement['titre']} »")
        db.commit()
        flash(f"Contribution de {filtre_fcfa(montant)} enregistrée pour {membre['nom']}.", "success")
    return retour


@app.get("/api/tontines/<int:id_tontine>/evenements/<int:id_evenement>/etat")
@membre_de_tontine
def api_etat_evenement(id_tontine, id_evenement):
    evenement = charger_evenement(obtenir_base(), id_evenement)
    return jsonify(evenement_id=evenement["id"], total=evenement["total"], objectif=evenement["objectif"],
                   nb_contributeurs=evenement["nb_contributeurs"], pourcentage=evenement["pourcentage"],
                   accepte=evenement["accepte"])


# ---------------------------------------------------------------- API JSON

@app.get("/api/mes-tontines")
@connexion_requise
def api_mes_tontines():
    resume = resumer_mes_tontines(obtenir_base(), g.utilisateur["id"])
    return jsonify({"tontines": resume,
                    "total_du": sum(t["du"] for t in resume),
                    "total_verse": sum(t["verse"] for t in resume)})


@app.get("/api/tontines/<int:id_tontine>/seances/<int:id_seance>/etat")
@gestionnaire_de_tontine
def api_etat_seance(id_tontine, id_seance):
    db = obtenir_base()
    seance, cycle = charger_seance_tontine(db, id_seance)
    return jsonify(etat_seance(db, seance, cycle))


@app.get("/api/tontines/<int:id_tontine>/statistiques")
@gestionnaire_de_tontine
def api_statistiques(id_tontine):
    db = obtenir_base()
    cycle = choisir_cycle(db, id_tontine)
    if cycle is None:
        return reponse_api_erreur(404, "Aucun cycle n'existe pour le moment.")
    return jsonify(construire_statistiques(db, cycle))


@app.get("/api/tontines/<int:id_tontine>/membres")
@membre_de_tontine
def api_membres(id_tontine):
    q = request.args.get("q", "").strip()[:60]
    lignes = obtenir_base().execute("""
        SELECT a.id, u.nom, u.telephone, a.role, a.date_adhesion FROM adhesions a
        JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE a.tontine_id = ? AND a.statut = 'active' AND u.nom LIKE ? ESCAPE '\\'
        ORDER BY u.nom LIMIT 100""", (id_tontine, motif_recherche(q))).fetchall()
    voit_telephones = g.adhesion["role"] in ("tresorier", "president")
    membres = []
    for ligne in lignes:
        element = dict(ligne)
        if not voit_telephones:
            element["telephone"] = None  # le numéro n'est visible que par le bureau
        membres.append(element)
    return jsonify(membres)


@app.get("/api/plateforme/statistiques")
@admin_plateforme
def api_plateforme_statistiques():
    return jsonify(statistiques_plateforme(obtenir_base()))


# ---------------------------------------------------------------- pages d'erreur

@app.errorhandler(403)
def erreur_403(erreur):
    if request.path.startswith("/api/"):
        return reponse_api_erreur(403, "Accès refusé.")
    return render_template("403.html"), 403


@app.errorhandler(404)
def erreur_404(erreur):
    if request.path.startswith("/api/"):
        return reponse_api_erreur(404, "Ressource introuvable.")
    return render_template("404.html"), 404


@app.errorhandler(500)
def erreur_500(erreur):
    return render_template("500.html"), 500


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
