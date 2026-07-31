import sqlite3
from datetime import datetime, timedelta
from utils.constants import DB_PATH, RELAY_EVENTS_KEEP_DAYS


def init_db():
    # Seule relay_events est créée : la table `detections` d'origine n'a jamais
    # reçu d'écriture (insert_detection n'était appelée nulle part). Les bases
    # existantes la conservent, vide, sans effet. Rétablir les deux — table et
    # insertion — si la traçabilité des détections devient un besoin, en tenant
    # compte de la rétention RGPD (voir purge_old_relay_events).
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS relay_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            zone TEXT NOT NULL,
            duration REAL NOT NULL,
            time_on TEXT NOT NULL,
            time_off TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()


def insert_relay_event(zone: str, duration: float, time_on: datetime, time_off: datetime):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO relay_events (zone, duration, time_on, time_off)
        VALUES (?, ?, ?, ?)
    ''', (zone, duration, time_on.isoformat(), time_off.isoformat()))
    conn.commit()
    conn.close()


def purge_old_relay_events():
    """Supprime les événements relais plus anciens que RELAY_EVENTS_KEEP_DAYS jours.

    Conforme RGPD — Art. 5-1-e (limitation de la conservation).
    Durée configurée via RELAY_EVENTS_KEEP_DAYS dans config/config.ini (défaut : 365 jours).
    """
    cutoff = (datetime.now() - timedelta(days=RELAY_EVENTS_KEEP_DAYS)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('DELETE FROM relay_events WHERE time_off < ?', (cutoff,))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted
