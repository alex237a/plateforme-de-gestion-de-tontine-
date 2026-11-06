// Mes tontines : les totaux personnels viennent de l'API /api/mes-tontines (fetch)
(function () {
  "use strict";
  var zone = document.getElementById("mes-tontines");
  if (!zone) { return; }
  var verse = document.getElementById("total-verse");
  var du = document.getElementById("total-du");

  Njangi.api(zone.dataset.api).then(function (r) {
    if (!r.ok) { throw new Error("Erreur"); }
    Njangi.compter(verse, r.donnees.total_verse, "\u00a0FCFA");
    Njangi.compter(du, r.donnees.total_du, "\u00a0FCFA");
  }).catch(function () {
    verse.textContent = "indisponible";
    du.textContent = "indisponible";
  });
})();
