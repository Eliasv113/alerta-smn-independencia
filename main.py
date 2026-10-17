
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
import json
import logging
import os
import re
import unicodedata

import feedparser
import requests


# =========================================================
# CONFIGURACIÓN
# =========================================================

RSS_URL = "https://ssl.smn.gob.ar/feeds/avisocorto_GeoRSS.xml"

PALABRAS_CLAVE = [
    "LA RIOJA:INDEPENDENCIA",
    "LA RIOJA: PATQUIA",
    "LA RIOJA: PATQUÍA",
]

# Estos valores se configuran en GitHub Secrets.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")

HISTORIAL_FILE = Path("historial_alertas.json")
MAX_HISTORIAL = 2000
TIMEOUT = 20

ZONA_ARGENTINA = timezone(timedelta(hours=-3))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =========================================================
# NORMALIZACIÓN Y LIMPIEZA
# =========================================================

def normalizar(texto):
    """Ignora mayúsculas, tildes y espacios innecesarios."""
    texto = unescape(str(texto or ""))
    texto = unicodedata.normalize("NFD", texto)
    texto = "".join(
        caracter for caracter in texto
        if unicodedata.category(caracter) != "Mn"
    )
    texto = texto.upper()
    texto = re.sub(r"\s*:\s*", ":", texto)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


PALABRAS_NORMALIZADAS = [
    normalizar(palabra) for palabra in PALABRAS_CLAVE
]


def limpiar_html(texto):
    """Convierte HTML sencillo en texto legible."""
    texto = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>",
        " ",
        texto or "",
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
    texto = re.sub(r"\n\s*\n+", "\n\n", texto)
    return texto.strip()


def obtener_imagenes(texto):
    """Extrae enlaces de imágenes presentes en la descripción."""
    encontrados = re.findall(
        r"""<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""",
        texto or "",
        flags=re.IGNORECASE,
    )
    return list(dict.fromkeys(unescape(url) for url in encontrados))


# =========================================================
# HISTORIAL
# =========================================================

def cargar_historial():
    if not HISTORIAL_FILE.exists():
        return []

    try:
        with HISTORIAL_FILE.open("r", encoding="utf-8") as archivo:
            datos = json.load(archivo)

        if not isinstance(datos, list):
            raise ValueError("El historial no contiene una lista.")

        return [str(item) for item in datos]

    except (json.JSONDecodeError, OSError, ValueError) as error:
        logging.error("No se pudo leer el historial: %s", error)
        raise


def guardar_historial(historial):
    historial = historial[-MAX_HISTORIAL:]

    temporal = HISTORIAL_FILE.with_suffix(".tmp")
    with temporal.open("w", encoding="utf-8") as archivo:
        json.dump(historial, archivo, ensure_ascii=False, indent=2)

    temporal.replace(HISTORIAL_FILE)


# =========================================================
# RSS DEL SMN
# =========================================================

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
            "El RSS presenta una advertencia de lectura: %s",
            feed.bozo_exception,
        )

    if not feed.entries:
        logging.warning("El RSS no contiene entradas.")
    
    return feed.entries


def identificar_alerta(entry):
    """Prefiere identificadores estables del RSS."""
    return str(
        getattr(entry, "id", "")
        or getattr(entry, "guid", "")
        or getattr(entry, "link", "")
        or getattr(entry, "title", "")
    ).strip()


def coincide_con_palabras_clave(entry):
    titulo = getattr(entry, "title", "")
    descripcion = getattr(entry, "summary", "")
    
    if not descripcion:
        descripcion = getattr(entry, "description", "")

    # Algunas fuentes incluyen el contenido en otro campo.
    if not descripcion and getattr(entry, "content", None):
        descripcion = " ".join(
            item.get("value", "")
            for item in entry.content
        )

    contenido = normalizar(
        f"{titulo} {limpiar_html(descripcion)}"
    )

    return any(
        palabra in contenido
        for palabra in PALABRAS_NORMALIZADAS
    )


# =========================================================
# TELEGRAM
# =========================================================

def enviar_telegram_texto(mensaje):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        raise RuntimeError(
            "Faltan TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID."
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
    resultado = respuesta.json()

    if not resultado.get("ok"):
        raise RuntimeError(
            f"Telegram rechazó el mensaje: {resultado}"
        )

    return True


# =========================================================
# CONSTRUCCIÓN DEL MENSAJE
# =========================================================

def construir_mensaje(entry):
    titulo = limpiar_html(getattr(entry, "title", "Alerta meteorológica"))

    descripcion_cruda = (
        getattr(entry, "summary", "")
        or getattr(entry, "description", "")
    )

    if not descripcion_cruda and getattr(entry, "content", None):
        descripcion_cruda = " ".join(
            item.get("value", "")
            for item in entry.content
        )

    descripcion = limpiar_html(descripcion_cruda)
    imagenes = obtener_imagenes(descripcion_cruda)

    ahora = datetime.now(ZONA_ARGENTINA)
    fecha = ahora.strftime("%d/%m/%Y")
    hora = ahora.strftime("%H:%M")

    # Conserva la fecha de publicación si el RSS la proporciona.
    fecha_emision = ""
    fecha_rss = (
        getattr(entry, "published", "")
        or getattr(entry, "updated", "")
    )

    if fecha_rss:
        try:
            fecha_dt = parsedate_to_datetime(fecha_rss)
            if fecha_dt.tzinfo is None:
                fecha_dt = fecha_dt.replace(tzinfo=timezone.utc)

            fecha_emision = (
                "\nPublicación del RSS: "
                + fecha_dt.astimezone(ZONA_ARGENTINA).strftime(
                    "%d/%m/%Y %H:%M"
                )
            )
        except (TypeError, ValueError, OverflowError):
            pass

    link = getattr(entry, "link", "")
    lineas = [
        "⚠️ NUEVA ALERTA SMN",
        "",
        f"El Servicio Meteorológico Nacional publicó una alerta: {titulo}",
        "",
        descripcion,
        "",
        f"Detectada el: {fecha} a las {hora} (hora argentina)"
        + fecha_emision,
    ]

    if link:
        lineas.extend(["", f"Más información: {link}"])

    if imagenes:
        lineas.extend(["", "Mapas:"])
        lineas.extend(imagenes)

    mensaje = "\n".join(lineas).strip()

    # Telegram admite hasta 4096 caracteres en sendMessage.
    if len(mensaje) > 4000:
        mensaje = mensaje[:3980] + "\n\n[Texto recortado]"

    return mensaje


# =========================================================
# PROCESAMIENTO
# =========================================================

def procesar_alertas():
    historial = cargar_historial()
    historial_set = set(historial)

    entradas = obtener_alertas()
    nuevas = []

    logging.info("Entradas encontradas en el RSS: %s", len(entradas))

    for entry in entradas:
        alerta_id = identificar_alerta(entry)

        if not alerta_id or alerta_id in historial_set:
            continue

        if coincide_con_palabras_clave(entry):
            nuevas.append((alerta_id, entry))

    if not nuevas:
        logging.info("No hay alertas nuevas que coincidan.")
        return

    logging.info("Alertas nuevas coincidentes: %s", len(nuevas))

    # Los feeds suelen mostrar primero las entradas recientes.
    # Invertimos la lista para enviar primero las más antiguas
    # entre las nuevas, sin omitir coincidencias.
    for alerta_id, entry in reversed(nuevas):
        mensaje = construir_mensaje(entry)

        try:
            enviar_telegram_texto(mensaje)
        except (requests.RequestException, RuntimeError, ValueError) as error:
            logging.error(
                "No se pudo enviar la alerta %s: %s",
                alerta_id,
                error,
            )
            # No registrar: se podrá reintentar en la próxima ejecución.
            continue

        historial.append(alerta_id)
        historial_set.add(alerta_id)
        guardar_historial(historial)

        logging.info("Alerta enviada correctamente: %s", alerta_id)


if __name__ == "__main__":
    try:
        procesar_alertas()
    except Exception:
        logging.exception("Falló el procesamiento de alertas.")
        raise
