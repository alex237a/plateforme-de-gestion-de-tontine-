// Tableau de bord : les statistiques viennent de l'API /api/statistiques (fetch)
(function () {
  "use strict";
  var conteneur = document.getElementById("tableau");
  if (!conteneur) { return; }

  function construireTableau(entetes, lignes) {
    var table = Njangi.creer("table");
    var tete = Njangi.creer("thead");
    var ligneTete = Njangi.creer("tr");
    entetes.forEach(function (titre) {
      var th = Njangi.creer("th", "", titre);
      th.scope = "col";
      ligneTete.appendChild(th);
    });
    tete.appendChild(ligneTete);
    var corps = Njangi.creer("tbody");
    lignes.forEach(function (cellules) {
      var tr = Njangi.creer("tr");
      cellules.forEach(function (cellule) {
        var td = Njangi.creer("td");
        if (cellule instanceof Node) { td.appendChild(cellule); } else { td.textContent = cellule; }
        tr.appendChild(td);
      });
      corps.appendChild(tr);
    });
    table.appendChild(tete);
    table.appendChild(corps);
    return table;
  }

  function remplir(zone, noeud) {
    zone.textContent = "";
    zone.appendChild(noeud);
  }

  function afficherRetards(retards) {
    var zone = document.getElementById("zone-retards");
    if (retards.length === 0) {
      remplir(zone, Njangi.creer("p", "mut espace-haut", "Aucun membre en retard : tout le monde est à jour."));
      return;
    }
    var lignes = retards.map(function (m) {
      return [m.nom, String(m.seances_manquantes), Njangi.fcfa(m.cotisations_dues),
              Njangi.fcfa(m.penalites_dues), Njangi.creer("span", "badge rouge", Njangi.fcfa(m.montant_du))];
    });
    remplir(zone, construireTableau(["Membre", "Séances manquées", "Cotisations", "Pénalités", "Montant dû"], lignes));
  }

  function afficherPenalites(penalites) {
    var zone = document.getElementById("zone-penalites");
    if (penalites.length === 0) {
      remplir(zone, Njangi.creer("p", "mut espace-haut", "Aucune pénalité enregistrée."));
      return;
    }
    var lignes = penalites.map(function (m) {
      return [m.nom, Njangi.fcfa(m.total), Njangi.fcfa(m.non_payees)];
    });
    remplir(zone, construireTableau(["Membre", "Total", "Non payées"], lignes));
  }

  function afficherPonctualite(liste) {
    var zone = document.getElementById("zone-ponctualite");
    zone.textContent = "";
    liste.forEach(function (m) {
      var ligne = Njangi.creer("div", "ligne-ponctualite");
      var barre = Njangi.creer("div", "barre");
      barre.setAttribute("role", "progressbar");
      barre.setAttribute("aria-label", "Ponctualité de " + m.nom);
      barre.setAttribute("aria-valuemin", "0");
      barre.setAttribute("aria-valuemax", "100");
      var remplissage = Njangi.creer("span");
      barre.appendChild(remplissage);
      var taux = m.taux === null ? 0 : m.taux;
      barre.setAttribute("aria-valuenow", String(taux));
      ligne.appendChild(Njangi.creer("span", "", m.nom));
      ligne.appendChild(barre);
      ligne.appendChild(Njangi.creer("span", "mut", m.taux === null ? "—" : m.taux + " %"));
      zone.appendChild(ligne);
      requestAnimationFrame(function () { remplissage.style.width = taux + "%"; });
    });
  }

  // Graphique en barres dessiné à la main avec le canvas
  var canvas = document.getElementById("graph-collecte");
  var donneesGraphique = [];
  var progression = 1;

  function dessiner() {
    var d = window.devicePixelRatio || 1;
    var L = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = L * d; canvas.height = H * d;
    var x = canvas.getContext("2d");
    x.setTransform(d, 0, 0, d, 0, 0);
    x.clearRect(0, 0, L, H);
    x.font = "12px Bricolage Grotesque,system-ui,sans-serif";
    if (donneesGraphique.length === 0) {
      x.fillStyle = Njangi.couleur("--mut"); x.textAlign = "center";
      x.fillText("Aucune séance passée pour le moment.", L / 2, H / 2);
      return;
    }
    var marge = { g: 46, d: 8, h: 10, b: 26 };
    var max = 1;
    donneesGraphique.forEach(function (s) { max = Math.max(max, s.collecte, s.attendu); });
    var hauteur = H - marge.h - marge.b, largeur = L - marge.g - marge.d;

    // lignes horizontales et valeurs en milliers de FCFA
    x.textAlign = "right"; x.textBaseline = "middle";
    for (var i = 0; i <= 4; i++) {
      var y = marge.h + hauteur * (1 - i / 4);
      x.strokeStyle = Njangi.couleur("--line"); x.lineWidth = 1;
      x.beginPath(); x.moveTo(marge.g, y); x.lineTo(L - marge.d, y); x.stroke();
      x.fillStyle = Njangi.couleur("--mut");
      x.fillText(Math.round(max * i / 4 / 1000) + " k", marge.g - 6, y);
    }

    var place = largeur / donneesGraphique.length;
    var epaisseur = Math.min(place * 0.6, 34);
    donneesGraphique.forEach(function (s, k) {
      var cx = marge.g + place * k + place / 2;
      var hAttendu = hauteur * s.attendu / max;
      var hCollecte = hauteur * s.collecte / max * progression;
      // attendu : contour doré ; collecté : barre verte
      x.strokeStyle = Njangi.couleur("--gold"); x.lineWidth = 2;
      x.strokeRect(cx - epaisseur / 2, marge.h + hauteur - hAttendu, epaisseur, hAttendu);
      x.fillStyle = Njangi.couleur("--green");
      x.globalAlpha = s.collecte >= s.attendu ? 1 : 0.7;
      x.fillRect(cx - epaisseur / 2 + 2, marge.h + hauteur - hCollecte, epaisseur - 4, hCollecte);
      x.globalAlpha = 1;
      x.fillStyle = Njangi.couleur("--mut"); x.textAlign = "center"; x.textBaseline = "top";
      x.fillText(String(s.numero), cx, marge.h + hauteur + 6);
    });
  }

  function animerGraphique() {
    if (Njangi.reduit) { progression = 1; dessiner(); return; }
    var debut = performance.now();
    (function pas(maintenant) {
      var p = Math.min((maintenant - debut) / 1000, 1);
      progression = 1 - Math.pow(1 - p, 3);
      dessiner();
      if (p < 1) { requestAnimationFrame(pas); }
    })(debut);
  }

  window.addEventListener("resize", dessiner);
  document.addEventListener("themechange", dessiner);

  Njangi.api(conteneur.dataset.api).then(function (r) {
    if (!r.ok) { throw new Error(r.donnees.erreur || "Erreur"); }
    donneesGraphique = r.donnees.collecte_par_seance;
    canvas.setAttribute("aria-label", "Graphique en barres : montant collecté et montant attendu pour "
      + donneesGraphique.length + " séances passées");
    animerGraphique();
    afficherRetards(r.donnees.retards);
    afficherPenalites(r.donnees.penalites_par_membre);
    afficherPonctualite(r.donnees.ponctualite);
  }).catch(function () {
    ["zone-retards", "zone-penalites", "zone-ponctualite"].forEach(function (id) {
      var zone = document.getElementById(id);
      zone.textContent = "";
      zone.appendChild(Njangi.creer("p", "erreur-champ", "Impossible de charger les statistiques."));
    });
  });
})();
