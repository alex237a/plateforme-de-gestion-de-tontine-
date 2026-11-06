// Page d'un événement : montants rapides, vérification de la contribution et état en direct (fetch)
(function () {
  "use strict";

  var formulaire = document.getElementById("form-contribution");
  if (formulaire) {
    var montant = document.getElementById("montant");
    var telephone = document.getElementById("telephone");
    Array.prototype.forEach.call(formulaire.querySelectorAll(".puces button"), function (bouton) {
      bouton.addEventListener("click", function () { montant.value = bouton.dataset.montant; montant.focus(); });
    });
    formulaire.addEventListener("submit", function (e) {
      var ok = true;
      var valeur = Number(montant.value);
      if (!Number.isInteger(valeur) || valeur < 500 || valeur > 5000000) {
        Njangi.erreurChamp(montant, "Entrez une contribution entre 500 et 5 000 000 FCFA.");
        ok = false;
      } else {
        Njangi.erreurChamp(montant, "");
      }
      if (!Njangi.telephoneValide(telephone.value)) {
        Njangi.erreurChamp(telephone, "Entrez 9 chiffres qui commencent par 6 (exemple : 677123456).");
        ok = false;
      } else {
        Njangi.erreurChamp(telephone, "");
      }
      if (!ok) { e.preventDefault(); }
    });
  }

  // Les chiffres de l'événement viennent de l'API : ils restent justes si d'autres membres contribuent en même temps
  var zone = document.getElementById("etat-evenement");
  if (zone) {
    Njangi.api(zone.dataset.api).then(function (r) {
      if (!r.ok) { return; }
      document.getElementById("total-evenement").textContent = Njangi.fcfa(r.donnees.total);
      document.getElementById("nb-contributeurs").textContent = r.donnees.nb_contributeurs;
    });
  }
})();
