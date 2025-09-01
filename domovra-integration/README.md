# Domovra — Intégration Home Assistant

![Domovra Logo](https://raw.githubusercontent.com/bryan1993-HA/domovra-addons-beta/main/domovra/icon.png)

## 📌 Description
Cette intégration Home Assistant permet de **faire remonter les données de l’add-on Domovra** (gestion de stock domestique) sous forme d’entités.  
Vous pourrez ainsi suivre dans Home Assistant :  
- le nombre total de produits  
- le nombre de lots  
- le nombre de lots **bientôt périmés**  
- le nombre de lots **urgents**  

## 🚀 Installation via HACS
1. Ouvrez **HACS → Intégrations → Dépôts personnalisés**.  
2. Ajoutez ce dépôt :  https://github.com/bryan1993-HA/domovra-addons-beta

Type : **Intégration**  
3. Recherchez ensuite **Domovra** dans HACS et installez l’intégration.  
4. Redémarrez Home Assistant.  

## ⚙️ Configuration
1. Allez dans **Paramètres → Appareils & services → Ajouter une intégration**.  
2. Recherchez **Domovra**.  
3. Saisissez l’URL de l’add-on (par ex. `http://127.0.0.1:8123` ou l’adresse IP locale de votre Home Assistant + port de l’add-on).  
4. Validez.  

Les entités suivantes apparaîtront :  
- `sensor.domovra_produits`  
- `sensor.domovra_lots`  
- `sensor.domovra_bientot`  
- `sensor.domovra_urgents`  

## 🛠️ Dépendances
- Add-on **Domovra** installé et accessible sur le réseau local.  
- Home Assistant Core ≥ 2023.9  

## 📖 Notes
- Le scan est fait toutes les 30 secondes par défaut (modifiable dans les options de l’intégration).  
- Vous pouvez enrichir les entités en exposant plus de données depuis l’API de l’add-on (`/api/ha/summary`).  

---

✨ Développé par [Bryan Thoury](https://github.com/bryan1993-HA)  
