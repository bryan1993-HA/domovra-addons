# Domovra — Gestion de stock

![logo](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/images/logo.png)

> Mini gestionnaire de stock (frigo, congélateur, placards) intégré à Home Assistant via **Ingress**.

## ✨ Fonctions
- Emplacements / Produits / Lots
- Ajout rapide depuis l’accueil
- Édition & suppression
- Filtres par produit, emplacement, état (OK / Bientôt / Urgent)

## 🧩 Installation
1. **Paramètres → Modules complémentaires → Magasin → ⋮ → Dépôts**  
2. Ajoutez : `https://github.com/<ton-user>/<ton-repo>`  
3. Recherchez **Domovra (Stock Manager)** → Installer → Démarrer → *Ouvrir l’interface*.

## ⚙️ Options
- `retention_days_warning` : seuil “Bientôt” (jours)
- `retention_days_critical` : seuil “Urgent” (jours)

> La base SQLite est stockée dans `/data/domovra.sqlite3`.

## 🖼️ Captures
![Accueil](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/images/EcranPrincipal.png)