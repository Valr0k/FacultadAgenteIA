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
import json
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


# Carpeta donde se guarda el texto ya extraído de cada documento (incluido el OCR).
# Así, cuando la app se reinicia, no hace falta volver a leer todo.
CARPETA_LECTURAS = "_texto_extraido"


def empaquetar_lectura(documento: DocumentoGuardado, datos: dict) -> bytes:
    """Agrega la versión del documento, para saber después si el texto
    guardado corresponde a esta versión del archivo o a una anterior."""
    paquete = dict(datos, version_documento=documento.version)
    return json.dumps(paquete, ensure_ascii=False).encode("utf-8")


def lectura_si_corresponde(contenido: bytes, documento: DocumentoGuardado) -> dict | None:
    """Devuelve el texto guardado solo si es de la misma versión del documento."""
    try:
        datos = json.loads(contenido.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if datos.get("version_documento") != documento.version:
        return None
    return datos


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
        self._ruta_lectura(documento).unlink(missing_ok=True)

    # ----- Datos en formato JSON (por ejemplo, conversaciones) -----

    def leer_json(self, ruta_relativa: str) -> dict | None:
        ruta = self.base / ruta_relativa
        if not ruta.exists():
            return None
        try:
            return json.loads(ruta.read_text(encoding="utf-8"))
        except ValueError:
            return None

    def escribir_json(self, ruta_relativa: str, datos: dict, descripcion: str):
        ruta = self.base / ruta_relativa
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")

    def eliminar_json(self, ruta_relativa: str, descripcion: str):
        (self.base / ruta_relativa).unlink(missing_ok=True)

    # ----- Texto ya extraído (para no repetir el OCR) -----

    def _ruta_lectura(self, documento: DocumentoGuardado) -> Path:
        return self.base / CARPETA_LECTURAS / f"{documento.ruta}.json"

    def leer_lectura(self, documento: DocumentoGuardado) -> dict | None:
        ruta = self._ruta_lectura(documento)
        if not ruta.exists():
            return None
        return lectura_si_corresponde(ruta.read_bytes(), documento)

    def guardar_lectura(self, documento: DocumentoGuardado, datos: dict):
        ruta = self._ruta_lectura(documento)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(empaquetar_lectura(documento, datos))


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

    def _escribir(self, ruta: str, contenido: bytes, descripcion: str) -> bool:
        """Crea o reemplaza un archivo. Devuelve True si ya existía."""
        sha = self._sha_actual(ruta)   # GitHub lo pide para reemplazar un archivo
        datos = {
            "message": f"{'Actualiza' if sha else 'Agrega'} {descripcion}",
            "content": base64.b64encode(contenido).decode("ascii"),
            "branch": self.rama,
        }
        if sha:
            datos["sha"] = sha
        # Tiempo de espera generoso: un archivo grande puede tardar en subir
        respuesta = self.sesion.put(self._url(ruta), json=datos, timeout=600)
        self._revisar(respuesta, f"guardar {descripcion}")
        return sha is not None

    def _eliminar(self, ruta: str, descripcion: str):
        sha = self._sha_actual(ruta)
        if sha is None:
            return
        respuesta = self.sesion.delete(
            self._url(ruta),
            json={"message": f"Elimina {descripcion}", "sha": sha, "branch": self.rama},
            timeout=30,
        )
        self._revisar(respuesta, f"borrar {descripcion}")

    def guardar(self, nombre: str, contenido: bytes) -> bool:
        """Guarda el archivo. Devuelve True si reemplazó uno con el mismo nombre."""
        nombre = limpiar_nombre(nombre)
        formato = validar(nombre, contenido, self.maximo_mb)
        ruta = f"{self.carpeta}/{CARPETA_POR_FORMATO[formato]}/{nombre}"
        return self._escribir(ruta, contenido, nombre)

    def borrar(self, documento: DocumentoGuardado):
        self._eliminar(documento.ruta, documento.nombre)
        try:
            self._eliminar(self._ruta_lectura(documento), f"texto extraído de {documento.nombre}")
        except Exception:
            pass   # si no se puede borrar el texto guardado, no es grave

    # ----- Datos en formato JSON (por ejemplo, conversaciones) -----

    def leer_json(self, ruta_relativa: str) -> dict | None:
        respuesta = self.sesion.get(self._url(f"{self.carpeta}/{ruta_relativa}"),
                                    params={"ref": self.rama},
                                    headers={"Accept": "application/vnd.github.raw+json"},
                                    timeout=30)
        if respuesta.status_code == 404:
            return None
        self._revisar(respuesta, f"leer {ruta_relativa}")
        try:
            return json.loads(respuesta.content.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None

    def escribir_json(self, ruta_relativa: str, datos: dict, descripcion: str):
        contenido = json.dumps(datos, ensure_ascii=False).encode("utf-8")
        self._escribir(f"{self.carpeta}/{ruta_relativa}", contenido, descripcion)

    def eliminar_json(self, ruta_relativa: str, descripcion: str):
        self._eliminar(f"{self.carpeta}/{ruta_relativa}", descripcion)

    # ----- Texto ya extraído (para no repetir el OCR cada vez que la app se reinicia) -----

    def _ruta_lectura(self, documento: DocumentoGuardado) -> str:
        relativa = documento.ruta.removeprefix(f"{self.carpeta}/")
        return f"{self.carpeta}/{CARPETA_LECTURAS}/{relativa}.json"

    def leer_lectura(self, documento: DocumentoGuardado) -> dict | None:
        respuesta = self.sesion.get(self._url(self._ruta_lectura(documento)),
                                    params={"ref": self.rama},
                                    headers={"Accept": "application/vnd.github.raw+json"},
                                    timeout=60)
        if respuesta.status_code == 404:
            return None
        self._revisar(respuesta, f"leer el texto guardado de {documento.nombre}")
        return lectura_si_corresponde(respuesta.content, documento)

    def guardar_lectura(self, documento: DocumentoGuardado, datos: dict):
        self._escribir(self._ruta_lectura(documento), empaquetar_lectura(documento, datos),
                       f"texto extraído de {documento.nombre}")


def crear_almacen(obtener_secreto, carpeta_local: Path):
    """Usa GitHub si están configurados los secretos; si no, una carpeta local."""
    maximo_mb = leer_limite(obtener_secreto("TAMANIO_MAXIMO_MB"))
    token = obtener_secreto("GITHUB_TOKEN")
    repositorio = obtener_secreto("GITHUB_REPO_DOCUMENTOS")
    if token and repositorio:
        rama = obtener_secreto("GITHUB_RAMA_DOCUMENTOS") or "main"
        return AlmacenGitHub(token, repositorio, rama, maximo_mb=maximo_mb)
    return AlmacenLocal(carpeta_local, maximo_mb=maximo_mb)
