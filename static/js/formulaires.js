// Vérification des formulaires avant l'envoi : inscription, connexion, profil, tontine
// (le serveur refait les mêmes vérifications)
(function () {
  "use strict";

  // Vérifie un champ avec un test ; affiche ou efface le message ; renvoie true si le champ est bon
  function verifier(champ, test, message) {
    if (!champ) { return true; }
    var ok = test(champ.value);
    Njangi.erreurChamp(champ, ok ? "" : message);
    return ok;
  }

  var nomValide = function (v) { var n = v.trim().length; return n >= 2 && n <= 80; };
  var codeValide = function (v) { return v.length >= 6; };
  var telephone = function (v) { return Njangi.telephoneValide(v); };
  var MSG_NOM = "Le nom doit contenir entre 2 et 80 caractères.";
  var MSG_TEL = "Entrez 9 chiffres qui commencent par 6 (exemple : 677123456).";
  var MSG_CODE = "Le code d'accès doit contenir au moins 6 caractères.";

  function surEnvoi(id, controle) {
    var formulaire = document.getElementById(id);
    if (!formulaire) { return; }
    formulaire.addEventListener("submit", function (e) {
      if (!controle(formulaire)) { e.preventDefault(); }
    });
  }

  function champ(formulaire, nom) { return formulaire.elements[nom]; }

  surEnvoi("form-inscription", function (f) {
    var confirmation = champ(f, "confirmation");
    var resultats = [
      verifier(champ(f, "nom"), nomValide, MSG_NOM),
      verifier(champ(f, "telephone"), telephone, MSG_TEL),
      verifier(champ(f, "code"), codeValide, MSG_CODE),
      verifier(confirmation, function (v) { return v === champ(f, "code").value; }, "Les deux codes ne sont pas identiques.")
    ];
    return resultats.every(Boolean);
  });

  surEnvoi("form-connexion", function (f) {
    return [
      verifier(champ(f, "telephone"), telephone, "Entrez un numéro de 9 chiffres qui commence par 6."),
      verifier(champ(f, "code"), function (v) { return v.length > 0; }, "Entrez votre code d'accès.")
    ].every(Boolean);
  });

  surEnvoi("form-profil", function (f) {
    return [verifier(champ(f, "nom"), nomValide, MSG_NOM), verifier(champ(f, "telephone"), telephone, MSG_TEL)].every(Boolean);
  });

  surEnvoi("form-code", function (f) {
    return [
      verifier(champ(f, "nouveau"), codeValide, "Le nouveau code doit contenir au moins 6 caractères."),
      verifier(champ(f, "confirmation"), function (v) { return v === champ(f, "nouveau").value; }, "Les deux codes ne sont pas identiques.")
    ].every(Boolean);
  });

  surEnvoi("form-evenement", function (f) {
    return [
      verifier(champ(f, "titre"), function (v) { var n = v.trim().length; return n >= 2 && n <= 80; }, "Le titre doit contenir entre 2 et 80 caractères."),
      verifier(champ(f, "date_evenement"), function (v) { return v !== ""; }, "Choisissez la date de l'événement.")
    ].every(Boolean);
  });

  surEnvoi("form-tontine", function (f) {
    return [
      verifier(champ(f, "nom"), nomValide, MSG_NOM),
      verifier(champ(f, "nombre_max_membres"), function (v) { var n = Number(v); return Number.isInteger(n) && n >= 2 && n <= 200; },
               "Le nombre de membres doit être compris entre 2 et 200.")
    ].every(Boolean);
  });
})();
