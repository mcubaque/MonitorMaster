import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi import UploadFile, File
from fastapi.responses import FileResponse
import pyodbc
import os
from decimal import Decimal
from datetime import datetime
from dotenv import load_dotenv
from PyPDF2 import PdfReader, PdfWriter


# Cargar variables de entorno desde el archivo .env
load_dotenv()

app = FastAPI()

DB_DATABASE = os.getenv("DB_DATABASE")

# Montar la carpeta 'img' para servir archivos estáticos
app.mount("/img", StaticFiles(directory="img"), name="img")

# Obtener credenciales de la base de datos desde variables de entorno
server = os.getenv("DB_SERVER")
database = os.getenv("DB_DATABASE")
username = os.getenv("DB_USERNAME")
password = os.getenv("DB_PASSWORD")
conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}"

@app.get("/metrics")
async def get_metrics():
    query = """
    SELECT 
        s.session_id,
        s.host_name,
        s.login_name,
        DB_NAME(r.database_id) AS database_name,
        s.status,
        s.cpu_time,
        s.memory_usage * 8 AS memory_usage_kb, -- Convert memory pages to KB
        s.total_scheduled_time,
        s.total_elapsed_time,
        r.wait_type,
        r.wait_time,
        r.blocking_session_id,
        r.command,
        r.reads,
        r.writes,
        r.logical_reads,
        t.text AS sql_text,
        q.query_plan
    FROM 
        sys.dm_exec_sessions s
    LEFT JOIN 
        sys.dm_exec_requests r ON s.session_id = r.session_id
    OUTER APPLY 
        sys.dm_exec_sql_text(r.sql_handle) t
    OUTER APPLY 
        sys.dm_exec_query_plan(r.plan_handle) q
    WHERE 
        s.is_user_process = 1 
    ORDER BY 
        s.status, s.total_elapsed_time Desc, s.session_id;
    """
    
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        results = []
        for row in cursor.fetchall():
            results.append(dict(zip(columns, row)))
    
    return JSONResponse(content=results)

@app.get("/cpu_usage")
async def get_cpu_usage():
    query = """
    WITH DB_CPU_Stats
    AS
    (SELECT DatabaseID, DB_Name(DatabaseID) AS [Database Name], SUM(total_worker_time) AS [CPU_Time_Ms]
     FROM sys.dm_exec_query_stats AS qs
     CROSS APPLY (SELECT CONVERT(int, value) AS [DatabaseID] 
                  FROM sys.dm_exec_plan_attributes(qs.plan_handle)
                  WHERE attribute = N'dbid') AS F_DB
     GROUP BY DatabaseID)
    SELECT ROW_NUMBER() OVER(ORDER BY [CPU_Time_Ms] DESC) AS [CPU Rank],
           [Database Name], [CPU_Time_Ms] AS [CPU Time (ms)], 
           CAST([CPU_Time_Ms] * 1.0 / SUM([CPU_Time_Ms]) OVER() * 100.0 AS DECIMAL(5, 2)) AS [CPU Percent]
    FROM DB_CPU_Stats
    """
    
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            if cursor.description is None:
                raise HTTPException(status_code=500, detail="Query did not return any results")
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                # Convert Decimal to float
                for key, value in row_dict.items():
                    if isinstance(value, Decimal):
                        row_dict[key] = float(value)
                results.append(row_dict)
        return JSONResponse(content=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/cpu_memory_disk")
async def get_cpu_memory_disk():
    query = """
    WITH CPU_Usage AS (
        SELECT TOP 1
            DATEADD(ms, -1 * (rb.timestamp - si.sqlserver_start_time_ms_ticks), GETDATE()) AS collection_time,
            CONVERT(INT, x.value('(//SystemIdle)[1]', 'int')) AS System_Idle,
            CONVERT(INT, x.value('(//SQLProcessUtilization)[1]', 'int')) AS SQL_CPU_Usage,
            100 - CONVERT(INT, x.value('(//SystemIdle)[1]', 'int')) - CONVERT(INT, x.value('(//SQLProcessUtilization)[1]', 'int')) AS Other_CPU_Usage
        FROM sys.dm_os_ring_buffers AS rb
        CROSS JOIN sys.dm_os_sys_info AS si
        CROSS APPLY (SELECT CONVERT(XML, rb.record)) AS T(x)
        WHERE rb.ring_buffer_type = N'RING_BUFFER_SCHEDULER_MONITOR'
        ORDER BY rb.timestamp DESC
    ),
    Memory_Usage AS (
        SELECT 
            total_physical_memory_kb / 1024 AS Total_RAM_MB,
            available_physical_memory_kb / 1024 AS Available_RAM_MB,
            (total_physical_memory_kb - available_physical_memory_kb) * 100.0 / total_physical_memory_kb AS RAM_Used_Percent,
            system_memory_state_desc
        FROM sys.dm_os_sys_memory
    ),
    Disk_IO AS (
        SELECT 
            SUM(num_of_reads) AS Total_Reads,
            SUM(num_of_writes) AS Total_Writes,
            SUM(io_stall_read_ms) AS Read_Stall_Time_ms,
            SUM(io_stall_write_ms) AS Write_Stall_Time_ms
        FROM sys.dm_io_virtual_file_stats(NULL, NULL)
    ),
    Connections AS (
        SELECT 
            COUNT(*) AS Active_Sessions
        FROM sys.dm_exec_sessions
        WHERE is_user_process = 1
    )
    SELECT 
        c.collection_time,
        
        -- Uso de CPU
        c.SQL_CPU_Usage,
        CASE 
            WHEN c.SQL_CPU_Usage IS NULL THEN 'Desconocido'
            WHEN c.SQL_CPU_Usage < 30 THEN 'Bajo'
            WHEN c.SQL_CPU_Usage BETWEEN 30 AND 70 THEN 'Normal'
            ELSE 'Alto'
        END AS CPU_Status,

        -- Uso de RAM
        m.RAM_Used_Percent,
        CASE 
            WHEN m.RAM_Used_Percent IS NULL THEN 'Desconocido'
            WHEN m.RAM_Used_Percent < 50 THEN 'Bajo'
            WHEN m.RAM_Used_Percent BETWEEN 50 AND 85 THEN 'Normal'
            ELSE 'Alto'
        END AS Memory_Status,

        -- Uso de Disco (Latencia de I/O)
        d.Read_Stall_Time_ms,
        d.Write_Stall_Time_ms,
        CASE 
            WHEN d.Read_Stall_Time_ms < 100 AND d.Write_Stall_Time_ms < 100 THEN 'Bajo'
            WHEN d.Read_Stall_Time_ms BETWEEN 100 AND 500 OR d.Write_Stall_Time_ms BETWEEN 100 AND 500 THEN 'Normal'
            ELSE 'Alto'
        END AS Disk_Status,

        -- Sesiones Activas
        con.Active_Sessions
    FROM CPU_Usage c
    CROSS JOIN Memory_Usage m
    CROSS JOIN Disk_IO d
    CROSS JOIN Connections con;
    """
    
    with pyodbc.connect(conn_str) as conn:
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [column[0] for column in cursor.description]
        results = []
        for row in cursor.fetchall():
            row_dict = dict(zip(columns, row))
            # Convert datetime objects to strings
            for key, value in row_dict.items():
                if isinstance(value, datetime):
                    row_dict[key] = value.isoformat()
                elif isinstance(value, Decimal):
                    row_dict[key] = float(value)
            results.append(row_dict)
    
    return JSONResponse(content=results)

@app.get("/locks")
async def get_locks():
    query = """
    SELECT 
        request_session_id AS 'ID de Sesión',
        request_status AS 'Estado',
        request_mode AS 'Modo',
        request_type AS 'Tipo',
        DB_NAME(resource_database_id) AS 'Base de datos',
        OBJECT_NAME(resource_associated_entity_id, resource_database_id) AS 'Objeto',
        request_lifetime AS 'Tiempo de Solicitud'
    FROM sys.dm_tran_locks
    WHERE resource_type <> 'DATABASE'
    ORDER BY request_session_id;
    """
    
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            if cursor.description is None:
                return JSONResponse(content=[])
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                # Convertir datetime a string para JSON
                for key, value in row_dict.items():
                    if isinstance(value, datetime):
                        row_dict[key] = value.isoformat()
                results.append(row_dict)
        return JSONResponse(content=results)
    except Exception as e:
        return JSONResponse(content={"error": str(e)}, status_code=500)
        
@app.get("/network_traffic")
async def get_network_traffic():
    query = """
    SELECT TOP 10
        session_id,
        local_net_address,
        client_net_address,
        num_writes AS packets_sent,
        num_reads AS packets_received,
        num_reads + num_writes AS total_packets,
        connect_time
    FROM sys.dm_exec_connections;
    """
    
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            if cursor.description is None:
                raise HTTPException(status_code=500, detail="Query did not return any results")
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                # Convert datetime objects to strings
                for key, value in row_dict.items():
                    if isinstance(value, datetime):
                        row_dict[key] = value.isoformat()
                    elif isinstance(value, Decimal):
                        row_dict[key] = float(value)
                results.append(row_dict)
        return JSONResponse(content=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/top_expensive_queries")
async def get_top_expensive_queries():
    query = """
    SELECT TOP 5
        qs.total_worker_time AS [Total CPU Time],
        qs.total_elapsed_time AS [Total Elapsed Time],
        qs.total_logical_reads AS [Total Logical Reads],
        qs.total_logical_writes AS [Total Logical Writes],
        qs.execution_count AS [Execution Count],
        SUBSTRING(st.text, (qs.statement_start_offset/2) + 1,
        ((CASE qs.statement_end_offset
            WHEN -1 THEN DATALENGTH(st.text)
            ELSE qs.statement_end_offset
        END - qs.statement_start_offset)/2) + 1) AS [Query Text]
    FROM
        sys.dm_exec_query_stats AS qs
    CROSS APPLY
        sys.dm_exec_sql_text(qs.sql_handle) AS st
    CROSS APPLY
        sys.dm_exec_query_plan(qs.plan_handle) AS qp
    ORDER BY
        qs.total_worker_time DESC;
    """
    
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            if cursor.description is None:
                raise HTTPException(status_code=500, detail="Query did not return any results")
            columns = [column[0] for column in cursor.description]
            results = []
            for row in cursor.fetchall():
                row_dict = dict(zip(columns, row))
                # Convert Decimal to float
                for key, value in row_dict.items():
                    if isinstance(value, Decimal):
                        row_dict[key] = float(value)
                results.append(row_dict)
        return JSONResponse(content=results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# Configuración SMTP desde variables de entorno
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

app.mount("/img", StaticFiles(directory="img"), name="img")

# Obtener credenciales de la base de datos desde variables de entorno
server = os.getenv("DB_SERVER")
database = os.getenv("DB_DATABASE")
username = os.getenv("DB_USERNAME")
password = os.getenv("DB_PASSWORD")
conn_str = f"DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={server};DATABASE={database};UID={username};PWD={password}"

# Configuración SMTP
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587  # Usa 465 si prefieres SSL
SMTP_USER = "notificacionesrithmxo@gmail.com"
SMTP_PASSWORD = "zbeyjzhmdafyzvmj"

def send_email_with_attachment(to_email, subject, body, attachment_path=None):
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    if attachment_path:
        with open(attachment_path, "rb") as attachment:
            part = MIMEApplication(attachment.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            msg.attach(part)

    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        print("Correo enviado con éxito")
    except Exception as e:
        print(f"Error enviando correo: {e}")

@app.get("/check-ram-usage")
async def check_ram_usage():
    query = """
    SELECT 
        (total_physical_memory_kb - available_physical_memory_kb) * 100.0 / total_physical_memory_kb AS RAM_Used_Percent
    FROM sys.dm_os_sys_memory
    """
    
    try:
        with pyodbc.connect(conn_str) as conn:
            cursor = conn.cursor()
            cursor.execute(query)
            result = cursor.fetchone()
            if result:
                ram_used_percent = float(result[0])  # Convertir Decimal a float
                if ram_used_percent > 30:  # Cambia este valor para probar la alerta
                    send_email_with_attachment(
                        "marco.cubaque@rithmxo.com",
                        f"Alerta de Uso de RAM en el servidor: {server}",
                        f"El uso de RAM ha superado el umbral establecido. Uso actual: {ram_used_percent:.2f}%"
                    )
                return JSONResponse(content={"RAM_Used_Percent": ram_used_percent})
            else:
                raise HTTPException(status_code=500, detail="No se pudo obtener el uso de RAM")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    

@app.get("/", response_class=HTMLResponse)
async def get_index():
    with open("index.html", "r", encoding="utf-8") as file:
        content = file.read()
        content = content.replace("{{DB_DATABASE}}", DB_DATABASE)
        return HTMLResponse(content=content)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)