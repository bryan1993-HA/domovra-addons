# Domovra — Gestion de stock

![logo](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/icon.png)

> Mini gestionnaire de stock (frigo, congélateur, placards) intégré à Home Assistant via **Ingress**.

## ✨ Fonctions
- Emplacements / Produits / Lots  
- Ajout rapide depuis l’accueil (avec date de congélation & DLC)  
- Édition & suppression, **consommation partielle des lots**  
- Filtres par produit, emplacement, état (OK / Bientôt / Urgent)  
- **Recherche produit par code‑barres** (Open Food Facts) avec **scanner live** (caméra) et fallback intégré
- **Journal des actions** (consultable + purge)  
- Thème clair/sombre automatique + **menu latéral compact** (paramètres)

## 🧩 Installation
1. **Paramètres → Modules complémentaires → Magasin → ⋮ → Dépôts**  
2. Ajoutez : `https://github.com/bryan1993-HA/domovra-addons`  
3. Recherchez **Domovra (Stock Manager)** → Installer → Démarrer → *Ouvrir l’interface*.

## ⚙️ Options
- `retention_days_warning` : seuil “Bientôt” (jours)  
- `retention_days_critical` : seuil “Urgent” (jours)

> La base SQLite est stockée dans `/data/domovra.sqlite3`.  
> (Les paramètres UI sont enregistrés dans `/data/settings.json` ; le log applicatif dans `/data/domovra.log`.)

## 📣 Forum HACF
Retours, idées et suivi : https://forum.hacf.fr/t/domovra-gestion-de-stock-domestique-pour-home-assistant/66040

## 🖼️ Captures
![Accueil](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/images/EcranPrincipal.png)
