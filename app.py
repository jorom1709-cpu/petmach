import os
from werkzeug.utils import secure_filename
from flask import Flask, render_template, request, redirect, url_for, session
from pymongo import MongoClient
from bson.objectid import ObjectId
import time

app = Flask(__name__)
app.secret_key = "llave_secreta_petmach"

# --- NUEVO: Configuración para subir archivos ---
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# -----------------------------------------------
# Conexión a la base de datos MongoDB
MONGO_URI = os.environ.get("MONGO_URI")
client = MongoClient(MONGO_URI)
db = client['pet_match_db']
coleccion_mascotas = db['mascotas']
coleccion_usuarios = db['usuarios']
coleccion_refugios = db['refugios'] 
coleccion_mensajes = db['mensajes']
coleccion_solicitudes = db['solicitudes']


# Ruta para el Registro de Usuarios (ACTUALIZADA PARA VERIFICACIÓN POR WHATSAPP)
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        # Tomamos los datos del formulario de registro
        nuevo_usuario = {
            "nombre": request.form['nombre'],
            "edad": request.form['edad'],
            "correo": request.form['correo'],
            "password": request.form['password'],
            "telefono": request.form['telefono'], # 🔥 Agregamos el teléfono
            "rol": "adoptante", 
            "verificado": False # 🔥 Nace bloqueado por seguridad
        }
        
        # Validamos si el correo ya existe para no tener duplicados
        usuario_existente = coleccion_usuarios.find_one({"correo": nuevo_usuario['correo']})
        
        if usuario_existente:
            return "Ese correo ya está registrado. Intenta con otro o inicia sesión."
        
        # Si no existe, lo guardamos en MongoDB
        coleccion_usuarios.insert_one(nuevo_usuario)
        
        # 🔥 En lugar del login, lo mandamos a la pantalla del botón de WhatsApp
        return render_template('espera_whatsapp.html', nombre=nuevo_usuario['nombre'], correo=nuevo_usuario['correo'])
        
    # Si es GET, mostramos el formulario
    return render_template('registro.html')

# Ruta para el Muro de Adopción con Búsqueda
@app.route('/dashboard')
def dashboard():
    # 🛡️ 1. CANDADO BÁSICO: Validamos que haya iniciado sesión
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    # 🛡️ 2. ESCUDO KYC: Bloqueamos a los que no han sido verificados por WhatsApp
    # Buscamos al usuario en la base de datos para leer su gafete
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    
    # Si es adoptante y su estatus de verificación es False, lo rebotamos
    if usuario_actual and usuario_actual.get('rol') == 'adoptante' and not usuario_actual.get('verificado', False):
        return render_template('espera_whatsapp.html', nombre=usuario_actual['nombre'], correo=usuario_actual['correo'])

    # ===============================================================
    # 🐾 3. TU LÓGICA DE BÚSQUEDA (Actualizada con moderación invisible)
    # ===============================================================
    # Leemos si el usuario escribió algo en la barra de búsqueda (la letra 'q')
    query = request.args.get('q')
    
    if query:
        # Si escribió algo, buscamos coincidencias, PERO solo si están aprobadas
        filtro = {
            "$and": [
                {"estado": "aprobado"},
                {"$or": [
                    {"nombre": {"$regex": query, "$options": "i"}},
                    {"raza": {"$regex": query, "$options": "i"}}
                ]}
            ]
        }
        mascotas = list(coleccion_mascotas.find(filtro))
    else:
        # Si no escribió nada, traemos a todos los peluditos APROBADOS
        mascotas = list(coleccion_mascotas.find({
            "$or": [{"estado": "aprobado"}, {"estado": {"$exists": False}}]
        }))

    return render_template('dashboard.html', mascotas=mascotas)

# Ruta para agregar una nueva mascota (Dar en adopción)
@app.route('/agregar', methods=['GET', 'POST'])
def agregar_mascota():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        nombre = request.form['nombre']
        raza = request.form['raza']
        descripcion = request.form['descripcion']
        refugio_seleccionado = request.form['refugio'] # Recibimos el refugio
        
        ruta_imagen = "https://cdn-icons-png.flaticon.com/512/194/194279.png"
        
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            if archivo_foto.filename != '':
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                ruta_imagen = f"/static/uploads/{nombre_seguro}"
        
        nueva_mascota = {
            "nombre": nombre,
            "raza": raza,
            "descripcion": descripcion,
            "imagen": ruta_imagen,
            "refugio": refugio_seleccionado, # Guardamos el refugio
            "creador_id": session['usuario_id'], # Guardamos quién lo publicó
            "estado": "pendiente" # 🔥 NUEVO: La publicación nace oculta hasta revisión
        }
        coleccion_mascotas.insert_one(nueva_mascota)
        return redirect(url_for('dashboard'))
    
    # Mandamos la lista de refugios al formulario
    lista_refugios = list(coleccion_refugios.find())
    return render_template('agregar.html', refugios=lista_refugios)

# Ruta para el directorio de Refugios
@app.route('/refugios')
def refugios():
    # Traemos los refugios de la base de datos
    lista_refugios = list(coleccion_refugios.find())
    return render_template('refugios.html', refugios=lista_refugios)

# Ruta para la bandeja de Mensajes (ACTUALIZADA)
@app.route('/mensajes')
def mensajes():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    
    # Si es Admin, ve todos los chats. Si es adoptante, solo ve los suyos.
    if usuario_actual['correo'] == 'admin@petmach.com':
        mis_chats = list(coleccion_solicitudes.find())
    else:
        mis_chats = list(coleccion_solicitudes.find({"id_adoptante": session['usuario_id']}))
        
    return render_template('mensajes.html', chats=mis_chats)


# Ruta para ver el chat y responder (SEPARADOS EN DOS SALAS CON BOT)
@app.route('/chat/<id_solicitud>/<tipo>', methods=['GET', 'POST'])
def chat(id_solicitud, tipo):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    solicitud = coleccion_solicitudes.find_one({"_id": ObjectId(id_solicitud)})
    
    if request.method == 'POST':
        # Nota que ahora usamos .get('mensaje', '') por si mandan un archivo sin texto
        mensaje_texto = request.form.get('mensaje', '')
        es_manual = request.form.get('es_manual')
        
        # 🔥 NUEVO: Manejo de archivos adjuntos 🔥
        archivo_url = None
        archivo_nombre = None
        
        if 'archivo' in request.files:
            archivo = request.files['archivo']
            if archivo.filename != '':
                nombre_seguro = secure_filename(archivo.filename)
                # Le agregamos un timestamp para que el nombre sea único
                nombre_unico = f"{int(time.time())}_{nombre_seguro}"
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_unico)
                archivo.save(ruta_guardado)
                
                archivo_url = f"/static/uploads/{nombre_unico}"
                archivo_nombre = nombre_seguro # Guardamos el nombre original para mostrarlo

        nombre_remitente = usuario_actual['nombre']
        if session.get('tipo_cuenta') == 'admin' and tipo == 'sistema':
            nombre_remitente = 'Sistema Pet Mach'
        
        nuevo_mensaje = {
            "remitente": nombre_remitente,
            "mensaje": mensaje_texto,
            "destino": tipo,
            "archivo_url": archivo_url,       # Guardamos la ruta del archivo
            "archivo_nombre": archivo_nombre  # Guardamos el nombre del archivo
        }
        
        mensajes_a_guardar = [nuevo_mensaje]
        
        # 🔥 LÓGICA DEL BOT: Solo se activa la PRIMERA VEZ 🔥
        if not es_manual and session.get('tipo_cuenta') == 'adoptante' and tipo == 'refugio':
            
            # Revisamos si el bot ya habló en el historial de este chat
            chat_historial = solicitud.get('chat', [])
            bot_ya_hablo = any(msg.get('remitente') == 'Sistema Bot 🤖' for msg in chat_historial)
            
            # Si el bot NO ha hablado, le damos permiso de responder
            if not bot_ya_hablo:
                mensaje_minusculas = mensaje_texto.lower()
                respuesta_auto = "¡Hola! Hemos recibido tu mensaje en el refugio. 🐾 En breve un humano leerá tu solicitud y te responderá."
                
                if "hola" in mensaje_minusculas or "buenos" in mensaje_minusculas or "buenas" in mensaje_minusculas:
                    respuesta_auto = "¡Hola, qué gusto saludarte! 👋 Hemos notificado a nuestro equipo. En un momento un voluntario se unirá al chat."
                elif "requisito" in mensaje_minusculas or "documento" in mensaje_minusculas:
                    respuesta_auto = "¡Claro que sí! Los requisitos básicos son: Identificación oficial y comprobante de domicilio. 🐶"
                elif "tiempo" in mensaje_minusculas or "cuando" in mensaje_minusculas:
                    respuesta_auto = "¡Entendemos la emoción! 🏡 El proceso suele tardar entre 2 y 3 días hábiles. Por favor, espera un momento."

                mensaje_automatico = {
                    "remitente": "Sistema Bot 🤖",
                    "mensaje": respuesta_auto,
                    "destino": tipo
                }
                mensajes_a_guardar.append(mensaje_automatico)
            
        coleccion_solicitudes.update_one(
            {"_id": ObjectId(id_solicitud)},
            {"$push": {"chat": {"$each": mensajes_a_guardar}}}
        )
        return redirect(url_for('chat', id_solicitud=id_solicitud, tipo=tipo))

    # Lógica GET para mostrar mensajes
    mensajes_filtrados = []
    for msg in solicitud.get('chat', []):
        es_sistema = (msg.get('remitente') == 'Sistema Pet Mach') or (msg.get('destino') == 'sistema')
        
        if tipo == 'sistema' and es_sistema:
            mensajes_filtrados.append(msg)
        elif tipo == 'refugio' and not es_sistema:
            mensajes_filtrados.append(msg)
            
    return render_template('chat.html', solicitud=solicitud, usuario=usuario_actual, mensajes=mensajes_filtrados, tipo=tipo)

# 1. NUEVA RUTA PRINCIPAL (La Portada o Landing Page)
@app.route('/')
def index():
    # Si el usuario ya tiene sesión iniciada, lo mandamos directo a los perritos
    if 'usuario_id' in session:
        return redirect(url_for('dashboard'))
    # Si no, le mostramos la portada bonita
    return render_template('index.html')


# 2. RUTA DE LOGIN (PROTEGIDA CON KYC Y DETECCIÓN DE RECHAZADOS)
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        correo = request.form['correo']
        password = request.form['password']
        
        # Buscamos al usuario en MongoDB
        usuario = coleccion_usuarios.find_one({'correo': correo})
        
        # 🔥 1. CANDADO DE RECHAZADOS 🔥
        # Si el usuario existe y tiene la marca de rechazado, le avisamos de inmediato de forma bonita
        if usuario and usuario.get('rechazado', False):
            return render_template('login.html', error="❌ Lo sentimos, tu solicitud de registro fue rechazada por el administrador.")
        
        # 2. Si no está rechazado, validamos su contraseña de forma normal
        if usuario and usuario['password'] == password:
            
            # 🔥 CANDADO DE SEGURIDAD INTERNO (CUENTAS EN ESPERA) 🔥
            if usuario.get('rol') == 'adoptante' and not usuario.get('verificado', False):
                return render_template('login.html', error="⚠️ Tu cuenta está en revisión. Manda el WhatsApp al administrador para activar tu acceso.")
            
            # Si pasó los candados, creamos la sesión
            session['usuario_id'] = str(usuario['_id'])
            session['correo'] = usuario['correo']
            
            tipo_cuenta = usuario.get('rol', 'adoptante')
            session['tipo_cuenta'] = tipo_cuenta
            
            if session['tipo_cuenta'] == 'admin':
                return redirect(url_for('panel_admin'))
            elif session['tipo_cuenta'] == 'refugio':
                return redirect(url_for('panel_refugio'))
            else:
                return redirect(url_for('dashboard'))
                
        else:
            # Error de credenciales tradicional (con diseño)
            return render_template('login.html', error="❌ Correo o contraseña incorrectos.")
            
    return render_template('login.html')

# Ruta para Mi Perfil (CORREGIDA PARA NO REPETIR FORMULARIOS)
@app.route('/perfil', methods=['GET', 'POST'])
def perfil():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    
    if request.method == 'POST':
        nuevo_nombre = request.form['nombre']
        
        # Revisamos si el usuario subió una foto nueva
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            
            if archivo_foto.filename != '': # Si realmente seleccionó un archivo
                # Aseguramos el nombre del archivo y lo guardamos
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                
                # Actualizamos la base de datos con la ruta local de la nueva foto
                coleccion_usuarios.update_one(
                    {"_id": ObjectId(session['usuario_id'])},
                    {"$set": {"foto": f"/static/uploads/{nombre_seguro}"}}
                )
        
        # Actualizamos el nombre
        coleccion_usuarios.update_one(
            {"_id": ObjectId(session['usuario_id'])},
            {"$set": {"nombre": nuevo_nombre}}
        )
        return redirect(url_for('perfil'))
        
    # 🔥 AQUÍ ESTÁ EL FILTRO MÁGICO 🔥
    # Revisamos qué tipo de cuenta está viendo el perfil
    if usuario_actual.get('tipo_cuenta') == 'refugio':
        # Si es un refugio, ve únicamente los formularios dirigidos a él
        formularios = list(coleccion_solicitudes.find({"refugio": usuario_actual.get('correo')}))
    else:
        # Si es un adoptante normal, ve únicamente los formularios que él envió
        formularios = list(coleccion_solicitudes.find({"id_adoptante": session['usuario_id']}))
        
    return render_template('perfil.html', usuario=usuario_actual, solicitudes=formularios)

# RUTA PARA CERRAR SESIÓN CORRECTAMENTE
@app.route('/logout')
def logout():
    session.clear()  # 🔥 Esto destruye el gafete y borra la memoria del usuario
    return redirect(url_for('index')) # Te regresa a la portada amarilla

# Ruta para ver el perfil detallado de una mascota (ACTUALIZADA)
@app.route('/detalle/<id_mascota>') # El nombre de tu ruta
def detalle_mascota(id_mascota):
    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id_mascota)})
    
    # 🔥 NUEVA LÓGICA: ¿Este usuario ya solicitó a esta mascota?
    ya_solicito = False
    if 'usuario_id' in session:
        solicitud_previa = coleccion_solicitudes.find_one({
            "id_mascota": id_mascota,
            "id_adoptante": session['usuario_id']
        })
        if solicitud_previa:
            ya_solicito = True

    # Le pasamos la variable "ya_solicito" al HTML
    return render_template('detalle.html', mascota=mascota, ya_solicito=ya_solicito)

# NUEVA RUTA: Borrar una mascota de la base de datos (ACTUALIZADA CON BORRADO EN CASCADA)
@app.route('/mascota/borrar/<id>', methods=['POST'])
def borrar_mascota(id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    
    # 1. Eliminamos el registro del peludito en MongoDB usando su ID único
    coleccion_mascotas.delete_one({"_id": ObjectId(id)})
    
    # 🔥 2. EL BORRADO EN CASCADA 🔥
    # Buscamos en la colección de solicitudes todas las que tengan este ID y las borramos
    coleccion_solicitudes.delete_many({"id_mascota": id})
    
    # 3. Redirigimos de vuelta al muro principal
    return redirect(url_for('dashboard'))

# Ruta para el Formulario de Pre-Adopción (ACTUALIZADA PARA INICIAR EL CHAT Y CAMBIAR ESTATUS)
@app.route('/adoptar/<id_mascota>', methods=['GET', 'POST'])
def preadopcion(id_mascota):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id_mascota)})
    refugio_nombre = mascota.get('refugio', 'Refugio Asociado')
    
    if request.method == 'POST':
        nueva_solicitud = {
            "id_mascota": id_mascota,
            "nombre_mascota": mascota['nombre'],
            "refugio": refugio_nombre,
            "id_adoptante": session['usuario_id'], # Guardamos de quién es el trámite
            "nombre_adoptante": request.form['nombre'],
            "telefono": request.form['telefono'],
            "motivo": request.form['motivo'],
            # Iniciamos el historial de chat con dos mensajes automáticos
            "chat": [
                {"remitente": "Sistema Pet Mach", "mensaje": f"Tu solicitud por {mascota['nombre']} ha sido recibida."},
                {"remitente": refugio_nombre, "mensaje": "¡Hola! Analizaremos tu perfil y te responderemos por este medio."}
            ]
        }
        # 1. Guardamos la solicitud en la colección de solicitudes
        coleccion_solicitudes.insert_one(nueva_solicitud)
        
        # 🔥 2. CAMBIO DE ESTATUS AUTOMÁTICO EN LA BASE DE DATOS 🔥
        # Buscamos esta mascota específica y le inyectamos el campo estatus como 'en_proceso'
        coleccion_mascotas.update_one(
            {"_id": ObjectId(id_mascota)},
            {"$set": {"estatus": "en_proceso"}}
        )
        
        # 3. Redirigimos al usuario a sus mensajes
        return redirect(url_for('mensajes'))
        
    return render_template('preadopcion.html', mascota=mascota)

# NUEVA RUTA: Editar publicación
@app.route('/mascota/editar/<id>', methods=['GET', 'POST'])
def editar_mascota(id):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    mascota = coleccion_mascotas.find_one({"_id": ObjectId(id)})

    # Validación: Solo el creador puede editar
    if mascota.get('creador_id') != session['usuario_id']:
        return "No tienes permiso para editar esta publicación."

    if request.method == 'POST':
        nuevos_datos = {
            "nombre": request.form['nombre'],
            "raza": request.form['raza'],
            "descripcion": request.form['descripcion'],
            "refugio": request.form['refugio']
        }

        # Si subió una foto nueva, la actualizamos
        if 'foto' in request.files:
            archivo_foto = request.files['foto']
            if archivo_foto.filename != '':
                nombre_seguro = secure_filename(archivo_foto.filename)
                ruta_guardado = os.path.join(app.config['UPLOAD_FOLDER'], nombre_seguro)
                archivo_foto.save(ruta_guardado)
                nuevos_datos["imagen"] = f"/static/uploads/{nombre_seguro}"

            coleccion_mascotas.update_one({"_id": ObjectId(id)}, {"$set": nuevos_datos})
            return redirect(url_for('detalle_mascota', id_mascota=id)) # <--- CORREGIDO

    lista_refugios = list(coleccion_refugios.find())
    return render_template('editar.html', mascota=mascota, refugios=lista_refugios)

# NUEVA RUTA: Página de Nuestra Historia
@app.route('/historia')
def historia():
    return render_template('historia.html')

# Actualiza esta ruta en tu app.py
@app.route('/donar', methods=['GET', 'POST'])
def donar():
    # 1. Obtenemos la lista de refugios de la colección 'refugios'
    lista_refugios = list(coleccion_refugios.find())
    
    if request.method == 'POST':
        # Aquí puedes capturar los datos (refugio_destino, cantidad, etc.) si decides guardarlos en BD
        # Por ahora, simplemente recargamos con una bandera de éxito
        return render_template('donar.html', refugios=lista_refugios, exito=True)
        
    return render_template('donar.html', refugios=lista_refugios)

## NUEVA RUTA: El Panel de Control exclusivo para Refugios (CORREGIDA)
@app.route('/panel_refugio')
def panel_refugio():
    # 1. Validamos que haya iniciado sesión
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
        
    # 2. Validamos que de verdad sea un refugio (El "cadenero")
    if session.get('tipo_cuenta') != 'refugio':
        return redirect(url_for('dashboard'))
        
    # 🔥 3. CORRECCIÓN MAESTRA 🔥
    # Primero buscamos al usuario en la base de datos para obtener su NOMBRE real (ej: "Caninos 911")
    usuario_actual = coleccion_usuarios.find_one({"_id": ObjectId(session['usuario_id'])})
    nombre_del_refugio = usuario_actual['nombre']
    
    # Ahora buscamos las solicitudes usando el NOMBRE, que es lo que está guardado en la solicitud
    solicitudes_recibidas = list(coleccion_solicitudes.find({"refugio": nombre_del_refugio})) 
    
    return render_template('panel_refugio.html', solicitudes=solicitudes_recibidas)

@app.route('/rechazar_adopcion/<id_solicitud>', methods=['POST'])
def rechazar_adopcion(id_solicitud):
    if session.get('tipo_cuenta') == 'refugio':
        # Borramos la solicitud de la base de datos
        coleccion_solicitudes.delete_one({"_id": ObjectId(id_solicitud)})
    return redirect(url_for('panel_refugio'))


# NUEVA RUTA: El switch para activar cuentas
@app.route('/activar_usuario/<correo_usuario>')
def activar_usuario(correo_usuario):
    # Validamos que el que está dando clic sea un administrador o refugio
    if session.get('tipo_cuenta') != 'refugio':
        return "No tienes permiso para hacer esto."
        
    # Cambiamos el estatus a True en MongoDB
    coleccion_usuarios.update_one(
        {"correo": correo_usuario},
        {"$set": {"verificado": True}}
    )
    
    return f"✅ El usuario {correo_usuario} ha sido verificado y ya puede adoptar."

# =======================================================
# 🔥 PANEL EXCLUSIVO DE ADMINISTRADOR (KYC y Moderación) 🔥
# =======================================================

@app.route('/panel_admin')
def panel_admin():
    if session.get('tipo_cuenta') != 'admin':
        return "Acceso denegado. Esta área es solo para administradores."
        
    # Buscamos usuarios que no estén verificados Y que tampoco hayan sido rechazados ya
    usuarios_pendientes = list(coleccion_usuarios.find({
        "verificado": False, 
        "rechazado": {"$ne": True}, 
        "rol": "adoptante"
    }))
    
    # 🔥 NUEVO: Traemos a las mascotas que están esperando revisión
    mascotas_pendientes = list(coleccion_mascotas.find({"estado": "pendiente"}))
    
    return render_template('panel_admin.html', pendientes=usuarios_pendientes, mascotas_pendientes=mascotas_pendientes)

@app.route('/aprobar_usuario/<id_usuario>', methods=['POST'])
def aprobar_usuario(id_usuario):
    if session.get('tipo_cuenta') == 'admin':
        # Cambiamos el candado a True
        coleccion_usuarios.update_one(
            {"_id": ObjectId(id_usuario)},
            {"$set": {"verificado": True}}
        )
    return redirect(url_for('panel_admin'))

@app.route('/rechazar_usuario/<id_usuario>', methods=['POST'])
def rechazar_usuario(id_usuario):
    if session.get('tipo_cuenta') == 'admin':
        # Ya no usamos delete_one, ahora actualizamos el campo 'rechazado' a True
        coleccion_usuarios.update_one(
            {"_id": ObjectId(id_usuario)},
            {"$set": {"rechazado": True}}
        )
    return redirect(url_for('panel_admin'))

# 🔥 NUEVAS RUTAS DE MODERACIÓN 🔥
@app.route('/aprobar_mascota/<id_mascota>', methods=['POST'])
def aprobar_mascota(id_mascota):
    if session.get('tipo_cuenta') == 'admin':
        coleccion_mascotas.update_one(
            {"_id": ObjectId(id_mascota)},
            {"$set": {"estado": "aprobado"}}
        )
    return redirect(url_for('panel_admin'))

@app.route('/rechazar_mascota/<id_mascota>', methods=['POST'])
def rechazar_mascota(id_mascota):
    if session.get('tipo_cuenta') == 'admin':
        coleccion_mascotas.delete_one({"_id": ObjectId(id_mascota)})
    return redirect(url_for('panel_admin'))

@app.route('/eliminar_chat/<id_solicitud>', methods=['POST'])
def eliminar_chat(id_solicitud):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    # Eliminamos la solicitud (y el chat embebido) de MongoDB
    coleccion_solicitudes.delete_one({"_id": ObjectId(id_solicitud)})
    return redirect(url_for('mensajes'))

# Borrar solo los mensajes del sistema (sin afectar al refugio)
@app.route('/eliminar_chat_sistema/<id_solicitud>', methods=['POST'])
def eliminar_chat_sistema(id_solicitud):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))

    # Eliminamos SOLO los mensajes con destino 'sistema' o remitente 'Sistema Pet Mach'
    coleccion_solicitudes.update_one(
        {"_id": ObjectId(id_solicitud)},
        {"$pull": {"chat": {"$or": [{"destino": "sistema"}, {"remitente": "Sistema Pet Mach"}]}}}
    )
    return redirect(url_for('mensajes'))

if __name__ == '__main__':
    app.run(debug=True)