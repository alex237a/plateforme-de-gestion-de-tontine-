// Liste des membres d'une tontine : recherche instantanée (fetch sur l'API de la tontine)
(function () {
  "use strict";
  var table = document.getElementById("table-membres");
  var champ = document.getElementById("q");
  if (!table || !champ) { return; }

  var corps = document.getElementById("corps-membres");
  var compte = document.getElementById("compte-membres");
  var avecTelephone = table.dataset.telephone === "1";
  var ROLES = { membre: "Membre", tresorier: "Trésorier", president: "Président" };
  var minuteur = null;

  function formaterDate(texte) {
    return new Date(texte + "T00:00:00").toLocaleDateString("fr-FR", { day: "numeric", month: "long", year: "numeric" });
  }

  function afficher(membres) {
    corps.textContent = "";
    membres.forEach(function (m) {
      var tr = Njangi.creer("tr");
      tr.appendChild(Njangi.creer("td", "", m.nom));
      var role = Njangi.creer("td");
      role.appendChild(Njangi.creer("span", "badge role-" + (ROLES[m.role] ? m.role : "membre"), ROLES[m.role] || m.role));
      tr.appendChild(role);
      if (avecTelephone) { tr.appendChild(Njangi.creer("td", "", m.telephone || "")); }
      tr.appendChild(Njangi.creer("td", "", formaterDate(m.date_adhesion)));
      corps.appendChild(tr);
    });
    compte.textContent = membres.length + " membre" + (membres.length > 1 ? "s" : "");
  }

  champ.addEventListener("input", function () {
    clearTimeout(minuteur);
    minuteur = setTimeout(function () {
      Njangi.api(table.dataset.api + "?q=" + encodeURIComponent(champ.value.trim()))
        .then(function (r) { if (r.ok) { afficher(r.donnees); } });
    }, 250);
  });
})();
