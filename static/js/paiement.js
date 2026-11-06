// Confirmation d'un paiement mobile (simulation) : attente de la demande, code secret, compte à rebours
(function () {
  "use strict";
  var zone = document.getElementById("zone-paiement");
  if (!zone || zone.dataset.statut !== "en_attente") { return; }
  var formulaire = document.getElementById("form-pin");
  var attente = document.getElementById("attente-message");
  var pin = document.getElementById("pin");
  var rebours = document.getElementById("compte-rebours");
  var restant = Number(zone.dataset.secondes) || 0;

  // Le paiement a peut-être déjà été traité depuis un autre onglet : on vérifie son état auprès du serveur
  Njangi.api(zone.dataset.api).then(function (r) {
    if (r.ok && r.donnees.statut !== "en_attente") { window.location.reload(); }
  });

  // Courte attente avant d'afficher la saisie du code, comme une vraie demande de confirmation
  if (!Njangi.reduit) {
    formulaire.hidden = true;
    attente.hidden = false;
    setTimeout(function () {
      attente.hidden = true;
      formulaire.hidden = false;
      pin.focus();
    }, 1800);
  }

  var minuteur = setInterval(function () {
    restant -= 1;
    if (restant <= 0) {
      clearInterval(minuteur);
      window.location.reload();
      return;
    }
    rebours.textContent = Math.floor(restant / 60) + ":" + String(restant % 60).padStart(2, "0");
  }, 1000);

  pin.addEventListener("input", function () { pin.value = pin.value.replace(/\D/g, "").slice(0, 4); });
  formulaire.addEventListener("submit", function (e) {
    if (!/^\d{4}$/.test(pin.value)) {
      Njangi.erreurChamp(pin, "Le code secret comporte 4 chiffres.");
      e.preventDefault();
    } else {
      Njangi.erreurChamp(pin, "");
    }
  });
})();
