
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
import hashlib
import json
import logging
import os
import re
import unicodedata

import feedparser
import requests


# ============================================================
# CONFIGURACIÓN
# ============================================================

RSS_URL = "https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml"
FUENTE_OFICIAL = "https://www.smn.gob.ar/rss"

PALABRAS_CLAVE = [
    "LA RIOJA:INDEPENDENCIA",
    "LA RIOJA:PATQUIA",
]

# Coordenadas aproximadas del centro de Patquía.
# Formato: latitud, longitud.
PATQUIA_LAT = -30.05
PATQUIA_LON = -66.88

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

HISTORIAL_FILE = Path("historial_alertas.json")
MAX_HISTORIAL = 2000
TIMEOUT = 25
MAX_MENSAJE = 4000

ZONA_ARGENTINA = timezone(timedelta(hours=-3))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# ============================================================
# NORMALIZACIÓN DE TEXTO
# ============================================================

def normalizar(texto):
    """Ignora tildes, mayúsculas y espacios innecesarios."""
    texto = unescape(str(texto or ""))
    texto = unicodedata.normalize("NFD", texto)

    texto = "".join(
        c for c in texto
        if unicodedata.category(c) != "Mn"
    )

    texto = texto.upper()
    texto = re.sub(r"\s*:\s*", ":", texto)
    texto = re.sub(r"\s+", " ", texto)

    return texto.strip()


PALABRAS_NORMALIZADAS = [
    normalizar(p) for p in PALABRAS_CLAVE
]


def limpiar_html(texto):
    """Convierte la descripción HTML del RSS en texto legible."""
    texto = unescape(str(texto or ""))

    texto = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        "",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )

    texto = re.sub(
        r"<br\s*/?>|</p>|</div>|</li>",
        "\n",
        texto,
        flags=re.IGNORECASE,
    )

    texto = re.sub(r"<[^>]+>", " ", texto)
    texto = unescape(texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r" *\n *", "\n", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto)

    return texto.strip()


def obtener_descripcion(entry):
    """Obtiene la descripción, incluso si viene en content."""
    descripcion = (
        entry.get("description", "")
        or entry.get("summary", "")
    )

    if not descripcion and entry.get("content"):
        descripcion = " ".join(
            item.get("value", "")
            for item in entry.get("content", [])
        )

    return str(descripcion or "")


def obtener_titulo(entry):
    return limpiar_html(entry.get("title", "")) or "Aviso meteorológico"


# ============================================================
# IDENTIFICACIÓN DE AVISOS
# ============================================================

def identificar_alerta(entry):
    """
    Genera un identificador estable.
    No utiliza el link genérico del RSS como identificador único.
    """
    identificador = (
        entry.get("id")
        or entry.get("guid")
        or ""
    )

    if identificador:
        return str(identificador).strip()

    titulo = obtener_titulo(entry)
    descripcion = obtener_descripcion(entry)

    fecha = (
        entry.get("dc_date")
        or entry.get("published")
        or entry.get("updated")
        or ""
    )

    contenido = f"{titulo}|{fecha}|{descripcion}"

    return hashlib.sha256(
        contenido.encode("utf-8")
    ).hexdigest()


# ============================================================
# HISTORIAL
# ============================================================

def cargar_historial():
    if not HISTORIAL_FILE.exists():
        return []

    try:
        with HISTORIAL_FILE.open("r", encoding="utf-8") as archivo:
            historial = json.load(archivo)

        if not isinstance(historial, list):
            raise ValueError("El historial no es una lista.")

        return [str(item) for item in historial]

    except (OSError, ValueError, json.JSONDecodeError) as error:
        logging.error("Error leyendo el historial: %s", error)
        raise


def guardar_historial(historial):
    historial = historial[-MAX_HISTORIAL:]

    temporal = HISTORIAL_FILE.with_suffix(".tmp")

    with temporal.open("w", encoding="utf-8") as archivo:
        json.dump(
            historial,
            archivo,
            ensure_ascii=False,
            indent=2,
        )

    temporal.replace(HISTORIAL_FILE)


# ============================================================
# LECTURA DEL RSS
# ============================================================

def obtener_alertas():
    respuesta = requests.get(
        RSS_URL,
        timeout=TIMEOUT,
        headers={"User-Agent": "AlertasSMN-Patquia/1.0"},
    )

    respuesta.raise_for_status()

    feed = feedparser.parse(respuesta.content)

    if feed.bozo:
        logging.warning(
            "Advertencia al interpretar el RSS: %s",
            feed.bozo_exception,
        )

    if not feed.entries:
        raise RuntimeError(
            "El RSS no devolvió entradas. Se interrumpe "
            "la ejecución para evitar un falso resultado vacío."
        )

    return feed.entries


# ============================================================
# DETECCIÓN POR PALABRAS CLAVE
# ============================================================

def coincide_con_palabras_clave(entry):
    titulo = obtener_titulo(entry)
    descripcion = limpiar_html(obtener_descripcion(entry))

    contenido = normalizar(f"{titulo} {descripcion}")

    coincidencias = [
        palabra
        for palabra in PALABRAS_NORMALIZADAS
        if palabra in contenido
    ]

    if coincidencias:
        logging.info(
            "Coincidencia textual: %s",
            ", ".join(coincidencias),
        )

    return bool(coincidencias)


# ============================================================
# DETECCIÓN GEOGRÁFICA
# ============================================================

def obtener_poligono(entry):
    """
    Lee las coordenadas GeoRSS del SMN.
    GeoRSS polygon utiliza pares: latitud longitud.
    """
    poligono = (
        entry.get("georss_polygon")
        or entry.get("polygon")
        or ""
    )

    if isinstance(poligono, list):
        poligono = " ".join(str(x) for x in poligono)

    numeros = re.findall(
        r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)",
        str(poligono),
    )

    if len(numeros) < 6 or len(numeros) % 2 != 0:
        return []

    try:
        valores = [float(n) for n in numeros]
    except ValueError:
        return []

    return [
        (valores[i], valores[i + 1])
        for i in range(0, len(valores), 2)
    ]


def punto_dentro_poligono(latitud, longitud, poligono):
    """
    Comprueba si un punto está dentro de un polígono.
    El método utiliza el algoritmo ray casting.
    """
    if len(poligono) < 3:
        return False

    dentro = False
    j = len(poligono) - 1

    for i in range(len(poligono)):
        lat_i, lon_i = poligono[i]
        lat_j, lon_j = poligono[j]

        cruza = (
            (lat_i > latitud) != (lat_j > latitud)
        ) and (
            longitud
            < (lon_j - lon_i)
            * (latitud - lat_i)
            / ((lat_j - lat_i) or 1e-15)
            + lon_i
        )

        if cruza:
            dentro = not dentro

        j = i

    return dentro


def afecta_patquia(entry):
    poligono = obtener_poligono(entry)

    if not poligono:
        logging.debug(
            "El aviso no contiene un polígono GeoRSS válido."
        )
        return False

    resultado = punto_dentro_poligono(
        PATQUIA_LAT,
        PATQUIA_LON,
        poligono,
    )

    if resultado:
        logging.info(
            "El polígono del SMN incluye las coordenadas "
            "configuradas para Patquía."
        )

    return resultado


# ============================================================
# DATOS DEL AVISO OFICIAL
# ============================================================

def extraer_fecha_oficial(entry):
    """
    Extrae la fecha y hora del título o de la descripción.
    Ejemplo: del 09-10-2026 a las 04:09 HOA.
    """
    texto = (
        obtener_titulo(entry)
        + " "
        + limpiar_html(obtener_descripcion(entry))
    )

    patron = (
        r"(\d{2}-\d{2}-\d{4})"
        r"\s+a\s+las\s+(\d{2}:\d{2})"
        r"(?:\s+HOA)?"
    )

    coincidencia = re.search(
        patron,
        texto,
        flags=re.IGNORECASE,
    )

    if coincidencia:
        fecha, hora = coincidencia.groups()

        try:
            fecha_dt = datetime.strptime(
                f"{fecha} {hora}",
                "%d-%m-%Y %H:%M",
            )

            return fecha_dt.replace(tzinfo=ZONA_ARGENTINA)

        except ValueError:
            pass

    # Alternativa: fecha de publicación del RSS.
    for campo in ("dc_date", "published", "updated"):
        valor = entry.get(campo)

        if not valor:
            continue

        try:
            fecha_dt = parsedate_to_datetime(valor)

            if fecha_dt.tzinfo is None:
                fecha_dt = fecha_dt.replace(tzinfo=timezone.utc)

            return fecha_dt.astimezone(ZONA_ARGENTINA)

        except (TypeError, ValueError, OverflowError):
            try:
                fecha_dt = datetime.fromisoformat(
                    str(valor).replace("Z", "+00:00")
                )

                if fecha_dt.tzinfo is None:
                    fecha_dt = fecha_dt.replace(tzinfo=timezone.utc)

                return fecha_dt.astimezone(ZONA_ARGENTINA)

            except (TypeError, ValueError, OverflowError):
                continue

    return None


def extraer_numero_aviso(titulo):
    coincidencia = re.search(
        r"\bN[°ºo.]?\s*(\d+)",
        titulo,
        flags=re.IGNORECASE,
    )

    return coincidencia.group(1) if coincidencia else None


def extraer_fenomeno(descripcion):
    """
    Busca el fenómeno en la frase oficial
    'por ocurrencia de ...' del SMN.
    """
    coincidencia = re.search(
        r"por\s+ocurrencia\s+de\s+(.*?)(?:</b>|</p>|<br|$)",
        descripcion,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if coincidencia:
        return limpiar_html(coincidencia.group(1)).strip(" .\n")

    texto = limpiar_html(descripcion)

    coincidencia = re.search(
        r"por\s+ocurrencia\s+de\s+(.+?)(?:\.\s|$)",
        texto,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if coincidencia:
        return coincidencia.group(1).strip(" .\n")

    return "Consultar descripción oficial del aviso."


def extraer_zona_afectada(descripcion):
    """
    Extrae el texto que sigue a la lista de departamentos.
    """
    coincidencia = re.search(
        r"Afectando\s+parcialmente\s+los\s+siguientes"
        r"\s+Partidos\s*\|\s*Departamentos\s*:\s*(.*?)"
        r"(?=<img\b|$)",
        descripcion,
        flags=re.IGNORECASE | re.DOTALL,
    )

    if not coincidencia:
        return ""

    zona = limpiar_html(coincidencia.group(1))

    return re.sub(r"\n{2,}", "\n", zona).strip(" \n:-")


def extraer_mapas(descripcion):
    """Extrae los enlaces a los mapas GIF del aviso."""
    imagenes = re.findall(
        r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""",
        descripcion,
        flags=re.IGNORECASE,
    )

    resultado = []

    for imagen in imagenes:
        url = unescape(imagen).strip()

        # El RSS oficial normalmente utiliza URLs HTTPS.
        if url.startswith("https://"):
            if url not in resultado:
                resultado.append(url)

    return resultado


# ============================================================
# CONSTRUCCIÓN DEL MENSAJE PARA TELEGRAM
# ============================================================

def construir_mensaje(entry, coincidencia_textual, coincidencia_geo):
    titulo = obtener_titulo(entry)
    descripcion = obtener_descripcion(entry)

    numero = extraer_numero_aviso(titulo)
    fecha_oficial = extraer_fecha_oficial(entry)
    fenomeno = extraer_fenomeno(descripcion)
    zona = extraer_zona_afectada(descripcion)
    mapas = extraer_mapas(descripcion)

    ahora = datetime.now(ZONA_ARGENTINA)

    if fecha_oficial:
        emision = fecha_oficial.strftime("%d/%m/%Y a las %H:%M h")
    else:
        emision = "No disponible en el RSS"

    if numero:
        encabezado = f"Aviso N.º {numero}"
    else:
        encabezado = titulo

    lineas = [
        "⚠️ AVISO METEOROLÓGICO A MUY CORTO PLAZO",
        "",
        f"{encabezado} · {emision}",
        "",
        "⛈️ FENÓMENO",
        fenomeno,
        "",
        "📍 ZONA AFECTADA",
    ]

    if zona:
        lineas.append(zona)

    if coincidencia_geo:
        lineas.extend([
            "",
            "📌 El polígono oficial del aviso alcanza "
            "las coordenadas configuradas para Patquía.",
        ])

    if not zona and coincidencia_geo:
        lineas.append(
            "Patquía, La Rioja (coincidencia geográfica)."
        )

    lineas.extend([
        "",
        "🕒 EMISIÓN OFICIAL",
        emision,
        "",
        f"🕓 Detectada por el sistema: {ahora.strftime('%d/%m/%Y a las %H:%M')} h",
    ])

    if mapas:
        lineas.extend(["", "🗺️ MAPAS DEL AVISO"])

        for i, mapa in enumerate(mapas, start=1):
            etiqueta = (
                "Mapa general"
                if i == 1
                else "Mapa del aviso"
                if i == 2
                else f"Mapa {i}"
            )

            lineas.append(f"{etiqueta}: {mapa}")

    lineas.extend([
        "",
        f"🔗 Fuente oficial: {FUENTE_OFICIAL}",
    ])

    mensaje = "\n".join(lineas).strip()

    if len(mensaje) > MAX_MENSAJE:
        mensaje = mensaje[:MAX_MENSAJE - 30] + "\n[Texto recortado]"

    return mensaje


# ============================================================
# ENVÍO A TELEGRAM
# ============================================================

def enviar_telegram_texto(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID "
            "en las variables de entorno."
        )

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    respuesta = requests.post(
        url,
        json={
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": mensaje,
            "disable_web_page_preview": True,
        },
        timeout=TIMEOUT,
    )

    respuesta.raise_for_status()
    datos = respuesta.json()

    if not datos.get("ok"):
        raise RuntimeError(
            f"Telegram rechazó el mensaje: {datos}"
        )

    return True


# ============================================================
# PROCESAMIENTO PRINCIPAL
# ============================================================

def procesar_alertas():
    historial = cargar_historial()
    historial_set = set(historial)

    entradas = obtener_alertas()

    logging.info("Entradas recibidas del SMN: %s", len(entradas))

    nuevas = []

    for entry in entradas:
        alerta_id = identificar_alerta(entry)

        if not alerta_id or alerta_id in historial_set:
            continue

        coincide_texto = coincide_con_palabras_clave(entry)
        coincide_geo = afecta_patquia(entry)

        # Se envía si coincide por texto O por ubicación.
        if coincide_texto or coincide_geo:
            nuevas.append(
                (alerta_id, entry, coincide_texto, coincide_geo)
            )

    if not nuevas:
        logging.info(
            "No hay alertas nuevas para las palabras clave "
            "ni para el área geográfica configurada."
        )
        return

    logging.info("Alertas nuevas detectadas: %s", len(nuevas))

    # Los RSS suelen presentar primero los avisos recientes.
    # Se procesan en orden inverso para evitar saltos.
    for alerta_id, entry, coincide_texto, coincide_geo in reversed(nuevas):
        mensaje = construir_mensaje(
            entry,
            coincide_texto,
            coincide_geo,
        )

        try:
            enviar_telegram_texto(mensaje)

        except (requests.RequestException, RuntimeError, ValueError) as error:
            logging.error(
                "Error al enviar %s: %s",
                alerta_id,
                error,
            )
            # No se registra: se intentará de nuevo más adelante.
            continue

        # Registrar únicamente después del envío confirmado.
        historial.append(alerta_id)
        historial_set.add(alerta_id)
        guardar_historial(historial)

        logging.info("Alerta enviada: %s", alerta_id)


if __name__ == "__main__":
    try:
        procesar_alertas()
    except Exception:
        logging.exception("Error general al procesar las alertas.")
        raise
