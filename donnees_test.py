# Crée la base à partir de schema.sql et la remplit de données de test
import random
import sqlite3
from calendar import monthrange
from datetime import date, timedelta

from werkzeug.security import generate_password_hash

AUJOURDHUI = date.today()

PRENOMS = ["Aline", "Paul", "Rose", "Moussa", "Sandra", "Ibrahim", "Marie", "Kevin", "Estelle", "Hervé",
           "Nadège", "Blaise", "Carine", "Thierry", "Odette", "Serge", "Pauline", "Landry", "Josiane", "Rodrigue",
           "Brigitte", "Valentin", "Clarisse", "Eric", "Félicité", "Armand", "Mireille", "Yves"]
NOMS = ["Mbarga", "Ngo Bassa", "Fotso", "Atangana", "Njoya", "Ekane", "Tchoupo", "Bello", "Nkou", "Kamga",
        "Essomba", "Tagne", "Mvondo", "Ndzana", "Onana", "Feutsa", "Nana", "Kenfack", "Biloa", "Manga",
        "Ateba", "Simo", "Ngassa", "Etoundi", "Tchamba", "Abega", "Zang", "Mouelle"]

CODE_MEMBRES = "Tontine2026"
CODE_BUREAU = "Admin!2026"
CODE_MULTI = "Multi!2026"
CODE_PLATEFORME = "Plateforme!2026"
NB_UTILISATEURS = 40

# Numéros fixes pour les comptes de test (les autres sont tirés au hasard)
TELEPHONES_FIXES = {0: "677000001", 1: "677000002", 2: "699000003", 3: "677000004", 39: "699000099"}


def ajouter_mois(depart, nombre):
    mois = depart.month - 1 + nombre
    annee = depart.year + mois // 12
    mois = mois % 12 + 1
    return date(annee, mois, min(depart.day, monthrange(annee, mois)[1]))


def creer_utilisateurs(db):
    noms = set()
    while len(noms) < NB_UTILISATEURS:
        noms.add(random.choice(PRENOMS) + " " + random.choice(NOMS))
    noms = sorted(noms)
    random.shuffle(noms)
    telephones = set(TELEPHONES_FIXES.values())
    while len(telephones) < NB_UTILISATEURS:
        telephones.add(f"6{random.choice('5679')}{random.randint(0, 9999999):07d}")
    libres = sorted(telephones - set(TELEPHONES_FIXES.values()))
    random.shuffle(libres)
    codes = {0: CODE_BUREAU, 1: CODE_BUREAU, 3: CODE_MULTI, 39: CODE_PLATEFORME}
    empreintes = {code: generate_password_hash(code) for code in {CODE_BUREAU, CODE_MULTI, CODE_PLATEFORME, CODE_MEMBRES}}
    for i in range(NB_UTILISATEURS):
        telephone = TELEPHONES_FIXES.get(i) or libres.pop()
        inscription = AUJOURDHUI - timedelta(days=random.randint(60, 700))
        db.execute("""INSERT INTO utilisateurs (nom, telephone, code_acces, date_inscription, est_admin_plateforme)
                      VALUES (?, ?, ?, ?, ?)""",
                   (noms[i], telephone, empreintes[codes.get(i, CODE_MEMBRES)], inscription.isoformat(),
                    1 if i == 39 else 0))


def creer_tontine(db, nom, description, createur, code, libre, publique, maximum, statut, couleur, creation):
    curseur = db.execute("""INSERT INTO tontines (nom, description, createur_id, code_invitation, adhesion_libre, publique,
                            nombre_max_membres, statut, couleur, date_creation) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (nom, description, createur + 1, code, libre, publique, maximum, statut, couleur, creation.isoformat()))
    return curseur.lastrowid


def ajouter_adhesions(db, id_tontine, membres, roles, jour):
    """membres : indices d'utilisateurs ; renvoie la liste des identifiants d'adhésion actifs."""
    ids = []
    for i in membres:
        adhesion = jour - timedelta(days=random.randint(0, 40))
        curseur = db.execute("""INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion)
                                VALUES (?, ?, ?, 'active', ?)""", (id_tontine, i + 1, roles.get(i, "membre"), adhesion.isoformat()))
        ids.append(curseur.lastrowid)
    return ids


def creer_cycle(db, id_tontine, nom, montant, periodicite, debut, adhesions, statut, pen_retard, pen_absence):
    curseur = db.execute("""INSERT INTO cycles (tontine_id, nom, montant_cotisation, periodicite, date_debut,
                            montant_penalite_retard, montant_penalite_absence, statut) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                         (id_tontine, nom, montant, periodicite, debut.isoformat(), pen_retard, pen_absence, statut))
    id_cycle = curseur.lastrowid
    ordre = adhesions[:]
    random.shuffle(ordre)  # bénéficiaires tous différents
    for numero in range(1, len(adhesions) + 1):
        if periodicite == "hebdomadaire":
            jour = debut + timedelta(days=7 * (numero - 1))
        else:
            jour = ajouter_mois(debut, numero - 1)
        db.execute("INSERT INTO seances (cycle_id, numero, date, beneficiaire_id) VALUES (?, ?, ?, ?)",
                   (id_cycle, numero, jour.isoformat(), ordre[numero - 1]))
    return id_cycle


def creer_cotisations(db, id_cycle, adhesions, nb_mauvais, proba_bon):
    montant = db.execute("SELECT montant_cotisation FROM cycles WHERE id = ?", (id_cycle,)).fetchone()[0]
    seances = db.execute("SELECT id, date FROM seances WHERE cycle_id = ? AND date <= ? ORDER BY numero",
                         (id_cycle, AUJOURDHUI.isoformat())).fetchall()
    mauvais = set(random.sample(adhesions[3:], nb_mauvais)) if nb_mauvais else set()
    for id_seance, texte in seances:
        jour_seance = date.fromisoformat(texte)
        for id_adhesion in adhesions:
            if random.random() > (0.7 if id_adhesion in mauvais else proba_bon):
                continue
            decalage = random.choice([0, 2, 4, 8, 12]) if id_adhesion in mauvais else random.choice([0, 0, 0, -1, -2, -3, 2, 5])
            paiement = min(jour_seance + timedelta(days=decalage), AUJOURDHUI)
            mode = "mobile_money" if random.random() < 0.6 else "especes"
            db.execute("""INSERT INTO cotisations (seance_id, adhesion_id, montant, date_paiement, mode)
                          VALUES (?, ?, ?, ?, ?)""", (id_seance, id_adhesion, montant, paiement.isoformat(), mode))
    db.execute("""UPDATE seances SET montant_total_collecte =
                  (SELECT COALESCE(SUM(montant), 0) FROM cotisations WHERE seance_id = seances.id)
                  WHERE cycle_id = ?""", (id_cycle,))
    creer_paiements(db, id_cycle)


def creer_paiements(db, id_cycle):
    """Chaque cotisation payée en mobile money correspond à un paiement réussi (Orange Money ou MTN MoMo)."""
    lignes = db.execute("""
        SELECT c.id, c.seance_id, c.adhesion_id, c.montant, c.date_paiement, u.telephone
        FROM cotisations c JOIN seances s ON s.id = c.seance_id
        JOIN adhesions a ON a.id = c.adhesion_id JOIN utilisateurs u ON u.id = a.utilisateur_id
        WHERE s.cycle_id = ? AND c.mode = 'mobile_money' ORDER BY c.id""", (id_cycle,)).fetchall()
    for id_cotisation, id_seance, id_adhesion, montant, jour, telephone in lignes:
        reference = "PAY" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(9))
        operateur = random.choice(["orange_money", "mtn_momo"])
        curseur = db.execute("""INSERT INTO paiements (adhesion_id, operateur, telephone, montant, reference, statut,
                                date_creation, date_confirmation) VALUES (?, ?, ?, ?, ?, 'reussi', ?, ?)""",
                             (id_adhesion, operateur, telephone, montant, reference, jour + " 10:00:00", jour + " 10:01:00"))
        db.execute("UPDATE cotisations SET paiement_id = ? WHERE id = ?", (curseur.lastrowid, id_cotisation))
        db.execute("INSERT INTO lignes_paiement (paiement_id, type, seance_id, montant) VALUES (?, 'cotisation', ?, ?)",
                   (curseur.lastrowid, id_seance, montant))


def nom_de(db, id_adhesion):
    return db.execute("SELECT u.nom FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id WHERE a.id = ?",
                      (id_adhesion,)).fetchone()[0]


def creer_evenement(db, id_tontine, createur, titre, type_evenement, description, jours, limite, concerne, objectif,
                    suggere, statut, contributeurs, montants):
    """Crée un événement et des contributions libres (espèces ou mobile money, avec un paiement réussi dans ce cas)."""
    date_evenement = (AUJOURDHUI + timedelta(days=jours)).isoformat()
    date_limite = (AUJOURDHUI + timedelta(days=limite)).isoformat() if limite is not None else None
    curseur = db.execute("""INSERT INTO evenements (tontine_id, titre, type, description, date_evenement, date_limite,
                            concerne_id, objectif, montant_suggere, statut, cree_par, date_creation)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (id_tontine, titre, type_evenement, description, date_evenement, date_limite, concerne, objectif,
                          suggere, statut, createur, (AUJOURDHUI - timedelta(days=random.randint(8, 25))).isoformat()))
    id_evenement = curseur.lastrowid
    for id_adhesion in contributeurs:
        montant = random.choice(montants)
        jour = (AUJOURDHUI - timedelta(days=random.randint(0, 7))).isoformat()
        if random.random() < 0.6:
            telephone = db.execute("""SELECT u.telephone FROM adhesions a JOIN utilisateurs u ON u.id = a.utilisateur_id
                                      WHERE a.id = ?""", (id_adhesion,)).fetchone()[0]
            reference = "PAY" + "".join(random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(9))
            paiement = db.execute("""INSERT INTO paiements (adhesion_id, operateur, telephone, montant, reference, statut,
                                     date_creation, date_confirmation) VALUES (?, ?, ?, ?, ?, 'reussi', ?, ?)""",
                                  (id_adhesion, random.choice(["orange_money", "mtn_momo"]), telephone, montant, reference,
                                   jour + " 15:00:00", jour + " 15:01:00")).lastrowid
            db.execute("INSERT INTO lignes_paiement (paiement_id, type, evenement_id, montant) VALUES (?, 'evenement', ?, ?)",
                       (paiement, id_evenement, montant))
            db.execute("""INSERT INTO contributions_evenement (evenement_id, adhesion_id, montant, date_contribution, mode, paiement_id)
                          VALUES (?, ?, ?, ?, 'mobile_money', ?)""", (id_evenement, id_adhesion, montant, jour, paiement))
        else:
            db.execute("""INSERT INTO contributions_evenement (evenement_id, adhesion_id, montant, date_contribution, mode, enregistre_par)
                          VALUES (?, ?, ?, ?, 'especes', ?)""", (id_evenement, id_adhesion, montant, jour, createur))


def creer_penalites(db, id_cycle, adhesions, nombre):
    retard, absence = db.execute("SELECT montant_penalite_retard, montant_penalite_absence FROM cycles WHERE id = ?",
                                 (id_cycle,)).fetchone()
    seances = [ligne[0] for ligne in db.execute("SELECT id FROM seances WHERE cycle_id = ? AND date <= ?",
                                                (id_cycle, AUJOURDHUI.isoformat()))]
    deja = set()
    while len(deja) < nombre:
        cle = (random.choice(adhesions[3:]), random.choice(seances), random.choice(["retard", "absence"]))
        if cle in deja:
            continue
        deja.add(cle)
        db.execute("INSERT INTO penalites (adhesion_id, seance_id, motif, montant, payee) VALUES (?, ?, ?, ?, ?)",
                   (cle[0], cle[1], cle[2], retard if cle[2] == "retard" else absence, 1 if random.random() < 0.4 else 0))


def journaliser(db, id_tontine, utilisateur, action, detail, jours):
    moment = f"{(AUJOURDHUI - timedelta(days=jours)).isoformat()} {random.randint(8, 18):02d}:{random.randint(0, 59):02d}:00"
    db.execute("INSERT INTO journal_actions (tontine_id, utilisateur_id, action, detail, date_action) VALUES (?, ?, ?, ?, ?)",
               (id_tontine, utilisateur + 1, action, detail, moment))


def remplir(db):
    creer_utilisateurs(db)
    debut1 = ajouter_mois(AUJOURDHUI - timedelta(days=10), -11)  # 12 séances passées, 13 à venir

    # Tontine principale : 25 membres, cycle mensuel de 25 séances
    t1 = creer_tontine(db, "Tontine des commerçants de Mboppi", "Les commerçants du marché de Mboppi cotisent chaque mois.",
                       0, "MBOP2026", 0, 0, 25, "active", "vert", debut1 - timedelta(days=20))
    a1 = ajouter_adhesions(db, t1, range(25), {0: "president", 1: "tresorier"}, debut1)
    c1 = creer_cycle(db, t1, "Cycle 2025-2026", 25000, "mensuelle", debut1, a1, "en_cours", 1000, 2000)
    creer_cotisations(db, c1, a1, 5, 0.992)
    creer_penalites(db, c1, a1, 9)

    # Événements de la tontine principale : chacun contribue s'il le souhaite
    creer_evenement(db, t1, a1[0], "Mariage de " + nom_de(db, a1[7]), "mariage", "Les membres qui le souhaitent contribuent pour le mariage.",
                    30, 25, a1[7], 300000, 5000, "ouvert", random.sample(a1, 14), [2000, 5000, 5000, 10000, 20000])
    creer_evenement(db, t1, a1[1], "Deuil dans la famille de " + nom_de(db, a1[11]), "deuil", "Soutien à la famille pour les obsèques.",
                    -6, None, a1[11], None, 2000, "ouvert", random.sample(a1, 18), [1000, 2000, 2000, 5000, 10000])
    creer_evenement(db, t1, a1[0], "Naissance chez " + nom_de(db, a1[15]), "naissance", "Un petit cadeau pour la nouvelle famille.",
                    -60, -50, a1[15], 100000, 2000, "clos", random.sample(a1, 10), [1000, 2000, 5000])

    # Njangi hebdomadaire de 12 membres, dont plusieurs aussi membres de la tontine principale
    membres2 = [3, 4, 5, 6, 7, 8, 25, 26, 27, 28, 29, 30]
    debut2 = AUJOURDHUI - timedelta(days=31)  # 5 séances passées sur 12
    t2 = creer_tontine(db, "Njangi des femmes de Bonabéri", "Une cotisation chaque semaine entre voisines.",
                       3, "BONA2026", 0, 0, 12, "active", "or", debut2 - timedelta(days=15))
    a2 = ajouter_adhesions(db, t2, membres2, {3: "president", 4: "tresorier"}, debut2)
    c2 = creer_cycle(db, t2, "Cycle Bonabéri", 10000, "hebdomadaire", debut2, a2, "en_cours", 500, 1000)
    creer_cotisations(db, c2, a2, 2, 0.99)
    creer_penalites(db, c2, a2, 3)
    creer_evenement(db, t2, a2[0], "Anniversaire de " + nom_de(db, a2[4]), "anniversaire", "Une fête pour les 50 ans.",
                    12, 10, a2[4], 60000, 2000, "ouvert", random.sample(a2, 6), [1000, 2000, 5000])
    db.execute("INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion) VALUES (?, ?, 'membre', 'quittee', ?)",
               (t2, 22 + 1, (debut2 - timedelta(days=60)).isoformat()))

    # Tontine en attente de membres : pas encore de cycle, des demandes à valider
    t3 = creer_tontine(db, "Jeunes entrepreneurs de Yaoundé", "Un groupe de jeunes qui lance sa première tontine.",
                       31, "JEUN2026", 0, 1, 12, "active", "turquoise", AUJOURDHUI - timedelta(days=12))
    ajouter_adhesions(db, t3, [31, 32, 33, 9, 10], {31: "president", 32: "tresorier"}, AUJOURDHUI - timedelta(days=8))
    for i in (34, 35, 36, 11):
        db.execute("INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion) VALUES (?, ?, 'membre', 'en_attente', ?)",
                   (t3, i + 1, (AUJOURDHUI - timedelta(days=random.randint(1, 5))).isoformat()))
    db.execute("INSERT INTO adhesions (tontine_id, utilisateur_id, role, statut, date_adhesion) VALUES (?, ?, 'membre', 'refusee', ?)",
               (t3, 20 + 1, (AUJOURDHUI - timedelta(days=6)).isoformat()))

    # Tontine terminée : lecture seule
    debut4 = ajouter_mois(AUJOURDHUI, -9)
    t4 = creer_tontine(db, "Anciens du lycée de Bali", "Cycle terminé, les comptes sont archivés.",
                       37, "LYCE2026", 0, 0, 8, "terminee", "corail", debut4 - timedelta(days=30))
    a4 = ajouter_adhesions(db, t4, [37, 3, 38, 12, 13, 14, 15, 16], {37: "president", 3: "tresorier"}, debut4)
    c4 = creer_cycle(db, t4, "Cycle des anciens", 15000, "mensuelle", debut4, a4, "termine", 1000, 2000)
    creer_cotisations(db, c4, a4, 0, 1.0)
    creer_evenement(db, t4, a4[0], "Retrouvailles des anciens", "fete", "Repas de retrouvailles de fin de cycle.",
                    -30, -35, None, 150000, 5000, "clos", random.sample(a4, 6), [5000, 10000])

    # Journal et notifications
    journaliser(db, t1, 0, "Tontine créée", "Tontine des commerçants de Mboppi", 330)
    journaliser(db, t1, 0, "Cycle créé", "Cycle 2025-2026 : 25 séances de 25000 FCFA", 325)
    journaliser(db, t1, 0, "Tirage au sort", "Cycle « Cycle 2025-2026 » : 25 bénéficiaire(s) tiré(s)", 324)
    journaliser(db, t1, 1, "Cotisations", "Séance n° 12 : 20 cotisation(s) enregistrée(s)", 9)
    journaliser(db, t2, 3, "Tontine créée", "Njangi des femmes de Bonabéri", 46)
    journaliser(db, t2, 4, "Cotisations", "Séance n° 5 : 11 cotisation(s) enregistrée(s)", 3)
    journaliser(db, t3, 31, "Tontine créée", "Jeunes entrepreneurs de Yaoundé", 12)
    journaliser(db, t4, 37, "Clôture", "La tontine est terminée", 40)
    notifications = [(1, t1, "Votre cotisation de la séance n° 12 est enregistrée."),
                     (3, t2, "Pénalité de 500 FCFA (retard) pour la séance n° 2."),
                     (32, t3, "Une personne demande à rejoindre la tontine."),
                     (32, t3, "Un nouveau membre a rejoint la tontine.")]
    for utilisateur, tontine, message in notifications:
        db.execute("INSERT INTO notifications (utilisateur_id, tontine_id, message) VALUES (?, ?, ?)", (utilisateur, tontine, message))
    db.commit()


if __name__ == "__main__":
    random.seed(42)  # mêmes données à chaque lancement
    db = sqlite3.connect("projet.db")
    db.execute("PRAGMA foreign_keys = ON")
    with open("schema.sql", encoding="utf-8") as f:
        db.executescript(f.read())
    remplir(db)
    print("Comptes de test (téléphone / code d'accès)")
    print("  677000001 / " + CODE_BUREAU + " : président de la tontine des commerçants de Mboppi")
    print("  677000002 / " + CODE_BUREAU + " : trésorier de la tontine des commerçants de Mboppi")
    print("  699000003 / " + CODE_MEMBRES + " : membre simple de la tontine de Mboppi")
    print("  677000004 / " + CODE_MULTI + " : membre à Mboppi, président à Bonabéri, trésorier chez les anciens du lycée")
    print("  699000099 / " + CODE_PLATEFORME + " : administrateur de la plateforme")
    print("  codes d'invitation : MBOP2026, BONA2026, JEUN2026, LYCE2026")
    print()
    for table in ("utilisateurs", "tontines", "adhesions", "cycles", "seances", "cotisations", "paiements",
                  "lignes_paiement", "evenements", "contributions_evenement", "penalites", "journal_actions", "notifications", "tentatives_connexion"):
        n = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"{table} : {n} lignes")
    db.close()
