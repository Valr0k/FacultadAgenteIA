"""
Módulo de documentos: lectura de archivos, división en fragmentos y búsqueda.

Formatos soportados:
- PDF (.pdf)             -> cita por página
- Word (.docx)           -> cita por sección (título) y página aproximada
- PowerPoint (.pptx)     -> cita por diapositiva
- Texto (.txt, .md)      -> cita por rango de líneas

Cada fragmento guarda el nombre del archivo y su ubicación dentro de él,
para que el asistente pueda citar la fuente exacta y el usuario la busque a mano.

OCR (reconocimiento de texto en imágenes): las páginas de PDF y las diapositivas
que son imágenes (por ejemplo, presentaciones exportadas como fotos) se leen
con Tesseract. Si Tesseract no está instalado, se avisa y se siguen leyendo
las páginas que tienen texto.
"""

import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

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

EXTENSIONES_SOPORTADAS = ["pdf", "docx", "pptx", "txt", "md"]

# Si cambia la forma de leer los documentos, se sube este número y el texto
# guardado de lecturas anteriores se descarta y se vuelve a generar.
VERSION_LECTOR = "2-ocr"

# ---------- OCR ----------
MINIMO_TEXTO_SIN_OCR = 100   # si una página/diapositiva tiene menos caracteres, se le aplica OCR
ESCALA_OCR = 2               # resolución al convertir la página en imagen (2 = ~150 ppp)
IDIOMAS_OCR = "spa+eng"      # español e inglés (muchos gráficos científicos están en inglés)
MAXIMO_PAGINAS_OCR = 300     # límite de seguridad para no dejar la app trabada


@dataclass
class Fragmento:
    archivo: str
    ubicacion: str   # por ejemplo: "pág. 3", "diapositiva 5", "líneas 10–40"
    texto: str

    def cita(self) -> str:
        return f"{self.archivo}, {self.ubicacion}"


@dataclass
class Unidad:
    """Una parte mínima de un documento (un párrafo, una línea, una tabla)
    con los datos necesarios para ubicarla después."""
    numero: int
    texto: str
    seccion: str | None = None
    pagina: int | None = None


# =====================================================================
# Utilidades de texto
# =====================================================================

def limpiar_texto(texto: str) -> str:
    """Quita espacios repetidos y saltos de línea innecesarios."""
    texto = texto.replace("\x00", " ")
    texto = re.sub(r"-\n(\w)", r"\1", texto)      # une palabras cortadas con guion
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def dividir_texto(texto: str) -> list[str]:
    """Divide un texto largo en partes con solapamiento,
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


def limpiar_texto_ocr(texto: str) -> str:
    """El OCR de diagramas y fórmulas devuelve líneas de ruido ('qa qa', 'CHa',
    '[oo] ¡o'). Se quedan solo las líneas que parecen texto: con al menos una
    palabra de 3 letras y mayoría de letras."""
    lineas_utiles = []
    for linea in texto.splitlines():
        linea = linea.strip(" |*•·-_~")
        letras = sum(c.isalpha() for c in linea)
        tiene_palabra = re.search(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ]{3,}", linea)
        if tiene_palabra and letras >= 4 and letras / max(len(linea), 1) >= 0.6:
            lineas_utiles.append(linea)
    return limpiar_texto(" ".join(lineas_utiles))


class LectorOCR:
    """Envuelve Tesseract. Si no está instalado, queda desactivado y lo avisa
    una sola vez, sin cortar la lectura del documento."""

    def __init__(self):
        self.disponible = True
        self.motivo = ""
        self.paginas_leidas = 0
        try:
            import pytesseract
            pytesseract.get_tesseract_version()
            idiomas = set(pytesseract.get_languages(config=""))
            self.idiomas = "+".join(i for i in IDIOMAS_OCR.split("+") if i in idiomas) or "eng"
            self.pytesseract = pytesseract
        except Exception:
            self.disponible = False
            self.motivo = ("no se pudo aplicar OCR porque Tesseract no está instalado "
                           "(en Streamlit Cloud se instala con packages.txt).")

    def leer_imagen(self, imagen) -> str:
        if not self.disponible or self.paginas_leidas >= MAXIMO_PAGINAS_OCR:
            return ""
        self.paginas_leidas += 1
        try:
            texto = self.pytesseract.image_to_string(imagen.convert("L"), lang=self.idiomas)
        except Exception:
            return ""
        return limpiar_texto_ocr(texto)

    def avisos(self, unidad: str) -> list[str]:
        if not self.disponible:
            return [self.motivo]
        if self.paginas_leidas:
            return [f"{self.paginas_leidas} {unidad} leída(s) con OCR (reconocimiento de texto "
                    "en imágenes): el texto puede tener errores de lectura."]
        return []


def rango(desde: int, hasta: int) -> str:
    return str(desde) if desde == hasta else f"{desde}–{hasta}"


def rango_con_nombre(singular: str, plural: str, desde: int, hasta: int) -> str:
    """Ej.: 'párrafo 3' o 'párrafos 3–7'."""
    return f"{singular} {desde}" if desde == hasta else f"{plural} {desde}–{hasta}"


def agrupar_unidades(archivo: str, unidades: list[Unidad],
                     describir_ubicacion) -> list[Fragmento]:
    """Junta unidades chicas (párrafos, líneas) hasta llegar al tamaño de un
    fragmento. Corta también cuando cambia la sección, para no mezclar temas.
    `describir_ubicacion(grupo)` arma el texto de la ubicación para la cita."""
    fragmentos = []
    grupo: list[Unidad] = []
    largo = 0

    def cerrar_grupo():
        if not grupo:
            return
        texto = " ".join(u.texto for u in grupo)
        ubicacion = describir_ubicacion(grupo)
        for parte in dividir_texto(texto):
            fragmentos.append(Fragmento(archivo=archivo, ubicacion=ubicacion, texto=parte))

    for unidad in unidades:
        cambia_seccion = grupo and unidad.seccion != grupo[-1].seccion
        if grupo and (largo + len(unidad.texto) > TAMANIO_FRAGMENTO or cambia_seccion):
            cerrar_grupo()
            grupo, largo = [], 0
        grupo.append(unidad)
        largo += len(unidad.texto) + 1
    cerrar_grupo()
    return fragmentos


# =====================================================================
# Lectores por formato
# Cada uno devuelve (fragmentos, avisos). Los avisos se muestran al usuario.
# =====================================================================

def leer_pdf(nombre: str, contenido: bytes) -> tuple[list[Fragmento], list[str]]:
    """PDF: se lee página por página. La cita es el número de página del archivo.
    Las páginas con poco o nada de texto (imágenes) se leen con OCR."""
    lector = PdfReader(io.BytesIO(contenido))
    ocr = LectorOCR()
    documento_imagen = None   # se abre solo si alguna página necesita OCR
    fragmentos = []
    paginas_vacias = 0
    for numero, pagina in enumerate(lector.pages, start=1):
        try:
            texto = limpiar_texto(pagina.extract_text() or "")
        except Exception:
            texto = ""
        ubicacion = f"pág. {numero}"

        if len(texto) < MINIMO_TEXTO_SIN_OCR and ocr.disponible:
            try:
                if documento_imagen is None:
                    import pypdfium2
                    documento_imagen = pypdfium2.PdfDocument(contenido)
                imagen = documento_imagen[numero - 1].render(scale=ESCALA_OCR).to_pil()
                texto_ocr = ocr.leer_imagen(imagen)
                del imagen   # libera memoria enseguida
            except Exception:
                texto_ocr = ""
            if texto_ocr:
                texto = f"{texto} {texto_ocr}".strip()
                ubicacion = f"pág. {numero} (texto de imagen)"

        if len(texto) < 20:
            paginas_vacias += 1
            continue
        for parte in dividir_texto(texto):
            fragmentos.append(Fragmento(archivo=nombre, ubicacion=ubicacion, texto=parte))

    if documento_imagen is not None:
        documento_imagen.close()   # libera la memoria del PDF abierto para el OCR

    avisos = ocr.avisos("página(s)")
    if paginas_vacias:
        avisos.append(f"{paginas_vacias} página(s) sin texto legible.")
    return fragmentos, avisos


def es_titulo(parrafo) -> bool:
    """Detecta si un párrafo de Word usa un estilo de título."""
    try:
        estilo = (parrafo.style.name or "").lower()
    except Exception:
        return False
    return estilo.startswith(("heading", "título", "titulo", "title"))


def contar_saltos_de_pagina(elemento) -> int:
    """Word guarda marcas donde terminó cada página la última vez que se abrió
    el archivo. Contarlas permite estimar el número de página."""
    return len(elemento.xpath('.//w:lastRenderedPageBreak | .//w:br[@w:type="page"]'))


def texto_de_tabla(tabla) -> str:
    """Convierte una tabla de Word en texto, fila por fila."""
    filas = []
    for fila in tabla.rows:
        celdas = []
        for celda in fila.cells:
            texto = limpiar_texto(celda.text)
            if texto and (not celdas or celdas[-1] != texto):   # evita celdas combinadas repetidas
                celdas.append(texto)
        if celdas:
            filas.append(" | ".join(celdas))
    return "Tabla: " + " / ".join(filas) if filas else ""


def leer_docx(nombre: str, contenido: bytes) -> tuple[list[Fragmento], list[str]]:
    """Word: se recorren párrafos y tablas en orden.
    Como Word no guarda números de página fijos, se cita la sección (último
    título) y una página aproximada si el archivo tiene las marcas necesarias."""
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    documento = Document(io.BytesIO(contenido))
    unidades = []
    seccion_actual = None
    pagina_actual = 1
    hay_marcas_de_pagina = False
    numero_parrafo = 0

    for elemento in documento.element.body.iterchildren():
        etiqueta = elemento.tag.split("}")[-1]
        if etiqueta == "p":
            bloque = Paragraph(elemento, documento)
            texto = limpiar_texto(bloque.text)
        elif etiqueta == "tbl":
            bloque = Table(elemento, documento)
            texto = texto_de_tabla(bloque)
        else:
            continue

        pagina_inicio = pagina_actual
        saltos = contar_saltos_de_pagina(elemento)
        if saltos:
            hay_marcas_de_pagina = True
            pagina_actual += saltos

        if not texto:
            continue
        if etiqueta == "p" and es_titulo(bloque):
            seccion_actual = texto[:80]
        numero_parrafo += 1
        unidades.append(Unidad(numero=numero_parrafo, texto=texto,
                               seccion=seccion_actual, pagina=pagina_inicio))

    def describir(grupo: list[Unidad]) -> str:
        partes = []
        if hay_marcas_de_pagina:
            partes.append(f"pág. aprox. {rango(grupo[0].pagina, grupo[-1].pagina)}")
        if grupo[0].seccion:
            partes.append(f"sección «{grupo[0].seccion}»")
        partes.append(rango_con_nombre("párrafo", "párrafos", grupo[0].numero, grupo[-1].numero))
        return ", ".join(partes)

    avisos = []
    if not unidades:
        avisos.append("no tiene texto legible.")
    elif not hay_marcas_de_pagina:
        avisos.append("no trae información de páginas: se citará por sección y número de párrafo.")
    return agrupar_unidades(nombre, unidades, describir), avisos


def textos_de_formas(formas) -> list[str]:
    """Saca el texto de las formas de una diapositiva (cuadros de texto,
    tablas y grupos de formas)."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    textos = []
    for forma in formas:
        if forma.shape_type == MSO_SHAPE_TYPE.GROUP:
            textos.extend(textos_de_formas(forma.shapes))
        elif getattr(forma, "has_table", False) and forma.has_table:
            filas = [" | ".join(limpiar_texto(c.text) for c in fila.cells if c.text.strip())
                     for fila in forma.table.rows]
            textos.append("Tabla: " + " / ".join(f for f in filas if f))
        elif getattr(forma, "has_text_frame", False) and forma.has_text_frame:
            texto = limpiar_texto(forma.text_frame.text)
            if texto:
                textos.append(texto)
    return textos


def imagenes_de_formas(formas) -> list:
    """Devuelve las imágenes de una diapositiva (incluidas las de grupos)."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    imagenes = []
    for forma in formas:
        if forma.shape_type == MSO_SHAPE_TYPE.GROUP:
            imagenes.extend(imagenes_de_formas(forma.shapes))
        elif forma.shape_type == MSO_SHAPE_TYPE.PICTURE:
            imagenes.append(forma)
    return imagenes


def leer_pptx(nombre: str, contenido: bytes) -> tuple[list[Fragmento], list[str]]:
    """PowerPoint: se lee diapositiva por diapositiva, incluyendo las notas
    del orador. La cita es el número de diapositiva. Si una diapositiva tiene
    poco texto, se aplica OCR a sus imágenes."""
    from pptx import Presentation

    presentacion = Presentation(io.BytesIO(contenido))
    ocr = LectorOCR()
    fragmentos = []
    diapositivas_vacias = 0
    for numero, diapositiva in enumerate(presentacion.slides, start=1):
        textos = textos_de_formas(diapositiva.shapes)
        ubicacion = f"diapositiva {numero}"

        if len(" ".join(textos)) < MINIMO_TEXTO_SIN_OCR and ocr.disponible:
            from PIL import Image
            textos_ocr = []
            for forma in imagenes_de_formas(diapositiva.shapes):
                try:
                    imagen = Image.open(io.BytesIO(forma.image.blob))
                    if imagen.width < 200 or imagen.height < 100:
                        continue   # íconos y logos chicos: no vale la pena
                    texto_ocr = ocr.leer_imagen(imagen)
                except Exception:
                    texto_ocr = ""
                if texto_ocr:
                    textos_ocr.append(texto_ocr)
            if textos_ocr:
                textos.extend(textos_ocr)
                ubicacion = f"diapositiva {numero} (texto de imagen)"

        if diapositiva.has_notes_slide:
            notas = limpiar_texto(diapositiva.notes_slide.notes_text_frame.text or "")
            if notas:
                textos.append(f"Notas del orador: {notas}")
        texto = " ".join(textos)
        if len(texto) < 5:
            diapositivas_vacias += 1
            continue
        for parte in dividir_texto(texto):
            fragmentos.append(Fragmento(archivo=nombre, ubicacion=ubicacion, texto=parte))

    avisos = ocr.avisos("imagen(es) de diapositivas")
    if diapositivas_vacias:
        avisos.append(f"{diapositivas_vacias} diapositiva(s) sin texto legible.")
    return fragmentos, avisos


def decodificar_texto(contenido: bytes) -> str:
    """Prueba las codificaciones más comunes en archivos de texto en español."""
    for codificacion in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return contenido.decode(codificacion)
        except UnicodeDecodeError:
            continue
    return contenido.decode("utf-8", errors="replace")


def leer_texto(nombre: str, contenido: bytes) -> tuple[list[Fragmento], list[str]]:
    """Texto plano: se cita por rango de líneas (se ven en cualquier editor)."""
    lineas = decodificar_texto(contenido).splitlines()
    unidades = [Unidad(numero=i, texto=limpiar_texto(linea))
                for i, linea in enumerate(lineas, start=1) if linea.strip()]

    def describir(grupo: list[Unidad]) -> str:
        return rango_con_nombre("línea", "líneas", grupo[0].numero, grupo[-1].numero)

    avisos = [] if unidades else ["está vacío."]
    return agrupar_unidades(nombre, unidades, describir), avisos


LECTORES = {
    "pdf": leer_pdf,
    "docx": leer_docx,
    "pptx": leer_pptx,
    "txt": leer_texto,
    "md": leer_texto,
}


def leer_documento(nombre: str, contenido: bytes) -> tuple[list[Fragmento], list[str]]:
    """Elige el lector según la extensión del archivo."""
    extension = Path(nombre).suffix.lower().lstrip(".")
    lector = LECTORES.get(extension)
    if lector is None:
        if extension in ("doc", "ppt"):
            return [], [f"el formato viejo .{extension} no se puede leer. Abrilo y "
                        f"guardalo como .{extension}x (Archivo → Guardar como)."]
        return [], [f"formato .{extension} no soportado."]
    try:
        return lector(nombre, contenido)
    except Exception as error:
        return [], [f"no se pudo leer ({error}). Si es un archivo protegido o dañado, "
                    "probá guardarlo de nuevo o exportarlo a PDF."]


# =====================================================================
# Búsqueda
# =====================================================================

class Buscador:
    """Encuentra los fragmentos más parecidos a una pregunta usando TF-IDF.
    Es gratuito, rápido y no gasta cuota de la API.

    Combina dos búsquedas:
    - por palabras completas (precisa), y
    - por partes de palabras de 3 a 5 letras (tolerante): así "lípidos"
      encuentra "fosfolípidos", plurales y palabras mal leídas por el OCR
      (por ejemplo "IPIDOS")."""

    PESO_PALABRAS = 0.5
    PESO_PARTES = 0.5
    PUNTAJE_MINIMO = 0.05   # por debajo, el fragmento se considera no relacionado

    def __init__(self, fragmentos: list[Fragmento]):
        self.fragmentos = fragmentos
        textos = [f.texto for f in fragmentos]
        self.por_palabras = TfidfVectorizer(
            strip_accents="unicode", lowercase=True, stop_words=PALABRAS_VACIAS,
            ngram_range=(1, 2), sublinear_tf=True,
        )
        self.por_partes = TfidfVectorizer(
            strip_accents="unicode", lowercase=True, analyzer="char_wb",
            ngram_range=(3, 5), sublinear_tf=True,
        )
        self.matriz_palabras = self.por_palabras.fit_transform(textos)
        self.matriz_partes = self.por_partes.fit_transform(textos)

    def quitar_palabras_vacias(self, consulta: str) -> str:
        """Para la búsqueda por partes se sacan palabras como 'qué' o 'los',
        que aparecen en todos lados y no ayudan a encontrar el tema."""
        palabras = re.findall(r"\w+", consulta.lower())
        normalizar = self.por_palabras.build_preprocessor()
        utiles = [p for p in palabras if normalizar(p) not in PALABRAS_VACIAS]
        return " ".join(utiles) or consulta

    def buscar(self, consulta: str, cantidad: int = 8) -> list[tuple[Fragmento, float]]:
        puntajes_palabras = cosine_similarity(
            self.por_palabras.transform([consulta]), self.matriz_palabras)[0]
        puntajes_partes = cosine_similarity(
            self.por_partes.transform([self.quitar_palabras_vacias(consulta)]), self.matriz_partes)[0]
        puntajes = self.PESO_PALABRAS * puntajes_palabras + self.PESO_PARTES * puntajes_partes
        orden = puntajes.argsort()[::-1][:cantidad]
        return [(self.fragmentos[i], float(puntajes[i])) for i in orden
                if puntajes[i] >= self.PUNTAJE_MINIMO]


# =====================================================================
# Conversión para guardar el texto extraído (y no repetir el OCR)
# =====================================================================

def lectura_a_diccionario(fragmentos: list[Fragmento], avisos: list[str]) -> dict:
    return {"version_lector": VERSION_LECTOR,
            "fragmentos": [asdict(f) for f in fragmentos],
            "avisos": avisos}


def lectura_desde_diccionario(datos: dict) -> tuple[list[Fragmento], list[str]] | None:
    """Devuelve None si el texto guardado es de una versión anterior del lector."""
    if not isinstance(datos, dict) or datos.get("version_lector") != VERSION_LECTOR:
        return None
    try:
        fragmentos = [Fragmento(**f) for f in datos["fragmentos"]]
    except (KeyError, TypeError):
        return None
    return fragmentos, list(datos.get("avisos", []))


def armar_contexto(resultados: list[tuple[Fragmento, float]]) -> str:
    """Convierte los fragmentos encontrados en el texto que recibe el modelo."""
    if not resultados:
        return "NO SE ENCONTRARON FRAGMENTOS RELEVANTES EN LOS DOCUMENTOS."
    bloques = []
    for i, (fragmento, _) in enumerate(resultados, start=1):
        bloques.append(
            f"[Fragmento {i}] Documento: {fragmento.archivo} | Ubicación: {fragmento.ubicacion}\n"
            f"{fragmento.texto}"
        )
    return "\n\n".join(bloques)
