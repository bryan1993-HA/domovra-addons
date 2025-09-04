# Changelog

## [1.4.2] - 2025-09-04 - 03:24
### Added
- Page `_about.html` regroupant plusieurs informations et liens :
  - **À propos / Infos système**
  - Add-on (nom, version, canal, slug)
  - Liens directs : Projet GitHub, Documentation, Issues, Changelog
  - Description de la version en cours
  - **Système** : Python, FastAPI, Jinja2, SQLite
  - **Données** : base SQLite, paramètres, journal (avec tailles affichées)
  - **Comportement & UI** : thème, sidebar, durée des toasts, seuils Bientôt/Urgent

### Changed
- `Settings.html` : menu repensé (plus esthétique et responsive) + ajout de l’onglet **À propos**
- `settings.py` : ajout des fonctions pour récupérer et afficher les informations dans la page About
- `run.sh` : ajout de la fonction permettant la lecture des informations système (About)
- `Dockerfile` : ajout de la copie de `config.json` dans l’image Docker pour intégration complète

---

## [1.4.1] - 2025-09-03 - 02:59
### Changed
- Version : 1.4.0 → 1.4.1
- `panel_title` : "Domovra (Beta)" → "Domovra"
- `panel_icon` : "mdi:test-tube" → "mdi:package-variant-closed"

### Documentation
- Ajout d'une section **Conventions de commits (simplifiées)** dans le README

---

## [1.3.39-beta.1] - 2025-09-02 - 04:36
### Added
- Fichier CHANGELOG initial
