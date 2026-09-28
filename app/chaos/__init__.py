"""Inyeccion de latencia y errores.

Apartado deliberadamente aislado: ninguna ruta, modelo o servicio de la API
importa nada de este paquete. Se engancha con una sola linea en
`app/main.py` (`app.add_middleware(ChaosMiddleware)`); borrando esa linea y
esta carpeta, la API queda intacta.
"""

from app.chaos.state import (
    ChaosState,
    ChaosUpdate,
    get_chaos_state,
    reset_chaos_state,
    set_chaos_state,
)

__all__ = [
    "ChaosState",
    "ChaosUpdate",
    "get_chaos_state",
    "reset_chaos_state",
    "set_chaos_state",
]
