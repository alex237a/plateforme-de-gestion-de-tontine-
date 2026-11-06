// Applique le thème choisi (clair ou sombre) avant l'affichage de la page, pour éviter un éclair blanc
(function () {
  "use strict";
  var choix = null;
  try { choix = localStorage.getItem("theme"); } catch (e) { choix = null; }
  var sombre = choix ? choix === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.setAttribute("data-theme", sombre ? "dark" : "light");
})();
