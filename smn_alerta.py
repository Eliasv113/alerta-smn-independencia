from datetime import datetime
import feedparser
import requests

# Única URL de feed configurada
RSS_URL = 'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml'

# Configuración de Telegram
TELEGRAM_BOT_TOKEN = '8744790579:AAGL5NKfM8j-J2gc4nkTKs3fRAFE-Mfs9vI'
TELEGRAM_CHANNEL_ID = '-1004449625331'


def enviar_telegram_texto(mensaje):
  url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
  payload = {
      'chat_id': TELEGRAM_CHANNEL_ID,
      'text': mensaje,
      'parse_mode': 'Markdown',
  }
  r = requests.post(url, json=payload)
  print(f'Respuesta de Telegram: {r.text}')


def procesar_alertas():
  print('--- INICIANDO DIAGNÓSTICO DE FEED ---')
  feed = feedparser.parse(RSS_URL)
  print(f'Total de entradas encontradas en el GeoRSS: {len(feed.entries)}')

  for i, entry in enumerate(feed.entries):
    print(f'\nEntrada #{i+1}:')
    print(f'Título: {getattr(entry, "title", "Sin título")}')
    desc = getattr(entry, 'description', 'Sin descripción')
    print(
        'Descripción (primeros 150 caracteres):'
        f' {desc[:150].replace(chr(10), " ")}'
    )

  # Forzamos un mensaje de prueba a Telegram para verificar que la conexión bot <-> canal funcione
  print('\nEnviando mensaje de prueba forzado a Telegram...')
  mensaje_prueba = (
      '*PRUEBA DE CONexIÓN SMN PAT*\n\nEl bot está conectado correctamente y'
      ' listo para vigilar las alertas de Patquía.'
  )
  enviar_telegram_texto(mensaje_prueba)


if __name__ == '__main__':
  procesar_alertas()
