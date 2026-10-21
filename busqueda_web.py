"""
Búsqueda web con fuentes gratuitas.

La búsqueda con Google desde la API de Gemini ("Grounding with Google Search")
solo está disponible en el plan pago. En su lugar se consultan, en paralelo,
estas fuentes gratuitas:

- Wikipedia (español e inglés): explicaciones generales. Sin clave.
- Europe PMC: resúmenes de artículos científicos de biología y biomedicina. Sin clave.
- Tavily (opcional): búsqueda web general. Requiere una clave gratuita
  (1.000 búsquedas por mes, sin tarjeta) en el secret TAVILY_API_KEY.

Después, el mismo buscador TF-IDF de los documentos elige los párrafos más
relevantes de todas las fuentes, y Gemini redacta la respuesta solo con ellos.
"""

import html
import re
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests

from documentos import PALABRAS_VACIAS, Buscador, Fragmento, dividir_texto

# Wikimedia y Europe PMC piden identificar a la aplicación en las consultas
ENCABEZADOS = {"User-Agent": "DocuGuia/1.0 (trabajo practico universitario; https://agenteiaiudpt.streamlit.app)"}
TIEMPO_MAXIMO = 15                # segundos por consulta a cada fuente
LARGO_MAXIMO_TEXTO = 30_000       # caracteres por artículo (los muy largos se recortan)
FRAGMENTOS_PARA_EL_MODELO = 8


class ErrorDeBusquedaWeb(Exception):
    pass


def consulta_de_busqueda(pregunta: str) -> str:
    """Saca signos y palabras como 'qué', 'son', 'los', que empeoran la búsqueda."""
    palabras = re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]+", pregunta.lower())
    sin_acento = str.maketrans("áéíóúü", "aeiouu")
    utiles = [p for p in palabras if p.translate(sin_acento) not in PALABRAS_VACIAS and len(p) > 1]
    return " ".join(utiles) or pregunta


def _limpiar_html(texto: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", texto or ""))).strip()


def _get(url: str, parametros: dict) -> dict:
    try:
        respuesta = requests.get(url, params=parametros, headers=ENCABEZADOS, timeout=TIEMPO_MAXIMO)
    except requests.RequestException as error:
        raise ErrorDeBusquedaWeb(f"no se pudo conectar ({error.__class__.__name__})") from error
    if not respuesta.ok:
        raise ErrorDeBusquedaWeb(f"respondió con el código {respuesta.status_code}")
    return respuesta.json()


# =====================================================================
# Fuente 1: Wikipedia
# =====================================================================

def buscar_en_wikipedia(terminos: dict, cantidad: int = 2) -> list[dict]:
    """Busca primero en español y, si no hay resultados, en inglés."""
    for idioma, consulta in (("es", terminos["es"]), ("en", terminos["en"])):
        api = f"https://{idioma}.wikipedia.org/w/api.php"
        resultados = _get(api, {"action": "query", "list": "search", "srsearch": consulta,
                                "srlimit": cantidad, "srprop": "", "format": "json", "formatversion": 2})
        articulos = []
        for titulo in [r["title"] for r in resultados.get("query", {}).get("search", [])]:
            # El texto completo de un artículo solo se puede pedir de a uno
            datos = _get(api, {"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                               "titles": titulo, "format": "json", "formatversion": 2})
            for pagina in datos.get("query", {}).get("pages", []):
                texto = (pagina.get("extract") or "").strip()
                if not texto:
                    continue
                # Se descartan secciones que no aportan (referencias, enlaces externos, etc.)
                texto = re.split(r"\n==+\s*(Referencias|Véase también|Enlaces externos|Bibliografía|"
                                 r"Notas|References|See also|External links|Further reading)\s*==+", texto)[0]
                titulo_real = pagina.get("title", titulo)
                articulos.append({
                    "fuente": "Wikipedia",
                    "titulo": f"Wikipedia — {titulo_real}",
                    "url": f"https://{idioma}.wikipedia.org/wiki/{quote(titulo_real.replace(' ', '_'))}",
                    "texto": texto[:LARGO_MAXIMO_TEXTO],
                })
        if articulos:
            return articulos
    return []


# =====================================================================
# Fuente 2: Europe PMC (artículos científicos)
# =====================================================================

def buscar_en_europe_pmc(terminos: dict, cantidad: int = 4) -> list[dict]:
    """Resúmenes (abstracts) de artículos científicos. Se busca en inglés, que es
    el idioma de la gran mayoría de las publicaciones."""
    datos = _get("https://www.ebi.ac.uk/europepmc/webservices/rest/search",
                 {"query": f"({terminos['en']}) AND HAS_ABSTRACT:y", "format": "json",
                  "resultType": "core", "pageSize": cantidad})
    articulos = []
    for r in datos.get("resultList", {}).get("result", []):
        resumen = _limpiar_html(r.get("abstractText", ""))
        if len(resumen) < 100:
            continue
        revista = (r.get("journalInfo") or {}).get("journal", {}).get("title") or r.get("journalTitle") or ""
        anio = r.get("pubYear") or ""
        detalle = ", ".join(x for x in (revista, anio) if x)
        if r.get("doi"):
            url = f"https://doi.org/{r['doi']}"
        else:
            url = f"https://europepmc.org/article/{r.get('source', 'MED')}/{r.get('id', '')}"
        titulo = _limpiar_html(r.get("title", "Artículo sin título")).rstrip(".")
        articulos.append({
            "fuente": "Europe PMC",
            "titulo": f"Europe PMC — {titulo}" + (f" ({detalle})" if detalle else ""),
            "url": url,
            "texto": f"{titulo}. {resumen}",
        })
    return articulos


# =====================================================================
# Fuente 3: Tavily (búsqueda web general, opcional)
# =====================================================================

def buscar_en_tavily(pregunta: str, clave: str, cantidad: int = 4) -> list[dict]:
    try:
        respuesta = requests.post("https://api.tavily.com/search",
                                  headers={"Authorization": f"Bearer {clave}", **ENCABEZADOS},
                                  json={"query": pregunta, "max_results": cantidad, "search_depth": "basic",
                                        "include_raw_content": "text"},
                                  timeout=TIEMPO_MAXIMO)
    except requests.RequestException as error:
        raise ErrorDeBusquedaWeb(f"no se pudo conectar ({error.__class__.__name__})") from error
    if respuesta.status_code in (401, 403):
        raise ErrorDeBusquedaWeb("la clave TAVILY_API_KEY no es válida")
    if respuesta.status_code in (429, 432, 433):
        raise ErrorDeBusquedaWeb("se agotó el cupo gratuito del mes")
    if not respuesta.ok:
        raise ErrorDeBusquedaWeb(f"respondió con el código {respuesta.status_code}")
    articulos = []
    for r in respuesta.json().get("results", []):
        texto = (r.get("raw_content") or r.get("content") or "").strip()
        if texto:
            articulos.append({"fuente": "Web", "titulo": f"Web — {r.get('title') or r.get('url')}",
                              "url": r.get("url", ""), "texto": texto[:LARGO_MAXIMO_TEXTO]})
    return articulos


# =====================================================================
# Búsqueda combinada
# =====================================================================

def buscar_en_todas_las_fuentes(pregunta: str, terminos: dict,
                                clave_tavily: str | None = None) -> tuple[list[dict], dict[str, str]]:
    """Consulta todas las fuentes al mismo tiempo (en paralelo, para no sumar demoras).
    Devuelve (artículos encontrados, estado de cada fuente para mostrar al usuario).
    Si una fuente falla, se sigue con las demás."""
    tareas = {
        "Wikipedia": lambda: buscar_en_wikipedia(terminos),
        "Europe PMC": lambda: buscar_en_europe_pmc(terminos),
    }
    if clave_tavily:
        tareas["Tavily"] = lambda: buscar_en_tavily(pregunta, clave_tavily)

    articulos, estado = [], {}
    with ThreadPoolExecutor(max_workers=len(tareas)) as ejecutor:
        futuros = {nombre: ejecutor.submit(funcion) for nombre, funcion in tareas.items()}
        for nombre, futuro in futuros.items():
            try:
                encontrados = futuro.result()
                articulos.extend(encontrados)
                estado[nombre] = f"{len(encontrados)} resultado(s)" if encontrados else "sin resultados"
            except Exception as error:
                estado[nombre] = f"no disponible ({error})"
    if not clave_tavily:
        estado["Tavily"] = "no configurado"
    return articulos, estado


def fragmentos_relevantes(consulta: str, articulos: list[dict], cantidad: int = FRAGMENTOS_PARA_EL_MODELO):
    """Divide los textos en partes y elige las más relacionadas con la consulta."""
    fragmentos = []
    for articulo in articulos:
        parrafos = [p.strip() for p in re.split(r"\n+", articulo["texto"])
                    if len(p.strip()) > 40 and not p.strip().startswith("==")]
        for parte in dividir_texto(" ".join(parrafos)):
            fragmentos.append(Fragmento(archivo=articulo["titulo"], ubicacion=articulo["url"], texto=parte))
    if not fragmentos:
        return []
    elegidos = Buscador(fragmentos).buscar(consulta, cantidad)
    if not elegidos:
        # Si ningún párrafo coincide, se usa el comienzo de cada texto (en Wikipedia,
        # el resumen del tema; en Europe PMC, el resumen del artículo)
        primeros = {}
        for fragmento in fragmentos:
            primeros.setdefault(fragmento.archivo, fragmento)
        elegidos = [(f, 0.0) for f in list(primeros.values())[:cantidad]]
    return elegidos


def armar_contexto_web(resultados) -> str:
    bloques = []
    for i, (fragmento, _) in enumerate(resultados, start=1):
        bloques.append(f"[Fuente web {i}] {fragmento.archivo} | Link: {fragmento.ubicacion}\n{fragmento.texto}")
    return "\n\n".join(bloques)
