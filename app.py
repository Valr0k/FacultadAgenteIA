"""
DocuGuía — Asistente de IA que responde con los documentos guardados
y cita archivo y ubicación de cada dato.

- Los documentos se guardan en un repositorio (GitHub privado o carpeta local)
  y quedan disponibles para las próximas consultas.
- La sección "Repositorio" los muestra separados por formato.
- Si la información no está en los documentos, avisa y ofrece (con botones)
  buscar en la web. Solo busca si el usuario acepta, y muestra los links.

Ejecutar localmente:  streamlit run app.py
"""

import hmac
import os
import time
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

from almacen import CARPETA_POR_FORMATO, ICONO_POR_FORMATO, ErrorDeAlmacen, crear_almacen
from documentos import EXTENSIONES_SOPORTADAS, Buscador, armar_contexto, leer_documento

# ---------- Configuración general ----------
MODELO_POR_DEFECTO = "gemini-flash-latest"   # alias que apunta al Flash vigente
MENSAJES_DE_HISTORIAL = 6                    # turnos previos que recuerda el asistente
CARPETA = Path(__file__).parent
RUTA_PROMPT_DOCUMENTOS = CARPETA / "prompt_sistema.txt"
RUTA_PROMPT_WEB = CARPETA / "prompt_web.txt"
CARPETA_ALMACEN_LOCAL = CARPETA / "almacen_documentos"
MARCADOR_SIN_INFORMACION = "[SIN_INFORMACION]"

PAGINA_CONSULTAS = "💬 Consultas"
PAGINA_REPOSITORIO = "📚 Repositorio de documentos"

st.set_page_config(page_title="DocuGuía", page_icon="📄", layout="centered")


# =====================================================================
# Configuración y almacenamiento
# =====================================================================

def obtener_secreto(nombre: str) -> str | None:
    """Busca un valor en variables de entorno (Hugging Face) o en secrets (Streamlit Cloud)."""
    valor = os.environ.get(nombre)
    if valor:
        return valor
    try:
        return st.secrets[nombre]
    except Exception:
        return None


def credenciales_admin() -> tuple[str | None, str | None]:
    """El usuario y la contraseña se leen de los Secrets, NO del código,
    porque el repositorio de la app es público."""
    return obtener_secreto("ADMIN_USUARIO"), obtener_secreto("ADMIN_CLAVE")


def validar_admin(usuario: str, clave: str) -> bool:
    usuario_correcto, clave_correcta = credenciales_admin()
    if not usuario_correcto or not clave_correcta:
        return False
    # compare_digest compara sin revelar por el tiempo de respuesta cuántos caracteres coinciden
    usuario_ok = hmac.compare_digest(usuario.strip().encode(), usuario_correcto.encode())
    clave_ok = hmac.compare_digest(clave.encode(), clave_correcta.encode())
    return usuario_ok and clave_ok


@st.cache_resource(show_spinner=False)
def obtener_almacen():
    """Se crea una sola vez y lo comparten todas las sesiones."""
    return crear_almacen(obtener_secreto, CARPETA_ALMACEN_LOCAL)


def documentos_guardados(forzar: bool = False):
    """Lista de documentos del repositorio. Se guarda en la sesión para no
    consultar GitHub en cada clic; se actualiza al subir o borrar."""
    if forzar or st.session_state.get("lista_documentos") is None:
        try:
            st.session_state.lista_documentos = obtener_almacen().listar()
            st.session_state.error_almacen = None
        except (ErrorDeAlmacen, Exception) as error:
            st.session_state.lista_documentos = []
            st.session_state.error_almacen = str(error)
    return st.session_state.lista_documentos


@st.cache_data(show_spinner=False, max_entries=10)   # pocos: los archivos pueden ser grandes
def contenido_de(ruta: str, version: str, _documento) -> bytes:
    """Descarga un documento. La caché usa ruta + versión: si el archivo no
    cambió, no se vuelve a descargar."""
    return obtener_almacen().leer(_documento)


@st.cache_data(show_spinner=False, max_entries=200)
def fragmentos_de(ruta: str, version: str, _documento):
    """Lee y fragmenta un documento (también queda en caché por versión)."""
    return leer_documento(_documento.nombre, contenido_de(ruta, version, _documento))


@st.cache_resource(show_spinner=False, max_entries=10)
def construir_buscador(claves: tuple, _documentos: list):
    """Arma el buscador con los documentos activos. `claves` identifica la
    combinación de documentos y versiones; si no cambia, se reutiliza."""
    todos_los_fragmentos, avisos = [], []
    for documento in _documentos:
        try:
            fragmentos, avisos_documento = fragmentos_de(documento.ruta, documento.version, documento)
        except Exception as error:
            fragmentos, avisos_documento = [], [f"no se pudo descargar ({error})."]
        todos_los_fragmentos.extend(fragmentos)
        avisos.extend(f"{documento.nombre}: {aviso}" for aviso in avisos_documento)
    buscador = Buscador(todos_los_fragmentos) if todos_los_fragmentos else None
    return buscador, avisos


# =====================================================================
# Funciones del asistente
# =====================================================================

def cargar_prompt(ruta: Path) -> str:
    """Lee un prompt desde archivo, salteando los comentarios (#)."""
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    return "\n".join(l for l in lineas if not l.strip().startswith("#")).strip()


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
valores_iniciales = {
    "historial": [],
    "pregunta_pendiente_web": None,   # pregunta no encontrada, esperando la decisión del usuario
    "inactivos": set(),               # rutas de documentos que el usuario no quiere consultar
    "clave_subida": 0,                # se cambia para vaciar el cuadro de subida después de guardar
    "mensajes_repositorio": [],
    "pagina": PAGINA_CONSULTAS,
    "es_admin": False,                # True después de ingresar con usuario y contraseña
    "intentos_fallidos": 0,
}
for clave, valor in valores_iniciales.items():
    if clave not in st.session_state:
        st.session_state[clave] = valor


def ir_al_repositorio():
    st.session_state.pagina = PAGINA_REPOSITORIO


def cambiar_activo(ruta: str):
    """Se llama al tildar o destildar 'Usar en consultas'."""
    if st.session_state[f"activo_{ruta}"]:
        st.session_state.inactivos.discard(ruta)
    else:
        st.session_state.inactivos.add(ruta)


almacen = obtener_almacen()
documentos = documentos_guardados()
documentos_activos = [d for d in documentos if d.ruta not in st.session_state.inactivos]

# =====================================================================
# Barra lateral
# =====================================================================
with st.sidebar:
    st.header("📄 DocuGuía")
    pagina = st.radio("Ir a", [PAGINA_CONSULTAS, PAGINA_REPOSITORIO], key="pagina",
                      label_visibility="collapsed")

    st.divider()
    st.markdown(f"**Documentos guardados:** {len(documentos)}")
    for formato in CARPETA_POR_FORMATO:
        cantidad = sum(1 for d in documentos if d.formato == formato)
        if cantidad:
            st.caption(f"{ICONO_POR_FORMATO[formato]} {formato}: {cantidad}")
    if len(documentos_activos) != len(documentos):
        st.caption(f"Se consultan {len(documentos_activos)} de {len(documentos)}.")

    # ---------- Acceso de administrador ----------
    st.divider()
    if st.session_state.es_admin:
        st.success("🔓 Sesión de administrador")
        if st.button("Cerrar sesión"):
            st.session_state.es_admin = False
            st.rerun()
    else:
        with st.expander("🔐 Ingresar como administrador"):
            if not all(credenciales_admin()):
                st.caption("El acceso de administrador no está configurado (ver README).")
            else:
                with st.form("ingreso_admin", clear_on_submit=True):
                    usuario = st.text_input("Usuario")
                    clave = st.text_input("Contraseña", type="password")
                    ingresar = st.form_submit_button("Ingresar")
                if ingresar:
                    if validar_admin(usuario, clave):
                        st.session_state.es_admin = True
                        st.session_state.intentos_fallidos = 0
                        st.rerun()
                    else:
                        st.session_state.intentos_fallidos += 1
                        # Cada intento fallido tarda un poco más, para frenar a quien pruebe contraseñas
                        time.sleep(min(st.session_state.intentos_fallidos, 5))
                        st.error("Usuario o contraseña incorrectos.")

    with st.expander("⚙️ Opciones avanzadas"):
        modelo = st.text_input("Modelo de Gemini", value=MODELO_POR_DEFECTO)
        cantidad_fragmentos = st.slider("Fragmentos por consulta", 3, 15, 8)

    if st.button("Borrar conversación"):
        st.session_state.historial = []
        st.session_state.pregunta_pendiente_web = None
        st.rerun()

    st.caption("DocuGuía es un sistema de inteligencia artificial. Puede cometer "
               "errores: verificá siempre las ubicaciones y los links citados.")

if st.session_state.get("error_almacen"):
    st.error(f"Problema con el repositorio de documentos: {st.session_state.error_almacen}")


# =====================================================================
# Página: Repositorio de documentos
# =====================================================================
def pagina_repositorio():
    st.title("📚 Repositorio de documentos")
    st.write("Los documentos que subas quedan guardados para las próximas consultas. "
             f"Se guardan en: **{almacen.descripcion()}**.")

    if not almacen.es_persistente_en_la_nube:
        st.info("Modo local: los documentos se guardan en una carpeta del servidor. "
                "En Streamlit Cloud esa carpeta se borra cuando la app se reinicia. "
                "Para que queden guardados siempre, configurá GitHub (ver README).", icon="ℹ️")

    # Mensajes del último guardado o borrado
    for tipo, texto in st.session_state.mensajes_repositorio:
        (st.success if tipo == "ok" else st.error)(texto)
    st.session_state.mensajes_repositorio = []

    # ---------- Subir documentos (solo administrador) ----------
    if not st.session_state.es_admin:
        st.info("Para subir o borrar documentos, ingresá como administrador "
                "desde la barra lateral (🔐).", icon="🔒")
    else:
        mostrar_subida()

    mostrar_listado()


def mostrar_subida():
    with st.container(border=True):
        st.subheader("Agregar documentos")
        archivos = st.file_uploader(
            "PDF, Word (.docx), PowerPoint (.pptx) o texto (.txt, .md)",
            type=EXTENSIONES_SOPORTADAS,
            accept_multiple_files=True,
            key=f"subida_{st.session_state.clave_subida}",
            help=f"Máximo {almacen.maximo_mb} MB por archivo. Los formatos viejos .doc y .ppt "
                 "no se pueden leer: guardalos como .docx o .pptx. Si subís un archivo con "
                 "el mismo nombre que uno guardado, se reemplaza.",
        )
        if st.button("💾 Guardar en el repositorio", type="primary", disabled=not archivos):
            mensajes = []
            with st.spinner("Guardando..."):
                for archivo in archivos:
                    try:
                        reemplazado = almacen.guardar(archivo.name, archivo.getvalue())
                        accion = "reemplazado" if reemplazado else "guardado"
                        mensajes.append(("ok", f"{archivo.name}: {accion}."))
                    except ErrorDeAlmacen as error:
                        mensajes.append(("error", str(error)))
                    except Exception as error:
                        mensajes.append(("error", f"{archivo.name}: no se pudo guardar ({error})."))
            st.session_state.mensajes_repositorio = mensajes
            st.session_state.clave_subida += 1   # vacía el cuadro de subida
            documentos_guardados(forzar=True)
            st.rerun()


def mostrar_listado():
    # ---------- Resumen por formato ----------
    formatos = list(CARPETA_POR_FORMATO)
    columnas = st.columns(len(formatos))
    for columna, formato in zip(columnas, formatos):
        columna.metric(f"{ICONO_POR_FORMATO[formato]} {formato}",
                       sum(1 for d in documentos if d.formato == formato))

    # ---------- Listado separado por formato ----------
    pestanias = st.tabs([f"{ICONO_POR_FORMATO[f]} {f} ({sum(1 for d in documentos if d.formato == f)})"
                         for f in formatos])
    for pestania, formato in zip(pestanias, formatos):
        with pestania:
            del_formato = [d for d in documentos if d.formato == formato]
            if not del_formato:
                st.caption("No hay documentos de este formato.")
                continue
            for documento in del_formato:
                with st.container(border=True):
                    col_nombre, col_usar, col_bajar, col_borrar = st.columns([5, 2, 1, 1])
                    col_nombre.markdown(f"**{documento.nombre}**")
                    col_nombre.caption(documento.tamanio_legible())
                    col_usar.checkbox(
                        "Usar en consultas",
                        value=documento.ruta not in st.session_state.inactivos,
                        key=f"activo_{documento.ruta}",
                        on_change=cambiar_activo, args=(documento.ruta,),
                    )
                    try:
                        col_bajar.download_button(
                            "⬇️", data=contenido_de(documento.ruta, documento.version, documento),
                            file_name=documento.nombre, key=f"bajar_{documento.ruta}",
                            help="Descargar para consulta manual",
                        )
                    except Exception:
                        col_bajar.caption("—")
                    if not st.session_state.es_admin:
                        continue   # solo el administrador ve el botón de borrar
                    with col_borrar.popover("🗑️", help="Borrar del repositorio"):
                        st.write(f"¿Borrar **{documento.nombre}**? No se puede deshacer.")
                        if st.button("Sí, borrar", key=f"borrar_{documento.ruta}", type="primary"):
                            if not st.session_state.es_admin:   # doble control por seguridad
                                st.stop()
                            try:
                                almacen.borrar(documento)
                                st.session_state.inactivos.discard(documento.ruta)
                                st.session_state.mensajes_repositorio = [
                                    ("ok", f"{documento.nombre}: borrado.")]
                            except Exception as error:
                                st.session_state.mensajes_repositorio = [("error", str(error))]
                            documentos_guardados(forzar=True)
                            st.rerun()

    if documentos:
        if st.button("🔄 Actualizar lista"):
            documentos_guardados(forzar=True)
            st.rerun()


# =====================================================================
# Página: Consultas (chat)
# =====================================================================
def pagina_consultas():
    st.title("💬 DocuGuía")
    st.write("Asistente de IA que responde con tus documentos guardados (PDF, Word, "
             "PowerPoint o texto) y cita archivo y ubicación. Solo busca en la web si vos lo autorizás.")

    clave_api = obtener_secreto("GEMINI_API_KEY")
    if not clave_api:
        st.error("Falta configurar la clave GEMINI_API_KEY (ver README).")
        st.stop()

    if not documentos_activos:
        st.info("Todavía no hay documentos para consultar. Subilos en el repositorio.", icon="📚")
        st.button("Ir al repositorio", on_click=ir_al_repositorio)
        return

    claves = tuple((d.ruta, d.version) for d in documentos_activos)
    with st.spinner("Preparando documentos..."):
        buscador, avisos = construir_buscador(claves, documentos_activos)
    nombres_documentos = [d.nombre for d in documentos_activos]

    if avisos:
        with st.expander(f"⚠️ Avisos de lectura ({len(avisos)})"):
            for aviso in avisos:
                st.caption(aviso)
    if buscador is None:
        st.warning("Los documentos activos no tienen texto legible.")
        return

    st.caption(f"Consultando {len(nombres_documentos)} documento(s): {', '.join(nombres_documentos)}")

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
    if not pregunta:
        return

    # Si había una búsqueda web sin responder y el usuario pregunta otra cosa, se descarta
    st.session_state.pregunta_pendiente_web = None
    mostrar_mensaje({"rol": "usuario", "texto": pregunta})

    # Se suma la pregunta anterior para que funcionen los "¿y eso qué significa?"
    preguntas_previas = [m["texto"] for m in st.session_state.historial if m["rol"] == "usuario"]
    consulta = " ".join(preguntas_previas[-1:] + [pregunta])
    resultados = buscador.buscar(consulta, cantidad_fragmentos)
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


if pagina == PAGINA_REPOSITORIO:
    pagina_repositorio()
else:
    pagina_consultas()
