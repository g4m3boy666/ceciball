"""
Base worker Ceciball - ESP32 MicroPython.

Ce fichier sert pour les bases 2, 3, 4, etc.
Pour creer une nouvelle base, il suffit surtout de modifier les variables
de configuration au debut du fichier.
"""

# Importe le module Wi-Fi de MicroPython.
import network

# Importe le module socket pour recevoir et envoyer des ordres HTTP.
import socket

# Importe le module temps de MicroPython.
import utime

# Importe Pin pour piloter le buzzer et lire le bouton.
from machine import Pin


# ---------------------------------------------------------------------------
# CONFIGURATION FACILE A MODIFIER
# ---------------------------------------------------------------------------

# Numero de cette base : mettez 2 pour la base 2, 3 pour la base 3, etc.
BASE_NUMBER = 2

# Adresse IP fixe de cette base.
STATIC_IP = "192.168.4.2"

# Adresse IP de la base 1, qui cree le Wi-Fi et affiche l'etat.
BASE_1_IP = "192.168.4.1"

# Masque reseau classique.
NETMASK = "255.255.255.0"

# Adresse de passerelle : ici la base 1.
GATEWAY_IP = BASE_1_IP

# Adresse DNS : pas tres utile ici, mais MicroPython demande une valeur.
DNS_IP = BASE_1_IP

# Nom du Wi-Fi cree par la base 1.
WIFI_SSID = "CECIBALL_BASE_1"

# Mot de passe du Wi-Fi cree par la base 1.
WIFI_PASSWORD = "CECIBALL123"

# Port HTTP ecoute par cette base.
SERVER_PORT = 80

# GPIO du buzzer actif.
BUZZER_PIN = 25

# GPIO du bouton.
BUTTON_PIN = 14

# Valeur lue quand le bouton est appuye, avec un cablage bouton -> GND.
BUTTON_PRESSED_VALUE = 0

# Duree pendant laquelle le buzzer reste allume.
BEEP_ON_MS = 180

# Duree pendant laquelle le buzzer reste eteint entre deux bips.
BEEP_OFF_MS = 180

# Anti-rebond du bouton.
DEBOUNCE_MS = 80

# Numero de la base appelee apres celle-ci.
NEXT_BASE_NUMBER = 3

# URL appelee quand le bouton de cette base est appuye.
# Pour la derniere base, mettez par exemple :
# NEXT_BASE_NUMBER = 1
# NEXT_BASE_URL = "http://192.168.4.1/activate"
NEXT_BASE_URL = "http://192.168.4.3/activate"

# URL de la base 1 pour annoncer quelle base est active.
REPORT_ACTIVE_URL = "http://192.168.4.1/report_active?base={}".format(BASE_NUMBER)

# Nombre d'essais pour appeler une autre base.
HTTP_RETRY_COUNT = 3

# Pause entre deux essais HTTP.
HTTP_RETRY_PAUSE_MS = 250

# Temps maximum pour une requete HTTP sortante.
HTTP_TIMEOUT_SECONDS = 2

# Nombre d'essais Wi-Fi avant de refaire une tentative complete.
WIFI_CONNECT_TRIES = 40


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

# Indique si cette base doit biper maintenant.
active = False

# Message court visible dans /state.
state_message = "Base {} prete".format(BASE_NUMBER)

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
# OUTILS WI-FI ET HTTP
# ---------------------------------------------------------------------------

def connect_to_wifi():
    """Connecte cette base au Wi-Fi de la base 1."""
    # Recupere l'interface station de l'ESP32.
    station = network.WLAN(network.STA_IF)

    # Active l'interface station.
    station.active(True)

    # Configure l'adresse IP fixe avant la connexion.
    station.ifconfig((STATIC_IP, NETMASK, GATEWAY_IP, DNS_IP))

    # Lance la connexion au Wi-Fi de la base 1.
    station.connect(WIFI_SSID, WIFI_PASSWORD)

    # Attend la connexion pendant un nombre limite d'essais.
    for _ in range(WIFI_CONNECT_TRIES):
        # Si la connexion est faite, on peut continuer.
        if station.isconnected():
            print("Connecte au Wi-Fi :", WIFI_SSID)
            print("Adresse IP :", station.ifconfig()[0])
            return station

        # Attend un court instant avant de re-verifier.
        utime.sleep_ms(250)

    # Si on arrive ici, la connexion a echoue.
    print("Wi-Fi introuvable, nouvelle tentative dans 2 secondes")

    # Petite pause avant une nouvelle tentative complete.
    utime.sleep_ms(2000)

    # Renvoie quand meme l'objet station pour pouvoir recommencer.
    return station


def ensure_wifi_connected(station):
    """Reconnecte le Wi-Fi si la base est deconnectee."""
    # Si la station est connectee, tout va bien.
    if station.isconnected():
        return station

    # Affiche la deconnexion dans la console serie.
    print("Wi-Fi perdu, reconnexion")

    # Retente une connexion complete.
    return connect_to_wifi()


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

        # Evite de rester bloque trop longtemps.
        client.settimeout(HTTP_TIMEOUT_SECONDS)

        # Ouvre la connexion TCP.
        client.connect(address)

        # Construit une requete HTTP minimale.
        request = "GET {} HTTP/1.0\r\nHost: {}\r\nConnection: close\r\n\r\n".format(path, host)

        # Envoie la requete.
        client.send(request.encode("utf-8"))

        # Lit le debut de la reponse.
        response = client.recv(128)

        # Recupere la premiere ligne HTTP.
        first_line = response.split(b"\r\n", 1)[0]

        # La requete est reussie si le code contient 200.
        return b"200" in first_line

    except Exception as error:
        # Affiche l'erreur dans la console serie.
        print("Erreur HTTP vers", url, ":", error)

        # Signale l'echec.
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
            return True

        # Affiche l'essai rate dans la console.
        print("Essai", attempt, "rate vers", url)

        # Attend un peu avant le prochain essai.
        utime.sleep_ms(HTTP_RETRY_PAUSE_MS)

    # Tous les essais ont echoue.
    return False


def create_server_socket():
    """Cree le petit serveur HTTP de cette base."""
    # Cree une socket TCP.
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

    # Essaie d'autoriser la reutilisation rapide du port.
    try:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:
        pass

    # Lie le serveur a toutes les interfaces reseau.
    server.bind(("0.0.0.0", SERVER_PORT))

    # Autorise quelques connexions en attente.
    server.listen(5)

    # Rend accept() non bloquant pour continuer a gerer le buzzer.
    server.setblocking(False)

    # Affiche l'adresse dans la console serie.
    print("Base {} prete : http://{}/".format(BASE_NUMBER, STATIC_IP))

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
        buzzer_off()
        return

    # Si le buzzer est allume depuis assez longtemps, on l'eteint.
    if buzzer_is_on and utime.ticks_diff(now, last_beep_change_ms) >= BEEP_ON_MS:
        buzzer_off()
        last_beep_change_ms = now

    # Si le buzzer est eteint depuis assez longtemps, on l'allume.
    elif (not buzzer_is_on) and utime.ticks_diff(now, last_beep_change_ms) >= BEEP_OFF_MS:
        buzzer_on()
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
        last_button_raw_value = raw_value
        last_button_change_ms = now

    # Si le changement est trop recent, on ignore encore le bouton.
    if utime.ticks_diff(now, last_button_change_ms) < DEBOUNCE_MS:
        return False

    # Si la valeur stable change apres le delai, elle est acceptee.
    if raw_value != last_button_stable_value:
        last_button_stable_value = raw_value

        # Detecte uniquement le passage vers "bouton appuye".
        if last_button_stable_value == BUTTON_PRESSED_VALUE:
            return True

    # Aucun nouvel appui valide.
    return False


# ---------------------------------------------------------------------------
# LOGIQUE CECIBALL
# ---------------------------------------------------------------------------

def activate_this_base():
    """Active cette base et annonce son activation a la base 1."""
    # Modifie l'etat global de la base.
    global active
    global state_message
    global last_beep_change_ms

    # Cette base doit maintenant biper.
    active = True

    # Met a jour le message local.
    state_message = "Base {} active".format(BASE_NUMBER)

    # Redemarre le rythme du buzzer depuis maintenant.
    last_beep_change_ms = utime.ticks_ms()

    # Allume tout de suite pour que le signal soit immediat.
    buzzer_on()

    # Informe la base 1 pour l'affichage web.
    http_get_with_retries(REPORT_ACTIVE_URL)


def stop_this_base(message):
    """Arrete cette base."""
    # Modifie l'etat global de la base.
    global active
    global state_message

    # Cette base ne doit plus biper.
    active = False

    # Met a jour le message local.
    state_message = message

    # Coupe le buzzer.
    buzzer_off()


def pass_to_next_base():
    """Arrete cette base puis active la base suivante."""
    # Modifie l'etat global de la base.
    global state_message

    # Si cette base n'est pas active, le bouton ne fait rien.
    if not active:
        return

    # Arrete le bip local.
    stop_this_base("Passage vers la base {}".format(NEXT_BASE_NUMBER))

    # Appelle la base suivante.
    if http_get_with_retries(NEXT_BASE_URL):
        # Message de succes local.
        state_message = "Base {} appelee".format(NEXT_BASE_NUMBER)
    else:
        # En cas d'echec, on reactive cette base pour eviter un silence total.
        activate_this_base()
        state_message = "Erreur: base {} injoignable".format(NEXT_BASE_NUMBER)


# ---------------------------------------------------------------------------
# REPONSES HTTP
# ---------------------------------------------------------------------------

def json_bool(value):
    """Transforme True/False en texte JSON."""
    # Renvoie la valeur JSON correcte.
    return "true" if value else "false"


def state_as_json():
    """Construit l'etat local sous forme de JSON simple."""
    # Protege le message contre les guillemets.
    safe_message = state_message.replace('"', "'")

    # Construit le texte JSON sans module supplementaire.
    return '{{"base":{},"active":{},"message":"{}"}}'.format(
        BASE_NUMBER,
        json_bool(active),
        safe_message,
    )


def send_response(client, status, content_type, body):
    """Envoie une reponse HTTP complete."""
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

    # Envoie le corps.
    client.send(body_bytes)


def handle_route(path):
    """Execute l'action HTTP demandee et renvoie la reponse."""
    # Page simple de diagnostic local.
    if path == "/":
        return "200 OK", "text/plain", "Base {} - {}\n".format(BASE_NUMBER, state_message)

    # Active cette base.
    if path == "/activate":
        activate_this_base()
        return "200 OK", "text/plain", "base {} activee\n".format(BASE_NUMBER)

    # Stoppe cette base.
    if path == "/stop":
        stop_this_base("Base {} arretee".format(BASE_NUMBER))
        return "200 OK", "text/plain", "base {} arretee\n".format(BASE_NUMBER)

    # Renvoie l'etat local.
    if path == "/state":
        return "200 OK", "application/json", state_as_json() + "\n"

    # Chemin inconnu.
    return "404 Not Found", "text/plain", "page inconnue\n"


def handle_http_client(client):
    """Lit une requete HTTP et envoie la bonne reponse."""
    try:
        # Evite qu'un client bloque trop longtemps la boucle principale.
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

        # Recupere le chemin demande, sans parametres.
        path = parts[1].split("?", 1)[0]

        # Execute la route.
        status, content_type, body = handle_route(path)

        # Envoie la reponse.
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
    """Connecte le Wi-Fi, demarre le serveur, puis boucle."""
    # Essaie de se connecter au Wi-Fi de la base 1.
    station = connect_to_wifi()

    # Tant que le Wi-Fi n'est pas connecte, on recommence.
    while not station.isconnected():
        station = connect_to_wifi()

    # Cree le serveur HTTP local.
    server = create_server_socket()

    # Boucle principale infinie.
    while True:
        # Verifie que le Wi-Fi est toujours connecte.
        station = ensure_wifi_connected(station)

        # Fait avancer le bip si la base est active.
        update_buzzer()

        # Traite un client HTTP s'il y en a un.
        poll_http_server(server)

        # Si le bouton est appuye pendant que cette base est active, passe a la suite.
        if active and button_pressed_once():
            pass_to_next_base()

        # Petite pause pour garder une boucle stable.
        utime.sleep_ms(10)


# Lance le programme quand MicroPython execute main.py.
main()
