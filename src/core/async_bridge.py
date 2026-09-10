"""Pont threads → boucle asyncio principale, avec journalisation des exceptions.

`asyncio.run_coroutine_threadsafe` renvoie un Future que personne ne lit : une
exception levée dans la coroutine (ex. commande relais refusée par le module)
disparaissait sans aucune trace. Toute planification depuis un thread (callback
d'inférence, watchdog fail-safe) passe par `schedule`, qui attache un callback
de fin journalisant l'exception en ERROR avec sa pile.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def schedule(coro, loop, what=None):
    """Planifie `coro` sur `loop` depuis un autre thread et journalise son échec éventuel."""
    label = what or getattr(coro, "__qualname__", None) or repr(coro)
    future = asyncio.run_coroutine_threadsafe(coro, loop)

    def _done(fut):
        if fut.cancelled():
            return
        exc = fut.exception()
        if exc is not None:
            logger.error(
                "Exception non rattrapée dans la coroutine %s : %r", label, exc, exc_info=exc
            )

    future.add_done_callback(_done)
    return future
