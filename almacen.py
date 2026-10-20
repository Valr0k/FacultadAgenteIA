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

# Límite por archivo. Se puede cambiar con el secret TAMANIO_MAXIMO_MB.
# GitHub no acepta archivos de más de 100 MB, por eso el tope es 95 MB
# (queda margen porque el archivo viaja codificado y ocupa ~33 % más).
TAMANIO_MAXIMO_MB_POR_DEFECTO = 50
TAMANIO_MAXIMO_MB_TOPE = 95


def leer_limite(valor) -> int:
    """Convierte el valor del secret en un límite válido entre 1 y el tope."""
    try:
        limite = int(float(valor))
    except (TypeError, ValueError):
        return TAMANIO_MAXIMO_MB_POR_DEFECTO
    return max(1, min(limite, TAMANIO_MAXIMO_MB_TOPE))


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


def validar(nombre: str, contenido: bytes, maximo_mb: int) -> str:
    """Revisa formato y tamaño antes de guardar. Devuelve el formato."""
    formato = formato_de(nombre)
    if formato is None:
        raise ErrorDeAlmacen(f"{nombre}: formato no soportado.")
    if len(contenido) > maximo_mb * 1024 * 1024:
        tamanio = len(contenido) / (1024 * 1024)
        raise ErrorDeAlmacen(f"{nombre}: pesa {tamanio:.1f} MB y el máximo es {maximo_mb} MB.")
    return formato


# =====================================================================
# Almacén local (carpeta en la computadora)
# =====================================================================

class AlmacenLocal:
    es_persistente_en_la_nube = False

    def __init__(self, carpeta_base: Path, maximo_mb: int = TAMANIO_MAXIMO_MB_POR_DEFECTO):
        self.base = carpeta_base
        self.maximo_mb = maximo_mb
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
        formato = validar(nombre, contenido, self.maximo_mb)
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
                 carpeta: str = "documentos", maximo_mb: int = TAMANIO_MAXIMO_MB_POR_DEFECTO):
        self.maximo_mb = maximo_mb
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
        # Se agrega el mensaje original de GitHub para poder diagnosticar el problema
        try:
            mensaje_github = respuesta.json().get("message", "")
        except Exception:
            mensaje_github = ""
        if mensaje_github:
            detalle += f" (GitHub dice: «{mensaje_github}»)"
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
        formato = validar(nombre, contenido, self.maximo_mb)
        ruta = f"{self.carpeta}/{CARPETA_POR_FORMATO[formato]}/{nombre}"
        sha = self._sha_actual(ruta)   # GitHub lo pide para reemplazar un archivo
        datos = {
            "message": f"{'Actualiza' if sha else 'Agrega'} {nombre}",
            "content": base64.b64encode(contenido).decode("ascii"),
            "branch": self.rama,
        }
        if sha:
            datos["sha"] = sha
        # Tiempo de espera generoso: un archivo grande puede tardar en subir
        respuesta = self.sesion.put(self._url(ruta), json=datos, timeout=600)
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
    maximo_mb = leer_limite(obtener_secreto("TAMANIO_MAXIMO_MB"))
    token = obtener_secreto("GITHUB_TOKEN")
    repositorio = obtener_secreto("GITHUB_REPO_DOCUMENTOS")
    if token and repositorio:
        rama = obtener_secreto("GITHUB_RAMA_DOCUMENTOS") or "main"
        return AlmacenGitHub(token, repositorio, rama, maximo_mb=maximo_mb)
    return AlmacenLocal(carpeta_local, maximo_mb=maximo_mb)
