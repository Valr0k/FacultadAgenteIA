"""
DocuGuía — Asistente de IA que responde con los documentos cargados
y cita archivo y página de cada dato.

Si la información no está en los documentos, avisa al usuario y le ofrece
(con botones) buscar en la web. Solo busca si el usuario acepta, y en ese
caso muestra los links de donde sacó la información.

Ejecutar localmente:  streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

from documentos import EXTENSIONES_SOPORTADAS, Buscador, armar_contexto, leer_documento

# ---------- Configuración general ----------
MODELO_POR_DEFECTO = "gemini-flash-latest"   # alias que apunta al Flash vigente
MENSAJES_DE_HISTORIAL = 6                    # turnos previos que recuerda el asistente
CARPETA = Path(__file__).parent
RUTA_PROMPT_DOCUMENTOS = CARPETA / "prompt_sistema.txt"
RUTA_PROMPT_WEB = CARPETA / "prompt_web.txt"
MARCADOR_SIN_INFORMACION = "[SIN_INFORMACION]"

st.set_page_config(page_title="DocuGuía", page_icon="📄", layout="centered")


# =====================================================================
# Funciones auxiliares
# =====================================================================

def obtener_clave_api() -> str | None:
    """Busca la clave en variables de entorno (Hugging Face) o en secrets (Streamlit Cloud)."""
    clave = os.environ.get("GEMINI_API_KEY")
    if clave:
        return clave
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def cargar_prompt(ruta: Path) -> str:
    """Lee un prompt desde archivo, salteando los comentarios (#)."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lineas if not l.strip().startswith("#")).strip()


@st.cache_data(show_spinner=False)
def procesar_documento(nombre: str, contenido: bytes):
    """Se guarda en caché para no volver a leer el mismo archivo en cada pregunta."""
    return leer_documento(nombre, contenido)


def historial_para_gemini(historial: list[dict]) -> list[types.Content]:
    """Convierte los últimos mensajes al formato que entiende Gemini."""
    contenidos = []
    for mensaje in historial[-MENSAJES_DE_HISTORIAL:]:
        rol = "user" if mensaje["rol"] == "usuario" else "model"
        contenidos.append(types.Content(role=rol, parts=[types.Part(text=mensaje["texto"])]))
    return contenidos


def describir_error(error: Exception) -> str:
    if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
        return "Se alcanzó el límite gratuito de la API. Esperá un minuto y volvé a intentar."
    return f"Ocurrió un error al consultar el modelo: {error}"


def preguntar_a_documentos(clave: str, modelo: str, historial: list[dict],
                           pregunta: str, contexto: str, nombres_documentos: list[str]) -> str:
    """Consulta a Gemini SIN herramientas: solo puede usar los fragmentos recibidos."""
    cliente = genai.Client(api_key=clave)
    contenidos = historial_para_gemini(historial)

    mensaje_actual = (
        f"DOCUMENTOS CARGADOS: {', '.join(nombres_documentos)}\n\n"
        "FRAGMENTOS DE LOS DOCUMENTOS (única fuente permitida):\n\n"
        f"{contexto}\n\n"
        "-----\n"
        f"PREGUNTA DEL USUARIO: {pregunta}"
    )
    contenidos.append(types.Content(role="user", parts=[types.Part(text=mensaje_actual)]))

    respuesta = cliente.models.generate_content(
        model=modelo,
        contents=contenidos,
        config=types.GenerateContentConfig(
            system_instruction=cargar_prompt(RUTA_PROMPT_DOCUMENTOS),
            temperature=0.2,   # baja: prioriza precisión sobre creatividad
        ),
    )
    return respuesta.text or "No pude generar una respuesta. Probá reformular la pregunta."


def extraer_fuentes_web(respuesta) -> list[dict]:
    """Saca de la respuesta los links que Google Search usó (sin repetidos)."""
    fuentes = []
    vistos = set()
    try:
        metadatos = respuesta.candidates[0].grounding_metadata
        for fragmento in (metadatos.grounding_chunks or []):
            if fragmento.web and fragmento.web.uri and fragmento.web.uri not in vistos:
                vistos.add(fragmento.web.uri)
                fuentes.append({"titulo": fragmento.web.title or fragmento.web.uri,
                                "url": fragmento.web.uri})
    except (AttributeError, IndexError, TypeError):
        pass
    return fuentes


def buscar_en_web(clave: str, modelo: str, pregunta: str,
                  nombres_documentos: list[str]) -> tuple[str, list[dict]]:
    """Consulta a Gemini CON la herramienta de Google Search.
    Solo se llama cuando el usuario autorizó la búsqueda con el botón."""
    cliente = genai.Client(api_key=clave)
    mensaje = (
        f"Tema de referencia (documentos del usuario): {', '.join(nombres_documentos)}\n"
        f"PREGUNTA DEL USUARIO: {pregunta}"
    )
    respuesta = cliente.models.generate_content(
        model=modelo,
        contents=mensaje,
        config=types.GenerateContentConfig(
            system_instruction=cargar_prompt(RUTA_PROMPT_WEB),
            tools=[types.Tool(google_search=types.GoogleSearch())],
            temperature=0.2,
        ),
    )
    texto = respuesta.text or "No encontré información confiable en la web sobre esa pregunta."
    return texto, extraer_fuentes_web(respuesta)


def mostrar_mensaje(mensaje: dict):
    """Dibuja un mensaje del historial con sus fragmentos o links."""
    with st.chat_message("user" if mensaje["rol"] == "usuario" else "assistant"):
        if mensaje.get("tipo") == "aviso":
            st.warning(mensaje["texto"], icon="⚠️")
        elif mensaje.get("tipo") == "web":
            st.info("Respuesta obtenida de la web, no de tus documentos.", icon="🌐")
            st.markdown(mensaje["texto"])
        else:
            st.markdown(mensaje["texto"])

        if mensaje.get("fuentes_web"):
            st.markdown("**Links consultados:**")
            for i, fuente in enumerate(mensaje["fuentes_web"], start=1):
                st.markdown(f"{i}. [{fuente['titulo']}]({fuente['url']})")
        elif mensaje.get("tipo") == "web":
            st.caption("La búsqueda no devolvió links verificables. Tomá esta respuesta con precaución.")

        if mensaje.get("fragmentos"):
            with st.expander("🔎 Fragmentos consultados"):
                for fragmento in mensaje["fragmentos"]:
                    st.markdown(f"**{fragmento['cita']}** — relevancia {fragmento['puntaje']:.2f}")
                    st.caption(fragmento["texto"])


# =====================================================================
# Estado de la sesión
# =====================================================================
if "historial" not in st.session_state:
    st.session_state.historial = []
if "buscador" not in st.session_state:
    st.session_state.buscador = None
if "archivos_cargados" not in st.session_state:
    st.session_state.archivos_cargados = ()
if "pregunta_pendiente_web" not in st.session_state:
    # Guarda la pregunta que no se encontró, mientras el usuario decide si buscar en la web
    st.session_state.pregunta_pendiente_web = None

# =====================================================================
# Barra lateral: carga de documentos
# =====================================================================
with st.sidebar:
    st.header("📚 Documentos")
    archivos = st.file_uploader(
        "Subí uno o más documentos",
        type=EXTENSIONES_SOPORTADAS,
        accept_multiple_files=True,
        help="Formatos: PDF, Word (.docx), PowerPoint (.pptx) y texto (.txt, .md). "
             "Los formatos viejos .doc y .ppt no se pueden leer: guardalos como .docx o .pptx.",
    )

    nombres_actuales = tuple(sorted((a.name, a.size) for a in archivos or []))
    if nombres_actuales != st.session_state.archivos_cargados:
        todos_los_fragmentos = []
        avisos_de_lectura = []
        with st.spinner("Leyendo documentos..."):
            for archivo in archivos or []:
                fragmentos, avisos = procesar_documento(archivo.name, archivo.getvalue())
                todos_los_fragmentos.extend(fragmentos)
                avisos_de_lectura.extend(f"{archivo.name}: {aviso}" for aviso in avisos)
        st.session_state.buscador = Buscador(todos_los_fragmentos) if todos_los_fragmentos else None
        st.session_state.archivos_cargados = nombres_actuales
        st.session_state.avisos_de_lectura = avisos_de_lectura

    # Los avisos se guardan para que no desaparezcan al hacer una pregunta
    for aviso in st.session_state.get("avisos_de_lectura", []):
        st.warning(aviso)

    nombres_documentos = [a.name for a in archivos or []]
    if st.session_state.buscador:
        cantidad = len(st.session_state.buscador.fragmentos)
        st.success(f"{len(nombres_documentos)} documento(s) listos — {cantidad} fragmentos indexados.")

    with st.expander("⚙️ Opciones avanzadas"):
        modelo = st.text_input("Modelo de Gemini", value=MODELO_POR_DEFECTO)
        cantidad_fragmentos = st.slider("Fragmentos por consulta", 3, 15, 8)

    if st.button("Borrar conversación"):
        st.session_state.historial = []
        st.session_state.pregunta_pendiente_web = None
        st.rerun()

    st.caption("DocuGuía es un sistema de inteligencia artificial. Puede cometer "
               "errores: verificá siempre las páginas y los links citados.")

# =====================================================================
# Área principal: chat
# =====================================================================
st.title("📄 DocuGuía")
st.write("Asistente de IA que responde con tus documentos (PDF, Word, PowerPoint o texto) "
         "y cita archivo y ubicación: página, diapositiva, sección o líneas. "
         "Solo busca en la web si vos lo autorizás.")

clave_api = obtener_clave_api()
if not clave_api:
    st.error("Falta configurar la clave GEMINI_API_KEY (ver README).")
    st.stop()

for mensaje in st.session_state.historial:
    mostrar_mensaje(mensaje)

# ---------- Botones: ¿buscar en la web? ----------
pendiente = st.session_state.pregunta_pendiente_web
if pendiente:
    st.markdown("**¿Querés que busque esta información en la web?**")
    columna_si, columna_no = st.columns(2)
    buscar = columna_si.button("🌐 Sí, buscar en la web", type="primary", use_container_width=True)
    no_buscar = columna_no.button("✋ No, gracias", use_container_width=True)

    if buscar:
        with st.spinner("Buscando en la web..."):
            try:
                texto, fuentes = buscar_en_web(clave_api, modelo, pendiente, nombres_documentos)
                st.session_state.historial.append(
                    {"rol": "asistente", "tipo": "web", "texto": texto, "fuentes_web": fuentes})
            except Exception as error:
                st.session_state.historial.append(
                    {"rol": "asistente", "tipo": "aviso", "texto": describir_error(error)})
        st.session_state.pregunta_pendiente_web = None
        st.rerun()

    if no_buscar:
        st.session_state.historial.append({
            "rol": "asistente",
            "texto": "Entendido, no voy a buscar en la web. Podés hacerme otra pregunta "
                     "sobre tus documentos.",
        })
        st.session_state.pregunta_pendiente_web = None
        st.rerun()

# ---------- Nueva pregunta ----------
pregunta = st.chat_input("Escribí tu pregunta sobre los documentos")

if pregunta:
    # Si había una búsqueda web sin responder y el usuario pregunta otra cosa, se descarta
    st.session_state.pregunta_pendiente_web = None

    if not st.session_state.buscador:
        st.warning("Primero subí al menos un documento en la barra lateral.")
        st.stop()

    mostrar_mensaje({"rol": "usuario", "texto": pregunta})

    # Se suma la pregunta anterior para que funcionen los "¿y eso qué significa?"
    preguntas_previas = [m["texto"] for m in st.session_state.historial if m["rol"] == "usuario"]
    consulta = " ".join(preguntas_previas[-1:] + [pregunta])
    resultados = st.session_state.buscador.buscar(consulta, cantidad_fragmentos)
    contexto = armar_contexto(resultados)

    with st.spinner("Buscando en los documentos..."):
        try:
            texto = preguntar_a_documentos(clave_api, modelo, st.session_state.historial,
                                           pregunta, contexto, nombres_documentos)
        except Exception as error:
            texto = describir_error(error)

    respuesta = {"rol": "asistente", "texto": texto}

    if MARCADOR_SIN_INFORMACION in texto:
        # La información no está en los documentos: se avisa y se ofrecen los botones
        detalle = texto.replace(MARCADOR_SIN_INFORMACION, "").strip()
        respuesta["tipo"] = "aviso"
        respuesta["texto"] = detalle or "No encontré esa información en tus documentos."
        st.session_state.pregunta_pendiente_web = pregunta
    elif resultados:
        respuesta["fragmentos"] = [
            {"cita": f.cita(), "puntaje": p,
             "texto": f.texto[:400] + ("..." if len(f.texto) > 400 else "")}
            for f, p in resultados
        ]

    st.session_state.historial.append({"rol": "usuario", "texto": pregunta})
    st.session_state.historial.append(respuesta)
    st.rerun()
