// Page d'accueil : animation de la tontine, étapes qui se remplissent et simulateur de cagnotte
(function () {
  "use strict";

  // Animation : les membres cotisent dans la cagnotte, puis la cagnotte va au bénéficiaire du tour
  (function () {
    var c = document.getElementById("cercle");
    if (!c) { return; }
    var x = c.getContext("2d");
    var fixe = Njangi.reduit;
    var couleurs = ["#14a85f", "#e9a21a", "#0f9fa0", "#e2673c", "#8a56b8"];
    var lettres = ["A", "B", "C", "D", "E", "F", "G", "H"];
    var N = lettres.length, DUREE = 5600;
    var W, H;

    function taille() {
      var d = window.devicePixelRatio || 1;
      W = c.clientWidth; H = c.clientHeight;
      c.width = W * d; c.height = H * d;
      x.setTransform(d, 0, 0, d, 0, 0);
    }
    window.addEventListener("resize", taille);
    taille();

    function fraction(ph, debut, duree) { return Math.min(1, Math.max(0, (ph - debut) / duree)); }

    function piece(a, b, p) {
      var e = p * p * (3 - 2 * p);
      var px = a.x + (b.x - a.x) * e, py = a.y + (b.y - a.y) * e - Math.sin(p * Math.PI) * 22;
      x.fillStyle = "#ffd86b"; x.strokeStyle = "#e9a21a"; x.lineWidth = 2;
      x.beginPath(); x.arc(px, py, 6, 0, 7); x.fill(); x.stroke();
    }

    function image(t) {
      x.clearRect(0, 0, W, H);
      var cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.36;
      var tour = Math.floor(t / DUREE), ph = (t % DUREE) / DUREE;
      var benef = tour % N;
      var membres = lettres.map(function (_, i) {
        var a = -Math.PI / 2 + i * 2 * Math.PI / N;
        return { x: cx + Math.cos(a) * R, y: cy + Math.sin(a) * R };
      });
      var centre = { x: cx, y: cy };

      // cercle de la tontine
      x.strokeStyle = Njangi.couleur("--line"); x.lineWidth = 2; x.setLineDash([4, 8]);
      x.beginPath(); x.arc(cx, cy, R, 0, 7); x.stroke(); x.setLineDash([]);

      // cagnotte au centre : elle grossit pendant les cotisations et se vide au paiement du bénéficiaire
      var remplie = ph < 0.3 ? fraction(ph, 0.02, 0.28) : ph < 0.55 ? 1 : 1 - fraction(ph, 0.55, 0.3);
      var rayon = 34 + remplie * 12;
      var lueur = x.createRadialGradient(cx, cy, 0, cx, cy, rayon * 2.6);
      lueur.addColorStop(0, "rgba(242,165,22," + (0.15 + remplie * 0.3).toFixed(2) + ")"); lueur.addColorStop(1, "rgba(242,165,22,0)");
      x.fillStyle = lueur; x.beginPath(); x.arc(cx, cy, rayon * 2.6, 0, 7); x.fill();
      x.fillStyle = Njangi.couleur("--gold"); x.beginPath(); x.arc(cx, cy, rayon, 0, 7); x.fill();
      x.fillStyle = "#2b1c00"; x.font = "800 " + Math.round(rayon * 0.42) + "px Bricolage Grotesque,sans-serif";
      x.textAlign = "center"; x.textBaseline = "middle"; x.fillText("FCFA", cx, cy);

      // membres : le bénéficiaire du tour est entouré d'or une fois la cagnotte reçue
      membres.forEach(function (m, i) {
        var est = i === benef, recu = est && ph > 0.8;
        var r = 24 + (recu ? 7 : 0);
        if (recu) {
          x.strokeStyle = Njangi.couleur("--gold"); x.lineWidth = 4;
          x.beginPath(); x.arc(m.x, m.y, r + 7, 0, 7); x.stroke();
        }
        x.fillStyle = couleurs[i % couleurs.length];
        x.beginPath(); x.arc(m.x, m.y, r, 0, 7); x.fill();
        x.fillStyle = "#fff"; x.font = "800 " + (recu ? 20 : 17) + "px Bricolage Grotesque,sans-serif";
        x.fillText(lettres[i], m.x, m.y + 1);
      });

      // pieces : cotisations vers la cagnotte, puis cagnotte vers le bénéficiaire
      membres.forEach(function (m, i) {
        var p = fraction(ph, 0.02 + i * 0.03, 0.26);
        if (p > 0 && p < 1) { piece(m, centre, p); }
      });
      for (var j = 0; j < 6; j++) {
        var q = fraction(ph, 0.55 + j * 0.04, 0.25);
        if (q > 0 && q < 1) { piece(centre, membres[benef], q); }
      }
      if (!fixe) { requestAnimationFrame(image); }
    }
    if (fixe) { image(DUREE * 0.9); } else { requestAnimationFrame(image); }
    document.addEventListener("themechange", function () { if (fixe) { image(DUREE * 0.9); } });
  })();

  // Ligne des étapes qui se remplit au scroll
  (function () {
    var boite = document.getElementById("steps");
    var remplissage = document.getElementById("fill");
    if (!boite || !remplissage) { return; }
    var etapes = Array.prototype.slice.call(boite.querySelectorAll(".etape"));
    function maj() {
      var r = boite.getBoundingClientRect(), vh = window.innerHeight;
      var p = Math.min(1, Math.max(0, (vh * 0.65 - r.top) / r.height));
      remplissage.style.height = (r.height - 16) * p + "px";
      etapes.forEach(function (e) { e.classList.toggle("on", e.getBoundingClientRect().top < vh * 0.65); });
    }
    window.addEventListener("scroll", maj, { passive: true });
    maj();
  })();

  // Simulateur de cagnotte
  (function () {
    var nb = document.getElementById("nb"), mt = document.getElementById("mt"), points = document.getElementById("dots");
    if (!nb || !mt) { return; }
    var courant = 0;
    function peindre() {
      Array.prototype.forEach.call(points.children, function (d, i) {
        d.className = i < courant ? "past" : i === courant ? "now" : "";
      });
    }
    function afficher() {
      var n = Number(nb.value), m = Number(mt.value);
      document.getElementById("nbv").textContent = n;
      document.getElementById("mtv").textContent = Njangi.fcfa(m);
      document.getElementById("pot").textContent = Njangi.fcfa(n * m);
      document.getElementById("dur").textContent = "Le cycle dure " + n + " mois, un bénéficiaire par mois";
      points.textContent = "";
      for (var i = 0; i < n; i++) { points.appendChild(document.createElement("i")); }
      courant = 0;
      peindre();
    }
    nb.addEventListener("input", afficher);
    mt.addEventListener("input", afficher);
    afficher();
    if (!Njangi.reduit) {
      setInterval(function () { courant = (courant + 1) % points.children.length; peindre(); }, 900);
    }
  })();

})();
