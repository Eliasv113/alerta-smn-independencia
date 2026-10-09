from datetime import datetime
import json
import os
import feedparser
import re
import requests

RSS_URL = 'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml'

# PALABRAS CLAVE: Dejamos 'FORMOSA' para probar. Luego poné las de Patquía.
PALABRAS_CLAVE = ['FORMOSA']

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
  # SIN parse_mode para evitar cualquier rechazo de Telegram por caracteres especiales
  payload = {
      'chat_id': TELEGRAM_CHANNEL_ID,
      'text': mensaje,
  }
  r = requests.post(url, json=payload)
  print(f'Respuesta Telegram: {r.text}')


def procesar_alertas():
  historial = cargar_historial()
  nuevos_enviados = False

  feed = feedparser.parse(RSS_URL)

  for entry in feed.entries:
    alerta_id = getattr(entry, 'title', '')

    if alerta_id in historial:
      continue

    titulo = getattr(entry, 'title', '')
    descripcion_cruda = getattr(entry, 'description', '')

    contenido_completo = f'{titulo} {descripcion_cruda}'.upper()
    coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)

    if coincide:
      # Limpiamos HTML básico
      limpio = re.sub(r'<p>', '', descripcion_cruda)
      limpio = re.sub(r'<\/p>', '\n', limpio)
      limpio = re.sub(r'<\/?b>', '', limpio)
      limpio = re.sub(r'<img.*?>', '', limpio)
      descripcion_limpia = limpio.strip()

      imagenes = re.findall(r'<img[^>]+src="([^">]+)"', descripcion_cruda)
      links_imagenes = '\n'.join([f'Ver mapa: {img}' for img in imagenes])

      hora_actual = datetime.now().strftime('%H:%M')
      fecha_actual = datetime.now().strftime('%d-%m-%Y')

      # Redacción exacta en texto plano
      mensaje = (
          f'NUEVA ALERTA SMN\n\n'
          f'A las {hora_actual} de hoy el Servicio Meteorológico Nacional ha emitido un {titulo}.\n\n'
          f'{descripcion_limpia}\n\n'
          f'{links_imagenes}\n\n'
          f'Fecha: {fecha_actual} {hora_actual}  Más info: {entry.link}'
      )

      enviar_telegram_texto(mensaje)

      historial.append(alerta_id)
      nuevos_enviados = True

  if nuevos_enviados:
    guardar_historial(historial)


if __name__ == '__main__':
  procesar_alertas()
