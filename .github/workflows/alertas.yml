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


def todos_hijos(elemento, nombre):
    """Obtiene todos los hijos directos que coinciden con el nombre."""
    if elemento is None:
        return []

    return [
        item for item in elemento
        if nombre_etiqueta(item) == nombre
    ]


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

        # Si la fecha no incluye zona horaria, CAP normalmente debe
        # interpretarse en UTC para evitar mostrar una hora incorrecta.
        if fecha.tzinfo is None:
            fecha = fecha.replace(tzinfo=timezone.utc)

        fecha = fecha.astimezone(ZONA_HORARIA)
        mes = MESES[fecha.month - 1]

        return f"{fecha.day} de {mes} - {fecha:%H:%M}"

    except (ValueError, TypeError):
        return valor


# =========================================================
# POLÍGONOS Y LOCALIDADES
# =========================================================

def leer_poligono(valor):
    """Convierte vértices CAP "lat,lon lat,lon ..." en pares (lat, lon)."""
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

    # La respuesta GeoJSON habitual es una FeatureCollection.
    if datos.get("type") == "FeatureCollection":
        features = datos.get("features", [])
    elif datos.get("type") == "Feature":
        features = [datos]
    else:
        raise RuntimeError(
            "Georef no devolvió un GeoJSON reconocible para General Alvear."
        )

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
    """Devuelve la zona monitoreada si el CAP intersecta el departamento."""
    if DEPARTAMENTO_GEOMETRIA is None:
        raise RuntimeError("No se cargó el límite de General Alvear.")

    for elemento in todos_hijos(area, "polygon"):
        puntos = leer_poligono(elemento.text)
        if len(puntos) < 3:
            continue

        # CAP expresa latitud,longitud; GeoJSON/Shapely utiliza longitud,latitud.
        poligono_cap = Polygon([(lon, lat) for lat, lon in puntos])
        if not poligono_cap.is_valid:
            poligono_cap = poligono_cap.buffer(0)

        if not poligono_cap.is_empty and DEPARTAMENTO_GEOMETRIA.intersects(poligono_cap):
            return {NOMBRE_ZONA}

    return set()


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
        json.dump(
            sorted(historial),
            archivo,
            ensure_ascii=False,
            indent=2,
        )


def clave_alerta(identificador, enviado):
    """Distingue una alerta de sus actualizaciones posteriores."""
    valor = f"{identificador}|{enviado}"
    return hashlib.sha256(valor.encode("utf-8")).hexdigest()


# =========================================================
# TELEGRAM
# =========================================================

def enviar_telegram(mensaje):
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Faltan los secretos TELEGRAM_BOT_TOKEN o TELEGRAM_CHANNEL_ID."
        )

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

    respuesta.raise_for_status()
    resultado = respuesta.json()

    if not resultado.get("ok"):
        raise RuntimeError(f"Telegram rechazó el mensaje: {resultado}")

    print("Mensaje enviado correctamente a Telegram.")


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
        lineas.extend([
            "",
            "📝 <b>Descripción:</b>",
            html.escape(descripcion),
        ])

    if instrucciones and instrucciones != "No especificada":
        lineas.extend([
            "",
            "🛡️ <b>Recomendaciones:</b>",
            html.escape(instrucciones),
        ])

    return "\n".join(lineas)


# =========================================================
# PROCESAMIENTO DE ALERTAS CAP
# =========================================================

def procesar_cap(contenido, historial, claves_procesadas):
    raiz = ET.fromstring(contenido)

    if nombre_etiqueta(raiz) != "alert":
        print("El documento recibido no es un XML CAP.")
        return

    identificador = texto(raiz, "identifier", "")
    enviado = texto(raiz, "sent", "")

    if not identificador:
        print("Se encontró una alerta sin identificador; se omite.")
        return

    clave = clave_alerta(identificador, enviado)

    if clave in historial or clave in claves_procesadas:
        print(f"Alerta ya notificada: {identificador}")
        return

    localidades = set()
    info_elegida = None

    for info in todos_hijos(raiz, "info"):
        localidades_info = set()

        for area in todos_hijos(info, "area"):
            localidades_info.update(localidades_afectadas(area))

        if localidades_info:
            localidades.update(localidades_info)

            if info_elegida is None:
                info_elegida = info

    if not localidades or info_elegida is None:
        print(f"Sin coincidencias geográficas: {identificador}")
        return

    mensaje = construir_mensaje(raiz, info_elegida, localidades)
    enviar_telegram(mensaje)

    # Se registra únicamente después de confirmar el envío.
    historial.add(clave)
    claves_procesadas.add(clave)
    guardar_historial(historial)


# =========================================================
# LECTURA DEL FEED DEL SMN
# =========================================================

def enlaces_cap(contenido):
    """Extrae los enlaces XML CAP de un RSS o Atom."""
    raiz = ET.fromstring(contenido)

    if nombre_etiqueta(raiz) == "alert":
        return [None]

    enlaces = []

    for elemento in raiz.iter():
        nombre = nombre_etiqueta(elemento)

        if nombre == "item":
            for item_hijo in elemento:
                if nombre_etiqueta(item_hijo) == "link" and item_hijo.text:
                    enlaces.append(item_hijo.text.strip())

        elif nombre == "entry":
            for item_hijo in elemento:
                if nombre_etiqueta(item_hijo) == "link":
                    href = item_hijo.attrib.get("href")
                    rel = item_hijo.attrib.get("rel", "alternate")

                    if href and rel in ("alternate", "enclosure"):
                        enlaces.append(href.strip())

    # Conserva el orden y elimina enlaces duplicados.
    return list(dict.fromkeys(enlaces))


def ejecutar():
    if not TOKEN or not CHAT_ID:
        raise RuntimeError(
            "Configurá TELEGRAM_BOT_TOKEN y TELEGRAM_CHANNEL_ID "
            "en los secretos de GitHub Actions."
        )

    global DEPARTAMENTO_GEOMETRIA
    DEPARTAMENTO_GEOMETRIA = cargar_limite_departamento()

    historial = cargar_historial()
    claves_procesadas = set()

    print(f"Monitoreando: {NOMBRE_ZONA}")
    print("Consultando el feed de alertas del SMN...")

    respuesta = requests.get(RSS_URL, timeout=30)
    respuesta.raise_for_status()

    enlaces = enlaces_cap(respuesta.content)

    # Permite procesar directamente un XML CAP si el servidor lo devuelve.
    raiz = ET.fromstring(respuesta.content)

    if nombre_etiqueta(raiz) == "alert":
        procesar_cap(
            respuesta.content,
            historial,
            claves_procesadas,
        )
        return

    if not enlaces:
        print("El feed no contiene enlaces CAP reconocibles.")
        return

    for enlace in enlaces:
        try:
            url_cap = urljoin(RSS_URL, enlace)

            print(f"Consultando: {url_cap}")

            respuesta_cap = requests.get(url_cap, timeout=30)
            respuesta_cap.raise_for_status()

            procesar_cap(
                respuesta_cap.content,
                historial,
                claves_procesadas,
            )

        except (requests.RequestException, ET.ParseError, RuntimeError) as error:
            print(f"Error al procesar {enlace}: {error}")

    print("Consulta finalizada.")


if __name__ == "__main__":
    ejecutar()
