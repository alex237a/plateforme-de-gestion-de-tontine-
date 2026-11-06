-- Schéma de la plateforme de tontines (SQLite)
-- Les montants sont des entiers en FCFA, les dates au format AAAA-MM-JJ.

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS tentatives_connexion;
DROP TABLE IF EXISTS notifications;
DROP TABLE IF EXISTS journal_actions;
DROP TABLE IF EXISTS contributions_evenement;
DROP TABLE IF EXISTS lignes_paiement;
DROP TABLE IF EXISTS penalites;
DROP TABLE IF EXISTS cotisations;
DROP TABLE IF EXISTS paiements;
DROP TABLE IF EXISTS evenements;
DROP TABLE IF EXISTS seances;
DROP TABLE IF EXISTS cycles;
DROP TABLE IF EXISTS adhesions;
DROP TABLE IF EXISTS tontines;
DROP TABLE IF EXISTS utilisateurs;

-- Compte global : un utilisateur peut appartenir à plusieurs tontines
CREATE TABLE utilisateurs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    nom                  TEXT    NOT NULL CHECK (length(nom) BETWEEN 2 AND 80),
    telephone            TEXT    NOT NULL UNIQUE CHECK (length(telephone) = 9),
    code_acces           TEXT    NOT NULL,  -- empreinte, jamais le code en clair
    date_inscription     TEXT    NOT NULL,
    est_admin_plateforme INTEGER NOT NULL DEFAULT 0 CHECK (est_admin_plateforme IN (0, 1)),
    actif                INTEGER NOT NULL DEFAULT 1 CHECK (actif IN (0, 1))
);

CREATE TABLE tontines (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    nom                   TEXT    NOT NULL CHECK (length(nom) BETWEEN 2 AND 80),
    description           TEXT    NOT NULL DEFAULT '' CHECK (length(description) <= 300),
    createur_id           INTEGER NOT NULL REFERENCES utilisateurs (id),
    code_invitation       TEXT    NOT NULL UNIQUE CHECK (length(code_invitation) = 8),
    adhesion_libre        INTEGER NOT NULL DEFAULT 0 CHECK (adhesion_libre IN (0, 1)),
    publique              INTEGER NOT NULL DEFAULT 0 CHECK (publique IN (0, 1)),
    nombre_max_membres    INTEGER NOT NULL CHECK (nombre_max_membres BETWEEN 2 AND 200),
    statut                TEXT    NOT NULL DEFAULT 'active'
                          CHECK (statut IN ('active', 'terminee', 'suspendue')),
    suspension_plateforme INTEGER NOT NULL DEFAULT 0 CHECK (suspension_plateforme IN (0, 1)),
    couleur               TEXT    NOT NULL DEFAULT 'vert'
                          CHECK (couleur IN ('vert', 'or', 'turquoise', 'corail', 'prune')),
    date_creation         TEXT    NOT NULL
);

-- Le rôle est propre à chaque tontine
CREATE TABLE adhesions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tontine_id     INTEGER NOT NULL REFERENCES tontines (id),
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs (id),
    role           TEXT    NOT NULL DEFAULT 'membre' CHECK (role IN ('membre', 'tresorier', 'president')),
    statut         TEXT    NOT NULL DEFAULT 'active'
                   CHECK (statut IN ('en_attente', 'active', 'quittee', 'refusee')),
    date_adhesion  TEXT    NOT NULL,
    UNIQUE (tontine_id, utilisateur_id)
);

CREATE TABLE cycles (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    tontine_id              INTEGER NOT NULL REFERENCES tontines (id),
    nom                     TEXT    NOT NULL,
    montant_cotisation      INTEGER NOT NULL CHECK (montant_cotisation > 0),
    periodicite             TEXT    NOT NULL CHECK (periodicite IN ('hebdomadaire', 'mensuelle')),
    date_debut              TEXT    NOT NULL,
    montant_penalite_retard  INTEGER NOT NULL DEFAULT 1000 CHECK (montant_penalite_retard >= 0),
    montant_penalite_absence INTEGER NOT NULL DEFAULT 2000 CHECK (montant_penalite_absence >= 0),
    statut                  TEXT    NOT NULL DEFAULT 'en_preparation'
                            CHECK (statut IN ('en_preparation', 'en_cours', 'termine'))
);

CREATE TABLE seances (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id               INTEGER NOT NULL REFERENCES cycles (id),
    numero                 INTEGER NOT NULL CHECK (numero > 0),
    date                   TEXT    NOT NULL,
    beneficiaire_id        INTEGER REFERENCES adhesions (id),
    montant_total_collecte INTEGER NOT NULL DEFAULT 0 CHECK (montant_total_collecte >= 0),
    UNIQUE (cycle_id, numero),
    -- un membre ne bénéficie qu'une fois par cycle (plusieurs NULL sont permis)
    UNIQUE (cycle_id, beneficiaire_id)
);

-- Paiements par mobile money (simulation) : Orange Money ou MTN MoMo
CREATE TABLE paiements (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    adhesion_id       INTEGER NOT NULL REFERENCES adhesions (id),
    operateur         TEXT    NOT NULL CHECK (operateur IN ('orange_money', 'mtn_momo')),
    telephone         TEXT    NOT NULL CHECK (length(telephone) = 9),
    montant           INTEGER NOT NULL CHECK (montant > 0),
    reference         TEXT    NOT NULL UNIQUE,
    statut            TEXT    NOT NULL DEFAULT 'en_attente' CHECK (statut IN ('en_attente', 'reussi', 'echoue')),
    motif_echec       TEXT,
    date_creation     TEXT    NOT NULL,
    date_confirmation TEXT
);

CREATE TABLE cotisations (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    seance_id     INTEGER NOT NULL REFERENCES seances (id),
    adhesion_id   INTEGER NOT NULL REFERENCES adhesions (id),
    montant       INTEGER NOT NULL CHECK (montant > 0),
    date_paiement TEXT    NOT NULL,
    mode          TEXT    NOT NULL CHECK (mode IN ('especes', 'mobile_money')),
    paiement_id   INTEGER REFERENCES paiements (id),  -- renseigné quand la cotisation vient d'un paiement en ligne
    UNIQUE (seance_id, adhesion_id)
);

CREATE TABLE penalites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    adhesion_id INTEGER NOT NULL REFERENCES adhesions (id),
    seance_id   INTEGER NOT NULL REFERENCES seances (id),
    motif       TEXT    NOT NULL CHECK (motif IN ('retard', 'absence')),
    montant     INTEGER NOT NULL CHECK (montant > 0),
    payee       INTEGER NOT NULL DEFAULT 0 CHECK (payee IN (0, 1)),
    paiement_id INTEGER REFERENCES paiements (id),
    UNIQUE (adhesion_id, seance_id, motif)
);

-- Événements de la tontine (mariage, deuil, naissance...) : les contributions sont libres, rien n'est obligatoire
CREATE TABLE evenements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tontine_id      INTEGER NOT NULL REFERENCES tontines (id),
    titre           TEXT    NOT NULL CHECK (length(titre) BETWEEN 2 AND 80),
    type            TEXT    NOT NULL CHECK (type IN ('mariage', 'deuil', 'naissance', 'anniversaire', 'fete', 'autre')),
    description     TEXT    NOT NULL DEFAULT '' CHECK (length(description) <= 500),
    date_evenement  TEXT    NOT NULL,
    date_limite     TEXT,  -- dernier jour pour contribuer (facultatif)
    concerne_id     INTEGER REFERENCES adhesions (id),  -- membre concerné (facultatif)
    objectif        INTEGER CHECK (objectif IS NULL OR objectif > 0),
    montant_suggere INTEGER CHECK (montant_suggere IS NULL OR montant_suggere > 0),
    statut          TEXT    NOT NULL DEFAULT 'ouvert' CHECK (statut IN ('ouvert', 'clos')),
    cree_par        INTEGER NOT NULL REFERENCES adhesions (id),
    date_creation   TEXT    NOT NULL
);

-- Ce que couvre un paiement : une cotisation de séance, une pénalité ou une contribution à un événement
CREATE TABLE lignes_paiement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    paiement_id INTEGER NOT NULL REFERENCES paiements (id),
    type        TEXT    NOT NULL CHECK (type IN ('cotisation', 'penalite', 'evenement')),
    seance_id   INTEGER REFERENCES seances (id),
    penalite_id INTEGER REFERENCES penalites (id),
    evenement_id INTEGER REFERENCES evenements (id),
    montant     INTEGER NOT NULL CHECK (montant > 0),
    CHECK ((type = 'cotisation' AND seance_id IS NOT NULL AND penalite_id IS NULL AND evenement_id IS NULL)
        OR (type = 'penalite' AND penalite_id IS NOT NULL AND seance_id IS NULL AND evenement_id IS NULL)
        OR (type = 'evenement' AND evenement_id IS NOT NULL AND seance_id IS NULL AND penalite_id IS NULL))
);

-- Contributions libres à un événement : un membre peut contribuer plusieurs fois, du montant qu'il veut
CREATE TABLE contributions_evenement (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    evenement_id      INTEGER NOT NULL REFERENCES evenements (id),
    adhesion_id       INTEGER NOT NULL REFERENCES adhesions (id),
    montant           INTEGER NOT NULL CHECK (montant > 0),
    date_contribution TEXT    NOT NULL,
    mode              TEXT    NOT NULL CHECK (mode IN ('especes', 'mobile_money')),
    paiement_id       INTEGER REFERENCES paiements (id),
    enregistre_par    INTEGER REFERENCES adhesions (id)  -- renseigné quand le bureau a noté une contribution en espèces
);

-- tontine_id reste vide pour les actions de l'administrateur de la plateforme sur un compte
CREATE TABLE journal_actions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    tontine_id     INTEGER REFERENCES tontines (id),
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs (id),
    action         TEXT    NOT NULL,
    detail         TEXT    NOT NULL,
    date_action    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE notifications (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    utilisateur_id INTEGER NOT NULL REFERENCES utilisateurs (id),
    tontine_id     INTEGER REFERENCES tontines (id),
    message        TEXT    NOT NULL,
    lue            INTEGER NOT NULL DEFAULT 0 CHECK (lue IN (0, 1)),
    date_creation  TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Pour limiter les essais de connexion répétés
CREATE TABLE tentatives_connexion (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    telephone        TEXT NOT NULL,
    adresse_ip       TEXT NOT NULL,
    date_tentative   TEXT NOT NULL
);

CREATE INDEX idx_adhesions_utilisateur ON adhesions (utilisateur_id);
CREATE INDEX idx_cycles_tontine ON cycles (tontine_id);
CREATE INDEX idx_cotisations_adhesion ON cotisations (adhesion_id);
CREATE INDEX idx_seances_date ON seances (date);
CREATE INDEX idx_notifications_utilisateur ON notifications (utilisateur_id, lue);
CREATE INDEX idx_paiements_adhesion ON paiements (adhesion_id);
CREATE INDEX idx_lignes_paiement ON lignes_paiement (paiement_id);
CREATE INDEX idx_evenements_tontine ON evenements (tontine_id);
CREATE INDEX idx_contributions_evenement ON contributions_evenement (evenement_id);
