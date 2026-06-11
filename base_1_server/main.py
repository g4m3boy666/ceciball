"""
Base 1 Ceciball - ESP32 MicroPython.

Cette carte est la base principale :
- elle cree le Wi-Fi du terrain ;
- elle affiche une petite page web de controle ;
- elle bipe quand la chaine arrive sur la base 1 ;
- elle appelle la base suivante quand le bouton est appuye.
"""

# Importe le module Wi-Fi de MicroPython.
import network

# Importe le module socket pour faire un petit serveur HTTP.
import socket

# Importe le module temps de MicroPython.
import utime

# Importe Pin pour piloter le buzzer et lire le bouton.
from machine import Pin


# ---------------------------------------------------------------------------
# CONFIGURATION FACILE A MODIFIER
# ---------------------------------------------------------------------------

# Numero de cette base.
BASE_NUMBER = 1

# Nom du Wi-Fi cree par la base 1.
WIFI_SSID = "CECIBALL_BASE_1"

# Mot de passe du Wi-Fi cree par la base 1.
WIFI_PASSWORD = "CECIBALL123"

# Adresse IP fixe de la base 1 en mode point d'acces.
BASE_1_IP = "192.168.4.1"

# Masque reseau classique pour un petit reseau local.
NETMASK = "255.255.255.0"

# Port HTTP du serveur web.
SERVER_PORT = 80

# GPIO du buzzer actif.
BUZZER_PIN = 4

# GPIO du bouton.
BUTTON_PIN = 15

# Valeur lue quand le bouton est appuye, avec un cablage bouton -> GND.
BUTTON_PRESSED_VALUE = 0

# Duree pendant laquelle le buzzer reste allume.
BEEP_ON_MS = 180

# Duree pendant laquelle le buzzer reste eteint entre deux bips.
BEEP_OFF_MS = 180

# Anti-rebond du bouton : ignore les micro-coupures mecaniques.
DEBOUNCE_MS = 80

# Numero de la base appelee apres la base 1.
NEXT_BASE_NUMBER = 2

# URL appelee quand le bouton de la base 1 est appuye.
NEXT_BASE_URL = "http://192.168.4.2/activate"

# Liste des autres bases connues pour pouvoir tout arreter.
KNOWN_BASES = (
    (2, "http://192.168.4.2"),
)

# Nombre d'essais pour appeler une autre base.
HTTP_RETRY_COUNT = 3

# Pause entre deux essais HTTP.
HTTP_RETRY_PAUSE_MS = 250

# Temps maximum pour une requete HTTP sortante.
HTTP_TIMEOUT_SECONDS = 2


# ---------------------------------------------------------------------------
# MATERIEL
# ---------------------------------------------------------------------------

# Cree la sortie du buzzer.
buzzer = Pin(BUZZER_PIN, Pin.OUT)

# Eteint le buzzer au demarrage.
buzzer.value(0)

# Cree l'entree du bouton avec resistance interne de tirage vers le haut.
button = Pin(BUTTON_PIN, Pin.IN, Pin.PULL_UP)


# ---------------------------------------------------------------------------
# ETAT DU PROGRAMME
# ---------------------------------------------------------------------------

# Indique si la chaine Ceciball est lancee.
system_running = False

# Indique si la base 1 doit biper maintenant.
active = False

# Numero de la base actuellement active selon la base 1.
current_base = 0

# Message court affiche dans l'interface.
state_message = "Systeme pret"

# Etat actuel du buzzer pendant le clignotement sonore.
buzzer_is_on = False

# Dernier moment ou le buzzer a change d'etat.
last_beep_change_ms = utime.ticks_ms()

# Derniere valeur brute lue sur le bouton.
last_button_raw_value = button.value()

# Derniere valeur stable validee apres anti-rebond.
last_button_stable_value = last_button_raw_value

# Moment du dernier changement brut du bouton.
last_button_change_ms = utime.ticks_ms()


# ---------------------------------------------------------------------------
# OUTILS RESEAU
# ---------------------------------------------------------------------------

def start_wifi_access_point():
    """Demarre le Wi-Fi cree par la base 1."""
    # Recupere l'interface point d'acces de l'ESP32.
    access_point = network.WLAN(network.AP_IF)

    # Active l'interface point d'acces.
    access_point.active(True)

    # Configure l'adresse IP du point d'acces.
    access_point.ifconfig((BASE_1_IP, NETMASK, BASE_1_IP, BASE_1_IP))

    # Configure le nom et le mot de passe du Wi-Fi.
    access_point.config(
        ssid=WIFI_SSID,
        password=WIFI_PASSWORD,
        authmode=network.AUTH_WPA_WPA2_PSK,
    )

    # Attend que le point d'acces soit pret.
    while not access_point.active():
        # Petite pause pour ne pas bloquer le processeur inutilement.
        utime.sleep_ms(100)

    # Affiche l'adresse IP dans la console serie.
    print("Wi-Fi cree :", WIFI_SSID)

    # Affiche la configuration reseau dans la console serie.
    print("Adresse IP :", access_point.ifconfig()[0])

    # Renvoie l'interface pour garder une reference si besoin.
    return access_point


def parse_http_url(url):
    """Decoupe une URL simple du type http://ip:port/chemin."""
    # Retire le prefixe http:// si present.
    if url.startswith("http://"):
        url = url[7:]

    # Separe la partie hote et la partie chemin.
    slash_index = url.find("/")

    # Si aucun chemin n'est donne, utilise /.
    if slash_index == -1:
        host_port = url
        path = "/"
    else:
        host_port = url[:slash_index]
        path = url[slash_index:]

    # Separe l'adresse IP et le port si un port est donne.
    if ":" in host_port:
        host, port_text = host_port.split(":", 1)
        port = int(port_text)
    else:
        host = host_port
        port = 80

    # Renvoie les morceaux utiles a socket.
    return host, port, path


def http_get_once(url):
    """Envoie une seule requete HTTP GET et renvoie True si elle reussit."""
    # Prepare une variable pour fermer la socket meme en cas d'erreur.
    client = None

    try:
        # Decoupe l'URL en hote, port et chemin.
        host, port, path = parse_http_url(url)

        # Cherche l'adresse reseau de la cible.
        address = socket.getaddrinfo(host, port)[0][-1]

        # Cree une socket TCP cliente.
        client = socket.socket()

        # Evite de rester bloque trop longtemps si une base ne repond pas.
        client.settimeout(HTTP_TIMEOUT_SECONDS)

        # Ouvre la connexion TCP.
        client.connect(address)

        # Construit une requete HTTP minimale.
        request = "GET {} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n\r\n".format(path, host)

        # Envoie la requete a la base cible.
        client.send(request.encode("utf-8"))

        # Lit le debut de la reponse HTTP.
        response = client.recv(128)

        # Recupere la premiere ligne de la reponse.
        first_line = response.split(b"\r\n", 1)[0]

        # La requete est consideree reussie si le code HTTP contient 200.
        return b"200" in first_line

    except Exception as error:
        # Affiche l'erreur dans la console serie pour le diagnostic.
        print("Erreur HTTP vers", url, ":", error)

        # Signale l'echec a l'appelant.
        return False

    finally:
        # Ferme la socket si elle a ete ouverte.
        if client:
            client.close()


def http_get_with_retries(url):
    """Essaie plusieurs fois d'appeler une autre base."""
    # Compte les essais de 1 a HTTP_RETRY_COUNT.
    for attempt in range(1, HTTP_RETRY_COUNT + 1):
        # Tente un appel HTTP.
        if http_get_once(url):
            # Renvoie True des que la base cible repond correctement.
            return True

        # Affiche l'essai rate dans la console serie.
        print("Essai", attempt, "rate vers", url)

        # Attend un peu avant de recommencer.
        utime.sleep_ms(HTTP_RETRY_PAUSE_MS)

    # Tous les essais ont echoue.
    return False


def create_server_socket():
    """Cree la socket du serveur HTTP de la base 1."""
    # Cree une socket TCP.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Essaie d'autoriser la reutilisation rapide du port.
    try:
        # Cette option evite certains blocages apres un redemarrage.
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        # Certaines versions MicroPython peuvent ne pas avoir cette option.
        pass

    # Lie le serveur a toutes les interfaces reseau sur le port choisi.
    server.bind(("0.0.0.0", SERVER_PORT))

    # Autorise quelques connexions en attente.
    server.listen(5)

    # Rend accept() non bloquant pour continuer a gerer le buzzer.
    server.setblocking(False)

    # Affiche l'URL de controle dans la console serie.
    print("Serveur pret : http://{}/".format(BASE_1_IP))

    # Renvoie la socket serveur.
    return server


# ---------------------------------------------------------------------------
# LOGIQUE BUZZER ET BOUTON
# ---------------------------------------------------------------------------

def buzzer_off():
    """Eteint toujours le buzzer."""
    # Indique que le buzzer n'est plus allume.
    global buzzer_is_on

    # Ecrit 0 sur le GPIO du buzzer.
    buzzer.value(0)

    # Memorise l'etat eteint.
    buzzer_is_on = False


def buzzer_on():
    """Allume le buzzer."""
    # Indique que le buzzer est allume.
    global buzzer_is_on

    # Ecrit 1 sur le GPIO du buzzer actif.
    buzzer.value(1)

    # Memorise l'etat allume.
    buzzer_is_on = True


def update_buzzer():
    """Fait biper la base si elle est active."""
    # Utilise les variables globales du clignotement sonore.
    global last_beep_change_ms

    # Recupere l'heure actuelle en millisecondes.
    now = utime.ticks_ms()

    # Si la base n'est pas active, le buzzer doit rester eteint.
    if not active:
        # Force le buzzer a l'arret.
        buzzer_off()

        # Sort de la fonction.
        return

    # Si le buzzer est allume depuis assez longtemps, on l'eteint.
    if buzzer_is_on and utime.ticks_diff(now, last_beep_change_ms) >= BEEP_ON_MS:
        # Eteint le buzzer.
        buzzer_off()

        # Memorise le moment du changement.
        last_beep_change_ms = now

    # Si le buzzer est eteint depuis assez longtemps, on l'allume.
    elif (not buzzer_is_on) and utime.ticks_diff(now, last_beep_change_ms) >= BEEP_OFF_MS:
        # Allume le buzzer.
        buzzer_on()

        # Memorise le moment du changement.
        last_beep_change_ms = now


def button_pressed_once():
    """Renvoie True une seule fois par appui stable du bouton."""
    # Utilise les variables globales de l'anti-rebond.
    global last_button_raw_value
    global last_button_stable_value
    global last_button_change_ms

    # Lit la valeur actuelle du bouton.
    raw_value = button.value()

    # Recupere l'heure actuelle.
    now = utime.ticks_ms()

    # Si la valeur brute change, on recommence le chronometre anti-rebond.
    if raw_value != last_button_raw_value:
        # Memorise la nouvelle valeur brute.
        last_button_raw_value = raw_value

        # Memorise le moment du changement.
        last_button_change_ms = now

    # Si le changement est trop recent, on ignore encore le bouton.
    if utime.ticks_diff(now, last_button_change_ms) < DEBOUNCE_MS:
        # Aucun appui valide pour le moment.
        return False

    # Si la valeur stable change apres le delai, elle est acceptee.
    if raw_value != last_button_stable_value:
        # Memorise la nouvelle valeur stable.
        last_button_stable_value = raw_value

        # Detecte uniquement le passage vers "bouton appuye".
        if last_button_stable_value == BUTTON_PRESSED_VALUE:
            # Signale un nouvel appui valide.
            return True

    # Aucun nouvel appui valide.
    return False


# ---------------------------------------------------------------------------
# LOGIQUE CECIBALL
# ---------------------------------------------------------------------------

def activate_local_base(message):
    """Active la base 1 et lance ses bips."""
    # Modifie l'etat global du systeme.
    global system_running
    global active
    global current_base
    global state_message
    global last_beep_change_ms

    # La chaine est maintenant consideree lancee.
    system_running = True

    # La base 1 devient active.
    active = True

    # La base courante est la base 1.
    current_base = BASE_NUMBER

    # Met a jour le message affiche.
    state_message = message

    # Redemarre le rythme du buzzer depuis maintenant.
    last_beep_change_ms = utime.ticks_ms()

    # Allume tout de suite pour que le signal soit immediat.
    buzzer_on()


def stop_local_base(message):
    """Arrete seulement la base 1."""
    # Modifie l'etat global de la base.
    global active
    global state_message

    # La base 1 ne doit plus biper.
    active = False

    # Met a jour le message affiche.
    state_message = message

    # Eteint le buzzer.
    buzzer_off()


def stop_all_bases():
    """Arrete la base 1 et toutes les bases connues."""
    # Modifie l'etat global du systeme.
    global system_running
    global current_base
    global state_message

    # Le systeme complet est arrete.
    system_running = False

    # Aucune base n'est active dans l'affichage.
    current_base = 0

    # Arrete la base 1 localement.
    stop_local_base("Arret general demande")

    # Demande a chaque base connue de s'arreter.
    for base_number, base_url in KNOWN_BASES:
        # Affiche la base arretee dans la console.
        print("Arret demande a la base", base_number)

        # Appelle /stop sur la base distante.
        http_get_with_retries(base_url + "/stop")

    # Met a jour le message final.
    state_message = "Tout est arrete"


def pass_to_next_base():
    """Arrete la base 1 puis active la base suivante."""
    # Modifie l'etat visible du serveur.
    global active
    global current_base
    global state_message

    # Si la base 1 n'est pas active, le bouton ne fait rien.
    if not active:
        # Sort sans action.
        return

    # Arrete le buzzer de la base 1.
    stop_local_base("Passage vers la base {}".format(NEXT_BASE_NUMBER))

    # L'affichage montre la base appelee.
    current_base = NEXT_BASE_NUMBER

    # Appelle la base suivante.
    if http_get_with_retries(NEXT_BASE_URL):
        # Message de succes.
        state_message = "Base {} activee".format(NEXT_BASE_NUMBER)
    else:
        # En cas d'echec, on relance la base 1 pour eviter un silence total.
        activate_local_base("Erreur: base {} injoignable".format(NEXT_BASE_NUMBER))


# ---------------------------------------------------------------------------
# REPONSES HTTP
# ---------------------------------------------------------------------------

def json_bool(value):
    """Transforme True/False en texte JSON."""
    # Renvoie la valeur JSON correcte.
    return "true" if value else "false"


def state_as_json():
    """Construit l'etat du systeme sous forme de JSON simple."""
    # Protege le message contre les guillemets.
    safe_message = state_message.replace('"', "'")

    # Construit le texte JSON sans importer de module supplementaire.
    return (
        '{{"base":{},"active":{},"system_running":{},'
        '"current_base":{},"message":"{}"}}'
    ).format(
        BASE_NUMBER,
        json_bool(active),
        json_bool(system_running),
        current_base,
        safe_message,
    )


def html_page():
    """Construit la page web de controle."""
    # Choisit un texte simple pour l'etat de la base 1.
    active_text = "OUI" if active else "NON"

    # Choisit un texte simple pour l'etat global.
    running_text = "OUI" if system_running else "NON"

    # Retourne une page HTML volontairement simple.
    return """<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="3">
  <title>Ceciball - Base 1</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f7f7f7; color: #111; }}
    main {{ max-width: 720px; margin: auto; }}
    a {{ display: inline-block; padding: 14px 18px; margin: 6px 4px; background: #1358d8; color: white; text-decoration: none; border-radius: 6px; }}
    a.stop {{ background: #b00020; }}
    a.reset {{ background: #555; }}
    .box {{ background: white; border: 1px solid #ddd; border-radius: 6px; padding: 16px; margin: 12px 0; }}
    strong {{ display: inline-block; min-width: 180px; }}
  </style>
</head>
<body>
  <main>
    <h1>Ceciball - Base 1</h1>
    <div class="box">
      <p><strong>Systeme lance :</strong> {running}</p>
      <p><strong>Base 1 active :</strong> {active}</p>
      <p><strong>Base actuelle :</strong> {current}</p>
      <p><strong>Message :</strong> {message}</p>
    </div>
    <a href="/start">Lancer</a>
    <a class="stop" href="/stop_all">Stop total</a>
    <a class="reset" href="/reset">Relancer du debut</a>
    <a href="/state">Etat brut</a>
  </main>
</body>
</html>""".format(
        running=running_text,
        active=active_text,
        current=current_base,
        message=state_message,
    )


def send_response(client, status, content_type, body):
    """Envoie une reponse HTTP complete au navigateur."""
    # Transforme le texte en octets.
    body_bytes = body.encode("utf-8")

    # Construit l'en-tete HTTP.
    header = (
        "HTTP/1.0 {}\r\n"
        "Content-Type: {}; charset=utf-8\r\n"
        "Content-Length: {}\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).format(status, content_type, len(body_bytes))

    # Envoie l'en-tete.
    client.send(header.encode("utf-8"))

    # Envoie le corps de la reponse.
    client.send(body_bytes)


def split_path_and_query(full_path):
    """Separe /chemin?param=valeur en chemin et requete."""
    # Cherche le separateur de requete.
    question_index = full_path.find("?")

    # Si aucun ? n'existe, il n'y a pas de requete.
    if question_index == -1:
        # Renvoie le chemin et une requete vide.
        return full_path, ""

    # Renvoie le chemin avant ? et la requete apres ?.
    return full_path[:question_index], full_path[question_index + 1:]


def query_value(query, key):
    """Lit une valeur simple dans une query string."""
    # Parcourt chaque morceau separe par &.
    for item in query.split("&"):
        # Ignore les morceaux sans signe egal.
        if "=" not in item:
            continue

        # Separe le nom et la valeur.
        name, value = item.split("=", 1)

        # Si le nom correspond a la cle demandee, renvoie la valeur.
        if name == key:
            return value

    # La cle n'a pas ete trouvee.
    return None


def handle_route(path, query):
    """Execute l'action HTTP demandee et renvoie la reponse."""
    # Donne acces aux variables globales modifiees par certaines routes.
    global current_base
    global state_message
    global system_running

    # Page d'accueil.
    if path == "/":
        return "200 OK", "text/html", html_page()

    # Lance la chaine depuis la base 1.
    if path == "/start":
        activate_local_base("Depart depuis la base 1")
        return "200 OK", "text/html", html_page()

    # Active la base 1, utile quand la derniere base boucle vers le debut.
    if path == "/activate":
        activate_local_base("Base 1 activee")
        return "200 OK", "text/plain", "base 1 activee\n"

    # Arrete seulement la base 1.
    if path == "/stop":
        stop_local_base("Base 1 arretee")
        return "200 OK", "text/plain", "base 1 arretee\n"

    # Arrete toutes les bases connues.
    if path == "/stop_all":
        stop_all_bases()
        return "200 OK", "text/html", html_page()

    # Arrete tout puis repart de la base 1.
    if path == "/reset":
        stop_all_bases()
        utime.sleep_ms(300)
        activate_local_base("Relance depuis la base 1")
        return "200 OK", "text/html", html_page()

    # Renvoie l'etat brut pour debug ou autre outil.
    if path == "/state":
        return "200 OK", "application/json", state_as_json() + "\n"

    # Une autre base signale qu'elle est devenue active.
    if path == "/report_active":
        base_text = query_value(query, "base")
        if base_text is not None:
            try:
                current_base = int(base_text)
            except ValueError:
                return "400 Bad Request", "text/plain", "numero de base invalide\n"
            system_running = True
            state_message = "Base {} signalee active".format(current_base)
            return "200 OK", "text/plain", "rapport recu\n"
        return "400 Bad Request", "text/plain", "parametre base manquant\n"

    # Chemin inconnu.
    return "404 Not Found", "text/plain", "page inconnue\n"


def handle_http_client(client):
    """Lit une requete HTTP et envoie la bonne reponse."""
    try:
        # Evite qu'un navigateur bloque trop longtemps la boucle principale.
        client.settimeout(1)

        # Lit la requete HTTP.
        request = client.recv(1024).decode("utf-8")

        # Ignore les requetes vides.
        if not request:
            return

        # Recupere la premiere ligne : GET /chemin HTTP/1.1.
        first_line = request.split("\r\n", 1)[0]

        # Decoupe la premiere ligne.
        parts = first_line.split(" ")

        # Verifie que la requete ressemble bien a une requete HTTP.
        if len(parts) < 2:
            send_response(client, "400 Bad Request", "text/plain", "requete invalide\n")
            return

        # Recupere le chemin demande.
        full_path = parts[1]

        # Separe le chemin et les parametres.
        path, query = split_path_and_query(full_path)

        # Execute la route.
        status, content_type, body = handle_route(path, query)

        # Envoie la reponse au client.
        send_response(client, status, content_type, body)

    except Exception as error:
        # Affiche l'erreur dans la console serie.
        print("Erreur client HTTP :", error)

    finally:
        # Ferme toujours la connexion client.
        client.close()


def poll_http_server(server):
    """Accepte une connexion HTTP si un client attend."""
    try:
        # Tente d'accepter une connexion.
        client, address = server.accept()

        # Affiche le client dans la console serie.
        print("Client HTTP :", address)

        # Traite la requete.
        handle_http_client(client)

    except OSError:
        # En non bloquant, OSError veut souvent dire "aucun client".
        pass


# ---------------------------------------------------------------------------
# PROGRAMME PRINCIPAL
# ---------------------------------------------------------------------------

def main():
    """Demarre le Wi-Fi, le serveur, puis la boucle principale."""
    # Demarre le point d'acces Wi-Fi.
    start_wifi_access_point()

    # Cree le serveur HTTP.
    server = create_server_socket()

    # Boucle principale infinie.
    while True:
        # Fait avancer le bip si la base est active.
        update_buzzer()

        # Traite un client HTTP s'il y en a un.
        poll_http_server(server)

        # Si le bouton est appuye pendant que la base 1 est active, passe a la suite.
        if active and button_pressed_once():
            pass_to_next_base()

        # Petite pause pour garder une boucle stable.
        utime.sleep_ms(10)


# Lance le programme quand MicroPython execute main.py.
main()
