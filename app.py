"""
DocuGuía — Asistente de IA que responde solo con los documentos cargados
y cita archivo y página de cada dato.

Ejecutar localmente:  streamlit run app.py
"""

import os
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

from documentos import Buscador, armar_contexto, leer_pdf

# ---------- Configuración general ----------
MODELO_POR_DEFECTO = "gemini-flash-latest"   # alias que apunta al Flash vigente
MENSAJES_DE_HISTORIAL = 6                    # turnos previos que recuerda el asistente
RUTA_PROMPT = Path(__file__).parent / "prompt_sistema.txt"

st.set_page_config(page_title="DocuGuía", page_icon="📄", layout="centered")


def obtener_clave_api() -> str | None:
    """Busca la clave en variables de entorno (Hugging Face) o en secrets (Streamlit Cloud)."""
    clave = os.environ.get("GEMINI_API_KEY")
    if clave:
        return clave
    try:
        return st.secrets["GEMINI_API_KEY"]
    except Exception:
        return None


def cargar_prompt_sistema() -> str:
    """Lee el system prompt desde el archivo, salteando los comentarios (#)."""
    lineas = RUTA_PROMPT.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lineas if not l.strip().startswith("#")).strip()


@st.cache_data(show_spinner=False)
def procesar_pdf(nombre: str, contenido: bytes):
    """Se guarda en caché para no volver a leer el mismo PDF en cada pregunta."""
    return leer_pdf(nombre, contenido)


def preguntar_a_gemini(clave: str, modelo: str, historial: list[dict],
                       pregunta: str, contexto: str) -> str:
    cliente = genai.Client(api_key=clave)

    # Historial reciente para que entienda preguntas de seguimiento
    contenidos = []
    for mensaje in historial[-MENSAJES_DE_HISTORIAL:]:
        rol = "user" if mensaje["rol"] == "usuario" else "model"
        contenidos.append(types.Content(role=rol, parts=[types.Part(text=mensaje["texto"])]))

    # La pregunta actual va acompañada de los fragmentos recuperados
    mensaje_actual = (
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
            system_instruction=cargar_prompt_sistema(),
            temperature=0.2,   # baja: prioriza precisión sobre creatividad
        ),
    )
    return respuesta.text or "No pude generar una respuesta. Probá reformular la pregunta."


# ---------- Estado de la sesión ----------
if "historial" not in st.session_state:
    st.session_state.historial = []
if "buscador" not in st.session_state:
    st.session_state.buscador = None
if "archivos_cargados" not in st.session_state:
    st.session_state.archivos_cargados = ()

# ---------- Barra lateral: carga de documentos ----------
with st.sidebar:
    st.header("📚 Documentos")
    archivos = st.file_uploader("Subí uno o más PDF", type=["pdf"], accept_multiple_files=True)

    nombres_actuales = tuple(sorted((a.name, a.size) for a in archivos or []))
    if nombres_actuales != st.session_state.archivos_cargados:
        todos_los_fragmentos = []
        with st.spinner("Leyendo documentos..."):
            for archivo in archivos or []:
                fragmentos, vacias = procesar_pdf(archivo.name, archivo.getvalue())
                todos_los_fragmentos.extend(fragmentos)
                if vacias:
                    st.warning(f"{archivo.name}: {vacias} página(s) sin texto legible "
                               "(pueden ser imágenes escaneadas).")
        st.session_state.buscador = Buscador(todos_los_fragmentos) if todos_los_fragmentos else None
        st.session_state.archivos_cargados = nombres_actuales

    if st.session_state.buscador:
        cantidad = len(st.session_state.buscador.fragmentos)
        st.success(f"{len(archivos)} documento(s) listos — {cantidad} fragmentos indexados.")

    with st.expander("⚙️ Opciones avanzadas"):
        modelo = st.text_input("Modelo de Gemini", value=MODELO_POR_DEFECTO)
        cantidad_fragmentos = st.slider("Fragmentos por consulta", 3, 15, 8)

    if st.button("Borrar conversación"):
        st.session_state.historial = []
        st.rerun()

    st.caption("DocuGuía es un sistema de inteligencia artificial. Puede cometer "
               "errores: verificá siempre las páginas citadas.")

# ---------- Área principal: chat ----------
st.title("📄 DocuGuía")
st.write("Asistente de IA que responde **solo** con tus documentos y cita archivo y página.")

clave_api = obtener_clave_api()
if not clave_api:
    st.error("Falta configurar la clave GEMINI_API_KEY (ver README).")
    st.stop()

for mensaje in st.session_state.historial:
    with st.chat_message("user" if mensaje["rol"] == "usuario" else "assistant"):
        st.markdown(mensaje["texto"])

pregunta = st.chat_input("Escribí tu pregunta sobre los documentos")

if pregunta:
    if not st.session_state.buscador:
        st.warning("Primero subí al menos un PDF en la barra lateral.")
        st.stop()

    with st.chat_message("user"):
        st.markdown(pregunta)

    # Se suma la pregunta anterior para que funcionen los "¿y eso qué significa?"
    preguntas_previas = [m["texto"] for m in st.session_state.historial if m["rol"] == "usuario"]
    consulta = " ".join(preguntas_previas[-1:] + [pregunta])
    resultados = st.session_state.buscador.buscar(consulta, cantidad_fragmentos)
    contexto = armar_contexto(resultados)

    with st.chat_message("assistant"):
        with st.spinner("Buscando en los documentos..."):
            try:
                texto = preguntar_a_gemini(clave_api, modelo, st.session_state.historial,
                                           pregunta, contexto)
            except Exception as error:
                if "429" in str(error) or "RESOURCE_EXHAUSTED" in str(error):
                    texto = "Se alcanzó el límite gratuito de la API. Esperá un minuto y volvé a intentar."
                else:
                    texto = f"Ocurrió un error al consultar el modelo: {error}"
        st.markdown(texto)

        # Transparencia: muestra qué fragmentos recibió el modelo
        if resultados:
            with st.expander("🔎 Fragmentos consultados"):
                for fragmento, puntaje in resultados:
                    st.markdown(f"**{fragmento.cita()}** — relevancia {puntaje:.2f}")
                    st.caption(fragmento.texto[:400] + ("..." if len(fragmento.texto) > 400 else ""))

    st.session_state.historial.append({"rol": "usuario", "texto": pregunta})
    st.session_state.historial.append({"rol": "asistente", "texto": texto})
