"""
Búsqueda web gratuita en Wikipedia.

La búsqueda con Google desde la API de Gemini ("Grounding with Google Search")
solo está disponible en el plan pago. Como alternativa gratuita se usa la API
pública de Wikipedia, que no requiere clave ni tiene costo:

1. Se buscan los artículos más relacionados con la pregunta.
2. Se descarga el texto de cada artículo.
3. El mismo buscador TF-IDF de los documentos elige los párrafos más relevantes.
4. Gemini (plan gratuito, sin herramientas) redacta la respuesta solo con esos
   párrafos, y la app muestra los links reales de los artículos usados.
"""

import re
from urllib.parse import quote

import requests

from documentos import PALABRAS_VACIAS, Buscador, Fragmento, dividir_texto

# Wikimedia pide identificar a la aplicación en las consultas a su API
ENCABEZADOS = {"User-Agent": "DocuGuia/1.0 (trabajo practico universitario; https://agenteiaiudpt.streamlit.app)"}
ARTICULOS_POR_BUSQUEDA = 3
LARGO_MAXIMO_ARTICULO = 30_000   # caracteres por artículo (los muy largos se recortan)
IDIOMAS = ("es", "en")           # primero en español; si no hay resultados, en inglés


class ErrorDeBusquedaWeb(Exception):
    pass


def consulta_de_busqueda(pregunta: str) -> str:
    """Saca signos y palabras como 'qué', 'son', 'los', que empeoran la búsqueda."""
    palabras = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", pregunta.lower())
    sin_acento = str.maketrans("áéíóúü", "aeiouu")
    utiles = [p for p in palabras if p.translate(sin_acento) not in PALABRAS_VACIAS and len(p) > 1]
    return " ".join(utiles) or pregunta


def _api(idioma: str, parametros: dict) -> dict:
    try:
        respuesta = requests.get(f"https://{idioma}.wikipedia.org/w/api.php",
                                 params={**parametros, "format": "json", "formatversion": 2},
                                 headers=ENCABEZADOS, timeout=15)
    except requests.RequestException as error:
        raise ErrorDeBusquedaWeb(f"No se pudo conectar con Wikipedia ({error}).") from error
    if not respuesta.ok:
        raise ErrorDeBusquedaWeb(f"Wikipedia respondió con el código {respuesta.status_code}.")
    return respuesta.json()


def buscar_articulos(pregunta: str, cantidad: int = ARTICULOS_POR_BUSQUEDA) -> list[dict]:
    """Devuelve [{'titulo', 'url', 'texto', 'idioma'}] de los artículos encontrados."""
    consulta = consulta_de_busqueda(pregunta)
    for idioma in IDIOMAS:
        resultados = _api(idioma, {"action": "query", "list": "search", "srsearch": consulta,
                                   "srlimit": cantidad, "srprop": ""})
        titulos = [r["title"] for r in resultados.get("query", {}).get("search", [])]
        articulos = []
        for titulo in titulos:
            # El texto completo de un artículo solo se puede pedir de a uno
            datos = _api(idioma, {"action": "query", "prop": "extracts", "explaintext": 1,
                                  "redirects": 1, "titles": titulo})
            for pagina in datos.get("query", {}).get("pages", []):
                texto = (pagina.get("extract") or "").strip()
                if texto:
                    titulo_real = pagina.get("title", titulo)
                    articulos.append({
                        "titulo": titulo_real,
                        "url": f"https://{idioma}.wikipedia.org/wiki/{quote(titulo_real.replace(' ', '_'))}",
                        "texto": texto[:LARGO_MAXIMO_ARTICULO],
                        "idioma": idioma,
                    })
        if articulos:
            return articulos
    return []


def fragmentos_relevantes(pregunta: str, articulos: list[dict], cantidad: int = 6):
    """Divide los artículos en párrafos y elige los más relacionados con la pregunta."""
    fragmentos = []
    for articulo in articulos:
        # Se descartan secciones que no aportan (referencias, enlaces externos, etc.)
        texto = re.split(r"\n==+\s*(Referencias|Véase también|Enlaces externos|Bibliografía|"
                         r"Notas|References|See also|External links)\s*==+", articulo["texto"])[0]
        parrafos = [p.strip() for p in re.split(r"\n+", texto) if len(p.strip()) > 40
                    and not p.strip().startswith("==")]
        for parte in dividir_texto(" ".join(parrafos)):
            fragmentos.append(Fragmento(archivo=articulo["titulo"], ubicacion=articulo["url"], texto=parte))
    if not fragmentos:
        return []
    elegidos = Buscador(fragmentos).buscar(pregunta, cantidad)
    if not elegidos:
        # Si ningún párrafo coincide con las palabras de la pregunta, se usa el
        # comienzo de cada artículo (en Wikipedia, el resumen del tema)
        primeros = {}
        for fragmento in fragmentos:
            primeros.setdefault(fragmento.archivo, fragmento)
        elegidos = [(f, 0.0) for f in primeros.values()]
    return elegidos


def armar_contexto_web(resultados) -> str:
    bloques = []
    for i, (fragmento, _) in enumerate(resultados, start=1):
        bloques.append(f"[Fuente web {i}] Artículo: {fragmento.archivo} | Link: {fragmento.ubicacion}\n"
                       f"{fragmento.texto}")
    return "\n\n".join(bloques)
