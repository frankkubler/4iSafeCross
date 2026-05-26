import sqlite3
from datetime import datetime, timedelta
from utils.constants import DB_PATH, RELAY_EVENTS_KEEP_DAYS


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS detections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            camera_id TEXT NOT NULL,
            zone TEXT NOT NULL,
            center_x REAL NOT NULL,
            center_y REAL NOT NULL,
            width REAL NOT NULL,
            height REAL NOT NULL
        )
    ''')
    # Ajout d'une table pour les événements relais
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


def insert_detection(timestamp: datetime, camera_id: str, zone: str, center_x: float, center_y: float, width: float, height: float):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        INSERT INTO detections (timestamp, camera_id, zone, center_x, center_y, width, height)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (timestamp.isoformat(), camera_id, zone, center_x, center_y, width, height))
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
