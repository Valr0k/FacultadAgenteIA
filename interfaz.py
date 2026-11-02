"""
Identidad visual de DocuGuía: "Laboratorio digital".

- Tema oscuro verde petróleo, acento menta (acciones, citas) y naranja (avisos).
- Tipografías: Space Grotesk (texto) y JetBrains Mono (datos: citas, páginas, tiempos).
- Las citas del texto se convierten en números que remiten al PANEL DE FUENTES,
  donde se ve cada fuente con su fragmento, ubicación, relevancia y descarga.

Los colores base están también en .streamlit/config.toml; acá se completa con
CSS lo que el tema de Streamlit no permite cambiar.
"""

import html
import math
import re
from functools import lru_cache
from pathlib import Path
from urllib.parse import unquote

import streamlit as st

# ---------- Colores (los mismos del Design System) ----------
FONDO = "#0F1B1E"
FONDO_LATERAL = "#0B1517"
SUPERFICIE = "#142427"
SUPERFICIE_ALTA = "#1D3236"
BORDE = "#2C474C"
BORDE_SUAVE = "#22383D"
TEXTO = "#E6F1EE"
TEXTO_SECUNDARIO = "#C8D9D5"
TEXTO_TENUE = "#9FB5B0"
MENTA = "#6FE3C1"
MENTA_OSCURO = "#17302F"
MENTA_BORDE = "#2E5A52"
NARANJA = "#FFA66B"
NARANJA_OSCURO = "#1A1714"
NARANJA_BORDE = "#6B4426"
TINTA_SOBRE_MENTA = "#0F1B1E"

CSS = f"""
<style>
/* Las tipografías se cargan desde static/ (ver .streamlit/config.toml) */

/* ---- Base ---- */
html, body, .stApp, [data-testid="stAppViewContainer"], .stMarkdown, .stButton button,
[data-testid="stChatInput"] textarea, input, textarea, select {{
  font-family: 'Space Grotesk', system-ui, sans-serif !important;
}}
code, pre, .dg-mono {{ font-family: 'JetBrains Mono', ui-monospace, monospace !important; }}
.stApp {{ background: {FONDO}; color: {TEXTO}; }}
[data-testid="stDecoration"] {{ display: none; }}
[data-testid="stHeader"] {{ background: transparent; }}
h1, h2, h3 {{ letter-spacing: -0.015em; }}

/* ---- Barra lateral ---- */
[data-testid="stSidebar"] {{ background: {FONDO_LATERAL}; border-right: 1px solid {BORDE_SUAVE}; }}
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {{ color: {TEXTO_SECUNDARIO}; }}

/* ---- Botones ---- */
button[kind="primary"], [data-testid="stBaseButton-primary"] {{
  background: {MENTA} !important; color: {TINTA_SOBRE_MENTA} !important;
  border: none !important; font-weight: 600 !important; border-radius: 10px !important;
}}
button[kind="primary"] p, [data-testid="stBaseButton-primary"] p {{ color: {TINTA_SOBRE_MENTA} !important; }}
button[kind="secondary"], [data-testid="stBaseButton-secondary"] {{
  background: transparent !important; border: 1px solid {BORDE} !important;
  color: {TEXTO} !important; border-radius: 10px !important;
}}
button[kind="secondary"]:hover, [data-testid="stBaseButton-secondary"]:hover {{ border-color: {MENTA} !important; color: {MENTA} !important; }}
button[kind="tertiary"], [data-testid="stBaseButton-tertiary"] {{ color: {MENTA} !important; }}

/* ---- Mensajes ---- */
[data-testid="stChatMessage"] {{ background: transparent; padding: 0.4rem 0; gap: 0.8rem; }}
/* Pregunta del usuario: burbuja a la derecha, sin avatar */
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {{ justify-content: flex-end; }}
[data-testid="stChatMessageAvatarUser"] {{ display: none; }}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {{
  flex: 0 1 auto; max-width: 72%; margin-left: auto !important; margin-right: 0 !important; background: {SUPERFICIE_ALTA};
  border: 1px solid {BORDE}; border-radius: 14px 14px 4px 14px; padding: 0.55rem 1rem;
}}
[data-testid="stChatMessageAvatarCustom"] img {{ border-radius: 10px; }}

/* ---- Barra para escribir ---- */
[data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {{ background: {FONDO}; }}
[data-testid="stChatInput"] {{ background: {SUPERFICIE} !important; border: 1px solid {BORDE} !important; border-radius: 14px !important; }}
[data-testid="stChatInput"]:focus-within {{ border-color: {MENTA} !important; }}
[data-testid="stChatInputSubmitButton"] {{ background: {MENTA} !important; border-radius: 10px !important; }}
[data-testid="stChatInputSubmitButton"] svg {{ color: {TINTA_SOBRE_MENTA} !important; fill: {TINTA_SOBRE_MENTA} !important; }}

/* ---- Avisos (st.warning / st.info / st.error) ---- */
[data-testid="stAlertContainer"] {{ border-radius: 12px !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {{
  background: {NARANJA_OSCURO} !important; border: 1px solid {NARANJA_BORDE} !important; }}
[data-testid="stAlertContentWarning"], [data-testid="stAlertContentWarning"] p {{ color: #FFE1CC !important; }}
[data-testid="stAlertContentWarning"] [data-testid="stIconMaterial"] {{ color: {NARANJA} !important; }}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {{
  background: {SUPERFICIE} !important; border: 1px solid {BORDE} !important; }}
[data-testid="stAlertContentInfo"], [data-testid="stAlertContentInfo"] p {{ color: {TEXTO} !important; }}
[data-testid="stAlertContentInfo"] [data-testid="stIconMaterial"] {{ color: {MENTA} !important; }}

/* ---- Panel de fuentes: queda fijo mientras se lee la conversación ---- */
@media (min-width: 900px) {{
  [data-testid="stColumn"]:has(.st-key-dg_panel) {{
    position: sticky; top: 4rem; align-self: flex-start;
    max-height: calc(100vh - 9rem); overflow-y: auto; }}
}}

/* ---- Barra lateral: la consulta abierta, resaltada sin gritar ---- */
[data-testid="stSidebar"] button[kind="primary"], [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] {{
  background: {MENTA_OSCURO} !important; color: {MENTA} !important; border: 1px solid {MENTA_BORDE} !important; }}
[data-testid="stSidebar"] button[kind="primary"] p, [data-testid="stSidebar"] [data-testid="stBaseButton-primary"] p {{ color: {MENTA} !important; }}

/* ---- Piezas propias ---- */
.dg-logo {{ display: flex; align-items: center; gap: 10px; margin: 0 0 0.5rem; }}
.dg-logo span {{ font-weight: 700; font-size: 1.35rem; letter-spacing: -0.02em; color: {TEXTO}; }}
.dg-logo b {{ color: {MENTA}; font-weight: 700; }}
.dg-titulo {{ display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-bottom: 0.4rem; }}
.dg-titulo h1 {{ margin: 0; padding: 0; font-size: 1.6rem; font-weight: 600; color: {TEXTO}; }}
.dg-pastilla {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600;
  color: {TINTA_SOBRE_MENTA}; background: {MENTA}; border-radius: 999px; padding: 3px 10px; }}
.dg-cita {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; color: {MENTA};
  background: {MENTA_OSCURO}; border: 1px solid {MENTA_BORDE}; border-radius: 6px; padding: 0 6px;
  margin: 0 1px; text-decoration: none; white-space: nowrap; }}
.dg-dato {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; color: {TEXTO_TENUE}; }}
.dg-panel-titulo {{ font-size: 0.95rem; font-weight: 600; color: {TEXTO_SECUNDARIO}; margin: 0.2rem 0 0.6rem; }}
.dg-fuente {{ background: {SUPERFICIE}; border: 1px solid {BORDE}; border-radius: 12px; padding: 12px 14px;
  display: flex; flex-direction: column; gap: 8px; margin-bottom: 4px; }}
.dg-fuente.dg-tenue {{ border-color: {BORDE_SUAVE}; }}
.dg-fuente-cabeza {{ display: flex; gap: 8px; align-items: center; }}
.dg-numero {{ font-family: 'JetBrains Mono', monospace; font-size: 12px; font-weight: 600; color: {TINTA_SOBRE_MENTA};
  background: {MENTA}; border-radius: 6px; padding: 1px 7px; }}
.dg-fuente.dg-tenue .dg-numero {{ background: {BORDE_SUAVE}; color: {TEXTO_SECUNDARIO}; }}
.dg-fuente-nombre {{ font-size: 0.9rem; font-weight: 600; line-height: 1.35; color: {TEXTO}; word-break: break-word; }}
.dg-fuente-texto {{ font-size: 0.82rem; color: {TEXTO_SECUNDARIO}; line-height: 1.5; margin: 0; }}
.dg-barra {{ height: 6px; border-radius: 3px; background: {BORDE_SUAVE}; }}
.dg-barra > div {{ height: 6px; border-radius: 3px; background: {MENTA}; }}
.dg-fuente a {{ color: {MENTA}; font-size: 0.85rem; font-weight: 600; word-break: break-all; }}
.dg-nota {{ font-size: 0.78rem; color: {TEXTO_TENUE}; line-height: 1.5; }}
</style>
"""

LOGO_SVG = (
    '<svg width="34" height="34" viewBox="0 0 36 36" aria-hidden="true" fill="none" stroke-width="2.2" '
    'stroke-linecap="round"><path d="M10 4c0 9 16 9 16 18s-16 4-16 10" stroke="#6FE3C1"></path>'
    '<path d="M26 4c0 9-16 9-16 18s16 4 16 10" stroke="#FFA66B"></path>'
    '<line x1="13" y1="9" x2="23" y2="9" stroke="#9FB5B0"></line>'
    '<line x1="13" y1="27" x2="23" y2="27" stroke="#9FB5B0"></line></svg>'
)


def aplicar_estilo():
    st.markdown(CSS, unsafe_allow_html=True)


def mostrar_logo():
    st.markdown(f'<div class="dg-logo">{LOGO_SVG}<span>Docu<b>Guía</b></span></div>',
                unsafe_allow_html=True)


def mostrar_titulo(titulo: str, pastilla: str | None = "solo tus documentos"):
    extra = f'<span class="dg-pastilla">{html.escape(pastilla)}</span>' if pastilla else ""
    st.markdown(f'<div class="dg-titulo"><h1>{html.escape(titulo)}</h1>{extra}</div>',
                unsafe_allow_html=True)


@lru_cache(maxsize=1)
def avatar_asistente():
    """Avatar de DocuGuía: la doble hélice del logo en un cuadrado redondeado.
    Se dibuja una sola vez con Pillow (en alta resolución y reducido, para que quede suave)."""
    from PIL import Image, ImageDraw

    escala, lado = 4, 96
    grande = lado * escala
    imagen = Image.new("RGBA", (grande, grande), (0, 0, 0, 0))
    dibujo = ImageDraw.Draw(imagen)
    dibujo.rounded_rectangle([0, 0, grande - 1, grande - 1], radius=22 * escala,
                             fill=MENTA_OSCURO, outline=MENTA_BORDE, width=2 * escala)
    centro, amplitud = grande / 2, grande * 0.2
    arriba, abajo = grande * 0.18, grande * 0.82

    def curva(fase):
        puntos = []
        for i in range(61):
            y = arriba + (abajo - arriba) * i / 60
            x = centro + amplitud * math.sin((y - arriba) / (abajo - arriba) * 2 * math.pi + fase)
            puntos.append((x, y))
        return puntos

    for i in range(1, 6):   # peldaños
        y = arriba + (abajo - arriba) * i / 6
        ancho = amplitud * abs(math.sin((y - arriba) / (abajo - arriba) * 2 * math.pi))
        dibujo.line([(centro - ancho, y), (centro + ancho, y)], fill=TEXTO_TENUE, width=3 * escala)
    dibujo.line(curva(0), fill=MENTA, width=6 * escala, joint="curve")
    dibujo.line(curva(math.pi), fill=NARANJA, width=6 * escala, joint="curve")
    return imagen.resize((lado, lado), Image.LANCZOS)


# =====================================================================
# Citas numeradas
# =====================================================================

_INICIO_CITA = re.compile(r"\((?:Fuente|Fuentes)\s*(?:web)?\s*:\s*", re.IGNORECASE)


def _reemplazar_citas(texto: str, funcion) -> str:
    """Busca cada "(Fuente: ...)" respetando los paréntesis de adentro (un archivo
    puede llamarse "Clase 1 (2).pdf" y una ubicación decir "pág. 29 (texto de imagen)")."""
    salida, posicion = [], 0
    for inicio in _INICIO_CITA.finditer(texto):
        if inicio.start() < posicion:
            continue
        nivel, i = 1, inicio.end()
        while i < len(texto) and nivel:
            nivel += {"(": 1, ")": -1}.get(texto[i], 0)
            i += 1
        if nivel:            # paréntesis sin cerrar: se deja el texto como está
            break
        salida.append(texto[posicion:inicio.start()])
        salida.append(funcion(texto[inicio.end():i - 1]))
        posicion = i
    salida.append(texto[posicion:])
    return "".join(salida)
_PATRON_UBICACIONES = re.compile(r"\n*\**\s*Ubicaciones para consulta manual\s*:?\**.*\Z",
                                 re.IGNORECASE | re.DOTALL)


def _separar_cita(fragmento: dict) -> tuple[str, str]:
    """Devuelve (archivo, ubicación) de un fragmento guardado."""
    if fragmento.get("archivo"):
        return fragmento["archivo"], fragmento.get("ubicacion", "")
    cita = fragmento.get("cita", "")
    for marca in (", pág.", ", diapositiva", ", línea", ", líneas", ", sección", ", párrafo"):
        if marca in cita:
            posicion = cita.index(marca)
            return cita[:posicion], cita[posicion + 2:]
    archivo, _, ubicacion = cita.partition(", ")
    return archivo, ubicacion


def _normalizar(texto: str) -> str:
    texto = texto.lower()
    for a, b in zip("áéíóúü", "aeiouu"):
        texto = texto.replace(a, b)
    return re.sub(r"[^a-z0-9]+", " ", texto).strip()


def _buscar_fragmento(cita: str, fragmentos: list[dict]) -> dict | None:
    """Encuentra el fragmento al que se refiere una cita escrita por el modelo."""
    cita_normal = _normalizar(cita)
    mejor, mejor_puntaje = None, 0
    for fragmento in fragmentos:
        archivo, ubicacion = _separar_cita(fragmento)
        puntaje = 0
        ubicacion_normal = _normalizar(ubicacion.replace("(texto de imagen)", ""))
        if ubicacion_normal and ubicacion_normal in cita_normal:
            puntaje += 2
        nombre = _normalizar(Path(archivo).stem)
        palabras = [p for p in nombre.split() if len(p) > 3]
        if nombre and nombre in cita_normal:
            puntaje += 2
        elif palabras and sum(p in cita_normal for p in palabras) >= max(1, len(palabras) // 2):
            puntaje += 1
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = fragmento, puntaje
    return mejor if mejor_puntaje >= 2 else None


def preparar_respuesta(texto: str, fragmentos: list[dict]) -> tuple[str, list[dict]]:
    """Convierte "(Fuente: archivo, pág. 29)" en números [1] que remiten al panel
    y devuelve (texto en HTML seguro, lista de fuentes citadas en orden)."""
    texto = _PATRON_UBICACIONES.sub("", texto).rstrip()   # el panel reemplaza esa lista
    texto = html.escape(texto, quote=False)                # el texto del modelo nunca se toma como HTML
    citadas: list[dict] = []

    def reemplazar(contenido: str):
        numeros = []
        for parte in contenido.split(";"):
            parte = html.unescape(parte).strip()
            if not parte:
                continue
            existente = next((c for c in citadas if c["cita"] == parte), None)
            if existente is None:
                existente = {"numero": len(citadas) + 1, "cita": parte,
                             "fragmento": _buscar_fragmento(parte, fragmentos)}
                citadas.append(existente)
            numeros.append(existente["numero"])
        return "".join(f'<span class="dg-cita" title="Ver la fuente {n} en el panel">{n}</span>'
                       for n in numeros)

    return _reemplazar_citas(texto, reemplazar), citadas


# =====================================================================
# Panel de fuentes
# =====================================================================

def _tarjeta(numero, encabezado: str, nombre: str, texto: str | None = None,
             relevancia: float | None = None, enlace: str | None = None, tenue: bool = False) -> str:
    partes = [f'<div class="dg-fuente{" dg-tenue" if tenue else ""}">',
              f'<div class="dg-fuente-cabeza"><span class="dg-numero">{numero}</span>'
              f'<span class="dg-dato">{html.escape(encabezado)}</span></div>',
              f'<span class="dg-fuente-nombre">{html.escape(nombre)}</span>']
    if texto:
        partes.append(f'<p class="dg-fuente-texto">«{html.escape(texto)}»</p>')
    if relevancia is not None:
        partes.append(f'<span class="dg-dato">relevancia {relevancia:.2f}'.replace(".", ",") + "</span>"
                      f'<div class="dg-barra"><div style="width: {max(4, min(100, relevancia * 100)):.0f}%"></div></div>')
    if enlace:
        legible = unquote(enlace).removeprefix("https://").removeprefix("http://")
        partes.append(f'<a href="{html.escape(enlace)}" target="_blank" rel="noopener">{html.escape(legible)}</a>')
    partes.append("</div>")
    return "".join(partes)


def _resumen(texto: str, largo: int = 170) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    return texto if len(texto) <= largo else texto[:largo].rsplit(" ", 1)[0] + "…"


def mostrar_panel_fuentes(mensaje: dict | None, al_descargar=None):
    """Panel lateral con las fuentes de la respuesta elegida.
    `al_descargar(nombre_de_archivo)` dibuja el botón de descarga del documento."""
    st.markdown('<p class="dg-panel-titulo">Fuentes de esta respuesta</p>', unsafe_allow_html=True)
    if not mensaje:
        st.markdown('<p class="dg-nota">Cuando hagas una pregunta, acá vas a ver de qué documento, '
                    'página o diapositiva salió cada dato.</p>', unsafe_allow_html=True)
        return

    if mensaje.get("tipo") == "web":
        fuentes = mensaje.get("fuentes_web") or []
        if not fuentes:
            st.markdown('<p class="dg-nota">La búsqueda web no devolvió links verificables.</p>',
                        unsafe_allow_html=True)
        for i, fuente in enumerate(fuentes, start=1):
            origen = fuente["titulo"].split(" — ")[0] if " — " in fuente["titulo"] else "Web"
            nombre = fuente["titulo"].split(" — ", 1)[-1]
            st.markdown(_tarjeta(i, origen, nombre, enlace=fuente["url"]), unsafe_allow_html=True)
        if mensaje.get("estado_fuentes"):
            st.markdown('<p class="dg-nota">' + " · ".join(
                f"{html.escape(n)}: {html.escape(e)}" for n, e in mensaje["estado_fuentes"].items())
                + "</p>", unsafe_allow_html=True)
        return

    fragmentos = mensaje.get("fragmentos") or []
    _, citadas = preparar_respuesta(mensaje.get("texto", ""), fragmentos)
    maximo = max((f.get("puntaje", 0) for f in fragmentos), default=0) or 1

    if citadas:
        for cita in citadas:
            fragmento = cita["fragmento"]
            if fragmento:
                archivo, ubicacion = _separar_cita(fragmento)
                extension = Path(archivo).suffix.lstrip(".").upper() or "DOC"
                st.markdown(_tarjeta(cita["numero"], f"{extension} · {ubicacion}", archivo,
                                     _resumen(fragmento.get("texto", "")),
                                     fragmento.get("puntaje", 0) / maximo), unsafe_allow_html=True)
                if al_descargar:
                    al_descargar(archivo, f"{mensaje.get('_indice', 0)}_{cita['numero']}")
            else:
                st.markdown(_tarjeta(cita["numero"], "cita", cita["cita"]), unsafe_allow_html=True)
    elif fragmentos:
        st.markdown('<p class="dg-nota">La respuesta no citó fuentes. Estos fueron los fragmentos '
                    'más relacionados:</p>', unsafe_allow_html=True)
        for i, fragmento in enumerate(fragmentos[:3], start=1):
            archivo, ubicacion = _separar_cita(fragmento)
            st.markdown(_tarjeta(i, ubicacion, archivo, _resumen(fragmento.get("texto", "")),
                                 fragmento.get("puntaje", 0) / maximo, tenue=True), unsafe_allow_html=True)
    else:
        st.markdown('<p class="dg-nota">Esta respuesta no usa fuentes de tus documentos.</p>',
                    unsafe_allow_html=True)
