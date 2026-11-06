// Saisie des cotisations d'une séance : total et retardataires en direct
(function () {
  "use strict";
  var formulaire = document.getElementById("form-cotisations");
  var etat = document.getElementById("etat-direct");
  if (!formulaire || !etat) { return; }

  var montant = Number(etat.dataset.montant);
  var dejaEnregistre = Number(etat.dataset.enregistre);
  var lignes = Array.prototype.slice.call(formulaire.querySelectorAll("tbody tr"));
  var totalDirect = document.getElementById("total-direct");
  var retardDirect = document.getElementById("retard-direct");
  var erreur = document.getElementById("err-cotisations");

  function cases() {
    return lignes.map(function (tr) { return tr.querySelector("input[type=checkbox]"); });
  }

  // Les montants des cases cochées s'ajoutent à ce qui est déjà enregistré
  function recalculer() {
    var total = dejaEnregistre;
    var sansPaiement = 0;
    lignes.forEach(function (tr) {
      var c = tr.querySelector("input[type=checkbox]");
      if (tr.classList.contains("enregistre")) { return; }
      if (c.checked) {
        var champ = tr.querySelector(".champ-montant");
        total += Number(champ ? champ.value : montant) || 0;
      } else {
        sansPaiement++;
      }
    });
    totalDirect.textContent = Njangi.fcfa(total);
    retardDirect.textContent = sansPaiement;
  }

  cases().forEach(function (c) { c.addEventListener("change", recalculer); });

  var toutCocher = document.getElementById("tout-cocher");
  if (toutCocher) {
    toutCocher.addEventListener("click", function () {
      cases().forEach(function (c) { if (!c.disabled) { c.checked = true; } });
      recalculer();
    });
  }

  // Vérification avant l'envoi : le serveur refait les mêmes contrôles
  formulaire.addEventListener("submit", function (e) {
    var message = "";
    var cochees = lignes.filter(function (tr) {
      var c = tr.querySelector("input[type=checkbox]");
      return c.checked && !c.disabled;
    });
    if (cochees.length === 0) {
      message = "Cochez au moins un membre qui a payé.";
    }
    cochees.forEach(function (tr) {
      var date = tr.querySelector("input[type=date]");
      if (!message && (!date.value || date.value > date.max)) {
        message = "La date de paiement de " + tr.children[1].textContent + " est vide ou dans le futur.";
      }
    });
    erreur.textContent = message;
    if (message) { e.preventDefault(); }
  });

  // Dernier état connu du serveur, pour comparer avec la saisie en cours
  Njangi.api(etat.dataset.api).then(function (r) {
    if (!r.ok) { return; }
    document.getElementById("etat-serveur").textContent =
      Njangi.fcfa(r.donnees.total_collecte) + " (" + r.donnees.nb_payeurs + " payeur" +
      (r.donnees.nb_payeurs > 1 ? "s" : "") + ")";
  });

  recalculer();
})();
