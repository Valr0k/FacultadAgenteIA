# DocuGuía

Asistente de IA que responde preguntas con los documentos guardados en su repositorio (PDF, Word, PowerPoint o texto) y cita el archivo y la ubicación de cada dato para que puedas verificarlo a mano. Los documentos quedan guardados para las próximas consultas. Solo busca en la web si el usuario lo autoriza.

## Secciones de la app

- **💬 Consultas:** el chat. Usa todos los documentos guardados que estén marcados como "Usar en consultas".
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
3. **Recuperación (RAG):** ante cada pregunta, un buscador TF-IDF (`scikit-learn`) elige los 8 fragmentos más relevantes. Es gratis y no gasta cuota de la API.
4. **Generación:** Gemini recibe el system prompt (`prompt_sistema.txt`), los fragmentos con sus encabezados `Documento | Ubicación` y la pregunta. El prompt lo obliga a citar cada dato.
5. **Transparencia:** debajo de cada respuesta se ve el desplegable "Fragmentos consultados" con lo que realmente leyó el modelo.
6. **Búsqueda web con permiso:** si la pregunta es del tema pero la respuesta no está en los documentos, el modelo responde con la etiqueta `[SIN_INFORMACION]`. La app la detecta, muestra un aviso y dos botones: **Sí, buscar en la web** / **No, gracias**.
   - Solo si el usuario acepta, se hace una segunda consulta a Gemini con la herramienta **Google Search** activada y con otro prompt (`prompt_web.txt`).
   - La respuesta web se marca con un cartel azul, empieza con una advertencia de "corroborá esta información" y muestra la lista de links consultados.
   - Si la pregunta está fuera del tema de los documentos, no se ofrece buscar: se rechaza.

## Archivos

| Archivo | Qué contiene |
|---|---|
| `app.py` | Interfaz (Streamlit): páginas de Consultas y Repositorio, llamadas a Gemini |
| `almacen.py` | Guardado de documentos en GitHub (o en una carpeta local para pruebas) |
| `documentos.py` | Lectura de PDF, Word, PowerPoint y texto; fragmentación y búsqueda |
| `prompt_sistema.txt` | System prompt con los 6 bloques de la guía. **Editalo para iterar**, sin tocar el código |
| `prompt_web.txt` | Prompt que se usa solo cuando el usuario autoriza la búsqueda web |
| `requirements.txt` | Librerías necesarias |

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

1. Subí los archivos de la app al repositorio público (`app.py`, `almacen.py`, `documentos.py`, `prompt_sistema.txt`, `prompt_web.txt`, `requirements.txt`, `README.md`).
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

```bash
pip install -r requirements.txt
# Windows (PowerShell):  $env:GEMINI_API_KEY="tu_clave"
# Linux / Mac:           export GEMINI_API_KEY="tu_clave"
# Para probar el ingreso de administrador, definí también ADMIN_USUARIO y ADMIN_CLAVE de la misma forma.
streamlit run app.py
```

Sin las variables de GitHub, los documentos se guardan en la carpeta `almacen_documentos/` junto a `app.py`.

## Ajustes útiles

- **Modelo:** por defecto usa `gemini-flash-latest`. Si da error de modelo, cambialo en *Opciones avanzadas* (barra lateral) por uno que figure como gratuito en la página de precios de Gemini.
- **Fragmentos por consulta:** más fragmentos = más contexto, pero más consumo. Con 8 suele alcanzar.
- **Error de límite (429):** el plan gratuito limita pedidos por minuto y por día. Esperá y reintentá.
- **Tamaño máximo de archivo:** agregá `TAMANIO_MAXIMO_MB = "80"` (o el número que quieras, hasta 95) en los Secrets. Para documentos más grandes conviene dividirlos (por ejemplo, un PDF por capítulo): además de entrar en el límite, la búsqueda funciona mejor y la app usa menos memoria.
- **Documentos subidos directo a GitHub:** también podés subir archivos a mano al repositorio privado, dentro de la carpeta del formato correcto. Después tocá **🔄 Actualizar lista** en la app.

## Limitaciones conocidas (para la sección de reflexión)

- **Hay un solo usuario administrador** con contraseña fija. Alcanza para el TP; en un uso real habría que tener un usuario por persona, contraseñas guardadas cifradas y registro de quién subió o borró cada documento. Cualquiera con el link de la app puede ver y descargar los documentos.
- La sesión de administrador dura mientras la pestaña del navegador esté abierta: al recargar la página hay que volver a ingresar.
- Los PDF escaneados (imágenes) y las diapositivas que son solo imágenes no tienen texto: la app avisa cuántas no pudo leer.
- El número de página es el **del archivo PDF**, que puede no coincidir con el número impreso en la hoja.
- Word no guarda números de página fijos: la página se estima con las marcas que Word deja al guardar, por eso dice "aprox.". Los .docx generados por Google Docs u otros programas a veces no traen esas marcas; en ese caso se cita por sección y párrafo.
- No se leen imágenes, gráficos ni texto dentro de imágenes en ningún formato.
- TF-IDF busca por palabras: si la pregunta usa sinónimos que no aparecen en el texto, puede no encontrar el fragmento. Una mejora futura es usar *embeddings*.
- La conversación (el chat) no se guarda: al recargar la página empieza de cero. Los documentos sí quedan guardados.
- GitHub no acepta archivos de más de 100 MB, y avisa que los de más de 50 MB son "grandes". Streamlit Community Cloud tiene memoria limitada: muchos archivos muy pesados pueden hacer que la app se reinicie.
- Con muchos documentos, la primera consulta después de que la app se "despierta" tarda más, porque tiene que descargar y leer todo de nuevo.
- En el plan gratuito de la API, Google puede usar los datos enviados para mejorar sus modelos: no subas documentos con datos personales.
- La búsqueda web (Grounding with Google Search) tiene su propio cupo gratuito, más chico que el de las consultas normales. Revisá el límite vigente en la página de precios de Gemini.
- Los links que devuelve Google Search a veces pasan por una dirección intermedia de Google (`vertexaisearch...`) que redirige a la página real: al hacer clic se abre el sitio original.
- La detección de "no está en los documentos" depende de que el modelo use la etiqueta `[SIN_INFORMACION]`; si alguna vez no la usa, no aparecen los botones. Es un buen caso para documentar en las pruebas.
