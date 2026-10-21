# DocuGuía

Asistente de IA que responde preguntas con los documentos guardados en su repositorio (PDF, Word, PowerPoint o texto) y cita el archivo y la ubicación de cada dato para que puedas verificarlo a mano. Los documentos quedan guardados para las próximas consultas. Solo busca en la web si el usuario lo autoriza.

## Secciones de la app

- **💬 Consultas:** el chat. Usa todos los documentos guardados que estén marcados como "Usar en consultas".
- **🗂️ Conversaciones guardadas:** cada conversación se guarda sola después de cada respuesta. Desde la barra lateral se puede empezar una **➕ Nueva conversación** o abrir una anterior y seguirla donde quedó (el asistente recuerda lo que se habló en ella). El título es la primera pregunta. Solo el administrador puede borrar conversaciones.
- **📚 Repositorio de documentos:** para ver, descargar y activar/desactivar documentos. Muestra un resumen y una pestaña por formato (PDF, Word, PowerPoint, Texto).
- **🔐 Administrador:** **subir y borrar** documentos requiere ingresar con usuario y contraseña desde la barra lateral. Consultar y descargar es libre.

## Formatos soportados y cómo se citan

| Formato | Cómo se cita | Ejemplo |
|---|---|---|
| PDF (`.pdf`) | Página del archivo | `apunte.pdf, pág. 4` |
| PowerPoint (`.pptx`) | Diapositiva (incluye tablas, grupos y notas del orador) | `clase3.pptx, diapositiva 7` |
| Word (`.docx`) | Página aproximada, sección (último título) y párrafo | `informe.docx, pág. aprox. 2, sección «Metodología», párrafos 10–14` |
| Texto (`.txt`, `.md`) | Rango de líneas | `notas.txt, líneas 20–35` |

Los formatos viejos `.doc` y `.ppt` no se pueden leer: hay que abrirlos y guardarlos como `.docx` o `.pptx`.

**Tamaño máximo por archivo:** 50 MB por defecto. Se puede cambiar con el secret `TAMANIO_MAXIMO_MB` (por ejemplo `TAMANIO_MAXIMO_MB = "80"`), hasta un tope de 95 MB, porque GitHub no acepta archivos de más de 100 MB.

## Cómo funciona (para explicar en el informe)

1. **Almacenamiento:** los documentos se guardan en un repositorio privado de GitHub, en carpetas por formato (`documentos/pdf`, `documentos/word`, `documentos/powerpoint`, `documentos/texto`). Cada subida o borrado queda registrado como un commit, así hay historial de cambios.
2. **Lectura:** cada archivo se lee con la librería de su formato (`pypdf`, `python-docx`, `python-pptx`). El texto se divide en fragmentos de ~1200 caracteres, y cada uno guarda su archivo y su ubicación. Lo leído queda en caché: un documento solo se vuelve a procesar si cambia.
   - **OCR:** las páginas de PDF y las diapositivas que son imágenes (por ejemplo, presentaciones exportadas como fotos) se leen con **Tesseract**, un motor de reconocimiento de texto gratuito que corre en el servidor (no usa la API de Gemini). Se aplica a las páginas con menos de 100 caracteres de texto. La cita indica `pág. 29 (texto de imagen)` para que se sepa que vino de OCR.
   - **Texto guardado:** el OCR tarda unos 3 segundos por página, así que el texto extraído de cada documento se guarda en el almacén (`documentos/_texto_extraido/`). Se hace una sola vez, al subir el documento; si se reemplaza el archivo, se vuelve a leer.
3. **Recuperación (RAG):** ante cada pregunta, un buscador TF-IDF (`scikit-learn`) elige los 8 fragmentos más relevantes. Combina búsqueda por **palabras completas** y por **partes de palabras** (3 a 5 letras), así "lípidos" también encuentra "fosfolípidos", plurales y palabras mal leídas por el OCR. Es gratis y no gasta cuota de la API.
4. **Generación:** Gemini recibe el system prompt (`prompt_sistema.txt`), los fragmentos con sus encabezados `Documento | Ubicación` y la pregunta. El prompt lo obliga a citar cada dato.
5. **Transparencia:** debajo de cada respuesta se ve el desplegable "Fragmentos consultados" con lo que realmente leyó el modelo.
6. **Clasificación de la consulta:** el prompt le pide al modelo que clasifique cada pregunta siguiendo pasos en orden, y que marque su respuesta con una etiqueta. La app lee la etiqueta y decide qué mostrar:

   | Paso | Caso | Etiqueta | Qué hace la app |
   |---|---|---|---|
   | 1 | Consulta médica personal (síntomas, tratamientos, medicamentos, dosis) | `[CONSULTA_MEDICA]` | No responde; muestra 🩺 y recomienda consultar a un médico (y emergencias: 107 / 911). Sin botones web. |
   | 2 | No tiene que ver con los temas de los documentos | `[FUERA_DE_TEMA]` | No responde; muestra 🚫. Sin botones web. |
   | 3 | Del tema y está en los fragmentos | (sin etiqueta) | Responde con citas. |
   | 4 | Del tema pero no está en los fragmentos | `[SIN_INFORMACION]` | Aviso ⚠️ y botones para buscar en la web. |

   Para decidir si una pregunta es "del tema", el modelo recibe los nombres de los documentos y sus **temas principales**, calculados automáticamente con las palabras más importantes de cada documento (TF-IDF). Una pregunta académica sobre salud ("¿qué es el colesterol?") no es una consulta médica personal: se responde con los documentos.
7. **Búsqueda web con permiso:** si la pregunta es del tema pero la respuesta no está en los documentos, el modelo responde con la etiqueta `[SIN_INFORMACION]`. La app la detecta, muestra un aviso y dos botones: **Sí, buscar en la web** / **No, gracias**.
   - Solo si el usuario acepta, la app consulta **en paralelo** tres fuentes gratuitas:
     | Fuente | Qué aporta | Clave |
     |---|---|---|
     | Wikipedia (español; si no hay resultados, inglés) | Explicaciones generales | No hace falta |
     | Europe PMC | Resúmenes de artículos científicos (biología, biomedicina) | No hace falta |
     | Tavily (opcional) | Búsqueda web general | Gratis en tavily.com (1.000 búsquedas/mes, sin tarjeta): secret `TAVILY_API_KEY` |
   - Antes de buscar, Gemini convierte la pregunta en palabras clave en español y en inglés (los artículos científicos están casi todos en inglés). Después, el mismo buscador TF-IDF elige los párrafos más relevantes de todas las fuentes y Gemini redacta la respuesta **solo con ellos**, usando otro prompt (`prompt_web.txt`). Se muestran los links de los textos realmente usados (en Europe PMC, el DOI del artículo) y qué encontró cada fuente. Si una fuente falla, se sigue con las demás.
   - La búsqueda con Google desde la API de Gemini (*Grounding with Google Search*) **solo funciona en el plan pago**. Si se activa la facturación en AI Studio, se puede usar con el secret `MOTOR_BUSQUEDA_WEB = "google"`.
   - La respuesta web se marca con un cartel azul, empieza con una advertencia de "corroborá esta información" y muestra la lista de links consultados.
   - Si la pregunta está fuera del tema de los documentos, no se ofrece buscar: se rechaza.

## Archivos

| Archivo | Qué contiene |
|---|---|
| `app.py` | Interfaz (Streamlit): páginas de Consultas y Repositorio, llamadas a Gemini |
| `almacen.py` | Guardado de documentos en GitHub (o en una carpeta local para pruebas) |
| `conversaciones.py` | Guardado, listado y borrado de conversaciones |
| `documentos.py` | Lectura de PDF, Word, PowerPoint y texto; fragmentación y búsqueda |
| `prompt_sistema.txt` | System prompt con los 6 bloques de la guía. **Editalo para iterar**, sin tocar el código |
| `prompt_web.txt` | Prompt que se usa solo cuando el usuario autoriza la búsqueda web |
| `requirements.txt` | Librerías de Python necesarias |
| `packages.txt` | Programas del sistema que instala Streamlit Cloud (Tesseract para OCR, en español e inglés) |

## 1. Conseguir la clave de Gemini (gratis)

1. Entrá a https://aistudio.google.com con tu cuenta de Google.
2. Botón **Get API key** → **Create API key**.
3. Copiala y guardala. **No la subas a GitHub.**

## 2. Crear el repositorio privado para los documentos

Streamlit Cloud borra los archivos del servidor cada vez que la app se reinicia o se "duerme". Por eso los documentos se guardan en un repositorio de GitHub aparte.

1. En GitHub: **+ → New repository**.
   - Nombre: por ejemplo `FacultadAgenteIA-documentos`.
   - Marcá **Private** (así los documentos no son públicos).
   - Tildá **Add a README file** (el repositorio no puede quedar vacío).
   - **Create repository**.
2. Crear un token para que la app pueda escribir en ese repositorio:
   - Tu foto (arriba a la derecha) → **Settings** → **Developer settings** (abajo de todo) → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
   - **Token name:** `docuguia`. **Expiration:** elegí una fecha posterior a la entrega del TP.
   - **Repository access:** *Only select repositories* → elegí `FacultadAgenteIA-documentos` (solo ese).
   - **Permissions → Repository permissions → Contents:** *Read and write*.
   - **Generate token** y copialo (GitHub lo muestra una sola vez).

> El token da acceso solo a ese repositorio. Igual tratalo como una contraseña: no lo pegues en ningún archivo del repositorio de la app.

## 3. Publicar gratis en Streamlit Community Cloud

1. Subí los archivos de la app al repositorio público (`app.py`, `almacen.py`, `conversaciones.py`, `documentos.py`, `prompt_sistema.txt`, `prompt_web.txt`, `requirements.txt`, `packages.txt`, `README.md`).
2. Entrá a https://share.streamlit.io con tu cuenta de GitHub → **Create app**.
3. Elegí el repositorio de la app y como archivo principal `app.py`.
4. En **Advanced settings → Secrets** pegá (con tus datos):
   ```
   GEMINI_API_KEY = "tu_clave_de_gemini"
   GITHUB_TOKEN = "tu_token_de_github"
   GITHUB_REPO_DOCUMENTOS = "Valr0k/FacultadAgenteIA-documentos"
   ADMIN_USUARIO = "admin"
   ADMIN_CLAVE = "tu_contraseña_de_admin"
   ```
   Si la app ya estaba publicada: en share.streamlit.io, menú **⋮** de la app → **Settings → Secrets**, agregá las líneas nuevas y guardá.

   > El usuario y la contraseña de administrador van **solo** en los Secrets, nunca en el código: el repositorio de la app es público y cualquiera podría leerlos. Si no se configuran, nadie puede subir ni borrar documentos desde la app.
5. **Deploy**. Te da un link público para la demo.

Si no configurás `GITHUB_TOKEN` y `GITHUB_REPO_DOCUMENTOS`, la app funciona igual pero guarda en una carpeta local (`almacen_documentos/`), que en Streamlit Cloud se pierde al reiniciar. La página del repositorio lo avisa.

> Los pasos de las plataformas pueden cambiar: verificalos en su documentación oficial el día que publiques.

## Probar en tu computadora (opcional)

Para que funcione el OCR en tu computadora hay que instalar Tesseract aparte (en Windows: el instalador de "Tesseract at UB Mannheim", tildando el idioma español). Sin Tesseract la app funciona igual, pero no lee las páginas que son imágenes.

```bash
pip install -r requirements.txt
# Windows (PowerShell):  $env:GEMINI_API_KEY="tu_clave"
# Linux / Mac:           export GEMINI_API_KEY="tu_clave"
# Para probar el ingreso de administrador, definí también ADMIN_USUARIO y ADMIN_CLAVE de la misma forma.
streamlit run app.py
```

Sin las variables de GitHub, los documentos se guardan en la carpeta `almacen_documentos/` junto a `app.py`.

## Ajustes útiles

- **Modelo:** por defecto usa `gemini-flash-lite-latest`, el más rápido. Si da error de modelo, cambialo en *Opciones avanzadas* (barra lateral) por uno que figure como gratuito en la página de precios de Gemini.
- **Fragmentos por consulta:** más fragmentos = más contexto, pero más consumo. Con 8 suele alcanzar.
- **Velocidad:** la respuesta se muestra a medida que el modelo la escribe (streaming); se le pide al modelo un nivel de razonamiento bajo (`thinking_level = low`), porque para responder con fragmentos ya elegidos no hace falta más; y la conversación se guarda en GitHub en segundo plano, sin hacer esperar. Si un modelo no empieza a responder en 20 s, se pasa al siguiente sin volver a esperarlo. Debajo de cada respuesta se muestra cuánto tardó (⏱️), cuándo apareció el primer texto, qué modelo respondió y qué intentos fallaron.
- **Modelos de respaldo:** si el modelo principal está saturado (error 503) la app reintenta; si sigue saturado o se quedó sin cupo (error 429), prueba en orden con `gemini-flash-latest`, `gemini-2.5-flash-lite` y `gemini-2.5-flash`. Debajo de la respuesta se indica si respondió un modelo de respaldo. La lista se puede cambiar con el secret `MODELOS_DE_RESPALDO = "modelo1, modelo2"` (los nombres vigentes están en la página de modelos de Gemini).
- **Error 403 "Your project has been denied access" / proyecto "Restringido":** suele pasar con cuentas institucionales (por ejemplo, `@iudpt.edu.ar`). Creá la clave de Gemini con una cuenta personal de Gmail y reemplazala en los Secrets.
- **Error de límite (429):** el plan gratuito limita pedidos por minuto y por día. Esperá y reintentá.
- **Tamaño máximo de archivo:** agregá `TAMANIO_MAXIMO_MB = "80"` (o el número que quieras, hasta 95) en los Secrets. Para documentos más grandes conviene dividirlos (por ejemplo, un PDF por capítulo): además de entrar en el límite, la búsqueda funciona mejor y la app usa menos memoria.
- **Documentos subidos directo a GitHub:** también podés subir archivos a mano al repositorio privado, dentro de la carpeta del formato correcto. Después tocá **🔄 Actualizar lista** en la app.

## Limitaciones conocidas (para la sección de reflexión)

- **Hay un solo usuario administrador** con contraseña fija. Alcanza para el TP; en un uso real habría que tener un usuario por persona, contraseñas guardadas cifradas y registro de quién subió o borró cada documento. Cualquiera con el link de la app puede ver y descargar los documentos.
- La sesión de administrador dura mientras la pestaña del navegador esté abierta: al recargar la página hay que volver a ingresar.
- **OCR:** el texto reconocido en imágenes puede tener errores, sobre todo en títulos con letras decorativas (por ejemplo, "LÍPIDOS" se lee "IPIDOS"), fórmulas químicas, diagramas y texto muy chico. Las fórmulas y los dibujos no se interpretan, solo las palabras.
- El OCR tarda unos 3 segundos por página: un PDF de 60 páginas escaneadas lleva unos 3–4 minutos al subirlo (una sola vez).
- Si Tesseract no está instalado (por ejemplo, al probar en Windows sin instalarlo), las páginas que son imágenes no se leen y la app lo avisa.
- El número de página es el **del archivo PDF**, que puede no coincidir con el número impreso en la hoja.
- Word no guarda números de página fijos: la página se estima con las marcas que Word deja al guardar, por eso dice "aprox.". Los .docx generados por Google Docs u otros programas a veces no traen esas marcas; en ese caso se cita por sección y párrafo.
- Las imágenes dentro de documentos Word no se leen con OCR (solo PDF y PowerPoint).
- TF-IDF busca por palabras y partes de palabras: si la pregunta usa sinónimos que no aparecen en el texto, puede no encontrar el fragmento. Una mejora futura es usar *embeddings*.
- **Las conversaciones son compartidas:** como no hay cuentas de usuario, cualquiera con el link de la app ve y puede continuar todas las conversaciones guardadas. No escribas datos personales en las preguntas. En un uso real, cada usuario debería ver solo las suyas.
- Las conversaciones se guardan en `documentos/_conversaciones/` del repositorio privado. Cada respuesta genera dos commits (la conversación y el índice), así que guardar tarda uno o dos segundos.
- Si dos personas escriben en la misma conversación al mismo tiempo, puede quedar guardada solo la última versión.
- GitHub no acepta archivos de más de 100 MB, y avisa que los de más de 50 MB son "grandes". Streamlit Community Cloud tiene memoria limitada: muchos archivos muy pesados pueden hacer que la app se reinicie.
- Con muchos documentos, la primera consulta después de que la app se "despierta" tarda más, porque tiene que descargar y leer todo de nuevo.
- En el plan gratuito de la API, Google puede usar los datos enviados para mejorar sus modelos: no subas documentos con datos personales.
- La búsqueda web gratuita usa Wikipedia (fuente general, no académica), resúmenes de Europe PMC (investigaciones puntuales, casi siempre en inglés: no son verdades generales) y, si se configura, Tavily (cualquier sitio web). Por eso la respuesta web siempre advierte que hay que corroborarla. La búsqueda con Google requiere el plan pago de Gemini (según la página de precios, 5.000 búsquedas por mes sin cargo y después US$14 cada 1.000).
- (Solo con el motor Google) Los links que devuelve Google Search a veces pasan por una dirección intermedia de Google (`vertexaisearch...`) que redirige a la página real: al hacer clic se abre el sitio original.
- La clasificación (médica, fuera de tema, sin información) la hace el modelo siguiendo el prompt: si alguna vez no pone la etiqueta, la respuesta se muestra como texto normal y no aparecen los botones. Es un buen caso para documentar en las pruebas.
- Si un guardado en segundo plano falla (por ejemplo, GitHub no responde), la app lo avisa en la siguiente interacción y se reintenta con la próxima pregunta.
