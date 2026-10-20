"""
Módulo de documentos: lectura de PDFs, división en fragmentos y búsqueda.

Cada fragmento guarda el nombre del archivo y el número de página de donde
salió, para que el asistente pueda citar la fuente exacta.
"""

import io
import re
from dataclasses import dataclass

from pypdf import PdfReader
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

# Palabras muy comunes en español que no aportan a la búsqueda
PALABRAS_VACIAS = [
    "a", "al", "algo", "ante", "con", "como", "cual", "cuando", "de", "del",
    "desde", "donde", "el", "ella", "en", "entre", "era", "es", "esa", "ese",
    "eso", "esta", "este", "esto", "fue", "ha", "hay", "la", "las", "le",
    "les", "lo", "los", "mas", "me", "mi", "muy", "no", "o", "para", "pero",
    "por", "que", "se", "ser", "si", "sin", "sobre", "son", "su",
    "sus", "tambien", "te", "tiene", "un", "una", "uno", "unos", "unas", "y",
    "ya", "yo",
]

TAMANIO_FRAGMENTO = 1200   # caracteres por fragmento
SOLAPAMIENTO = 200         # caracteres compartidos entre fragmentos vecinos


@dataclass
class Fragmento:
    archivo: str
    pagina: int
    texto: str

    def cita(self) -> str:
        return f"{self.archivo}, pág. {self.pagina}"


def limpiar_texto(texto: str) -> str:
    """Quita espacios repetidos y saltos de línea innecesarios."""
    texto = texto.replace("\x00", " ")
    texto = re.sub(r"-\n(\w)", r"\1", texto)      # une palabras cortadas con guion
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def dividir_texto(texto: str) -> list[str]:
    """Divide el texto de una página en partes con solapamiento,
    para no cortar una idea justo en el borde."""
    if len(texto) <= TAMANIO_FRAGMENTO:
        return [texto]
    partes = []
    inicio = 0
    while inicio < len(texto):
        fin = inicio + TAMANIO_FRAGMENTO
        # Intenta cortar al final de una oración para no partir frases
        if fin < len(texto):
            punto = texto.rfind(". ", inicio + TAMANIO_FRAGMENTO // 2, fin)
            if punto != -1:
                fin = punto + 1
        partes.append(texto[inicio:fin].strip())
        if fin >= len(texto):
            break
        inicio = fin - SOLAPAMIENTO
    return partes


def leer_pdf(nombre: str, contenido: bytes) -> tuple[list[Fragmento], int]:
    """Lee un PDF página por página.
    Devuelve los fragmentos y la cantidad de páginas sin texto (escaneadas)."""
    lector = PdfReader(io.BytesIO(contenido))
    fragmentos = []
    paginas_vacias = 0
    for numero, pagina in enumerate(lector.pages, start=1):
        texto = limpiar_texto(pagina.extract_text() or "")
        if len(texto) < 20:
            paginas_vacias += 1
            continue
        for parte in dividir_texto(texto):
            fragmentos.append(Fragmento(archivo=nombre, pagina=numero, texto=parte))
    return fragmentos, paginas_vacias


class Buscador:
    """Encuentra los fragmentos más parecidos a una pregunta usando TF-IDF.
    Es gratuito, rápido y no gasta cuota de la API."""

    def __init__(self, fragmentos: list[Fragmento]):
        self.fragmentos = fragmentos
        self.vectorizador = TfidfVectorizer(
            strip_accents="unicode",
            lowercase=True,
            stop_words=PALABRAS_VACIAS,
            ngram_range=(1, 2),
            sublinear_tf=True,
        )
        self.matriz = self.vectorizador.fit_transform([f.texto for f in fragmentos])

    def buscar(self, consulta: str, cantidad: int = 8) -> list[tuple[Fragmento, float]]:
        vector = self.vectorizador.transform([consulta])
        puntajes = cosine_similarity(vector, self.matriz)[0]
        orden = puntajes.argsort()[::-1][:cantidad]
        return [(self.fragmentos[i], float(puntajes[i])) for i in orden if puntajes[i] > 0]


def armar_contexto(resultados: list[tuple[Fragmento, float]]) -> str:
    """Convierte los fragmentos encontrados en el texto que recibe el modelo."""
    if not resultados:
        return "NO SE ENCONTRARON FRAGMENTOS RELEVANTES EN LOS DOCUMENTOS."
    bloques = []
    for i, (fragmento, _) in enumerate(resultados, start=1):
        bloques.append(
            f"[Fragmento {i}] Documento: {fragmento.archivo} | Página: {fragmento.pagina}\n"
            f"{fragmento.texto}"
        )
    return "\n\n".join(bloques)
