"""Local compatible Narrator packages, isolated from the Windows installation."""
import os
from .books import DATA

RUNTIME=DATA/'narrator-runtime'
MODELS=DATA/'narrator-voices'
VOICES={
    'narrator-es-MX-Jorge-1.0.2.0':('Jorge','Jorge','es-MX','1.0.2.0'),
    'narrator-es-MX-Dalia-1.0.3.0':('Dalia','Dalia','es-MX','1.0.3.0'),
    'narrator-es-ES-Alvaro-1.0.3.0':('Alvaro','Álvaro','es-ES','1.0.3.0'),
    'narrator-es-ES-Elvira-1.0.3.0':('Elvira','Elvira','es-ES','1.0.3.0'),
}
def catalog():
    return [{'id':id,'name':f'Microsoft {display} (Natural) · {locale} · Local {version}','lang':locale,'engine':'narrator','installed':ready(id)} for id,(name,display,locale,version) in VOICES.items()]
def ready(id):
    if id not in VOICES or os.name!='nt':return False
    name=VOICES[id][0]
    return (MODELS/name/'AppxManifest.xml').exists() and (RUNTIME/'x64/Microsoft.CognitiveServices.Speech.core.dll').exists() and (RUNTIME/'config.json').exists()
def request(id,text,output):
    if not ready(id):raise ValueError('Primero instala las voces naturales locales con instalar-voces-locales.bat.')
    name=VOICES[id][0]
    return {'text':text,'output':str(output.resolve()),'model':str((MODELS/name).resolve()),'runtime':str((RUNTIME/'x64').resolve()),'configuration':str((RUNTIME/'config.json').resolve())}
