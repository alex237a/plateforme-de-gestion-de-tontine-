// Fonctions communes à toutes les pages : menu, messages flash, animations, petits outils
(function () {
  "use strict";

  var reduit = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  var Njangi = {
    reduit: reduit,

    // Jeton CSRF lu dans la page, envoyé avec chaque requête POST de fetch
    jeton: function () {
      return document.body.dataset.csrf || "";
    },

    // Création d'un élément avec textContent : jamais d'innerHTML avec des données d'utilisateur
    creer: function (balise, classe, texte) {
      var element = document.createElement(balise);
      if (classe) { element.className = classe; }
      if (texte !== undefined && texte !== null) { element.textContent = texte; }
      return element;
    },

    fcfa: function (montant) {
      return Math.round(montant).toLocaleString("fr-FR") + "\u00a0FCFA";
    },

    normaliserTelephone: function (texte) {
      var chiffres = String(texte).replace(/[\s.\-]/g, "");
      var prefixes = ["+237", "00237", "237"];
      for (var i = 0; i < prefixes.length; i++) {
        if (chiffres.indexOf(prefixes[i]) === 0 && chiffres.length > 9) {
          return chiffres.slice(prefixes[i].length);
        }
      }
      return chiffres;
    },

    // Un numéro camerounais : 9 chiffres, le premier est un 6
    telephoneValide: function (texte) {
      return /^6\d{8}$/.test(Njangi.normaliserTelephone(texte));
    },

    // Appel fetch vers l'API ; renvoie {ok, statut, donnees}
    api: function (url, options) {
      options = options || {};
      var entetes = { "Accept": "application/json" };
      if (options.method && options.method !== "GET") {
        entetes["X-CSRF-Token"] = Njangi.jeton();
      }
      if (options.corps) {
        entetes["Content-Type"] = "application/json";
      }
      return fetch(url, {
        method: options.method || "GET",
        headers: entetes,
        credentials: "same-origin",
        body: options.corps ? JSON.stringify(options.corps) : undefined
      }).then(function (reponse) {
        return reponse.json().catch(function () { return {}; }).then(function (donnees) {
          return { ok: reponse.ok, statut: reponse.status, donnees: donnees };
        });
      });
    },

    // Affiche ou efface le message d'erreur d'un champ
    erreurChamp: function (champ, message) {
      var zone = document.getElementById("err-" + champ.id);
      if (zone) { zone.textContent = message || ""; }
      champ.classList.toggle("invalide", Boolean(message));
      if (message) { champ.setAttribute("aria-invalid", "true"); } else { champ.removeAttribute("aria-invalid"); }
    }
  };
  window.Njangi = Njangi;

  // Bascule clair et sombre : le choix est gardé dans le navigateur
  var bascule = document.querySelector(".bascule-theme");
  if (bascule) {
    var majBouton = function () {
      var sombre = document.documentElement.getAttribute("data-theme") === "dark";
      bascule.setAttribute("aria-label", sombre ? "Activer le mode clair" : "Activer le mode sombre");
    };
    majBouton();
    bascule.addEventListener("click", function () {
      var sombre = document.documentElement.getAttribute("data-theme") !== "dark";
      document.documentElement.setAttribute("data-theme", sombre ? "dark" : "light");
      try { localStorage.setItem("theme", sombre ? "dark" : "light"); } catch (e) { /* stockage indisponible */ }
      majBouton();
      document.dispatchEvent(new Event("themechange"));
    });
  }

  // Couleurs du thème courant, pour les graphiques dessinés dans un canvas
  Njangi.couleur = function (nom) {
    return getComputedStyle(document.documentElement).getPropertyValue(nom).trim();
  };

  // Menu burger
  var burger = document.querySelector(".burger");
  var menu = document.getElementById("menu-principal");
  if (burger && menu) {
    var basculer = function (ouvrir) {
      menu.classList.toggle("ouvert", ouvrir);
      burger.setAttribute("aria-expanded", ouvrir ? "true" : "false");
      burger.setAttribute("aria-label", ouvrir ? "Fermer le menu" : "Ouvrir le menu");
    };
    burger.addEventListener("click", function () {
      basculer(burger.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") { basculer(false); }
    });
    menu.addEventListener("click", function (e) {
      if (e.target.tagName === "A") { basculer(false); }
    });
  }

  // Messages flash : ils glissent, restent quelques secondes, puis disparaissent
  document.querySelectorAll(".flash").forEach(function (flash) {
    var retirer = function () {
      flash.classList.add("sort");
      setTimeout(function () { flash.remove(); }, reduit ? 0 : 500);
    };
    flash.querySelector(".flash-fermer").addEventListener("click", retirer);
    if (!flash.classList.contains("error")) { setTimeout(retirer, 7000); }
  });

  // Confirmation avant une action sensible (formulaire avec data-confirmer)
  document.querySelectorAll("form[data-confirmer]").forEach(function (formulaire) {
    formulaire.addEventListener("submit", function (e) {
      if (!window.confirm(formulaire.dataset.confirmer)) { e.preventDefault(); }
    });
  });

  // Bouton d'impression
  document.querySelectorAll("[data-imprimer]").forEach(function (bouton) {
    bouton.addEventListener("click", function () { window.print(); });
  });

  // Photos absentes : on garde le fond en dégradé et l'illustration
  document.querySelectorAll(".photo").forEach(function (cadre) {
    var image = cadre.querySelector(".photo-img");
    if (!image) { return; }
    var marquer = function () { cadre.classList.add("absente"); };
    if (image.complete && image.naturalWidth === 0) { marquer(); }
    image.addEventListener("error", marquer);
  });

  // Compteurs, apparitions et barres de progression au moment où ils deviennent visibles
  function animerCompteur(element) {
    var cible = Number(element.dataset.to) || 0;
    var suffixe = element.dataset.suf || "";
    if (reduit || cible === 0) {
      element.textContent = cible.toLocaleString("fr-FR") + suffixe;
      return;
    }
    var debut = performance.now();
    (function pas(maintenant) {
      var p = Math.min((maintenant - debut) / 1400, 1);
      var valeur = Math.round(cible * (1 - Math.pow(1 - p, 3)));
      element.textContent = valeur.toLocaleString("fr-FR") + suffixe;
      if (p < 1) { requestAnimationFrame(pas); }
    })(debut);
  }

  Njangi.compter = function (element, cible, suffixe) {
    element.dataset.to = String(cible);
    element.dataset.suf = suffixe || "";
    animerCompteur(element);
  };

  // Les cartes d'une grille « cascade » apparaissent l'une après l'autre
  document.querySelectorAll(".cascade").forEach(function (grille) {
    Array.prototype.forEach.call(grille.children, function (carte, i) {
      carte.style.animationDelay = (i * 90) + "ms";
    });
  });

  var observateur = new IntersectionObserver(function (entrees) {
    entrees.forEach(function (entree) {
      if (!entree.isIntersecting) { return; }
      var element = entree.target;
      observateur.unobserve(element);
      if (element.classList.contains("rv")) { element.classList.add("in"); }
      if (element.hasAttribute("data-to")) { animerCompteur(element); }
      if (element.classList.contains("anneau")) {
        var cercle = element.querySelector(".valeur");
        var part = Math.max(0, Math.min(100, Number(element.dataset.pct) || 0));
        requestAnimationFrame(function () { cercle.style.strokeDashoffset = String(326.73 * (1 - part / 100)); });
      }
      if (element.classList.contains("barre")) {
        var barre = element.querySelector("span");
        var pct = Math.max(0, Math.min(100, Number(element.dataset.pct) || 0));
        requestAnimationFrame(function () { barre.style.width = pct + "%"; });
      }
    });
  }, { threshold: 0.3 });
  document.querySelectorAll(".rv, [data-to], .barre, .anneau").forEach(function (element) {
    observateur.observe(element);
  });
})();
