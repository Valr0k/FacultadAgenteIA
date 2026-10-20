"""
Módulo de conversaciones: guarda cada conversación por separado para poder
retomarla después.

Se guardan en el mismo almacén que los documentos (GitHub privado o carpeta
local), dentro de la carpeta "_conversaciones":
    _conversaciones/indice.json        -> lista con título y fechas de cada una
    _conversaciones/<id>.json          -> mensajes de cada conversación

El índice existe para poder mostrar la lista sin abrir cada conversación.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

CARPETA_CONVERSACIONES = "_conversaciones"
RUTA_INDICE = f"{CARPETA_CONVERSACIONES}/indice.json"
LARGO_MAXIMO_TITULO = 60
ZONA_HORARIA = timezone(timedelta(hours=-3), "ART")   # hora de Argentina


def ahora() -> str:
    # Con segundos, para ordenar bien conversaciones del mismo minuto
    return datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M:%S")


def titulo_desde(pregunta: str) -> str:
    """El título de una conversación es su primera pregunta, recortada."""
    titulo = re.sub(r"\s+", " ", pregunta).strip()
    if len(titulo) > LARGO_MAXIMO_TITULO:
        titulo = titulo[:LARGO_MAXIMO_TITULO].rsplit(" ", 1)[0] + "…"
    return titulo or "Conversación sin título"


def fecha_legible(fecha: str) -> str:
    """'2026-10-20 20:39:15' -> '20/10 20:39'."""
    for formato in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(fecha, formato).strftime("%d/%m %H:%M")
        except (TypeError, ValueError):
            continue
    return fecha or ""


class GestorDeConversaciones:
    def __init__(self, almacen):
        self.almacen = almacen

    def _ruta(self, id_conversacion: str) -> str:
        # El id lo genera la app, pero se valida igual para no salir de la carpeta
        if not re.fullmatch(r"[0-9a-f]{32}", id_conversacion or ""):
            raise ValueError("Identificador de conversación inválido.")
        return f"{CARPETA_CONVERSACIONES}/{id_conversacion}.json"

    def listar(self) -> list[dict]:
        """Conversaciones guardadas, de la más reciente a la más vieja."""
        indice = self.almacen.leer_json(RUTA_INDICE) or {}
        conversaciones = indice.get("conversaciones", [])
        # Ante un empate de fecha, va primero la última guardada (está al final del índice)
        ordenadas = sorted(enumerate(conversaciones),
                           key=lambda par: (par[1].get("actualizada", ""), par[0]), reverse=True)
        return [conversacion for _, conversacion in ordenadas]

    def cargar(self, id_conversacion: str) -> dict | None:
        return self.almacen.leer_json(self._ruta(id_conversacion))

    def guardar(self, id_conversacion: str | None, historial: list[dict],
                pendiente_web: str | None = None) -> str:
        """Guarda los mensajes. Si la conversación es nueva, le crea un id.
        Devuelve el id."""
        es_nueva = id_conversacion is None
        if es_nueva:
            id_conversacion = uuid.uuid4().hex

        primera_pregunta = next((m["texto"] for m in historial if m["rol"] == "usuario"), "")
        titulo = titulo_desde(primera_pregunta)
        cantidad_preguntas = sum(1 for m in historial if m["rol"] == "usuario")
        momento = ahora()

        anterior = None if es_nueva else self.cargar(id_conversacion)
        creada = (anterior or {}).get("creada", momento)

        self.almacen.escribir_json(self._ruta(id_conversacion), {
            "id": id_conversacion,
            "titulo": titulo,
            "creada": creada,
            "actualizada": momento,
            "historial": historial,
            "pendiente_web": pendiente_web,
        }, f"conversación «{titulo}»")

        # Actualiza el índice (se reemplaza la entrada de esta conversación)
        conversaciones = [c for c in self.listar() if c.get("id") != id_conversacion]
        conversaciones.append({
            "id": id_conversacion,
            "titulo": titulo,
            "creada": creada,
            "actualizada": momento,
            "preguntas": cantidad_preguntas,
        })
        self.almacen.escribir_json(RUTA_INDICE, {"conversaciones": conversaciones},
                                   "índice de conversaciones")
        return id_conversacion

    def borrar(self, id_conversacion: str):
        conversaciones = [c for c in self.listar() if c.get("id") != id_conversacion]
        self.almacen.escribir_json(RUTA_INDICE, {"conversaciones": conversaciones},
                                   "índice de conversaciones")
        self.almacen.eliminar_json(self._ruta(id_conversacion), "conversación")
