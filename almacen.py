"""
Módulo de almacenamiento: guarda los documentos para próximas consultas.

Hay dos formas de guardar:
- AlmacenGitHub: guarda los archivos en un repositorio PRIVADO de GitHub.
  Es la opción para la app publicada, porque Streamlit Cloud borra los
  archivos del servidor cada vez que la app se reinicia.
- AlmacenLocal: guarda en una carpeta de la computadora. Sirve para probar
  la app localmente sin configurar nada.

En los dos casos los archivos quedan separados en carpetas por formato:
    documentos/pdf/, documentos/word/, documentos/powerpoint/, documentos/texto/
"""

import base64
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import requests

# Extensión -> formato que se muestra al usuario
FORMATO_POR_EXTENSION = {
    "pdf": "PDF",
    "docx": "Word",
    "pptx": "PowerPoint",
    "txt": "Texto",
    "md": "Texto",
}

# Formato -> carpeta donde se guarda
CARPETA_POR_FORMATO = {
    "PDF": "pdf",
    "Word": "word",
    "PowerPoint": "powerpoint",
    "Texto": "texto",
}

ICONO_POR_FORMATO = {"PDF": "📕", "Word": "📘", "PowerPoint": "📙", "Texto": "📄"}

TAMANIO_MAXIMO_MB = 20   # límite razonable para la API de GitHub y para el plan gratuito


@dataclass
class DocumentoGuardado:
    nombre: str      # nombre del archivo, ej.: "clase3.pptx"
    formato: str     # "PDF", "Word", "PowerPoint" o "Texto"
    ruta: str        # ruta dentro del almacén, ej.: "documentos/powerpoint/clase3.pptx"
    tamanio: int     # en bytes
    version: str     # identificador que cambia cuando cambia el archivo (sirve para la caché)

    def tamanio_legible(self) -> str:
        if self.tamanio < 1024 * 1024:
            return f"{self.tamanio / 1024:.0f} KB"
        return f"{self.tamanio / (1024 * 1024):.1f} MB"


class ErrorDeAlmacen(Exception):
    """Error al guardar, leer o borrar un documento, con un mensaje para el usuario."""


def formato_de(nombre: str) -> str | None:
    return FORMATO_POR_EXTENSION.get(Path(nombre).suffix.lower().lstrip("."))


def limpiar_nombre(nombre: str) -> str:
    """Deja solo el nombre del archivo y quita caracteres que pueden dar problemas."""
    nombre = Path(nombre).name.strip()
    nombre = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nombre)
    return nombre or "documento"


def validar(nombre: str, contenido: bytes) -> str:
    """Revisa formato y tamaño antes de guardar. Devuelve el formato."""
    formato = formato_de(nombre)
    if formato is None:
        raise ErrorDeAlmacen(f"{nombre}: formato no soportado.")
    if len(contenido) > TAMANIO_MAXIMO_MB * 1024 * 1024:
        raise ErrorDeAlmacen(f"{nombre}: supera el máximo de {TAMANIO_MAXIMO_MB} MB.")
    return formato


# =====================================================================
# Almacén local (carpeta en la computadora)
# =====================================================================

class AlmacenLocal:
    es_persistente_en_la_nube = False

    def __init__(self, carpeta_base: Path):
        self.base = carpeta_base
        self.base.mkdir(parents=True, exist_ok=True)

    def descripcion(self) -> str:
        return f"carpeta local «{self.base.name}»"

    def listar(self) -> list[DocumentoGuardado]:
        documentos = []
        for formato, carpeta in CARPETA_POR_FORMATO.items():
            directorio = self.base / carpeta
            if not directorio.exists():
                continue
            for archivo in sorted(directorio.iterdir()):
                if archivo.is_file() and formato_de(archivo.name) == formato:
                    datos = archivo.stat()
                    documentos.append(DocumentoGuardado(
                        nombre=archivo.name, formato=formato,
                        ruta=f"{carpeta}/{archivo.name}", tamanio=datos.st_size,
                        version=f"{datos.st_mtime_ns}-{datos.st_size}",
                    ))
        return documentos

    def leer(self, documento: DocumentoGuardado) -> bytes:
        return (self.base / documento.ruta).read_bytes()

    def guardar(self, nombre: str, contenido: bytes) -> bool:
        """Guarda el archivo. Devuelve True si reemplazó uno con el mismo nombre."""
        nombre = limpiar_nombre(nombre)
        formato = validar(nombre, contenido)
        destino = self.base / CARPETA_POR_FORMATO[formato] / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        existia = destino.exists()
        destino.write_bytes(contenido)
        return existia

    def borrar(self, documento: DocumentoGuardado):
        (self.base / documento.ruta).unlink(missing_ok=True)


# =====================================================================
# Almacén en GitHub (repositorio privado)
# =====================================================================

class AlmacenGitHub:
    """Usa la API de contenidos de GitHub: cada documento es un archivo del
    repositorio y cada subida o borrado queda registrado como un commit."""

    es_persistente_en_la_nube = True
    API = "https://api.github.com"

    def __init__(self, token: str, repositorio: str, rama: str = "main",
                 carpeta: str = "documentos"):
        self.repositorio = repositorio.strip().strip("/")
        self.rama = rama
        self.carpeta = carpeta
        self.sesion = requests.Session()
        self.sesion.headers.update({
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def descripcion(self) -> str:
        return f"repositorio de GitHub «{self.repositorio}»"

    def _url(self, ruta: str) -> str:
        return f"{self.API}/repos/{self.repositorio}/contents/{quote(ruta)}"

    def _revisar(self, respuesta: requests.Response, accion: str):
        if respuesta.ok:
            return
        mensajes = {
            401: "el token de GitHub no es válido o venció.",
            403: "el token no tiene permiso de escritura (Contents: Read and write).",
            404: "no se encontró el repositorio. Revisá el nombre y que el token tenga acceso.",
        }
        detalle = mensajes.get(respuesta.status_code, f"código {respuesta.status_code}.")
        raise ErrorDeAlmacen(f"No se pudo {accion}: {detalle}")

    def listar(self) -> list[DocumentoGuardado]:
        documentos = []
        for formato, carpeta in CARPETA_POR_FORMATO.items():
            respuesta = self.sesion.get(self._url(f"{self.carpeta}/{carpeta}"),
                                        params={"ref": self.rama}, timeout=20)
            if respuesta.status_code == 404:   # la carpeta todavía no existe
                continue
            self._revisar(respuesta, "listar los documentos")
            for item in respuesta.json():
                if item.get("type") == "file" and formato_de(item["name"]) == formato:
                    documentos.append(DocumentoGuardado(
                        nombre=item["name"], formato=formato, ruta=item["path"],
                        tamanio=item.get("size", 0), version=item["sha"],
                    ))
        return sorted(documentos, key=lambda d: (d.formato, d.nombre.lower()))

    def leer(self, documento: DocumentoGuardado) -> bytes:
        # El tipo "raw" devuelve el archivo tal cual (sirve para archivos grandes)
        respuesta = self.sesion.get(self._url(documento.ruta), params={"ref": self.rama},
                                    headers={"Accept": "application/vnd.github.raw+json"},
                                    timeout=60)
        self._revisar(respuesta, f"descargar {documento.nombre}")
        return respuesta.content

    def _sha_actual(self, ruta: str) -> str | None:
        respuesta = self.sesion.get(self._url(ruta), params={"ref": self.rama}, timeout=20)
        if respuesta.status_code == 404:
            return None
        self._revisar(respuesta, "consultar el documento")
        return respuesta.json().get("sha")

    def guardar(self, nombre: str, contenido: bytes) -> bool:
        """Guarda el archivo. Devuelve True si reemplazó uno con el mismo nombre."""
        nombre = limpiar_nombre(nombre)
        formato = validar(nombre, contenido)
        ruta = f"{self.carpeta}/{CARPETA_POR_FORMATO[formato]}/{nombre}"
        sha = self._sha_actual(ruta)   # GitHub lo pide para reemplazar un archivo
        datos = {
            "message": f"{'Actualiza' if sha else 'Agrega'} {nombre}",
            "content": base64.b64encode(contenido).decode("ascii"),
            "branch": self.rama,
        }
        if sha:
            datos["sha"] = sha
        respuesta = self.sesion.put(self._url(ruta), json=datos, timeout=120)
        self._revisar(respuesta, f"guardar {nombre}")
        return sha is not None

    def borrar(self, documento: DocumentoGuardado):
        sha = self._sha_actual(documento.ruta)
        if sha is None:
            return
        respuesta = self.sesion.delete(
            self._url(documento.ruta),
            json={"message": f"Elimina {documento.nombre}", "sha": sha, "branch": self.rama},
            timeout=30,
        )
        self._revisar(respuesta, f"borrar {documento.nombre}")


def crear_almacen(obtener_secreto, carpeta_local: Path):
    """Usa GitHub si están configurados los secretos; si no, una carpeta local."""
    token = obtener_secreto("GITHUB_TOKEN")
    repositorio = obtener_secreto("GITHUB_REPO_DOCUMENTOS")
    if token and repositorio:
        rama = obtener_secreto("GITHUB_RAMA_DOCUMENTOS") or "main"
        return AlmacenGitHub(token, repositorio, rama)
    return AlmacenLocal(carpeta_local)
