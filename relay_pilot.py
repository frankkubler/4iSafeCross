from yoctopuce.yocto_api import YRefParam, YAPI
from yoctopuce.yocto_relay import YRelay
import logging


class YoctoRelay:
    def __init__(self):
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.initialized = False
        self.relay = None
        self.last_state = None
        errmsg = YRefParam()
        if YAPI.RegisterHub("usb", errmsg) != YAPI.SUCCESS:
            self.logger.error(f"Erreur d'initialisation du hub Yoctopuce : {errmsg.value}")
            return
        self.relay = YRelay.FirstRelay()
        if self.relay is None:
            self.logger.error("Aucun relais trouvé.")
        else:
            self.logger.info(f"Relais trouvé : {self.relay.get_hardwareId()} - État actuel : {self.relay.get_state()}")
            self.initialized = True

    @property
    def state(self):
        if self.initialized and self.relay:
            return self.last_state

    @property
    def is_initialized(self):
        return self.initialized

    def action_on(self):
        if self.initialized and self.relay:
            self.relay.set_state(YRelay.STATE_A)
            self.last_state = self.relay.get_state()
            self.logger.info(f"Relais STATE A : {self.last_state}")
        else:
            self.logger.error("Relais non initialisé ou non trouvé.")

    def action_off(self):
        if self.initialized and self.relay:
            self.relay.set_state(YRelay.STATE_B)
            self.last_state = self.relay.get_state()
            self.logger.info(f"Relais STATE B : {self.last_state}")
        else:
            self.logger.error("Relais non initialisé ou non trouvé.")

    def relay_state(self):
        if self.initialized and self.relay:
            self.last_state = self.relay.get_state()
            return self.last_state
        else:
            self.logger.error("Relais non initialisé ou non trouvé.")
            return None


class YoctoMultiRelay:
    def __init__(self):
        self.logger = logging.getLogger(__name__).getChild(__class__.__name__)
        self.initialized = False
        self.relays = []
        self.last_states = []

        errmsg = YRefParam()
        if YAPI.RegisterHub("usb", errmsg) != YAPI.SUCCESS:
            self.logger.error(f"Erreur d'initialisation du hub Yoctopuce : {errmsg.value}")
            return

        relay = YRelay.FirstRelay()
        while relay is not None:
            self.relays.append(relay)
            relay = relay.nextRelay()
        self.relays.reverse()  # Trie la liste des relais dans l'ordre croissant d'index (reverse)

        if len(self.relays) == 0:
            self.logger.error("Aucun relais trouvé.")
        else:
            self.last_states = [None] * len(self.relays)
            self.initialized = True
            self.logger.info(f"{len(self.relays)} relais détectés.")
            self.logger.debug(self.relays)

    @property
    def states(self):
        return self.last_states

    @property
    def is_initialized(self):
        return self.initialized

    def set_relay(self, index, state):
        if not self.initialized:
            self.logger.error("Relais non initialisés.")
            return

        if 0 <= index < len(self.relays):
            self.relays[index].set_state(state)
            self.last_states[index] = self.relays[index].get_state()
            self.logger.info(f"Relais {index} -> état {self.last_states[index]}")
        else:
            self.logger.error(f"Index de relais invalide : {index}")

    def get_relay_state(self, index):
        if not self.initialized:
            self.logger.error("Relais non initialisés.")
            return None

        if 0 <= index < len(self.relays):
            state = self.relays[index].get_state()
            self.last_states[index] = state
            return state
        else:
            self.logger.error(f"Index de relais invalide : {index}")
            return None

    def action_on(self, index=0):
        self.set_relay(index, YRelay.STATE_B)

    def action_off(self, index=0):
        self.set_relay(index, YRelay.STATE_A)
