from datetime import datetime
import json
import os
import feedparser
import re
import requests

# URLs de los feeds del SMN
RSS_URLS = [
    'https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml',
    'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml',
]

# Palabras clave (dejamos 'MISIONES' para tu prueba actual, luego podés dejar solo las de La Rioja)
PALABRAS_CLAVE = [
    'LA RIOJA:INDEPENDENCIA',
    'LA RIOJA: PATQUIA',
    'LA RIOJA: PATQUÍA',
    'MISIONES',
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


def limpiar_html(texto_html):
  if not texto_html:
    return ''
  limpio = re.sub('<p>', '', texto_html)
  limpio = re.sub('</p>', '\n', limpio)
  limpio = re.sub('<b>', '*', limpio)
  limpio = re.sub('</b>', '*', limpio)
  limpio = re.sub('<.*?>', '', limpio)
  return limpio.strip()


def extraer_imagenes(texto_html):
  if not texto_html:
    return []
  return re.findall(r'<img[^>]+src="([^">]+)"', texto_html)


def enviar_telegram(mensaje, imagenes_urls):
  if imagenes_urls and len(imagenes_urls) > 0:
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto'
    payload = {
        'chat_id': TELEGRAM_CHANNEL_ID,
        'photo': imagenes_urls[0],
        'caption': mensaje,
        'parse_mode': 'Markdown',
    }
    requests.post(url, json=payload)

    if len(imagenes_urls) > 1:
      payload_segunda = {
          'chat_id': TELEGRAM_CHANNEL_ID,
          'photo': imagenes_urls[1],
          'caption': '🗺️ *Mapa adicional de la alerta*',
          'parse_mode': 'Markdown',
      }
      requests.post(url, json=payload_segunda)
  else:
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
        titulo = limpiar_html(entry.title)
        descripcion_cruda = getattr(entry, 'description', '')
        descripcion_limpia = limpiar_html(descripcion_cruda)

        imagenes = extraer_imagenes(descripcion_cruda)

        mensaje = (
            f'🚨 *NUEVA ALERTA SMN - ZONA DE INTERÉS* 🚨\n\n'
            f'*TÍTULO:*\n{titulo}\n\n'
            f'*DESCRIPCIÓN:*\n{descripcion_limpia}\n\n'
            f'📅 *Fecha de emisión:* {datetime.now().strftime("%d-%m-%Y %H:%M")}\n'
            f'🔗 *Más información:* {entry.link}'
        )

        enviar_telegram(mensaje, imagenes)
        historial.append(alerta_id)
        nuevos_enviados = True

  if nuevos_enviados:
    guardar_historial(historial)


if __name__ == '__main__':
  procesar_alertas()
