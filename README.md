# DocuGuía

Asistente de IA que responde preguntas con los documentos que subís (PDF, Word, PowerPoint o texto) y cita el archivo y la ubicación de cada dato para que puedas verificarlo a mano. Solo busca en la web si el usuario lo autoriza.

## Formatos soportados y cómo se citan

| Formato | Cómo se cita | Ejemplo |
|---|---|---|
| PDF (`.pdf`) | Página del archivo | `apunte.pdf, pág. 4` |
| PowerPoint (`.pptx`) | Diapositiva (incluye tablas, grupos y notas del orador) | `clase3.pptx, diapositiva 7` |
| Word (`.docx`) | Página aproximada, sección (último título) y párrafo | `informe.docx, pág. aprox. 2, sección «Metodología», párrafos 10–14` |
| Texto (`.txt`, `.md`) | Rango de líneas | `notas.txt, líneas 20–35` |

Los formatos viejos `.doc` y `.ppt` no se pueden leer: hay que abrirlos y guardarlos como `.docx` o `.pptx`.

## Cómo funciona (para explicar en el informe)

1. **Lectura:** cada archivo se lee con la librería de su formato (`pypdf`, `python-docx`, `python-pptx`). El texto se divide en fragmentos de ~1200 caracteres, y cada uno guarda su archivo y su ubicación (página, diapositiva, sección o líneas).
2. **Recuperación (RAG):** ante cada pregunta, un buscador TF-IDF (`scikit-learn`) elige los 8 fragmentos más relevantes. Es gratis y no gasta cuota de la API.
3. **Generación:** Gemini recibe el system prompt (`prompt_sistema.txt`), los fragmentos con sus encabezados `Documento | Página` y la pregunta. El prompt lo obliga a citar `(Fuente: archivo.pdf, pág. N)`.
4. **Transparencia:** debajo de cada respuesta se ve el desplegable "Fragmentos consultados" con lo que realmente leyó el modelo.
5. **Búsqueda web con permiso:** si la pregunta es del tema pero la respuesta no está en los documentos, el modelo responde con la etiqueta `[SIN_INFORMACION]`. La app la detecta, muestra un aviso y dos botones: **Sí, buscar en la web** / **No, gracias**.
   - Solo si el usuario acepta, se hace una segunda consulta a Gemini con la herramienta **Google Search** activada y con otro prompt (`prompt_web.txt`).
   - La respuesta web se marca con un cartel azul, empieza con una advertencia de "corroborá esta información" y muestra la lista de links consultados.
   - Si la pregunta está fuera del tema de los documentos, no se ofrece buscar: se rechaza.

En el modo normal el asistente no tiene herramienta de búsqueda web: solo ve los fragmentos que le pasa la app. La búsqueda web es una herramienta aparte que solo se activa con el botón.

## Archivos

| Archivo | Qué contiene |
|---|---|
| `app.py` | Interfaz de chat (Streamlit) y llamada a Gemini |
| `documentos.py` | Lectura de PDF, Word, PowerPoint y texto; fragmentación y búsqueda |
| `prompt_sistema.txt` | System prompt con los 6 bloques de la guía. **Editalo para iterar**, sin tocar el código |
| `prompt_web.txt` | Prompt que se usa solo cuando el usuario autoriza la búsqueda web |
| `requirements.txt` | Librerías necesarias |

## 1. Conseguir la clave de Gemini (gratis)

1. Entrá a https://aistudio.google.com con tu cuenta de Google.
2. Botón **Get API key** → **Create API key**.
3. Copiala y guardala. **No la subas a GitHub.**

## 2. Probar en tu computadora (opcional)

```bash
pip install -r requirements.txt
# Windows (PowerShell):  $env:GEMINI_API_KEY="tu_clave"
# Linux / Mac:           export GEMINI_API_KEY="tu_clave"
streamlit run app.py
```

## 3. Publicar gratis en Streamlit Community Cloud

1. Creá un repositorio en GitHub y subí los archivos (`app.py`, `documentos.py`, `prompt_sistema.txt`, `prompt_web.txt`, `requirements.txt`).
2. Entrá a https://share.streamlit.io con tu cuenta de GitHub → **Create app**.
3. Elegí el repositorio y como archivo principal `app.py`.
   (Si la app ya estaba publicada, al actualizar `requirements.txt` Streamlit reinstala las librerías solo; puede tardar unos minutos más que lo habitual.)
4. En **Advanced settings → Secrets** pegá:
   ```
   GEMINI_API_KEY = "tu_clave"
   ```
5. **Deploy**. Te da un link público para la demo.

Alternativa: Hugging Face Spaces. Ahí la clave se carga en *Settings → Variables and secrets* con el nombre `GEMINI_API_KEY`; la app la lee igual.

> Los pasos de las plataformas pueden cambiar: verificalos en su documentación oficial el día que publiques.

## Ajustes útiles

- **Modelo:** por defecto usa `gemini-flash-latest`. Si da error de modelo, cambialo en *Opciones avanzadas* (barra lateral) por uno que figure como gratuito en la página de precios de Gemini.
- **Fragmentos por consulta:** más fragmentos = más contexto, pero más consumo. Con 8 suele alcanzar.
- **Error de límite (429):** el plan gratuito limita pedidos por minuto y por día. Esperá y reintentá.

## Limitaciones conocidas (para la sección de reflexión)

- Los PDF escaneados (imágenes) y las diapositivas que son solo imágenes no tienen texto: la app avisa cuántas no pudo leer.
- El número de página es el **del archivo PDF**, que puede no coincidir con el número impreso en la hoja.
- Word no guarda números de página fijos: la página se estima con las marcas que Word deja al guardar, por eso dice "aprox.". Los .docx generados por Google Docs u otros programas a veces no traen esas marcas; en ese caso se cita por sección y párrafo.
- No se leen imágenes, gráficos ni texto dentro de imágenes en ningún formato.
- TF-IDF busca por palabras: si la pregunta usa sinónimos que no aparecen en el texto, puede no encontrar el fragmento. Una mejora futura es usar *embeddings*.
- Los documentos se guardan solo durante la sesión: al recargar la página hay que subirlos de nuevo.
- En el plan gratuito de la API, Google puede usar los datos enviados para mejorar sus modelos: no subas documentos con datos personales.
- La búsqueda web (Grounding with Google Search) tiene su propio cupo gratuito, más chico que el de las consultas normales. Revisá el límite vigente en la página de precios de Gemini.
- Los links que devuelve Google Search a veces pasan por una dirección intermedia de Google (`vertexaisearch...`) que redirige a la página real: al hacer clic se abre el sitio original.
- La detección de "no está en los documentos" depende de que el modelo use la etiqueta `[SIN_INFORMACION]`; si alguna vez no la usa, no aparecen los botones. Es un buen caso para documentar en las pruebas.
