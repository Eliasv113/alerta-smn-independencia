import feedparser

RSS_URL = 'https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml'
PALABRAS_CLAVE = ['FORMOSA']

feed = feedparser.parse(RSS_URL)
print(f'Total entradas en RSS: {len(feed.entries)}')

for entry in feed.entries:
  titulo = getattr(entry, 'title', '')
  descripcion = getattr(entry, 'description', '')
  texto_completo = f'{titulo} {descripcion}'.upper()
  
  coincide = any(kw.upper() in texto_completo for kw in PALABRAS_CLAVE)
  print(f'Título: {titulo}')
  print(f'¿Coincide con FORMOSA?: {coincide}')
