from datetime import datetime, timedelta, timezone
import json
import os
import feedparser
import re
import requests

# Única URL de feed configurada
RSS_URL = 'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml'

# PALABRAS CLAVE: Dejamos 'FORMOSA' para probar. Luego poné las de Patquía.
PALABRAS_CLAVE = [
    'LA RIOJA:INDEPENDENCIA',
    'LA RIOJA: PATQUIA',
    'LA RIOJA: PATQUÍA',
]

# Configuración de Telegram
TELEGRAM_BOT_TOKEN = '8744790579:AAGL5NKfM8j-J2gc4nkTKs3fRAFE-Mfs9vI'
TELEGRAM_CHANNEL_ID = '-1004449625331'

HISTORIAL_FILE = 'historial_alertas.json'


def cargar_historial():
  if os.path.exists(HISTORIAL_FILE):
    with open(HISTORIAL_FILE, 'r', encoding='utf-8') as f:
      try:
        return json.load(f)
      except:
        return []
  return []


def guardar_historial(historial):
  with open(HISTORIAL_FILE, 'w', encoding='utf-8') as f:
    json.dump(historial, f, ensure_ascii=False, indent=4)


def enviar_telegram_texto(mensaje):
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {
      'chat_id': TELEGRAM_CHANNEL_ID,
      'text': mensaje,
  }
  requests.post(url, json=payload)


def procesar_alertas():
  historial = cargar_historial()
  nuevos_enviados = False

  feed = feedparser.parse(RSS_URL)

  # Buscamos todas las alertas que coincidan con la palabra clave
  alertas_coincidentes = []

  for entry in feed.entries:
    alerta_id = getattr(entry, 'title', '')

    if alerta_id in historial:
      continue

    titulo = getattr(entry, 'title', '')
    descripcion_cruda = getattr(entry, 'description', '')

    contenido_completo = f'{titulo} {descripcion_cruda}'.upper()
    coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)

    if coincide:
      alertas_coincidentes.append(entry)

  # Si hay nuevas alertas, procesamos unicamente la MAS RECIENTE (la ultima del feed) para evitar avalanchas
  if alertas_coincidentes:
    # Tomamos la ultima entrada coincidente
    entry = alertas_coincidentes[-1]
    alerta_id = getattr(entry, 'title', '')

    titulo = getattr(entry, 'title', '')
    descripcion_cruda = getattr(entry, 'description', '')

    # Limpiamos HTML básico (incluyendo los <br /> sueltos si los hubiera)
    limpio = re.sub(r'<p>', '', descripcion_cruda)
    limpio = re.sub(r'<\/p>', '\n', limpio)
    limpio = re.sub(r'<br\s*\/?>', '\n', limpio)
    limpio = re.sub(r'<\/?b>', '', limpio)
    limpio = re.sub(r'<img.*?>', '', limpio)
    descripcion_limpia = limpio.strip()

    # Extraemos mapas en formato link
    imagenes = re.findall(r'<img[^>]+src="([^">]+)"', descripcion_cruda)
    links_imagenes = '\n'.join([f'Ver mapa: {img}' for img in imagenes])

    # Hora local exacta de Argentina (UTC-3)
    zona_horaria_arg = timezone(timedelta(hours=-3))
    ahora_arg = datetime.now(zona_horaria_arg)
    hora_actual = ahora_arg.strftime('%H:%M')
    fecha_actual = ahora_arg.strftime('%d-%m-%Y')

    # Redacción exacta solicitada
    mensaje = (
        f'NUEVA ALERTA SMN\n\n'
        f'A las {hora_actual} de hoy el Servicio Meteorológico Nacional ha emitido un {titulo}.\n\n'
        f'{descripcion_limpia}\n\n'
        f'{links_imagenes}\n\n'
        f'Fecha: {fecha_actual} {hora_actual}  Más info: {entry.link}'
    )

    enviar_telegram_texto(mensaje)

    historial.append(alerta_id)
    guardar_historial(historial)


if __name__ == '__main__':
  procesar_alertas()
