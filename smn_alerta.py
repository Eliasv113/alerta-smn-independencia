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

# Palabras clave exactas que querés buscar en el contenido de la alerta
PALABRAS_CLAVE = ['LA RIOJA:INDEPENDENCIA', 'LA RIOJA: PATQUIA', 'LA RIOJA: PATQUÍA']

# Configuración de CallMeBot (reemplaza con tus datos reales)
TELEFONO = 'TU_TELEFONO'  # Ej: 5493821xxxxxx
APIKEY = 'TU_APIKEY'

# Archivo local para no repetir alertas ya enviadas
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


def enviar_whatsapp(mensaje, imagen_url=None):
  # Enviar texto
  texto_codificado = requests.utils.quote(mensaje)
  url_texto = f'https://api.callmebot.com/whatsapp.php?phone={TELEFONO}&text={texto_codificado}&apikey={APIKEY}'
  requests.get(url_texto)

  # Si el feed incluye alguna imagen asociada, CallMeBot permite enviarla
  if imagen_url:
    url_img = f'https://api.callmebot.com/whatsapp.php?phone={TELEFONO}&photo={requests.utils.quote(imagen_url)}&apikey={APIKEY}'
    requests.get(url_img)


def procesar_alertas():
  historial = cargar_historial()
  nuevos_enviados = False

  for url_rss in RSS_URLS:
    feed = feedparser.parse(url_rss)

    for entry in feed.entries:
      # Identificador único de la alerta
      alerta_id = getattr(
          entry, 'id', getattr(entry, 'link', entry.title)
      )

      if alerta_id in historial:
        continue  # Si ya la procesamos en otra ejecución, la salteamos

      # Combinamos título y descripción para buscar las palabras clave
      contenido_completo = (
          f'{entry.title} {getattr(entry, "description", "")}'
      ).upper()

      # Verificamos si contiene alguna de tus palabras clave para Patquía/Independencia
      coincide = any(kw.upper() in contenido_completo for kw in PALABRAS_CLAVE)

      if coincide:
        # Extraer campos detallados
        titulo = entry.title

        # Descripción cruda del feed
        descripcion = getattr(entry, 'description', 'Sin descripción')

        # Buscar si hay imágenes adjuntas en el feed RSS
        imagen_url = None
        if 'media_content' in entry and len(entry.media_content) > 0:
          imagen_url = entry.media_content[0].get('url')
        elif 'enclosures' in entry and len(entry.enclosures) > 0:
          imagen_url = entry.enclosures[0].get('href')

        # Armar el mensaje final formateado tal como pediste
        mensaje = (
            f'🚨 *NUEVA ALERTA SMN - PATQUÍA / INDEPENDENCIA* 🚨\n\n'
            f'*TÍTULO:*\n{titulo}\n\n'
            f'*DESCRIPCIÓN:*\n{descripcion}\n\n'
            f'📅 *Fecha de emisión:* {datetime.now().strftime("%d-%m-%Y %H:%M")}\n'
            f'🔗 *Más información oficial:* {entry.link}'
        )

        # Enviamos por WhatsApp
        enviar_whatsapp(mensaje, imagen_url)

        # Guardamos en el historial para no repetirla
        historial.append(alerta_id)
        nuevos_enviados = True

  if nuevos_enviados:
    guardar_historial(historial)


if __name__ == '__main__':
  procesar_alertas()
