import os
import json
import html
import hashlib
import base64
import re
import mimetypes
import requests
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urljoin, urlparse


# =========================================================
# CONFIGURACIÓN
# =========================================================

# Se consultan primero las fuentes de avisos a corto plazo para dar
# prioridad a sus posibles imágenes asociadas. Se conserva también
# el feed CAP general que ya utilizaba el sistema.
FEEDS_SMN = [
    "https://ssl.smn.gob.ar/feeds/CAP/avisocortoplazo/rss_acpCAP.xml",
    "https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml",
    "https://ssl.smn.gob.ar/CAP/AR.php",
]

HISTORIAL_ARCHIVO = "historial_alertas.json"

# Límite administrativo oficial consultado en la API Georef (Argentina.gob.ar).
GEOREF_URL = "https://apis.datos.gob.ar/georef/api/departamentos"
NOMBRE_ZONA = "Departamento de General Alvear, Mendoza"
DEPARTAMENTO_GEOMETRIA = None

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHANNEL_ID")

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

MAX_IMAGENES_TELEGRAM = 10
MAX_BYTES_IMAGEN = 10 * 1024 * 1024

MESES = [
    "enero", "febrero", "marzo", "abril",
    "mayo", "junio", "julio", "agosto",
    "septiembre", "octubre", "noviembre", "diciembre",
]

TRADUCCIONES = {
    "Extreme": "Extrema",
    "Severe": "Severa",
    "Moderate": "Moderada",
    "Minor": "Leve",
    "Unknown": "Desconocida",
    "Observed": "Observada",
    "Likely": "Probable",
    "Possible": "Posible",
    "Unlikely": "Improbable",
    "Immediate": "Inmediata",
    "Expected": "Esperada",
    "Future": "Futura",
    "Past": "Pasada",
}

ICONOS_SEVERIDAD = {
    "Extreme": "🚨",
    "Severe": "🔴",
    "Moderate": "🟠",
    "Minor": "🟡",
    "Unknown": "⚪",
}


# =========================================================
# FUNCIONES XML
# =========================================================

def nombre_etiqueta(elemento):
    """Devuelve el nombre de una etiqueta XML sin su espacio de nombres."""
    return elemento.tag.split("}")[-1].split(":")[-1]


def hijo(elemento, nombre):
    """Busca el primer hijo directo con el nombre indicado."""
    if elemento is None:
        return None

    for item in elemento:
        if nombre_etiqueta(item) == nombre:
            return item

    return None


def texto(elemento, nombre, predeterminado="No especificada"):
    """Obtiene el texto de un hijo XML."""
    elemento_hijo = hijo(elemento, nombre)

    if elemento_hijo is None or not elemento_hijo.text:
        return predeterminado

    return elemento_hijo.text.strip()


def todos_hijos(elemento, nombre):
    """Obtiene todos los hijos directos que coinciden con el nombre."""
    if elemento is None:
        return []

    return [item for item in elemento if nombre_etiqueta(item) == nombre]


# =========================================================
# FECHAS Y TRADUCCIONES
# =========================================================

def traducir(valor):
    return TRADUCCIONES.get(valor, valor or "No especificada")


def fecha_argentina(valor):
    """Convierte una fecha CAP a hora argentina y la muestra en español."""
    if not valor or valor == "No especificada":
        return "Sin especificar"

    try:
        valor = valor.strip()

        if valor.endswith("Z"):
            valor = valor[:-1] + "+00:00"

        fecha = datetime.fromisoformat(valor)

        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        fecha = fecha.astimezone(ZONA_HORARIA)
        mes = MESES[fecha.month - 1]
        return f"{fecha.day} de {mes} - {fecha:%H:%M}"

    except (ValueError, TypeError):
        return valor


# =========================================================
# GEOGRAFÍA DEL DEPARTAMENTO
# =========================================================

def leer_poligono(valor):
    """Convierte vértices CAP 'lat,lon lat,lon ...' en pares (lat, lon)."""
    puntos = []

    if not valor:
        return puntos

    for par in valor.split():
        try:
            partes = par.split(",")
            if len(partes) != 2:
                continue
            latitud = float(partes[0])
            longitud = float(partes[1])
            puntos.append((latitud, longitud))
        except (ValueError, TypeError):
            continue

    return puntos


def cargar_limite_departamento():
    """Obtiene el polígono oficial del departamento desde la API Georef."""
    parametros = {
        "nombre": "General Alvear",
        "provincia": "Mendoza",
        "formato": "geojson",
        "max": 10,
    }

    print("Descargando el límite geográfico de General Alvear desde Georef...")
    respuesta = requests.get(GEOREF_URL, params=parametros, timeout=45)
    respuesta.raise_for_status()
    datos = respuesta.json()

    if datos.get("type") == "FeatureCollection":
        features = datos.get("features", [])
    elif datos.get("type") == "Feature":
        features = [datos]
    else:
        raise RuntimeError("Georef no devolvió un GeoJSON reconocible para General Alvear.")

    if not features:
        raise RuntimeError(
            "Georef no devolvió el límite de General Alvear, Mendoza. "
            "Se cancela la ejecución para evitar alertas geográficas incorrectas."
        )

    geometries = []
    for feature in features:
        geometria = feature.get("geometry")
        if geometria:
            geometries.append(shape(geometria))

    if not geometries:
        raise RuntimeError("El GeoJSON de General Alvear no contiene geometrías.")

    limite = unary_union(geometries)
    if limite.is_empty:
        raise RuntimeError("El límite geográfico de General Alvear está vacío.")

    if not limite.is_valid:
        limite = limite.buffer(0)

    if limite.is_empty or not limite.is_valid:
        raise RuntimeError("No se pudo validar el polígono del departamento.")

    print(f"Límite cargado correctamente: {limite.geom_type}")
    return limite


def localidades_afectadas(area):
    """Detecta intersección por polygon, circle o geocode CAP."""
    if DEPARTAMENTO_GEOMETRIA is None:
        raise RuntimeError("No se cargó el límite de General Alvear.")

    # 1) Polígonos CAP: cada vértice se expresa como latitud,longitud.
    for elemento in todos_hijos(area, "polygon"):
        puntos = leer_poligono(elemento.text)
        if len(puntos) < 3:
            continue
        poligono_cap = Polygon([(lon, lat) for lat, lon in puntos])
        if not poligono_cap.is_valid:
            poligono_cap = poligono_cap.buffer(0)
        if not poligono_cap.is_empty and DEPARTAMENTO_GEOMETRIA.intersects(poligono_cap):
            return {NOMBRE_ZONA}

    # 2) Círculos CAP: "latitud,longitud radio_km".
    # Se aproxima el círculo en grados, ajustando la longitud por latitud.
    for elemento in todos_hijos(area, "circle"):
        try:
            partes = elemento.text.strip().replace(",", " ").split()
            lat, lon, radio_km = map(float, partes[:3])
            if radio_km <= 0 or not (-90 <= lat <= 90 and -180 <= lon <= 180):
                continue
            delta_lat = radio_km / 111.32
            cos_lat = max(abs(__import__("math").cos(__import__("math").radians(lat))), 0.01)
            delta_lon = radio_km / (111.32 * cos_lat)
            circulo_aprox = Polygon([
                (lon - delta_lon, lat - delta_lat),
                (lon + delta_lon, lat - delta_lat),
                (lon + delta_lon, lat + delta_lat),
                (lon - delta_lon, lat + delta_lat),
            ])
            if DEPARTAMENTO_GEOMETRIA.intersects(circulo_aprox):
                return {NOMBRE_ZONA}
        except (AttributeError, ValueError, TypeError):
            print(f"No se pudo interpretar el círculo CAP: {elemento.text!r}")

    # 3) Geocódigos o descripciones administrativas explícitas.
    area_desc = texto(area, "areaDesc", "").casefold()
    if "general alvear" in area_desc and ("mendoza" in area_desc or "general alvear" in area_desc):
        return {NOMBRE_ZONA}

    for geocode in todos_hijos(area, "geocode"):
        nombre = texto(geocode, "valueName", "").casefold()
        valor = texto(geocode, "value", "").casefold()
        if "general alvear" in nombre or "general alvear" in valor:
            return {NOMBRE_ZONA}

    return set()


# =========================================================
# EXTRACCIÓN DE IMÁGENES DE LOS FEEDS Y MENSAJES CAP
# =========================================================

def normalizar_url_imagen(url, url_base):
    """Resuelve URL relativas y descarta esquemas que Telegram no puede usar."""
    if not url:
        return None
    url = html.unescape(url.strip())
    if not url or url.startswith("data:"):
        return None
    url = urljoin(url_base, url)
    if urlparse(url).scheme not in ("http", "https"):
        return None
    return url


def extraer_imagenes_de_html(contenido, url_base):
    """Extrae imágenes enlazadas dentro de descripciones HTML de un RSS."""
    if not contenido:
        return []

    encontradas = re.findall(
        r"<img\b[^>]*?\bsrc\s*=\s*['\"]([^'\"]+)['\"]",
        html.unescape(contenido),
        flags=re.IGNORECASE,
    )

    return [
        {"url": url, "mime_type": ""}
        for valor in encontradas
        if (url := normalizar_url_imagen(valor, url_base))
    ]


def extraer_datos_feed(contenido, url_feed):
    """Lee RSS/Atom, recupera enlaces CAP e imágenes adjuntas al artículo."""
    raiz = ET.fromstring(contenido)
    if nombre_etiqueta(raiz) == "alert":
        return [(None, [])]

    resultados = []
    entradas = [e for e in raiz.iter() if nombre_etiqueta(e) in ("item", "entry")]
    for entrada in entradas:
        enlaces, imagenes = [], []
        for elemento in entrada:
            nombre = nombre_etiqueta(elemento)
            if nombre == "link":
                href = elemento.attrib.get("href")
                rel = elemento.attrib.get("rel", "alternate").lower()
                tipo = elemento.attrib.get("type", "").lower()
                if href and rel in ("alternate", "related", "enclosure"):
                    destino = urljoin(url_feed, href.strip())
                    if tipo.startswith("image/") or rel == "enclosure":
                        if tipo.startswith("image/") or re.search(r"\.(png|jpe?g|gif|webp)(?:[?#]|$)", destino, re.I):
                            imagenes.append({"url": destino, "mime_type": tipo})
                        elif rel != "enclosure":
                            enlaces.append(destino)
                    else:
                        enlaces.append(destino)
                elif elemento.text and elemento.text.strip():
                    enlaces.append(urljoin(url_feed, elemento.text.strip()))
            elif nombre in ("enclosure", "content", "thumbnail"):
                destino = elemento.attrib.get("url") or elemento.attrib.get("href")
                mime_type = elemento.attrib.get("type", "")
                if destino and (mime_type.startswith("image/") or nombre in ("thumbnail", "content")):
                    imagen_url = normalizar_url_imagen(destino, url_feed)
                    if imagen_url:
                        imagenes.append({"url": imagen_url, "mime_type": mime_type})
            elif nombre in ("description", "encoded", "summary") and elemento.text:
                imagenes.extend(extraer_imagenes_de_html(elemento.text, url_feed))
            elif nombre == "guid" and elemento.text:
                guid = elemento.text.strip()
                if guid.startswith(("http://", "https://")) and re.search(r"\.(xml|cap)(?:[?#]|$)", guid, re.I):
                    enlaces.append(guid)

        enlaces = list(dict.fromkeys(enlaces))
        imagenes_unicas, vistos = [], set()
        for imagen in imagenes:
            clave = imagen.get("url")
            if clave and clave not in vistos:
                vistos.add(clave)
                imagenes_unicas.append(imagen)
        for enlace in enlaces:
            resultados.append((enlace, imagenes_unicas))

        # Si el artículo tiene recursos gráficos pero no enlaza un CAP,
        # se informa en el diagnóstico; no se inventa un documento CAP.
        if imagenes_unicas and not enlaces:
            print(f"Artículo RSS con {len(imagenes_unicas)} imagen(es), sin enlace CAP reconocible.")

    return resultados


def extraer_imagenes_cap(info, url_cap):
    """Extrae recursos gráficos declarados dentro del bloque info del CAP."""
    imagenes = []

    for recurso in todos_hijos(info, "resource"):
        mime_type = texto(recurso, "mimeType", "").lower()
        if not mime_type.startswith("image/"):
            continue

        uri = texto(recurso, "uri", "")
        if uri and uri != "No especificada":
            url = normalizar_url_imagen(uri, url_cap or FEEDS_SMN[0])
            if url:
                imagenes.append({"url": url, "mime_type": mime_type})
                continue

        # CAP también permite incluir el recurso dentro del XML en derefUri.
        deref_uri = texto(recurso, "derefUri", "")
        if deref_uri and deref_uri != "No especificada":
            try:
                datos = base64.b64decode("".join(deref_uri.split()), validate=False)
                if datos:
                    extension = mimetypes.guess_extension(mime_type) or ".jpg"
                    imagenes.append({
                        "data": datos,
                        "mime_type": mime_type,
                        "filename": f"radar{extension}",
                    })
            except (ValueError, base64.binascii.Error) as error:
                print(f"No se pudo decodificar un recurso gráfico CAP: {error}")

    return imagenes


def combinar_imagenes(*grupos):
    """Combina fuentes de imágenes y elimina duplicados."""
    resultado = []
    vistos = set()

    for grupo in grupos:
        for imagen in grupo:
            clave = imagen.get("url") or hashlib.sha256(imagen.get("data", b"")).hexdigest()
            if clave not in vistos:
                vistos.add(clave)
                resultado.append(imagen)

    return resultado[:MAX_IMAGENES_TELEGRAM]


# =========================================================
# HISTORIAL DE ALERTAS
# =========================================================

def cargar_historial():
    if not os.path.exists(HISTORIAL_ARCHIVO):
        return set()

    try:
        with open(HISTORIAL_ARCHIVO, "r", encoding="utf-8") as archivo:
            datos = json.load(archivo)

        if isinstance(datos, list):
            return set(str(item) for item in datos)

        if isinstance(datos, dict):
            return set(str(item) for item in datos.get("alertas", []))

        return set()

    except (OSError, json.JSONDecodeError):
        print("No se pudo leer el historial. Se iniciará vacío.")
        return set()


def guardar_historial(historial):
    with open(HISTORIAL_ARCHIVO, "w", encoding="utf-8") as archivo:
        json.dump(sorted(historial), archivo, ensure_ascii=False, indent=2)


def clave_alerta(identificador, enviado):
    """Distingue una alerta de sus actualizaciones posteriores."""
    valor = f"{identificador}|{enviado}"
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


# =========================================================
# TELEGRAM: TEXTO E IMÁGENES
# =========================================================

def validar_respuesta_telegram(respuesta):
    respuesta.raise_for_status()
    resultado = respuesta.json()
    if not resultado.get("ok"):
        raise RuntimeError(f"Telegram rechazó la solicitud: {resultado}")
    return resultado


def descargar_imagen(imagen):
    """Descarga una imagen o utiliza los bytes incluidos en el CAP."""
    if imagen.get("data"):
        datos = imagen["data"]
        mime_type = imagen.get("mime_type") or "image/jpeg"
        filename = imagen.get("filename") or "radar.jpg"
    else:
        url = imagen.get("url")
        respuesta = requests.get(url, timeout=35, stream=True)
        respuesta.raise_for_status()

        mime_type = respuesta.headers.get("Content-Type", "").split(";")[0].lower()
        if not mime_type.startswith("image/"):
            mime_type = imagen.get("mime_type") or mimetypes.guess_type(urlparse(url).path)[0] or ""
        if not mime_type.startswith("image/"):
            raise ValueError(f"El recurso no parece ser una imagen: {url}")

        partes = []
        total = 0
        for bloque in respuesta.iter_content(chunk_size=64 * 1024):
            if not bloque:
                continue
            total += len(bloque)
            if total > MAX_BYTES_IMAGEN:
                raise ValueError(f"La imagen supera el límite de {MAX_BYTES_IMAGEN // (1024 * 1024)} MB")
            partes.append(bloque)
        datos = b"".join(partes)
        filename = os.path.basename(urlparse(url).path) or "radar" + (mimetypes.guess_extension(mime_type) or ".jpg")

    if not datos:
        raise ValueError("La imagen descargada está vacía.")
    if len(datos) > MAX_BYTES_IMAGEN:
        raise ValueError("La imagen supera el límite permitido por este bot.")

    return filename, datos, mime_type


def enviar_imagenes_telegram(imagenes):
    """Envía una imagen o un álbum de imágenes junto a la alerta."""
    if not imagenes:
        print("El aviso no contiene imágenes asociadas; se envió solamente el texto.")
        return

    archivos_preparados = []
    for imagen in imagenes[:MAX_IMAGENES_TELEGRAM]:
        try:
            archivos_preparados.append(descargar_imagen(imagen))
        except (requests.RequestException, ValueError, OSError) as error:
            print(f"No se pudo obtener una imagen del aviso: {error}")

    if not archivos_preparados:
        print("No se pudieron preparar imágenes; se conserva la alerta de texto.")
        return

    try:
        if len(archivos_preparados) == 1:
            filename, datos, mime_type = archivos_preparados[0]
            url = f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
            respuesta = requests.post(
                url,
                data={
                    "chat_id": CHAT_ID,
                    "caption": "🛰️ Imagen asociada al aviso meteorológico del SMN.",
                },
                files={"photo": (filename, datos, mime_type)},
                timeout=60,
            )
        else:
            media = []
            archivos = {}
            for indice, (filename, datos, mime_type) in enumerate(archivos_preparados):
                campo = f"photo{indice}"
                media.append({
                    "type": "photo",
                    "media": f"attach://{campo}",
                    "caption": "🛰️ Imágenes asociadas al aviso meteorológico del SMN." if indice == 0 else "",
                })
                archivos[campo] = (filename, datos, mime_type)

            url = f"https://api.telegram.org/bot{TOKEN}/sendMediaGroup"
            respuesta = requests.post(
                url,
                data={"chat_id": CHAT_ID, "media": json.dumps(media, ensure_ascii=False)},
                files=archivos,
                timeout=90,
            )

        validar_respuesta_telegram(respuesta)
        print(f"Imágenes enviadas correctamente a Telegram: {len(archivos_preparados)}")

    except (requests.RequestException, RuntimeError, ValueError) as error:
        # No se pierde la alerta principal si falla la descarga o el envío gráfico.
        print(f"No se pudieron enviar las imágenes a Telegram: {error}")


def enviar_telegram(mensaje, imagenes=None):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Faltan los secretos TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID.")

    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    respuesta = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=30,
    )

    validar_respuesta_telegram(respuesta)
    print("Mensaje enviado correctamente a Telegram.")

    # Las imágenes se envían inmediatamente después del texto, en un álbum si hay varias.
    enviar_imagenes_telegram(imagenes or [])


def construir_mensaje(alerta, info, localidades):
    evento = texto(info, "event", "Alerta meteorológica")
    severidad = texto(info, "severity", "Unknown")
    certeza = texto(info, "certainty", "Unknown")
    urgencia = texto(info, "urgency", "Unknown")

    inicio = texto(info, "onset", "")
    if not inicio or inicio == "No especificada":
        inicio = texto(info, "effective", "")

    fin = texto(info, "expires", "")
    descripcion = texto(info, "description", "")
    instrucciones = texto(info, "instruction", "")

    icono = ICONOS_SEVERIDAD.get(severidad, "⚠️")

    lineas = [
        f"{icono} <b>ALERTA METEOROLÓGICA DEL SMN</b>",
        "",
        f"🌦️ <b>Fenómeno:</b> {html.escape(evento)}",
        f"📍 <b>Zona monitoreada:</b> {html.escape(', '.join(sorted(localidades)))}",
        f"{icono} <b>Severidad:</b> {html.escape(traducir(severidad))}",
        f"🎯 <b>Certeza:</b> {html.escape(traducir(certeza))}",
        f"⏳ <b>Urgencia:</b> {html.escape(traducir(urgencia))}",
        "",
        f"🟢 <b>Inicio:</b> {html.escape(fecha_argentina(inicio))}",
        f"🔚 <b>Fin:</b> {html.escape(fecha_argentina(fin))}",
    ]

    if descripcion and descripcion != "No especificada":
        lineas.extend(["", "📝 <b>Descripción:</b>", html.escape(descripcion)])

    if instrucciones and instrucciones != "No especificada":
        lineas.extend(["", "🛡️ <b>Recomendaciones:</b>", html.escape(instrucciones)])

    return "\n".join(lineas)


# =========================================================
# PROCESAMIENTO DE ALERTAS CAP
# =========================================================

def procesar_cap(contenido, historial, claves_procesadas, url_cap=None, imagenes_feed=None):
    raiz = ET.fromstring(contenido)
    if nombre_etiqueta(raiz) != "alert":
        print(f"El recurso no es CAP XML (raíz: {nombre_etiqueta(raiz)}): {url_cap}")
        return "no_cap"

    identificador = texto(raiz, "identifier", "")
    enviado = texto(raiz, "sent", "")
    if not identificador:
        print("CAP sin identificador; se omite.")
        return "sin_identificador"

    clave = clave_alerta(identificador, enviado)
    if clave in historial or clave in claves_procesadas:
        print(f"Alerta ya notificada: {identificador}")
        return "duplicada"

    localidades, info_elegida, imagenes_cap = set(), None, []
    cantidad_areas = 0
    for info in todos_hijos(raiz, "info"):
        for area in todos_hijos(info, "area"):
            cantidad_areas += 1
            localidades_info = localidades_afectadas(area)
            if localidades_info:
                localidades.update(localidades_info)
                imagenes_cap.extend(extraer_imagenes_cap(info, url_cap))
                if info_elegida is None:
                    info_elegida = info

    if not localidades or info_elegida is None:
        print(f"Sin coincidencias geográficas: {identificador} | áreas CAP analizadas: {cantidad_areas}")
        return "fuera_de_zona"

    imagenes = combinar_imagenes(imagenes_cap, imagenes_feed or [])
    print(f"ALERTA PARA {NOMBRE_ZONA}: {identificador}")
    print(f"Imágenes asociadas encontradas: {len(imagenes)}")
    mensaje = construir_mensaje(raiz, info_elegida, localidades)
    enviar_telegram(mensaje, imagenes)

    historial.add(clave)
    claves_procesadas.add(clave)
    guardar_historial(historial)
    return "enviada"


# =========================================================
# LECTURA DE LOS FEEDS DEL SMN
# =========================================================

def ejecutar():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError("Faltan los secretos TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID.")

    global DEPARTAMENTO_GEOMETRIA
    DEPARTAMENTO_GEOMETRIA = cargar_limite_departamento()
    historial = cargar_historial()
    claves_procesadas = set()
    resumen = {"feeds_ok": 0, "feeds_error": 0, "cap_procesados": 0,
               "enviadas": 0, "fuera_de_zona": 0, "duplicadas": 0,
               "no_cap": 0, "sin_identificador": 0}

    print("=" * 58)
    print(f"MONITOREO SMN: {NOMBRE_ZONA}")
    print(f"Historial cargado: {len(historial)} alerta(s)")
    print("=" * 58)

    for url_feed in FEEDS_SMN:
        print(f"\n[FEED] Consultando: {url_feed}")
        try:
            respuesta = requests.get(url_feed, timeout=45, headers={"User-Agent": "SMN-Alertas/1.0"})
            respuesta.raise_for_status()
            resumen["feeds_ok"] += 1
            print(f"[FEED] HTTP {respuesta.status_code} | {len(respuesta.content)} bytes")
            elementos = extraer_datos_feed(respuesta.content, url_feed)
            print(f"[FEED] Enlaces CAP/entradas reconocidas: {len(elementos)}")
            if not elementos:
                print("[FEED] No se encontraron enlaces procesables en este feed.")
                continue

            for url_cap, imagenes_feed in elementos:
                try:
                    if url_cap is None:
                        contenido_cap, url_base_cap = respuesta.content, url_feed
                    else:
                        print(f"[CAP] Descargando: {url_cap}")
                        respuesta_cap = requests.get(url_cap, timeout=45, headers={"User-Agent": "SMN-Alertas/1.0"})
                        respuesta_cap.raise_for_status()
                        contenido_cap, url_base_cap = respuesta_cap.content, url_cap

                    resumen["cap_procesados"] += 1
                    estado = procesar_cap(contenido_cap, historial, claves_procesadas,
                                          url_cap=url_base_cap, imagenes_feed=imagenes_feed)
                    if estado in resumen:
                        resumen[estado] += 1
                except (requests.RequestException, ET.ParseError, RuntimeError, ValueError) as error:
                    print(f"[ERROR CAP] {url_cap or url_feed}: {type(error).__name__}: {error}")
        except (requests.RequestException, ET.ParseError, RuntimeError, ValueError) as error:
            resumen["feeds_error"] += 1
            print(f"[ERROR FEED] {url_feed}: {type(error).__name__}: {error}")

    print("\n" + "=" * 58)
    print("RESUMEN DE EJECUCIÓN")
    for clave, valor in resumen.items():
        print(f"{clave}: {valor}")
    print("Consulta finalizada.")
    print("=" * 58)


if __name__ == "__main__":
    ejecutar()
