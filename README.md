# Ceciball ESP32 - Bases sonores automatiques

Ce projet propose une première version simple pour piloter des bases de Ceciball avec des ESP32.
Chaque base possède :

- une ESP32 avec Wi-Fi ;
- un buzzer actif ;
- un bouton ;
- un programme MicroPython.

Le principe est volontairement direct : une base bipe, le joueur appuie sur son bouton, la base s'arrête, puis elle demande à la base suivante de biper.

## Structure du projet

```text
ceciball/
├── base_1_server/
│   └── main.py        # Programme à envoyer sur la base 1
├── base_worker/
│   └── main.py        # Modèle à envoyer sur les bases 2, 3, 4...
├── main.py            # Note de sécurité pour ne pas flasher le mauvais fichier
└── README.md
```

Important : sur une ESP32 MicroPython, le fichier lancé automatiquement doit s'appeler `main.py`.
Il faut donc envoyer le `main.py` du bon dossier sur la bonne carte.

## Fonctionnement général

La base 1 crée son propre Wi-Fi :

- nom : `CECIBALL_BASE_1`
- mot de passe : `CECIBALL123`
- adresse de la base 1 : `192.168.4.1`

Les autres bases se connectent à ce Wi-Fi avec une adresse fixe :

- base 2 : `192.168.4.2`
- base 3 : `192.168.4.3`
- base 4 : `192.168.4.4`

Chaque base possède un petit serveur HTTP.
Quand une base doit activer la suivante, elle appelle simplement :

```text
http://ADRESSE_DE_LA_BASE_SUIVANTE/activate
```

Exemple :

```text
base 1 -> http://192.168.4.2/activate
base 2 -> http://192.168.4.3/activate
base 3 -> http://192.168.4.1/activate
```

Dans cet exemple, la base 3 boucle vers la base 1.

## Câblage conseillé

Les valeurs par défaut du code sont :

| Élément | GPIO ESP32 | Remarque |
|---|---:|---|
| Buzzer actif | GPIO25 | Le code met la broche à `1` pour faire sonner |
| Bouton | GPIO14 | Le bouton doit relier GPIO14 à GND quand on appuie |

Le bouton utilise `Pin.PULL_UP`.
Cela veut dire :

- bouton relâché : la broche lit `1` ;
- bouton appuyé : la broche lit `0`.

Si votre câblage est différent, modifiez les variables au début des fichiers `main.py`.

## Installer MicroPython sur l'ESP32

Une méthode classique consiste à utiliser `mpremote`.
Exemple d'installation sur ordinateur :

```bash
pip install mpremote
```

Ensuite, branchez l'ESP32 en USB.
La commande exacte dépend du port série de votre ordinateur.

Exemple Linux :

```bash
mpremote connect /dev/ttyUSB0 fs cp base_1_server/main.py :main.py
```

Exemple pour une base worker :

```bash
mpremote connect /dev/ttyUSB0 fs cp base_worker/main.py :main.py
```

Après l'envoi du fichier, redémarrez l'ESP32.

## Configurer la base 1

Ouvrez `base_1_server/main.py`.
Les variables importantes sont au début du fichier.

Pour une base 1 qui appelle la base 2, gardez :

```python
NEXT_BASE_NUMBER = 2
NEXT_BASE_URL = "http://192.168.4.2/activate"

KNOWN_BASES = (
    (2, "http://192.168.4.2"),
)
```

Si vous ajoutez une base 3, mettez aussi la base 3 dans `KNOWN_BASES` :

```python
KNOWN_BASES = (
    (2, "http://192.168.4.2"),
    (3, "http://192.168.4.3"),
)
```

`KNOWN_BASES` sert surtout au bouton web `Stop total`.

## Configurer une base 2, 3, 4...

Ouvrez `base_worker/main.py`.
Pour une base 2 qui appelle une base 3 :

```python
BASE_NUMBER = 2
STATIC_IP = "192.168.4.2"
NEXT_BASE_NUMBER = 3
NEXT_BASE_URL = "http://192.168.4.3/activate"
```

Pour une base 3 qui boucle vers la base 1 :

```python
BASE_NUMBER = 3
STATIC_IP = "192.168.4.3"
NEXT_BASE_NUMBER = 1
NEXT_BASE_URL = "http://192.168.4.1/activate"
```

Le reste peut rester identique.

## Interface web de la base 1

Quand la base 1 est allumée, connectez un téléphone ou un ordinateur au Wi-Fi :

```text
CECIBALL_BASE_1
```

Puis ouvrez :

```text
http://192.168.4.1/
```

La page permet de :

- lancer la chaîne depuis la base 1 ;
- arrêter toutes les bases connues ;
- relancer depuis le début ;
- voir la base actuellement active.

La page se recharge automatiquement toutes les 3 secondes.

## Endpoints utiles

Base 1 :

| URL | Action |
|---|---|
| `/` | Page web de contrôle |
| `/start` | Lance la chaîne depuis la base 1 |
| `/activate` | Active la base 1 |
| `/stop` | Arrête seulement la base 1 |
| `/stop_all` | Arrête la base 1 et toutes les bases connues |
| `/reset` | Arrête tout puis relance depuis la base 1 |
| `/state` | Affiche l'état brut |
| `/report_active?base=N` | Indique que la base N est active |

Bases worker :

| URL | Action |
|---|---|
| `/` | Diagnostic simple |
| `/activate` | Active cette base |
| `/stop` | Arrête cette base |
| `/state` | Affiche l'état local |

## Test conseillé

Commencez toujours petit.

1. Flashez seulement la base 1.
2. Allumez la base 1.
3. Connectez un téléphone au Wi-Fi `CECIBALL_BASE_1`.
4. Ouvrez `http://192.168.4.1/`.
5. Cliquez sur `Lancer`.
6. Vérifiez que la base 1 bipe.
7. Appuyez sur le bouton de la base 1.

À ce stade, si la base 2 n'existe pas encore, la base 1 va essayer de l'appeler puis se réactiver.
C'est volontaire : cela évite un silence total si la base suivante est absente.

Ensuite :

1. Flashez une base 2 avec `base_worker/main.py`.
2. Vérifiez que `BASE_NUMBER = 2` et `STATIC_IP = "192.168.4.2"`.
3. Si vous n'avez que deux bases, faites boucler la base 2 vers la base 1 :

```python
NEXT_BASE_NUMBER = 1
NEXT_BASE_URL = "http://192.168.4.1/activate"
```

4. Lancez depuis l'interface web.
5. Appuyez sur le bouton de la base 1 : la base 2 doit biper.
6. Appuyez sur le bouton de la base 2 : la base 1 doit rebiper.

## Ajouter une nouvelle base

Pour ajouter une base 4 :

1. Copiez `base_worker/main.py` sur la nouvelle ESP32.
2. Mettez :

```python
BASE_NUMBER = 4
STATIC_IP = "192.168.4.4"
NEXT_BASE_NUMBER = 1
NEXT_BASE_URL = "http://192.168.4.1/activate"
```

3. Sur la base précédente, par exemple la base 3, mettez :

```python
NEXT_BASE_NUMBER = 4
NEXT_BASE_URL = "http://192.168.4.4/activate"
```

4. Sur la base 1, ajoutez la base 4 dans `KNOWN_BASES` pour le stop total :

```python
KNOWN_BASES = (
    (2, "http://192.168.4.2"),
    (3, "http://192.168.4.3"),
    (4, "http://192.168.4.4"),
)
```

## Points importants pour la fiabilité

- Allumez d'abord la base 1, car elle crée le Wi-Fi.
- Allumez ensuite les autres bases.
- Vérifiez que chaque base a une adresse IP différente.
- Gardez le même `WIFI_SSID` et `WIFI_PASSWORD` partout.
- Si une base suivante ne répond pas, la base actuelle se réactive pour éviter que le terrain reste silencieux.
- Le bouton possède un anti-rebond logiciel avec `DEBOUNCE_MS`.

## Limites de cette première version

Cette version est simple et lisible.
Elle ne fait pas encore :

- de chiffrement avancé entre les bases ;
- de détection automatique de toutes les bases ;
- de journal complet de partie ;
- de serveur web graphique avancé.

Ces points peuvent être ajoutés plus tard sans changer le principe de base.
