# MonitorMaster

MonitorMaster es una aplicación de monitoreo de servidores diseñada para supervisar el uso de recursos del servidor, generar reportes en formato PDF y enviar alertas por correo electrónico cuando se superan ciertos umbrales.

## Características

- Monitoreo del uso de RAM del servidor
- Generación de reportes en formato PDF
- Envío de alertas por correo electrónico
- Visualización de consultas costosas
- Visualización de tráfico de red
- Visualización de bloqueos de sesiones

## Requisitos

- Python 3.8+
- FastAPI
- Uvicorn
- PyODBC
- smtplib
- html2pdf.js
- dotenv

## Instalación

1. Clona el repositorio:

    ```bash
    git clone https://github.com/tu-usuario/MonitorMaster.git
    cd MonitorMaster
    ```

2. Crea un entorno virtual y actívalo:

    ```bash
    python -m venv venv
    source venv/bin/activate  # En Windows: venv\Scripts\activate
    ```

3. Instala las dependencias:

    ```bash
    pip install -r requirements.txt
    ```

4. Crea un archivo [.env](http://_vscodecontentref_/1) en el directorio raíz del proyecto con las siguientes variables de entorno:

    ```plaintext
    # Configuración SMTP
    SMTP_SERVER=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=email_de_notificaciones(remitente)
    SMTP_PASSWORD=clave_de_aplicacion

    # Credenciales de la base de datos
    DB_SERVER=tu_servidor_de_base_de_datos
    DB_DATABASE=tu_base_de_datos
    DB_USERNAME=tu_usuario_de_base_de_datos
    DB_PASSWORD=tu_contraseña_de_base_de_datos
    ```

## Uso

1. Inicia la aplicación:

    ```bash
    uvicorn main:app --reload
    ```

2. Abre tu navegador y navega a `http://127.0.0.1:8000` para ver la interfaz de monitoreo.

## Endpoints

- `GET /check-ram-usage`: Verifica el uso de RAM del servidor y envía una alerta si se supera el umbral establecido.
- `POST /send-report/`: Recibe un archivo PDF y lo guarda en el servidor.
- `GET /top_expensive_queries`: Obtiene las consultas más costosas en términos de uso de recursos.
- `GET /`: Devuelve la página principal de la aplicación.

## Contribuciones

Las contribuciones son bienvenidas. Por favor, abre un issue o envía un pull request para discutir cualquier cambio que te gustaría realizar.

## Licencia

Este proyecto está licenciado bajo la Licencia MIT. Consulta el archivo `LICENSE` para obtener más detalles.

## Contacto

Para cualquier pregunta o comentario, por favor contacta a [tu-email@dominio.com](mailto:tu-email@dominio.com).
