from datetime import datetime
import feedparser
import re
import requests

# URLs de los feeds del SMN
RSS_URLS = [
    'https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml',
    'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml',
]

# Palabras clave (dejamos 'MISIONES' para la prueba)
PALABRAS_CLAVE = ['MISIONES']

# Configuración de Telegram
TELEGRAM_BOT_TOKEN = '8744790579:AAGL5NKfM8j-J2gc4nkTKs3fRAFE-Mfs9vI'
TELEGRAM_CHANNEL_ID = '-1004449625331'


def limpiar_html(texto_html):
  if not texto_html:
    return ''
  limpio = re.sub('<p>', '', texto_html)
  limpio = re.sub('</p>', '\n', limpio)
  limpio = re.sub('<.*?>', '', limpio)
  return limpio.strip()


def enviar_telegram_texto(mensaje):
  # Enviamos como texto plano sin Markdown para evitar cualquier error de sintaxis
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {
      'chat_id': TELEGRAM_CHANNEL_ID,
      'text': mensaje,
  }
  r = requests.post(url, json=payload)
  print(f'Respuesta Telegram: {r.text}')


def procesar_alertas():
  for url_rss in RSS_URLS:
    feed = feedparser.parse(url_rss)
    print(f'Analizando feed: {url_rss} (Total entradas: {len(feed.entries)})')

    for entry in feed.entries:
      contenido_completo = (
          f'{entry.title} {getattr(entry, "description", "")}'
      ).upper()
      coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)

      print(
          f'Revisando alerta: {entry.title[:30]}... Coincide con Misiones:'
          f' {coincide}'
      )

      if coincide:
        titulo = limpiar_html(entry.title)
        descripcion_cruda = getattr(entry, 'description', '')
        descripcion_limpia = limpiar_html(descripcion_cruda)

        # Buscamos si hay imágenes en el HTML para adjuntar los links directamente en el texto
        imagenes = re.findall(r'<img[^>]+src="([^">]+)"', descripcion_cruda)
        links_imagenes = '\n'.join([f'🗺️ Ver mapa: {img}' for img in imagenes])

        mensaje = (
            f'🚨 NUEVA ALERTA SMN - PRUEBA 🚨\n\n'
            f'TÍTULO:\n{titulo}\n\n'
            f'DESCRIPCIÓN:\n{descripcion_limpia}\n\n'
            f'{links_imagenes}\n\n'
            f'📅 Fecha: {datetime.now().strftime("%d-%m-%Y %H:%M")}\n'
            f'🔗 Más info: {entry.link}'
        )

        print('Enviando mensaje a Telegram...')
        enviar_telegram_texto(mensaje)


if __name__ == '__main__':
  procesar_alertas()
