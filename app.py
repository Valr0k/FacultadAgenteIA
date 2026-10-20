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

from almacen import (CARPETA_POR_FORMATO, ICONO_POR_FORMATO, ErrorDeAlmacen, crear_almacen,
                     limpiar_nombre)
from conversaciones import GestorDeConversaciones, fecha_legible
from documentos import (EXTENSIONES_SOPORTADAS, Buscador, armar_contexto, leer_documento,
                        lectura_a_diccionario, lectura_desde_diccionario)

# ---------- Configuración general ----------
MODELO_POR_DEFECTO = "gemini-flash-latest"   # alias que apunta al Flash vigente
# Si el modelo principal está saturado o sin cupo, se prueban estos en orden.
# Se pueden cambiar con el secret MODELOS_DE_RESPALDO (separados por comas).
MODELOS_DE_RESPALDO_POR_DEFECTO = "gemini-flash-lite-latest, gemini-2.5-flash, gemini-2.5-flash-lite"
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


MODELOS_DE_RESPALDO = [
    m.strip() for m in
    (obtener_secreto("MODELOS_DE_RESPALDO") or MODELOS_DE_RESPALDO_POR_DEFECTO).split(",")
    if m.strip()
]


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


def _fecha_de_almacen_py() -> float:
    """Fecha de modificación de almacen.py. Si el archivo cambia (por ejemplo,
    al subir una versión nueva a GitHub), cambia este valor y el almacén se
    vuelve a crear en lugar de seguir usando el viejo guardado en memoria."""
    try:
        return (CARPETA / "almacen.py").stat().st_mtime
    except OSError:
        return 0.0


@st.cache_resource(show_spinner=False)
def _crear_almacen_en_cache(version_codigo: float, tamanio_configurado: str | None):
    return crear_almacen(obtener_secreto, CARPETA_ALMACEN_LOCAL)


def obtener_almacen():
    """Se crea una sola vez y lo comparten todas las sesiones. Se vuelve a crear
    si cambia el código de almacen.py o el secret TAMANIO_MAXIMO_MB."""
    return _crear_almacen_en_cache(_fecha_de_almacen_py(), obtener_secreto("TAMANIO_MAXIMO_MB"))


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
    """Devuelve el texto de un documento dividido en fragmentos.
    1) Si ya se leyó antes (texto guardado en el almacén), se usa eso: es instantáneo.
    2) Si no, se lee el archivo (con OCR si hace falta, puede tardar minutos)
       y el resultado se guarda en el almacén para la próxima vez."""
    almacen_actual = obtener_almacen()
    try:
        guardado = almacen_actual.leer_lectura(_documento)
        resultado = lectura_desde_diccionario(guardado) if guardado else None
        if resultado:
            return resultado
    except Exception:
        pass   # si falla la lectura del texto guardado, se lee el documento de nuevo

    fragmentos, avisos = leer_documento(_documento.nombre, contenido_de(ruta, version, _documento))
    try:
        almacen_actual.guardar_lectura(_documento, lectura_a_diccionario(fragmentos, avisos))
    except Exception:
        pass   # no poder guardarlo no impide usar el documento ahora
    return fragmentos, avisos


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
    texto = str(error)
    if "429" in texto or "RESOURCE_EXHAUSTED" in texto:
        return "Se alcanzó el límite gratuito de la API. Esperá un minuto y volvé a intentar."
    if "503" in texto or "UNAVAILABLE" in texto or "overloaded" in texto.lower():
        return ("Los servidores de Google están saturados en este momento y ningún modelo "
                "pudo responder. Es temporal: esperá unos segundos y volvé a preguntar.")
    if "403" in texto or "PERMISSION_DENIED" in texto:
        return ("Google rechazó la clave de la API (403). Revisá en AI Studio que el proyecto "
                "no esté «Restringido» o creá una clave nueva (ver README).")
    return f"Ocurrió un error al consultar el modelo: {error}"


# Errores pasajeros: conviene esperar un poco y reintentar con el mismo modelo
ERRORES_TEMPORALES = ("503", "UNAVAILABLE", "500", "INTERNAL", "DEADLINE_EXCEEDED", "overloaded")
# Errores de un modelo en particular: conviene pasar directo al siguiente modelo
ERRORES_DEL_MODELO = ("429", "RESOURCE_EXHAUSTED", "404", "NOT_FOUND")
INTENTOS_POR_MODELO = 2
ESPERA_ENTRE_INTENTOS = 2   # segundos


def lista_de_modelos(principal: str) -> list[str]:
    """El modelo elegido primero y después los de respaldo, sin repetir."""
    modelos = []
    for modelo in [principal] + MODELOS_DE_RESPALDO:
        modelo = modelo.strip()
        if modelo and modelo not in modelos:
            modelos.append(modelo)
    return modelos


def generar_con_respaldo(cliente, modelo_principal: str, contenidos, configuracion):
    """Llama a Gemini y, si el modelo está saturado o sin cupo, reintenta y
    prueba con los modelos de respaldo. Devuelve (respuesta, modelo_usado).
    Los errores que no se arreglan cambiando de modelo (clave inválida,
    pedido mal armado) se informan enseguida."""
    ultimo_error = None
    for modelo in lista_de_modelos(modelo_principal):
        for intento in range(1, INTENTOS_POR_MODELO + 1):
            try:
                respuesta = cliente.models.generate_content(
                    model=modelo, contents=contenidos, config=configuracion)
                return respuesta, modelo
            except Exception as error:
                ultimo_error = error
                texto = str(error)
                if any(codigo in texto for codigo in ERRORES_DEL_MODELO):
                    break   # este modelo no va a responder: probar el siguiente
                if not any(codigo in texto for codigo in ERRORES_TEMPORALES):
                    raise   # otro problema (por ejemplo, la clave): no tiene sentido seguir
                if intento < INTENTOS_POR_MODELO:
                    time.sleep(ESPERA_ENTRE_INTENTOS * intento)
    raise ultimo_error


def preguntar_a_documentos(clave: str, modelo: str, historial: list[dict],
                           pregunta: str, contexto: str,
                           nombres_documentos: list[str]) -> tuple[str, str]:
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

    configuracion = types.GenerateContentConfig(
        system_instruction=cargar_prompt(RUTA_PROMPT_DOCUMENTOS),
        temperature=0.2,   # baja: prioriza precisión sobre creatividad
    )
    respuesta, modelo_usado = generar_con_respaldo(cliente, modelo, contenidos, configuracion)
    texto = respuesta.text or "No pude generar una respuesta. Probá reformular la pregunta."
    return texto, modelo_usado


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
                  nombres_documentos: list[str]) -> tuple[str, list[dict], str]:
    """Consulta a Gemini CON la herramienta de Google Search.
    Solo se llama cuando el usuario autorizó la búsqueda con el botón."""
    cliente = genai.Client(api_key=clave)
    mensaje = (
        f"Tema de referencia (documentos del usuario): {', '.join(nombres_documentos)}\n"
        f"PREGUNTA DEL USUARIO: {pregunta}"
    )
    configuracion = types.GenerateContentConfig(
        system_instruction=cargar_prompt(RUTA_PROMPT_WEB),
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2,
    )
    respuesta, modelo_usado = generar_con_respaldo(cliente, modelo, mensaje, configuracion)
    texto = respuesta.text or "No encontré información confiable en la web sobre esa pregunta."
    return texto, extraer_fuentes_web(respuesta), modelo_usado


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

        if mensaje.get("modelo_respaldo"):
            st.caption(f"ℹ️ El modelo principal no estaba disponible (saturado o sin cupo); respondió el modelo de "
                       f"respaldo «{mensaje['modelo_respaldo']}».")


# =====================================================================
# Estado de la sesión
# =====================================================================
valores_iniciales = {
    "historial": [],
    "conversacion_id": None,          # None = conversación nueva, todavía no guardada
    "indice_conversaciones": None,    # lista de conversaciones guardadas (se carga una vez)
    "aviso_conversacion": None,
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
gestor_conversaciones = GestorDeConversaciones(almacen)


# ---------- Conversaciones guardadas ----------

def conversaciones_guardadas(forzar: bool = False) -> list[dict]:
    if forzar or st.session_state.indice_conversaciones is None:
        try:
            st.session_state.indice_conversaciones = gestor_conversaciones.listar()
        except Exception:
            st.session_state.indice_conversaciones = []
    return st.session_state.indice_conversaciones


def guardar_conversacion_actual():
    """Se llama después de cada respuesta. Si falla (por ejemplo, GitHub no
    responde), se avisa pero el chat sigue funcionando."""
    if not any(m["rol"] == "usuario" for m in st.session_state.historial):
        return
    try:
        st.session_state.conversacion_id = gestor_conversaciones.guardar(
            st.session_state.conversacion_id,
            st.session_state.historial,
            st.session_state.pregunta_pendiente_web,
        )
        conversaciones_guardadas(forzar=True)
    except Exception as error:
        st.session_state.aviso_conversacion = f"No se pudo guardar la conversación: {error}"


def nueva_conversacion():
    st.session_state.historial = []
    st.session_state.conversacion_id = None
    st.session_state.pregunta_pendiente_web = None
    st.session_state.pagina = PAGINA_CONSULTAS


def abrir_conversacion(id_conversacion: str):
    try:
        datos = gestor_conversaciones.cargar(id_conversacion)
    except Exception as error:
        datos, st.session_state.aviso_conversacion = None, f"No se pudo abrir la conversación: {error}"
    if not datos:
        st.session_state.aviso_conversacion = (st.session_state.aviso_conversacion
                                               or "La conversación ya no existe.")
        conversaciones_guardadas(forzar=True)
        return
    st.session_state.historial = datos.get("historial", [])
    st.session_state.pregunta_pendiente_web = datos.get("pendiente_web")
    st.session_state.conversacion_id = id_conversacion
    st.session_state.pagina = PAGINA_CONSULTAS


def borrar_conversacion(id_conversacion: str):
    if not st.session_state.es_admin:   # control por seguridad
        return
    try:
        gestor_conversaciones.borrar(id_conversacion)
    except Exception as error:
        st.session_state.aviso_conversacion = f"No se pudo borrar la conversación: {error}"
    if st.session_state.conversacion_id == id_conversacion:
        nueva_conversacion()
    conversaciones_guardadas(forzar=True)


documentos = documentos_guardados()
documentos_activos = [d for d in documentos if d.ruta not in st.session_state.inactivos]

# =====================================================================
# Barra lateral
# =====================================================================
with st.sidebar:
    st.header("📄 DocuGuía")
    pagina = st.radio("Ir a", [PAGINA_CONSULTAS, PAGINA_REPOSITORIO], key="pagina",
                      label_visibility="collapsed")

    # ---------- Conversaciones ----------
    st.divider()
    st.button("➕ Nueva conversación", on_click=nueva_conversacion, use_container_width=True,
              type="primary" if st.session_state.conversacion_id is None else "secondary")
    lista_conversaciones = conversaciones_guardadas()
    if lista_conversaciones:
        st.markdown("**🗂️ Conversaciones guardadas**")
        with st.container(height=min(60 + 52 * len(lista_conversaciones), 330), border=False):
            for conversacion in lista_conversaciones:
                es_la_actual = conversacion["id"] == st.session_state.conversacion_id
                st.button(
                    conversacion.get("titulo", "Sin título"),
                    key=f"conv_{conversacion['id']}",
                    on_click=abrir_conversacion, args=(conversacion["id"],),
                    type="primary" if es_la_actual else "secondary",
                    use_container_width=True,
                    help=f"{fecha_legible(conversacion.get('actualizada'))} · "
                         f"{conversacion.get('preguntas', 0)} pregunta(s)",
                )
    else:
        st.caption("Todavía no hay conversaciones guardadas.")

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
            help=f"Máximo {getattr(almacen, 'maximo_mb', 50)} MB por archivo. Los formatos viejos .doc y .ppt "
                 "no se pueden leer: guardalos como .docx o .pptx. Si subís un archivo con "
                 "el mismo nombre que uno guardado, se reemplaza.",
        )
        st.caption("Las páginas que son imágenes (por ejemplo, presentaciones exportadas a PDF "
                   "como fotos) se leen con OCR al guardar. Puede tardar unos segundos por página, "
                   "pero se hace una sola vez.")
        if st.button("💾 Guardar en el repositorio", type="primary", disabled=not archivos):
            mensajes = []
            guardados = []
            with st.spinner("Guardando..."):
                for archivo in archivos:
                    try:
                        reemplazado = almacen.guardar(archivo.name, archivo.getvalue())
                        accion = "reemplazado" if reemplazado else "guardado"
                        mensajes.append(("ok", f"{archivo.name}: {accion}."))
                        guardados.append(limpiar_nombre(archivo.name))
                    except ErrorDeAlmacen as error:
                        mensajes.append(("error", str(error)))
                    except Exception as error:
                        mensajes.append(("error", f"{archivo.name}: no se pudo guardar ({error})."))

            # Se leen enseguida (con OCR si hace falta) y se guarda el texto extraído,
            # así la primera consulta no tiene que esperar.
            lista = documentos_guardados(forzar=True)
            for documento in [d for d in lista if d.nombre in guardados]:
                with st.spinner(f"Leyendo {documento.nombre}... (si tiene páginas escaneadas "
                                "puede tardar algunos minutos, no cierres la página)"):
                    try:
                        fragmentos, avisos = fragmentos_de(documento.ruta, documento.version, documento)
                        resumen = f"{documento.nombre}: listo para consultas ({len(fragmentos)} fragmentos)."
                        if avisos:
                            resumen += " " + " ".join(avisos)
                        mensajes.append(("ok", resumen))
                    except Exception as error:
                        mensajes.append(("error", f"{documento.nombre}: se guardó, pero no se pudo "
                                                  f"leer ({error})."))

            st.session_state.mensajes_repositorio = mensajes
            st.session_state.clave_subida += 1   # vacía el cuadro de subida
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
    with st.spinner("Preparando documentos... (si hay documentos nuevos con páginas escaneadas, "
                    "la primera vez puede tardar algunos minutos)"):
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

    # ---------- Encabezado de la conversación ----------
    if st.session_state.aviso_conversacion:
        st.warning(st.session_state.aviso_conversacion)
        st.session_state.aviso_conversacion = None
    actual = next((c for c in conversaciones_guardadas()
                   if c["id"] == st.session_state.conversacion_id), None)
    if actual:
        columna_titulo, columna_borrar = st.columns([6, 1])
        columna_titulo.subheader(f"🗂️ {actual.get('titulo', 'Conversación')}")
        columna_titulo.caption(f"Creada {fecha_legible(actual.get('creada'))} · "
                               f"última actividad {fecha_legible(actual.get('actualizada'))}")
        if st.session_state.es_admin:
            with columna_borrar.popover("🗑️", help="Borrar esta conversación"):
                st.write("¿Borrar esta conversación? No se puede deshacer.")
                st.button("Sí, borrar", key="borrar_conversacion", type="primary",
                          on_click=borrar_conversacion, args=(actual["id"],))
    elif not st.session_state.historial:
        st.caption("💡 Nueva conversación: se guarda automáticamente después de la primera "
                   "respuesta y la podés retomar desde la barra lateral.")

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
                    texto, fuentes, modelo_usado = buscar_en_web(clave_api, modelo, pendiente,
                                                                 nombres_documentos)
                    st.session_state.historial.append(
                        {"rol": "asistente", "tipo": "web", "texto": texto, "fuentes_web": fuentes,
                         "modelo_respaldo": modelo_usado if modelo_usado != modelo else None})
                except Exception as error:
                    st.session_state.historial.append(
                        {"rol": "asistente", "tipo": "aviso", "texto": describir_error(error)})
            st.session_state.pregunta_pendiente_web = None
            guardar_conversacion_actual()
            st.rerun()

        if no_buscar:
            st.session_state.historial.append({
                "rol": "asistente",
                "texto": "Entendido, no voy a buscar en la web. Podés hacerme otra pregunta "
                         "sobre tus documentos.",
            })
            st.session_state.pregunta_pendiente_web = None
            guardar_conversacion_actual()
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
            texto, modelo_usado = preguntar_a_documentos(clave_api, modelo, st.session_state.historial,
                                                         pregunta, contexto, nombres_documentos)
            hubo_error = False
        except Exception as error:
            texto, modelo_usado, hubo_error = describir_error(error), modelo, True

    respuesta = {"rol": "asistente", "texto": texto,
                 "modelo_respaldo": modelo_usado if modelo_usado != modelo else None}

    if hubo_error:
        respuesta["tipo"] = "aviso"
    elif MARCADOR_SIN_INFORMACION in texto:
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
    with st.spinner("Guardando la conversación..."):
        guardar_conversacion_actual()
    st.rerun()


if pagina == PAGINA_REPOSITORIO:
    pagina_repositorio()
else:
    pagina_consultas()
