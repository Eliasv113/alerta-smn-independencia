import feedparser

RSS_URL = 'https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml'

feed = feedparser.parse(RSS_URL)
print(f'Total de alertas encontradas en el RSS: {len(feed.entries)}')

for i, entry in enumerate(feed.entries):
  print(f'\n--- Alerta #{i+1} ---')
  print(f'TÍTULO: {entry.title}')
  # Mostramos un fragmento de la descripción para ver qué dice
  desc = getattr(entry, 'description', '')
  print(
      f'DESCRIPCIÓN (primeros 200 caracteres): {desc[:200].replace(chr(10), " ")}'
  )
