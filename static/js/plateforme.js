// Tableau de bord de la plateforme : graphique des tontines les plus actives (fetch)
(function () {
  "use strict";
  var zone = document.getElementById("plateforme");
  var canvas = document.getElementById("graph-plateforme");
  if (!zone || !canvas) { return; }
  var donnees = [];
  var progression = 1;

  function dessiner() {
    var d = window.devicePixelRatio || 1;
    var L = canvas.clientWidth, H = canvas.clientHeight;
    canvas.width = L * d; canvas.height = H * d;
    var x = canvas.getContext("2d");
    x.setTransform(d, 0, 0, d, 0, 0);
    x.clearRect(0, 0, L, H);
    x.font = "13px Bricolage Grotesque,system-ui,sans-serif";
    if (donnees.length === 0) {
      x.fillStyle = Njangi.couleur("--mut"); x.textAlign = "center"; x.fillText("Aucune donnée pour le moment.", L / 2, H / 2);
      return;
    }
    var max = Math.max.apply(null, donnees.map(function (t) { return t.total; })) || 1;
    var margeG = Math.min(190, L * 0.38), hauteurLigne = H / donnees.length;
    donnees.forEach(function (t, i) {
      var y = i * hauteurLigne + hauteurLigne / 2;
      var nom = t.nom.length > 26 ? t.nom.slice(0, 25) + "…" : t.nom;
      x.fillStyle = Njangi.couleur("--txt"); x.textAlign = "right"; x.textBaseline = "middle";
      x.fillText(nom, margeG - 10, y);
      var longueur = (L - margeG - 110) * t.total / max * progression;
      x.fillStyle = i === 0 ? Njangi.couleur("--gold") : Njangi.couleur("--green");
      x.beginPath(); x.roundRect(margeG, y - 11, Math.max(longueur, 2), 22, 8); x.fill();
      x.fillStyle = Njangi.couleur("--mut"); x.textAlign = "left";
      x.fillText(Njangi.fcfa(t.total), margeG + longueur + 8, y);
    });
  }

  function animer() {
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
  Njangi.api(zone.dataset.api).then(function (r) {
    if (!r.ok) { throw new Error("Erreur"); }
    donnees = r.donnees.plus_actives;
    animer();
  }).catch(function () {
    var x = canvas.getContext("2d");
    x.fillStyle = "#d93a2b"; x.fillText("Impossible de charger les statistiques.", 10, 30);
  });
})();
