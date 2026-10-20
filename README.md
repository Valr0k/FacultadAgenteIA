# DocuGuía

Asistente de IA que responde preguntas **solo** con los PDF que subís, sin buscar en la web, y cita el archivo y la página de cada dato para que puedas verificarlo a mano.

## Cómo funciona (para explicar en el informe)

1. **Lectura:** cada PDF se lee página por página (`pypdf`). El texto se divide en fragmentos de ~1200 caracteres, y cada uno guarda su archivo y número de página.
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
| `documentos.py` | Lectura de PDF, fragmentación y búsqueda |
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

- Los PDF escaneados (imágenes) no tienen texto: la app avisa qué páginas no pudo leer.
- El número de página es el **del archivo PDF**, que puede no coincidir con el número impreso en la hoja.
- TF-IDF busca por palabras: si la pregunta usa sinónimos que no aparecen en el texto, puede no encontrar el fragmento. Una mejora futura es usar *embeddings*.
- Los documentos se guardan solo durante la sesión: al recargar la página hay que subirlos de nuevo.
- En el plan gratuito de la API, Google puede usar los datos enviados para mejorar sus modelos: no subas documentos con datos personales.
- La búsqueda web (Grounding with Google Search) tiene su propio cupo gratuito, más chico que el de las consultas normales. Revisá el límite vigente en la página de precios de Gemini.
- Los links que devuelve Google Search a veces pasan por una dirección intermedia de Google (`vertexaisearch...`) que redirige a la página real: al hacer clic se abre el sitio original.
- La detección de "no está en los documentos" depende de que el modelo use la etiqueta `[SIN_INFORMACION]`; si alguna vez no la usa, no aparecen los botones. Es un buen caso para documentar en las pruebas.
