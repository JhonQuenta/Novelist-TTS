# Novelist TTS

Aplicación local para convertir EPUB en audiolibros y videos. Los proyectos se guardan en este equipo.

## Iniciar

Abre **iniciar.bat** y mantén su ventana abierta mientras trabajas. La dirección habitual es http://127.0.0.1:8765. Para cerrar el servidor, pulsa Ctrl+C. Si el puerto está ocupado: `.venv\Scripts\python.exe app.py --port 8766`.

Después de actualizar, reinicia el servidor y recarga con Ctrl+F5. Para otra instalación, ejecuta **instalar.bat**; necesita Python de 64 bits (3.10+) e internet. **instalar-supertonic.bat** e **instalar-voces-locales.bat** preparan esos motores; también se pueden preparar desde la interfaz.

## Flujo

1. **Libro y capítulos**: importa un EPUB, selecciona capítulos, un rango o la novela completa. Al guardar ajustes o crear una salida se conserva la selección.
2. **Voz y prueba**: elige una voz, ajusta velocidad, tono y volumen y genera una muestra.
3. **Audio**: elige un único formato, calidad y etiquetas opcionales. Organiza capítulos por archivo o en lotes y pulsa **Crear audio**.
4. **Video**: configura fondo, subtítulos y sus propios lotes. En **Ilustraciones** puedes girar, excluir o configurar las apariciones de las imágenes. Pulsa **Crear video** para obtener MP4 y SRT; no se publica automáticamente.
5. **Trabajos**: consulta progreso, etiquetas de Audio/Video/Prueba, tiempo transcurrido y estimación restante de la etapa actual (narración o exportación de un lote). La estimación se calcula con el trabajo medido; inicialmente muestra «Calculando». La espera en cola se cuenta por separado. Los trabajos antiguos sin fechas de procesamiento muestran «No registrado». Descarga, cancela, reanuda o elimina resultados; eliminar un trabajo conserva libros, modelos y caché.

En **Trabajos → Fragmentos guardados**, «Actualizar espacio» muestra el tamaño de la caché y la parte protegida por conversiones activas o en cola. «Limpiar caché» borra únicamente los archivos de `data/books/<id>/cache/`, incluido el audio nativo de `source/`, de los libros que no estén en uso. Conserva EPUB, imágenes, ajustes, modelos y exportaciones. La caché es compartida entre trabajos del mismo libro; al borrarla se tendrá que generar otra vez el audio necesario para conversiones futuras. No se siguen enlaces ni uniones de directorio y los archivos bloqueados se notifican sin detener el resto de la limpieza. El espacio se consulta al entrar en Trabajos y al solicitarlo, sin recorrer todos los archivos durante cada actualización de progreso.

Audio y Video comparten la voz elegida, pero conservan sus ajustes y lotes separados. La portada del audio puede ser la del EPUB, otra imagen del libro o un PNG/JPEG/WebP de tu PC; no cambia el fondo del video.

## Voces disponibles

| Motor | Uso |
|---|---|
| Supertonic 3 | Local; cinco voces masculinas y cinco femeninas en español |
| Microsoft Natural local | Jorge y Dalia (México), Álvaro y Elvira (España) |
| Microsoft Edge | Online; envía el texto a Microsoft |
| Google Traductor | Online; envía el texto a Google; voz distinta de Chrome |

Todos los motores del selector permiten exportar audio. Edge y Google Traductor utilizan integraciones no oficiales y pueden cambiar o aplicar límites. Las voces clásicas SAPI/OneCore se conservan internamente únicamente para trabajos antiguos; no aparecen en el selector. Kokoro y MeloTTS están retirados.

Microsoft Natural local usa paquetes compatibles aislados (Jorge 1.0.2.0; las otras tres voces 1.0.3.0) con Speech SDK 1.41.1. No reemplaza los paquetes de Narrador ni registra un adaptador en Windows. Los paquetes recientes instalados en Windows no funcionaron con este runtime.

Supertonic utiliza modelos locales completos de unos 401 MB, con revisión fijada a `aafc6e32416a594460b32413efc49d7fe4ce6d46`. La primera generación carga los modelos y tarda más. El código auxiliar procede de [Supertonic](https://github.com/supertone-oss-archive/supertonic), bajo MIT; su licencia se conserva en `novelavoz/SUPERTONIC_CODE_LICENSE.txt`. Los modelos archivados usan OpenRAIL-M y conservan su licencia en sus datos. El proyecto original está archivado.

## Audio y calidad

| Formato | Bitrates disponibles |
|---|---|
| MP3 | 64, 96, 128, 192, 256 y 320 kbps |
| M4A/AAC | 48, 64, 96, 128, 192 y 256 kbps objetivo |
| Opus | 24, 32, 48, 64, 96 y 128 kbps objetivo |

Más bitrate ocupa más espacio y no recupera detalle que no exista en la voz. MP3 por encima de 160 kbps utiliza salida de 44,1 kHz; AAC por encima de 128 kbps usa 48 kHz.

**Incrustar letras dentro del audio**, **Guardar también un archivo LRC aparte** y portada son opciones independientes. Las dos primeras vienen activadas: desmarcar el LRC no elimina las letras incrustadas. MP3 usa ID3v2.3, APIC, USLT y SYLT; M4A y Opus guardan portada y texto LRC en sus etiquetas. Se conserva Unicode, incluidas ñ/Ñ, vocales con tilde, diéresis y signos españoles. Su visualización depende del reproductor. Para un LRC aparte, copia audio y LRC con el mismo nombre a la misma carpeta del móvil. Poweramp aún requiere comprobación física.

El selector **Compresión del audio (bitrate)** muestra una estimación de MB por hora. Los kbps describen la codificación de salida, no la naturalidad ni la resolución original del motor. La aplicación prepara la narración en mono a 24 kHz antes de codificar; aumentar frecuencia de salida o bitrate no recupera frecuencias descartadas. Una exportación MP3 de 320 kbps es válida, pero en narración suele aumentar mucho el tamaño con escasa ventaja perceptible. Las opciones máximas configuradas son MP3 320, M4A 256 y Opus 128 kbps; no son una escala de calidad equivalente entre códecs ni los máximos técnicos de todos ellos.

Video genera H.264 720p a 24 fps con audio AAC, fondo, ilustraciones y subtítulos visibles, además de SRT separado. La duración inicial de las ilustraciones es 20 segundos y se puede cambiar. Su aparición depende de la posición en el texto, no de reconocer escenas.

## Ajustes de narración

- Google Traductor tiene base fija de **+20 %**: el control de velocidad en 0 usa ese ritmo, aplicado después de sintetizar.
- Supertonic tiene base fija de **+20 %**: el control de velocidad en 0 usa ese ritmo. La aceleración se aplica después de sintetizar. Calidad Rápida/Equilibrada/Cuidada usa 5/10/16 pasos. Más pasos tardan más y no garantizan mejor pronunciación. Cambia Variación de interpretación para probar otra generación de una frase problemática.
- Las comas se conservan dentro de las frases, sin silencios fijos añadidos. El motor puede introducir sus propias pausas.
- El tono se ajusta en semitonos; no reproduce exactamente la escala de Balabolka.
- Edge y Microsoft local ofrecen reducción de sibilancia y preguntas/exclamaciones con entonación neutra. Esta última cambia solo el texto enviado a síntesis, conservando EPUB y letras, y puede perder expresividad. No garantiza eliminar susurros ni defectos de pronunciación.

Las frases se conservan completas con objetivo flexible de 280 caracteres. Oraciones excepcionales de más de 1200 caracteres pueden dividirse en cláusulas o palabras. Subtítulos e imágenes se sincronizan por fragmentos: no hay alineación por palabra ni karaoke.

## Datos y rendimiento

**data/** contiene libros originales, ajustes, voces, caché, trabajos y exportaciones. No elimines esta carpeta si quieres conservarlos. `.venv/` contiene las dependencias. `novelavoz/`, `static/` y `vendor/` son código necesario; `tests/` permite comprobarlo; las pruebas generan EPUB sintéticos en memoria.

Supertonic conserva el audio nativo en `data/books/<id>/cache/source/` para reutilizarlo al cambiar velocidad, tono, volumen o pausa. Cambiar voz, texto, calidad o variación requiere nueva síntesis. La caché ocupa espacio en disco. Las pruebas de voz sin libro todavía no usan esta caché.

La unión de audio trabaja por bloques y el ZIP guarda los archivos multimedia sin recomprimirlos. La cola procesa un trabajo a la vez. Los cambios de portada, letras, bitrate o tipo de salida reutilizan la narración disponible. El backend conserva soporte para reanudar trabajos antiguos con varios formatos, aunque la interfaz actual separa Audio y Video.

Microsoft Natural local mantiene un proceso aislado abierto y reutiliza las bibliotecas del motor entre fragmentos, evitando iniciar Python en cada frase. Conserva el texto, la segmentación, los filtros y el formato de caché. Cancelar o agotar el tiempo de espera cierra ese proceso; la siguiente petición inicia otro. No cambia las voces instaladas en Windows ni envía texto a internet.

Supertonic puede usar **DirectML en un proceso aislado** cuando existe un runtime opcional en `data/supertonic-gpu-runtime/` y una configuración verificada en `data/supertonic-compute.json`. La aceleración es opcional y debe verificarse con el hardware y los controladores del equipo. La biblioteca de CPU de `.venv` se conserva; si falla la GPU, vuelve a CPU y muestra el motivo al actualizar el catálogo de voces. El texto, modelo, calidad, variación, velocidad y caché se mantienen. La primera petición incluye carga y preparación de GPU; los siguientes fragmentos reutilizan el proceso. Los resultados de GPU y CPU pueden tener pequeñas diferencias de redondeo. El ZIP de código no incluye ese runtime opcional ni su configuración; una instalación nueva sigue usando CPU hasta preparar y verificar la aceleración en su equipo. Una conversión activa necesita reiniciarse y reanudarse para adoptar cambios de motor.

**Ajustar pausas automáticamente**, activado por defecto, modifica únicamente los bordes silenciosos al unir fragmentos. Conserva las pausas internas que genera la voz para comas y puntos; distingue las uniones dentro de un párrafo, los saltos de párrafo y los cambios de capítulo. Mantiene un margen de seguridad de 25 ms junto al habla y deja intactas respuestas silenciosas como «…». Reutiliza la caché y recalcula las marcas de letras e imágenes según el audio final. Desactivarlo permite usar la pausa adicional fija anterior. Los archivos ya exportados no cambian.

La ruta DirectML conserva los datos intermedios de Supertonic en GPU mediante I/O Binding, evitando devolverlos a CPU en cada paso. Mantiene la precisión y las dimensiones originales: no agrupa ni rellena frases. Si el controlador no admite esta optimización, usa la ruta anterior de GPU y conserva el estado del generador aleatorio al repetir el fragmento. El rendimiento depende del hardware, el tamaño de los fragmentos y la carga del equipo; no se garantiza un tiempo de conversión.

Límites de importación: 200 MB comprimidos, 1 GB extraído y 20 000 archivos. No se admiten EPUB cifrados/DRM ni se traducen o reparan automáticamente.

## Desarrollo

Servidor HTTP de Python limitado a localhost. Interfaz HTML/CSS/JavaScript sin compilación ni dependencias de frontend. `books.py` lee EPUB; `engines.py` integra voces; `exporter.py` genera y etiqueta archivos; `server.py` expone la API.

Desde la carpeta de la aplicación:

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Se reutiliza código de NovelaEPUB en `vendor/epubstudio`; no se modifica el proyecto original. Las dependencias conservan sus licencias. El soporte interno de Piper es legado y no se instala por defecto. Revisa las condiciones de los modelos y los derechos del contenido antes de distribuir resultados. El ZIP de código excluye entornos, proyectos personales, modelos y muestras generadas.

## Publicación y privacidad

Solo se versiona código y documentación. Los modelos, voces, EPUB, portadas, caché, resultados y entornos locales quedan excluidos. Consulta [SECURITY.md](SECURITY.md) y ejecuta `python tools/check_publication.py` antes de publicar cambios. El nombre interno del paquete Python y la variable `NOVELAVOZ_DATA_DIR` se conservan por compatibilidad con instalaciones existentes.
