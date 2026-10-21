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
import threading
import uuid
from datetime import datetime, timedelta, timezone

# Los guardados se hacen en segundo plano; el candado evita que dos se mezclen.
_CANDADO_DE_ESCRITURA = threading.Lock()
# id de conversación -> mensaje de error, si un guardado en segundo plano falló
ERRORES_DE_GUARDADO: dict[str, str] = {}

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

    @staticmethod
    def preparar(id_conversacion: str | None, historial: list[dict],
                 pendiente_web: str | None = None, creada: str | None = None) -> tuple[dict, dict]:
        """Arma los datos a guardar SIN conectarse a nada (es instantáneo).
        Devuelve (conversación completa, entrada para el índice)."""
        id_conversacion = id_conversacion or uuid.uuid4().hex
        primera_pregunta = next((m["texto"] for m in historial if m["rol"] == "usuario"), "")
        titulo = titulo_desde(primera_pregunta)
        momento = ahora()
        creada = creada or momento
        datos = {
            "id": id_conversacion, "titulo": titulo, "creada": creada, "actualizada": momento,
            "historial": historial, "pendiente_web": pendiente_web,
        }
        entrada = {
            "id": id_conversacion, "titulo": titulo, "creada": creada, "actualizada": momento,
            "preguntas": sum(1 for m in historial if m["rol"] == "usuario"),
        }
        return datos, entrada

    def escribir(self, datos: dict, entrada: dict):
        """Escribe la conversación y actualiza el índice (es lo que demora:
        varias llamadas a GitHub). Se protege con un candado para que dos
        guardados seguidos no se pisen."""
        with _CANDADO_DE_ESCRITURA:
            self.almacen.escribir_json(self._ruta(datos["id"]), datos, f"conversación «{datos['titulo']}»")
            # El índice se vuelve a leer justo antes de escribirlo, por si otra persona
            # guardó una conversación mientras tanto
            conversaciones = [c for c in self.listar() if c.get("id") != datos["id"]]
            conversaciones.append(entrada)
            self.almacen.escribir_json(RUTA_INDICE, {"conversaciones": conversaciones},
                                       "índice de conversaciones")

    def guardar_en_segundo_plano(self, datos: dict, entrada: dict):
        """Guarda sin hacer esperar al usuario. Si falla, deja el error anotado
        para mostrarlo en la próxima interacción."""
        def tarea():
            try:
                self.escribir(datos, entrada)
                ERRORES_DE_GUARDADO.pop(datos["id"], None)
            except Exception as error:
                ERRORES_DE_GUARDADO[datos["id"]] = str(error)
        threading.Thread(target=tarea, daemon=True).start()

    def guardar(self, id_conversacion: str | None, historial: list[dict],
                pendiente_web: str | None = None, creada: str | None = None) -> str:
        """Versión que espera a terminar (se usa en pruebas). Devuelve el id."""
        datos, entrada = self.preparar(id_conversacion, historial, pendiente_web, creada)
        self.escribir(datos, entrada)
        return datos["id"]

    def borrar(self, id_conversacion: str):
        with _CANDADO_DE_ESCRITURA:
            conversaciones = [c for c in self.listar() if c.get("id") != id_conversacion]
            self.almacen.escribir_json(RUTA_INDICE, {"conversaciones": conversaciones},
                                       "índice de conversaciones")
            self.almacen.eliminar_json(self._ruta(id_conversacion), "conversación")
