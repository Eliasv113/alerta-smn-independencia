from datetime import datetime
import json
import os
import feedparser
import requests

# URLs de los feeds del SMN
RSS_URLS = [
    'https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml',
    'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml',
]

# Palabras clave exactas para buscar en el contenido
PALABRAS_CLAVE = ['LA RIOJA:INDEPENDENCIA', 'LA RIOJA: PATQUIA', 'LA RIOJA: PATQUÍA']

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


def enviar_telegram(mensaje, imagen_url=None):
  if imagen_url:
    # Enviar foto con descripción si el feed tiene imagen
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto'
    payload = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'photo': imagen_url,
        'caption': mensaje,
        'parse_mode': 'Markdown',
    }
  else:
    # Enviar solo texto
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'text': mensaje,
        'parse_mode': 'Markdown',
    }
  requests.post(url, json=payload)


def procesar_alertas():
  historial = cargar_historial()
  nuevos_enviados = False

  for url_rss in RSS_URLS:
    feed = feedparser.parse(url_rss)

    for entry in feed.entries:
      alerta_id = getattr(
          entry, 'id', getattr(entry, 'link', entry.title)
      )

      if alerta_id in historial:
        continue

      contenido_completo = (
          f'{entry.title} {getattr(entry, "description", "")}'
      ).upper()
      coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)

      if coincide:
        titulo = entry.title
        descripcion = getattr(entry, 'description', 'Sin descripción')

        imagen_url = None
        if 'media_content' in entry and len(entry.media_content) > 0:
          imagen_url = entry.media_content[0].get('url')
        elif 'enclosures' in entry and len(entry.enclosures) > 0:
          imagen_url = entry.enclosures[0].get('href')

        mensaje = (
            f'🚨 *NUEVA ALERTA SMN - PATQUÍA / INDEPENDENCIA* 🚨\n\n'
            f'*TÍTULO:*\n{titulo}\n\n'
            f'*DESCRIPCIÓN:*\n{descripcion}\n\n'
            f'📅 *Fecha:* {datetime.now().strftime("%d-%m-%Y %H:%M")}\n'
            f'🔗 *Más info:* {entry.link}'
        )

        enviar_telegram(mensaje, imagen_url)
        historial.append(alerta_id)
        nuevos_enviados = True

  if nuevos_enviados:
    guardar_historial(historial)


if __name__ == '__main__':
  procesar_alertas()
