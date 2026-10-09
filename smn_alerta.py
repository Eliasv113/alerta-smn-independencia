from datetime import datetime
import feedparser
import re
import requests

RSS_URL = 'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml'
PALABRAS_CLAVE = ['FORMOSA']

TELEGRAM_BOT_TOKEN = '8744790579:AAGL5NKfM8j-J2gc4nkTKs3fRAFE-Mfs9vI'
TELEGRAM_CHANNEL_ID = '-1004449625331'


def enviar_telegram_texto(mensaje):
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {
      'chat_id': TELEGRAM_CHANNEL_ID,
      'text': mensaje,
  }
  r = requests.post(url, json=payload)
  print(f'Respuesta Telegram: {r.text}')


def procesar_alertas():
  feed = feedparser.parse(RSS_URL)
  print(f'Total de entradas en el RSS: {len(feed.entries)}')

  for entry in feed.entries:
    titulo = getattr(entry, 'title', '')
    descripcion_cruda = getattr(entry, 'description', '')

    contenido_completo = f'{titulo} {descripcion_cruda}'.upper()
    coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)
    print(f'Revisando: "{titulo}" -> ¿Coincide con FORMOSA?: {coincide}')

    if coincide:
      limpio = re.sub(r'<p>', '', descripcion_cruda)
      limpio = re.sub(r'<\/p>', '\n', limpio)
      limpio = re.sub(r'<\/?b>', '', limpio)
      limpio = re.sub(r'<img.*?>', '', limpio)
      descripcion_limpia = limpio.strip()

      imagenes = re.findall(r'<img[^>]+src="([^">]+)"', descripcion_cruda)
      links_imagenes = '\n'.join([f'Ver mapa: {img}' for img in imagenes])

      hora_actual = datetime.now().strftime('%H:%M')
      fecha_actual = datetime.now().strftime('%d-%m-%Y')

      mensaje = (
          f'NUEVA ALERTA SMN\n\n'
          f'A las {hora_actual} de hoy el Servicio Meteorológico Nacional ha'
          f' emitido un {titulo}.\n\n'
          f'{descripcion_limpia}\n\n'
          f'{links_imagenes}\n\n'
          f'Fecha: {fecha_actual} {hora_actual}  Más info: {entry.link}'
      )

      print('Enviando a Telegram...')
      enviar_telegram_texto(mensaje)


if __name__ == '__main__':
  procesar_alertas()
