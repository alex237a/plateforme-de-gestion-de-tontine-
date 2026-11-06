// Page de paiement : total en direct et vérification avant l'envoi (le serveur recalcule tout)
(function () {
  "use strict";
  var formulaire = document.getElementById("form-paiement");
  if (!formulaire) { return; }
  var total = document.getElementById("total-paiement");
  var erreur = document.getElementById("err-paiement");
  var telephone = document.getElementById("telephone");
  var cases = Array.prototype.slice.call(formulaire.querySelectorAll(".liste-sommes input[type=checkbox]"));

  function recalculer() {
    var somme = 0;
    cases.forEach(function (c) { if (c.checked) { somme += Number(c.dataset.montant) || 0; } });
    total.textContent = Njangi.fcfa(somme);
  }
  cases.forEach(function (c) { c.addEventListener("change", recalculer); });

  formulaire.addEventListener("submit", function (e) {
    var ok = true;
    erreur.textContent = "";
    if (!cases.some(function (c) { return c.checked; })) {
      erreur.textContent = "Cochez au moins une somme à régler.";
      ok = false;
    }
    if (!Njangi.telephoneValide(telephone.value)) {
      Njangi.erreurChamp(telephone, "Entrez 9 chiffres qui commencent par 6 (exemple : 677123456).");
      ok = false;
    } else {
      Njangi.erreurChamp(telephone, "");
    }
    if (!ok) { e.preventDefault(); }
  });
  recalculer();
})();
