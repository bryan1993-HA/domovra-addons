# 📖 Domovra — Documentation Utilisateur

Domovra est un mini gestionnaire de stock pour Home Assistant (frigo, congélateur, placards…), intégré via **Ingress** et pensé pour un usage rapide au quotidien.

---

## 🚀 Utilisation rapide

1. **Ajout d’un lot**  
   - Depuis l’accueil : saisissez le produit, l’emplacement, la quantité et la DLC.  
   - Vous pouvez aussi renseigner la date de congélation (facultatif).

2. **Gérer vos stocks**  
   - Accédez aux onglets **Produits**, **Emplacements**, **Lots** pour créer, modifier ou supprimer des éléments.
   - Utilisez les filtres par produit, emplacement ou état (OK / Bientôt / Urgent).

3. **Scanner un code-barres**  
   - Cliquez sur l’icône scanner 📷 depuis un formulaire produit.
   - Domovra détecte automatiquement le code-barres avec la caméra (ou via saisie manuelle).
   - Les informations (nom, marque, unité) peuvent être remplies depuis **Open Food Facts**.

4. **Consommer un lot**  
   - Bouton “Consommer” pour enlever une partie ou la totalité d’un lot.

5. **Journal des actions**  
   - Accessible depuis le menu → *Journal*.  
   - Historique des ajouts, consommations, suppressions.  
   - Bouton pour vider le journal.

6. **Personnalisation de l’affichage**  
   - Dans les paramètres : thème clair/sombre/auto, sidebar compacte, affichage tableau, seuils de conservation.

---

## 📦 Options du module complémentaire
- `retention_days_warning` : seuil “Bientôt” (jours)
- `retention_days_critical` : seuil “Urgent” (jours)

---

## 📂 Données stockées
- Base SQLite : `/data/domovra.sqlite3`
- Paramètres UI : `/data/settings.json`
- Journal : `/data/domovra.log`

---

## 🖼️ Captures
![Accueil](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons/main/domovra/images/EcranPrincipal.png)
