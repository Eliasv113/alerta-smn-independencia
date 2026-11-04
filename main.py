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
