// Tirage au sort : les noms défilent, puis chaque bénéficiaire est révélé tour à tour
(function () {
  "use strict";
  var liste = document.getElementById("tirage-liste");
  var etat = document.getElementById("etat-tirage");
  if (!liste || liste.dataset.animation !== "1") { return; }
  if (Njangi.reduit) {
    etat.textContent = "Tirage terminé : l'ordre est enregistré.";
    return;
  }

  var lignes = Array.prototype.slice.call(liste.querySelectorAll("li"));
  var noms = lignes.map(function (li) { return li.dataset.nom; }).filter(Boolean);
  var duree = Math.max(250, 7000 / lignes.length);  // le tirage entier dure environ 7 secondes
  var rang = 0;

  lignes.forEach(function (li) { li.querySelector(".nom-tire").textContent = "…"; });
  etat.textContent = "Tirage en cours…";

  function suivant() {
    if (rang >= lignes.length) {
      etat.textContent = "Tirage terminé : l'ordre est enregistré.";
      return;
    }
    var ligne = lignes[rang];
    var zone = ligne.querySelector(".nom-tire");
    var cible = ligne.dataset.nom || "Pas encore tiré";
    ligne.classList.add("en-cours");
    var debut = performance.now();
    var minuteur = setInterval(function () {
      if (performance.now() - debut >= duree) {
        clearInterval(minuteur);
        zone.textContent = cible;
        ligne.classList.remove("en-cours");
        ligne.classList.add("revele");
        rang++;
        setTimeout(suivant, 120);
      } else {
        zone.textContent = noms[Math.floor(Math.random() * noms.length)];
      }
    }, 60);
  }
  suivant();
})();
