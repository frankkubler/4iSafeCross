"""L'index d'une caméra est sa position dans config.ini — pas son ordre de réponse
au réseau, ni un rang compacté après retrait des caméras absentes (src/core/camera_order,
src/core/bootstrap._wait_for_rtsp_streams)."""
import pytest

from src.core import bootstrap
from src.core.camera_order import order_cameras, rtsp_host

A = "rtsp://u:p@192.168.0.60:554/stream1"   # HOST[0] → zones _cam0
B = "rtsp://u:p@192.168.0.61:554/stream1"   # HOST[1] → zones _cam1


def test_l_ordre_de_reponse_ne_change_pas_l_index():
    # Dictionnaire rempli dans l'ordre de FIN des tests : la .61 a répondu la première.
    toutes, disponibles = order_cameras([A, B], {B: True, A: True})
    assert toutes == [A, B]
    assert disponibles == [A, B]          # et non [B, A]


def test_une_camera_absente_conserve_sa_place_et_celle_des_autres():
    toutes, disponibles = order_cameras([A, B], {A: False, B: True})
    assert toutes == [A, B]               # la .60 reste à l'index 0 : zones _cam0, fail-safe
    assert disponibles == [B]
    assert toutes.index(B) == 1           # la .61 n'hérite pas de l'index 0


def test_aucune_camera_disponible():
    toutes, disponibles = order_cameras([A, B], {A: False, B: False})
    assert toutes == [A, B] and disponibles == []


@pytest.fixture
def boot(monkeypatch):
    """Démarrage à sec : hôtes fixés, test RTSP simulé, aucune attente réelle."""
    monkeypatch.setattr(bootstrap, "RTSP_HOST", ["192.168.0.60", "192.168.0.61"])
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
    # Reproduit le défaut : la .61 répond avant la .60 → le dict arrive dans cet ordre.
    boot([{B: True, A: True}])
    assert bootstrap._wait_for_rtsp_streams() == [A, B]


def test_demarrage_camera_absente_conservee_a_son_index(boot):
    boot([{B: True, A: False}])
    cams = bootstrap._wait_for_rtsp_streams()
    assert cams == [A, B]                 # la .60 absente est conservée à l'index 0


def test_demarrage_attend_qu_au_moins_une_camera_reponde(boot):
    calls = boot([{A: False, B: False}, {A: False, B: False}, {A: True, B: False}])
    assert bootstrap._wait_for_rtsp_streams() == [A, B]
    assert len(calls) == 3                # deux tentatives vides, la troisième débloque


def test_rtsp_host_masque_les_identifiants():
    assert rtsp_host(A) == "192.168.0.60"
    assert rtsp_host(0) == "0"            # index V4L2, renvoyé tel quel
