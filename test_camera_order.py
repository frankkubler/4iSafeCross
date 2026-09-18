"""L'index d'une caméra est sa position dans config.ini — pas son ordre de réponse
au réseau, ni un rang compacté après retrait des caméras absentes (src/core/camera_order,
src/core/bootstrap._wait_for_rtsp_streams)."""
import pytest

from src.core import bootstrap
from src.core.camera_order import order_cameras, rtsp_host

A = "rtsp://u:p@172.16.10.169:554/stream1"  # HOST[0] → zones _cam0
B = "rtsp://u:p@172.16.11.91:554/stream1"   # HOST[1] → zones _cam1


def test_l_ordre_de_reponse_ne_change_pas_l_index():
    # Dictionnaire rempli dans l'ordre de FIN des tests : la .61 a répondu la première.
    toutes, disponibles = order_cameras([A, B], {B: True, A: True})
    assert toutes == [A, B]
    assert disponibles == [A, B]          # et non [B, A]


def test_une_camera_absente_conserve_sa_place_et_celle_des_autres():
    toutes, disponibles = order_cameras([A, B], {A: False, B: True})
    assert toutes == [A, B]               # la .10.169 reste à l'index 0 : zones _cam0, fail-safe
    assert disponibles == [B]
    assert toutes.index(B) == 1           # la .11.91 n'hérite pas de l'index 0


def test_aucune_camera_disponible():
    toutes, disponibles = order_cameras([A, B], {A: False, B: False})
    assert toutes == [A, B] and disponibles == []


@pytest.fixture
def boot(monkeypatch):
    """Démarrage à sec : hôtes fixés, test RTSP simulé, aucune attente réelle."""
    monkeypatch.setattr(bootstrap, "RTSP_HOST", ["172.16.10.169", "172.16.11.91"])
    monkeypatch.setattr(bootstrap, "RTSP_SCHEME", "rtsp")
    monkeypatch.setattr(bootstrap, "RTSP_LOGIN", "u")
    monkeypatch.setattr(bootstrap, "RTSP_PASSWORD", "p")
    monkeypatch.setattr(bootstrap, "RTSP_PORT", 554)
    monkeypatch.setattr(bootstrap, "RTSP_STREAM", "stream1")
    monkeypatch.setattr(bootstrap, "WAIT_BEFORE_TEST_RTSP", 0)
    monkeypatch.setattr(bootstrap.time, "sleep", lambda *_: None)
    calls = []

    def install(reponses):
        """`reponses` : liste de dicts renvoyés successivement par le test RTSP."""
        def fake(cids, timeout=5, max_workers=8):
            calls.append(list(cids))
            return reponses[min(len(calls) - 1, len(reponses) - 1)]
        monkeypatch.setattr(bootstrap.CameraManager, "test_rtsp_streams_parallel", staticmethod(fake))
        return calls
    return install


def test_demarrage_inversion_de_l_ordre_de_reponse(boot):
    # Reproduit le défaut : la .11.91 répond avant la .10.169 → le dict arrive dans cet ordre.
    boot([{B: True, A: True}])
    assert bootstrap._wait_for_rtsp_streams() == [A, B]


def test_demarrage_camera_absente_conservee_a_son_index(boot):
    boot([{B: True, A: False}])
    cams = bootstrap._wait_for_rtsp_streams()
    assert cams == [A, B]                 # la .10.169 absente est conservée à l'index 0


def test_demarrage_attend_qu_au_moins_une_camera_reponde(boot):
    calls = boot([{A: False, B: False}, {A: False, B: False}, {A: True, B: False}])
    assert bootstrap._wait_for_rtsp_streams() == [A, B]
    assert len(calls) == 3                # deux tentatives vides, la troisième débloque


def test_rtsp_host_masque_les_identifiants():
    assert rtsp_host(A) == "172.16.10.169"
    assert rtsp_host(0) == "0"            # index V4L2, renvoyé tel quel


# ── Mot de passe non percent-encodé : l'hôte et le masquage ne doivent pas en dépendre ──
# Constat boîtier 2026-09-16 : « Caméras : 0=admin, 1=admin » et libellé « Camera 1 — admin »
# dans l'IHM — urlsplit prenait un ``?`` ou ``#`` du mot de passe pour le début de la
# requête/du fragment et renvoyait le login comme hôte.
from src.core.camera_order import split_userinfo, strip_userinfo

MOTS_DE_PASSE_PIEGES = ["Se?ret1", "Se#ret1", "Se/ret1", "Se@ret1", "Se%ret1", "Se[ret1", "a:b:c", ""]


@pytest.mark.parametrize("pw", MOTS_DE_PASSE_PIEGES)
def test_rtsp_host_ignore_le_contenu_du_mot_de_passe(pw):
    assert rtsp_host(f"rtsp://admin:{pw}@172.16.10.169:554/stream1") == "172.16.10.169"
    assert rtsp_host(f"rtsps://admin:{pw}@cam-nord.local/stream1") == "cam-nord.local"


@pytest.mark.parametrize("pw", MOTS_DE_PASSE_PIEGES)
def test_strip_userinfo_ne_laisse_jamais_fuir_le_mot_de_passe(pw):
    url = f"rtsp://admin:{pw}@172.16.10.169:554/stream1"
    masque = strip_userinfo(url)
    assert masque == "rtsp://***@172.16.10.169:554/stream1"
    if pw:
        assert pw not in masque
    assert "admin" not in masque


def test_strip_userinfo_sans_identifiants_et_non_url():
    assert strip_userinfo("rtsp://172.16.10.169:554/stream1") == "rtsp://172.16.10.169:554/stream1"
    assert strip_userinfo(0) == 0
    assert strip_userinfo(None) is None
    assert split_userinfo("pas une url") is None


from src.core.camera_order import rtsp_host_port


@pytest.mark.parametrize("pw", MOTS_DE_PASSE_PIEGES)
def test_rtsp_host_port_pour_le_test_tcp(pw):
    assert rtsp_host_port(f"rtsp://admin:{pw}@172.16.10.169:554/stream1") == ("172.16.10.169", 554)
    assert rtsp_host_port(f"rtsps://admin:{pw}@172.16.11.91/stream1") == ("172.16.11.91", 554)
    assert rtsp_host_port(f"rtsp://admin:{pw}@cam.local:8554/live") == ("cam.local", 8554)


def test_rtsp_host_port_sans_identifiants_et_cas_limites():
    assert rtsp_host_port("rtsp://172.16.10.169:554/stream1") == ("172.16.10.169", 554)
    assert rtsp_host_port("rtsp://172.16.10.169") == ("172.16.10.169", 554)
    assert rtsp_host_port("http://172.16.10.169/") is None
    assert rtsp_host_port(0) is None


# ── Libellé de vue : index technique, sans décalage (2026-09-16) ──────────────
from src.core.camera_order import camera_label


def test_camera_label_affiche_l_index_technique():
    assert camera_label(0, A) == "Caméra 0 — 172.16.10.169"
    assert camera_label(1, B) == "Caméra 1 — 172.16.11.91"


@pytest.mark.parametrize("pw", MOTS_DE_PASSE_PIEGES)
def test_camera_label_ne_fuit_pas_le_mot_de_passe(pw):
    libelle = camera_label(0, f"rtsp://admin:{pw}@172.16.10.169:554/stream1")
    assert libelle == "Caméra 0 — 172.16.10.169"
    if pw:
        assert pw not in libelle


# ── Le masquage doit opérer AU MILIEU d'un texte ─────────────────────────────
# Régression réelle (v3.0.4 → v3.0.12) : l'expression était ancrée sur l'URL entière,
# or camera_manager journalise la chaîne de pipeline GStreamer complète. Le mot de
# passe RTSP est apparu en clair dans les journaux du boîtier.

PIPELINE = ("rtspsrc location={url} latency=200 protocols=tcp ! rtph264depay ! h264parse "
            "! nvv4l2decoder ! nvvidconv ! video/x-raw,format=BGRx,width=1920,height=1080 "
            "! videoconvert ! video/x-raw,format=BGR ! appsink name=sink")


@pytest.mark.parametrize("pw", MOTS_DE_PASSE_PIEGES)
def test_masquage_dans_une_chaine_de_pipeline(pw):
    url = f"rtsp://admin:{pw}@172.16.11.91:554/stream1"
    masque = strip_userinfo(PIPELINE.format(url=url))
    assert "rtsp://***@172.16.11.91:554/stream1" in masque
    assert "admin" not in masque
    if pw:
        assert pw not in masque
    # le reste du pipeline est intact
    assert masque.endswith("! appsink name=sink")
    assert "latency=200 protocols=tcp" in masque


def test_masquage_de_plusieurs_urls_dans_un_meme_texte():
    texte = ("essai rtsp://u1:p1@10.0.0.1:554/s1 puis rtsps://u2:p2@cam.local/s2 fin")
    masque = strip_userinfo(texte)
    assert masque == "essai rtsp://***@10.0.0.1:554/s1 puis rtsps://***@cam.local/s2 fin"


def test_texte_sans_identifiants_inchange():
    for texte in ("rtspsrc location=rtsp://10.0.0.1:554/s1 latency=200",
                  "aucune url ici", "http://exemple.local/page"):
        assert strip_userinfo(texte) == texte
