# Domovra — Gestion de stock

![logo](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/icon.png)

> Mini gestionnaire de stock (frigo, congélateur, placards) intégré à Home Assistant via **Ingress**.

## ✨ Fonctions
- Emplacements / Produits / Lots  
- Ajout rapide depuis l’accueil (avec date de congélation & DLC)  
- Édition & suppression, **consommation partielle des lots**  
- Filtres par produit, emplacement, état (OK / Bientôt / Urgent)  
- **Recherche produit par code-barres** (Open Food Facts) avec **scanner live** (caméra) et fallback intégré  
- **Journal des actions** (consultable + purge)  
- Thème clair/sombre automatique + **menu latéral compact** (paramètres)  
- **Page Support** intégrée pour soutenir le projet via Ko-fi

## 🧩 Installation
1. **Paramètres → Modules complémentaires → Magasin → ⋮ → Dépôts**  
2. Ajoutez : `https://github.com/bryan1993-HA/domovra-addons`  
3. Recherchez **Domovra (Stock Manager)** → Installer → Démarrer → *Ouvrir l’interface*.

## ⚙️ Options
- `retention_days_warning` : seuil “Bientôt” (jours)  
- `retention_days_critical` : seuil “Urgent” (jours)

> La base SQLite est stockée dans `/data/domovra.sqlite3`.  
> (Les paramètres UI sont enregistrés dans `/data/settings.json` ; le log applicatif dans `/data/domovra.log`.)

## ❤️ Support
Domovra est un projet personnel développé sur mon temps libre, par plaisir de coder.

Si vous trouvez cet add-on utile et souhaitez me soutenir, vous pouvez m’offrir un café sur Ko-fi ☕

[![Support on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/domovra)

Ou directement via ce lien : [https://ko-fi.com/domovra](https://ko-fi.com/domovra)

Les dons sont entièrement facultatifs et n’ouvrent aucune contrepartie payante.

## 📣 Forum HACF
Retours, idées et suivi : https://forum.hacf.fr/t/domovra-gestion-de-stock-domestique-pour-home-assistant/66040

## 🖼️ Captures
![Accueil](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/images/EcranPrincipal.png)
