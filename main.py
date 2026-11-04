import os
import json
import html
import hashlib
import requests
import xml.etree.ElementTree as ET

from shapely.geometry import Polygon, shape
from shapely.ops import unary_union

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib.parse import urljoin


# =========================================================z
# CONFIGURACIÓN
# =========================================================

RSS_URL = "https://ssl.smn.gob.ar/CAP/AR.php"
HISTORIAL_ARCHIVO = "historial_alertas.json"

# Límite administrativo oficial consultado en la API Georef (Argentina.gob.ar).
GEOREF_URL = "https://apis.datos.gob.ar/georef/api/departamentos"
NOMBRE_ZONA = "Departamento de General Alvear, Mendoza"
DEPARTAMENTO_GEOMETRIA = None

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHANNEL_ID")

ZONA_HORARIA = ZoneInfo("America/Argentina/Buenos_Aires")

# El monitoreo se realiza sobre el polígono completo del departamento.


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
    return elemento.tag.split("}")[-1]


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
