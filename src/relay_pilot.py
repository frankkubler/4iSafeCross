"""Pilote de la carte relais Yoctopuce (Yocto-MaxiPowerRelay) en USB direct.

Contrat de sûreté : une commande relais ne doit JAMAIS échouer en silence.
La bibliothèque Yoctopuce lève une YAPI_Exception dès que le module ne répond
plus (ré-énumération USB, câble, alimentation) ; avant ce pilote, l'exception
tuait la coroutine appelante sans aucune trace et l'alerte n'était jamais
signalée physiquement. Ici :

- toute commande retourne un booléen et journalise son échec en ERROR (avec
  rappel périodique tant que la panne dure, sans inonder le log) ;
- `check_health()` (appelé par le watchdog fail-safe) rafraîchit la liste des
  périphériques et constate le retour du module après une ré-énumération, pour
  que l'AlerteManager resynchronise l'état physique des relais ;
- tous les appels à la bibliothèque sont sérialisés par un verrou : ils
  viennent de la boucle asyncio (alertes), du watchdog (forçages) et des
  threads waitress (état), et la sûreté multi-thread de la version Python de
  la bibliothèque n'est pas documentée.
"""
import logging
import threading
import time

from yoctopuce.yocto_api import YAPI, YAPI_Exception, YRefParam
from yoctopuce.yocto_relay import YRelay


class YoctoMultiRelay:
    # Intervalle minimal entre deux rappels ERROR d'une panne qui persiste (s).
    FAILURE_LOG_INTERVAL = 30

    def __init__(self, hub_url="usb"):
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.hub_url = hub_url
        self._lock = threading.RLock()
        self.initialized = False
        self.relays = []
        self.last_states = []
        # Diagnostic exposé au watchdog, à /health et au tableau de bord.
        self.online = False            # dernier constat : le module répond
        self.last_error = None         # texte de la dernière erreur
        self.last_error_time = None    # time.time() de la dernière erreur
        self.failed_commands = 0       # commandes perdues depuis la dernière réussite
        # Dernière COMMANDE (set/get) perdue, avec le texte de l'exception. Distinct de
        # last_error : le watchdog appelle check_health() toutes les 5 s, son message
        # (« isOnline() faux ») écrase last_error avant chaque rappel périodique et
        # l'exception réelle levée par set_state n'apparaissait jamais dans le log.
        self.last_command_error = None
        self._last_failure_log = 0.0
        # Séries déjà vues par les callbacks yapi : le premier UpdateDeviceList signale
        # les modules présents comme « arrivés » — seule une 2e arrivée est un retour.
        self._seen_serials = set()
        self.reenumerations = 0        # retours USB constatés par yapi depuis le démarrage
        self._connect()

    # ── Connexion / reprise ──────────────────────────────────────────────────

    def _connect(self):
        """Enregistre le hub et énumère les relais. Idempotent, appelable en reprise."""
        with self._lock:
            errmsg = YRefParam()
            if YAPI.RegisterHub(self.hub_url, errmsg) != YAPI.SUCCESS:
                self._mark_failure(f"initialisation du hub Yoctopuce ({self.hub_url}) : {errmsg.value}")
                return False

            self._register_yapi_callbacks()

            relays = []
            relay = YRelay.FirstRelay()
            while relay is not None:
                relays.append(relay)
                relay = relay.nextRelay()
            relays.reverse()  # Trie la liste des relais dans l'ordre croissant d'index (reverse)

            if not relays:
                self._mark_failure("aucun relais trouvé sur le hub Yoctopuce")
                return False

            self.relays = relays
            self.last_states = [None] * len(relays)
            self.initialized = True
            self._mark_online()
            self.logger.info(f"{len(self.relays)} relais détectés.")
            self.logger.debug(self.relays)
            return True

    def _register_yapi_callbacks(self):
        """Journalise ce que la bibliothèque voit : arrivée/retrait du module, journal yapi.

        Constat 2026-09-14 : carte ré-énumérée toutes les 8–13 s, nœud visible dans le
        conteneur, et pourtant aucune reprise en 5 min. Sans ces callbacks, impossible de
        savoir si yapi détecte les retours (UpdateDeviceList les déclenche) ou s'il
        échoue plus loin (ouverture, détachement d'usbhid, handshake). Idempotent.
        """
        if getattr(self, '_callbacks_registered', False):
            return
        try:
            YAPI.RegisterDeviceArrivalCallback(self._on_device_arrival)
            YAPI.RegisterDeviceRemovalCallback(self._on_device_removal)
            YAPI.RegisterLogFunction(self._on_yapi_log)
            self._callbacks_registered = True
        except Exception as exc:  # bibliothèque simulée ou native indisponible : non bloquant
            self.logger.debug(f"Callbacks yapi non enregistrés : {exc!r}")

    def _on_device_arrival(self, module):
        try:
            serial = module.get_serialNumber()
            ident = f"{serial} ({module.get_productName()})"
        except Exception:
            serial, ident = None, "module inconnu"
        if serial is not None and serial not in self._seen_serials:
            self._seen_serials.add(serial)
            self.logger.info(f"🔌 yapi : module {ident} présent (énumération initiale)")
            return
        self.reenumerations += 1
        self.logger.warning(
            f"🔌 yapi : module {ident} de retour (ré-énumération USB n°{self.reenumerations} depuis le démarrage)"
        )

    def _on_device_removal(self, module):
        try:
            ident = module.get_serialNumber()
        except Exception:
            ident = "module inconnu"
        self.logger.warning(f"🔌 yapi : module {ident} retiré (déconnexion USB)")

    def _on_yapi_log(self, line):
        # Journal interne de la bibliothèque (erreurs USB, handshakes) — en INFO, il est
        # peu verbeux et c'est lui qui nomme la cause d'une reprise qui échoue.
        self.logger.info(f"yapi : {str(line).rstrip()}")

    def check_health(self):
        """Constate si le module répond. Appelé périodiquement par le watchdog fail-safe.

        `UpdateDeviceList` est indispensable : sans lui, la bibliothèque ne voit
        jamais revenir un module ré-énuméré par le noyau (nouveau numéro USB).
        Retourne True si tous les relais sont en ligne.
        """
        with self._lock:
            try:
                errmsg = YRefParam()
                if YAPI.UpdateDeviceList(errmsg) != YAPI.SUCCESS:
                    self._mark_failure(f"UpdateDeviceList : {errmsg.value}")
                    return False
                if not self.initialized:
                    # Carte absente au démarrage (ou hub indisponible) : nouvelle tentative.
                    return self._connect()
                if all(r.isOnline() for r in self.relays):
                    self._mark_online()
                    return True
                self._mark_failure("module relais hors ligne (isOnline() faux)")
                return False
            except YAPI_Exception as exc:
                self._mark_failure(f"contrôle de santé : {exc}")
                return False
            except Exception as exc:  # la bibliothèque native peut lever autre chose
                self._mark_failure(f"contrôle de santé (erreur inattendue) : {exc!r}")
                return False

    # ── Commandes ────────────────────────────────────────────────────────────

    @property
    def states(self):
        return self.last_states

    @property
    def is_initialized(self):
        return self.initialized

    @property
    def is_online(self):
        return self.initialized and self.online

    def set_relay(self, index, state):
        """Commande physique. Retourne True si le module a confirmé, False sinon (déjà journalisé)."""
        with self._lock:
            if not self.initialized:
                self._mark_failure(f"commande relais {index} impossible : relais non initialisés")
                return False
            if not 0 <= index < len(self.relays):
                self.logger.error(f"Index de relais invalide : {index}")
                return False
            try:
                relay = self.relays[index]
                relay.set_state(state)
                self.last_states[index] = relay.get_state()
                self._mark_online()
                self.logger.info(f"Relais {index} -> état {self.last_states[index]}")
                return True
            except YAPI_Exception as exc:
                self._mark_failure(f"commande relais {index} -> état {state} perdue : {exc}", command=True)
                return False
            except Exception as exc:
                self._mark_failure(f"commande relais {index} -> état {state} perdue (erreur inattendue) : {exc!r}", command=True)
                return False

    def get_relay_state(self, index):
        """État physique lu sur le module, ou None si le module ne répond pas."""
        with self._lock:
            if not self.initialized:
                self._mark_failure(f"lecture relais {index} impossible : relais non initialisés")
                return None
            if not 0 <= index < len(self.relays):
                self.logger.error(f"Index de relais invalide : {index}")
                return None
            try:
                state = self.relays[index].get_state()
            except YAPI_Exception as exc:
                self._mark_failure(f"lecture relais {index} : {exc}", command=True)
                return None
            except Exception as exc:
                self._mark_failure(f"lecture relais {index} (erreur inattendue) : {exc!r}", command=True)
                return None
            if state == YRelay.STATE_INVALID:
                # Les getters Yoctopuce ne lèvent pas : ils renvoient INVALID hors ligne.
                self._mark_failure(f"lecture relais {index} : module hors ligne (état invalide)", command=True)
                return None
            self.last_states[index] = state
            self._mark_online()
            return state

    def action_on(self, index=0):
        return self.set_relay(index, YRelay.STATE_B)

    def action_off(self, index=0):
        return self.set_relay(index, YRelay.STATE_A)

    # ── Suivi de l'état de santé ─────────────────────────────────────────────

    def _mark_failure(self, message, command=False):
        now = time.time()
        first = self.online or self.failed_commands == 0
        self.online = False
        self.failed_commands += 1
        self.last_error = message
        self.last_error_time = now
        if command:
            self.last_command_error = message
        if first or now - self._last_failure_log >= self.FAILURE_LOG_INTERVAL:
            self._last_failure_log = now
            # Le rappel porte aussi la dernière commande perdue si elle diffère du
            # message courant (typiquement celui de check_health) : c'est l'exception
            # de set_state qui distingue « périphérique introuvable » de « muet ».
            detail = ""
            if self.last_command_error and self.last_command_error != message:
                detail = f" ; dernière commande perdue : {self.last_command_error}"
            self.logger.error(
                f"⚠️  MODULE RELAIS INJOIGNABLE — {message} "
                f"({self.failed_commands} commande(s) perdue(s) depuis la dernière réussite{detail})"
            )
        else:
            self.logger.debug(f"Module relais toujours injoignable — {message}")

    def _mark_online(self):
        if not self.online and self.failed_commands:
            self.logger.warning(
                f"✅ Module relais de nouveau joignable après {self.failed_commands} commande(s) perdue(s)"
            )
        self.online = True
        self.failed_commands = 0
        self.last_command_error = None
