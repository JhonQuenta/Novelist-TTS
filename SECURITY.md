# Seguridad y privacidad

Novelist TTS es una aplicación local. El servidor escucha solo en `127.0.0.1`, valida el Host y el origen de las peticiones y exige una cabecera propia para las operaciones que modifican datos. No debe exponerse directamente a internet ni usarse como servidor multiusuario.

## Datos que no se publican

El repositorio contiene código y documentación. Se excluyen `data/`, entornos Python, archivos de configuración locales, registros, libros EPUB, portadas, grabaciones, voces descargadas, modelos, fragmentos de caché y exportaciones. Las pruebas construyen libros sintéticos en memoria.

Antes de hacer un commit, revisa `git status`, el contenido preparado y ejecuta `python tools/check_publication.py`. El comprobador busca tipos de archivos privados, rutas personales y algunos formatos habituales de credenciales; no sustituye una revisión manual ni garantiza detectar todos los secretos.

## Motores y descargas

- Supertonic y Microsoft Natural local procesan el texto en el equipo una vez preparados sus componentes.
- Microsoft Edge y Google Traductor envían el texto al servicio correspondiente. Son integraciones no oficiales y su disponibilidad puede cambiar.
- Los instaladores opcionales descargan componentes de terceros por HTTPS. Supertonic comprueba el tamaño y SHA-256 fijados en su manifiesto. El instalador de Microsoft local usa fuentes de terceros fijadas por versión, pero no verifica todos los binarios mediante hashes; no equivale a una instalación firmada o auditada de extremo a extremo.
- No se incluyen DLL, ejecutables, claves de configuración de modelos ni paquetes de voces de Microsoft en Git.

No desactives el antivirus o el Control Inteligente de Aplicaciones para ejecutar componentes bloqueados. Revisa las fuentes y las licencias de cada motor antes de instalarlo o distribuir resultados.

## Informar de un problema

No adjuntes novelas, audios privados, `data/`, credenciales ni registros completos a una incidencia pública. Para errores de seguridad, utiliza el mecanismo privado de GitHub que ofrezca el repositorio, si está disponible. Para otros fallos, proporciona una descripción mínima y un ejemplo inventado que permita reproducirlos.
