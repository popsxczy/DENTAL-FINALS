# =============================================================================
# DENTAL INFORMATION SYSTEM (DIS) - app.py
# =============================================================================
# WHAT : The complete Flask backend - configuration, database models, default
#        account seeding, role-based access control (RBAC) and every route.
# WHY  : Keeping the MVP in one file makes it easy to read, run and debug.
# RUN  : 1) pip install flask flask-sqlalchemy        (needs Flask-SQLAlchemy 3.x)
#        2) python app.py
#        3) open http://127.0.0.1:5000 and log in with a default account:
#              frontdesk / password123   -> Front Desk dashboard
#              doctor    / password123   -> Doctor dashboard
#
# REQUIRED FOLDER LAYOUT (the folder MUST be named exactly "templates"):
#   dental_clinic/
#   |-- app.py
#   `-- templates/
#       |-- login.html
#       |-- front_desk_dashboard.html
#       |-- doctor_dashboard.html
#       `-- edit_appointment.html
#
# HOW TO FIX "jinja2.exceptions.TemplateNotFound":
#   The "templates" folder must sit NEXT TO app.py and the file names must match
#   the names used in render_template(...) below, letter for letter.
# =============================================================================

import os                                   # WHAT: read environment variables. WHY: keep the secret key out of the code.
from datetime import datetime, date, timedelta  # WHAT: date/time classes. WHY: appointments store a date AND a time.
from functools import wraps                 # WHAT: helper for writing decorators. WHY: used by login_required below.

from flask import (                         # WHAT: the Flask tools this app uses.
    Flask,                                  #   Flask            -> the application object
    render_template,                        #   render_template  -> fills a Jinja2 .html file with data
    request,                                #   request          -> gives access to submitted form data
    redirect,                               #   redirect         -> sends the browser to another URL
    url_for,                                #   url_for          -> builds a URL from a route FUNCTION name
    session,                                #   session          -> small signed cookie that remembers the login
    flash,                                  #   flash            -> one-time message shown on the next page
)
from flask_sqlalchemy import SQLAlchemy     # WHAT: ORM = use Python classes instead of raw SQL.
from werkzeug.security import generate_password_hash, check_password_hash
# WHY the two werkzeug helpers: passwords are stored as one-way HASHES, never as
# readable text. If the database file leaks, the real passwords are not exposed.


import requests

# The IP address and endpoint displayed in your app
SMS_GATEWAY_URL = "http://192.168.31.8:8080/send-sms"

def send_local_sms(patient_phone, patient_name, treatment, date_time):
    """Sends an automated SMS via Simple SMS Gateway on local Wi-Fi."""
    try:
        payload = {
            "phone": patient_phone,
            "message": (
                f"Hello {patient_name}, your appointment for {treatment} "
                f"at Dental Clinic is confirmed for {date_time}. See you there!"
            )
        }
        
        response = requests.post(SMS_GATEWAY_URL, json=payload, timeout=5)
        
        if response.status_code == 200:
            print("SMS dispatched successfully!")
        else:
            print(f"Gateway returned status {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"Failed to connect to phone SMS gateway: {e}")




# =============================================================================
# 1. APP + DATABASE CONFIGURATION
# =============================================================================

app = Flask(__name__)   # WHAT: create the web application. __name__ lets Flask find the "templates" folder.

# WHAT: the secret key signs the session cookie so users cannot forge a login.
# WHY : Flask refuses to use sessions or flash() without it.
# HOW TO MODIFY: set a real value before going live, e.g. (Windows) set DIS_SECRET_KEY=any-long-random-text
#                If you change the key, everyone is logged out - that is normal.
app.config['SECRET_KEY'] = os.environ.get('DIS_SECRET_KEY', 'change-this-secret-key-before-production')

# WHAT: tells SQLAlchemy where the database lives. "sqlite:///dental_clinic.db" = a single local file.
# NOTE: with Flask-SQLAlchemy 3.x the file is created inside an "instance" folder
#       (instance/dental_clinic.db), NOT next to app.py. Do not panic if you cannot find it.
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///dental_clinic.db'

# WHAT: switches off an extra change-tracking feature. WHY: saves memory and hides a warning.
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)    # WHAT: the database handle used by every model and query below.

# ---- Constants used across the app (change them HERE only) ------------------
ROLE_FRONT_DESK = 'front_desk'      # WHAT: the exact role string stored in User.role for reception staff.
ROLE_DOCTOR = 'dental_doctor'       # WHAT: the exact role string stored in User.role for the dentist.

# WHAT: the only statuses an appointment may have. WHY: lets the backend reject tampered form data.
# HOW TO MODIFY: add a new status here AND add a colour for it in the "status_colors" dict at the top
#                of each template, otherwise it shows as a grey badge.
VALID_STATUSES = ['Scheduled', 'Pending', 'Completed', 'Cancelled']


# =============================================================================
# 2. DATABASE MODELS (each class = one table)
# =============================================================================

class User(db.Model):
    """Staff account that can log in. One table row per person."""

    id = db.Column(db.Integer, primary_key=True)                 # WHAT: unique row number, created automatically.
    username = db.Column(db.String(50), unique=True, nullable=False)   # WHAT: login name. unique=True -> no duplicates.
    # WHAT: stores the password HASH (not the plain text). 255 characters is long enough for the hash string.
    # NOTE: the column is still called "password" exactly as specified.
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)              # WHAT: 'front_desk' or 'dental_doctor' - drives RBAC.


class Patient(db.Model):
    """A registered patient. One row per person, however many appointments they have."""

    id = db.Column(db.Integer, primary_key=True)                 # WHAT: unique patient number.
    name = db.Column(db.String(100), nullable=False)             # WHAT: full name shown in every table.
    age = db.Column(db.Integer, nullable=False)                  # WHAT: age in years.
    contact_number = db.Column(db.String(30), nullable=False)    # WHAT: phone number. String (not Integer) so leading 0s and "+" survive.
    created_at = db.Column(db.DateTime, default=datetime.now)    # WHAT: registration time, filled automatically.
    # (datetime.now is passed WITHOUT brackets on purpose - SQLAlchemy calls it for every new row.)


class Appointment(db.Model):
    """One visit booked for one patient."""

    id = db.Column(db.Integer, primary_key=True)                 # WHAT: unique appointment number (shown as "ID" in tables).
    # WHAT: foreign key = links this appointment to a row in the patient table.
    # HOW TO FIX "FOREIGN KEY constraint failed": the patient_id must belong to an existing patient.
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=False)
    treatment_type = db.Column(db.String(100), nullable=False)   # WHAT: e.g. "Cleaning", "Root Canal".
    date_and_time = db.Column(db.DateTime, nullable=False)       # WHAT: when the visit happens (date + time together).
    status = db.Column(db.String(20), nullable=False, default='Scheduled')   # WHAT: one of VALID_STATUSES.

    # WHAT: lets you write appointment.patient.name instead of running a second query.
    # WHY : the templates need the patient's name/age/contact next to each appointment.
    # backref='appointments' ALSO gives every Patient a patient.appointments list (used for the visit count).
    patient = db.relationship('Patient', backref='appointments')


# =============================================================================
# 3. HELPER FUNCTIONS
# =============================================================================

def parse_datetime_local(value):
    """Convert the text sent by an <input type="datetime-local"> into a Python datetime.

    WHAT: browsers send "2026-10-26T14:30"; the database needs a real datetime object.
    WHY : bad or missing text must not crash the page - we return None instead.
    HOW TO FIX "Please choose a valid appointment date": the form field name must stay
    'date_and_time' and the input type must stay 'datetime-local' in the templates.
    """
    for pattern in ('%Y-%m-%dT%H:%M', '%Y-%m-%dT%H:%M:%S'):   # WHAT: accept with or without seconds.
        try:
            return datetime.strptime(value, pattern)          # WHAT: text -> datetime.
        except (ValueError, TypeError):
            continue                                          # WHAT: wrong pattern, try the next one.
    return None                                               # WHAT: nothing matched -> caller shows an error.


def read_and_validate_form(form):
    """Read the shared patient + appointment fields from a submitted form and check them.

    WHAT: used by BOTH /front-desk (create) and /edit-appointment (update).
    WHY : one place for the rules means create and edit can never disagree.
    RETURNS: (clean_values_dict, None) when OK, or (None, "error message") when something is wrong.
    HOW TO MODIFY: add a new rule as another `if` below; return (None, 'your message').
    """
    name = form.get('name', '').strip()                       # WHAT: .strip() removes accidental spaces.
    contact = form.get('contact_number', '').strip()
    treatment = form.get('treatment_type', '').strip()
    status = form.get('status', '').strip()
    age_text = form.get('age', '').strip()
    when_text = form.get('date_and_time', '').strip()

    if not name or not contact or not treatment:              # WHAT: required text fields.
        return None, 'Patient name, contact number and treatment type are required.'

    try:
        age = int(age_text)                                   # WHAT: text -> whole number.
    except ValueError:
        return None, 'Age must be a whole number.'
    if not 0 <= age <= 120:                                   # WHAT: sanity range. Change 120 if you need to.
        return None, 'Age must be between 0 and 120.'

    when = parse_datetime_local(when_text)                    # WHAT: text -> datetime (or None).
    if when is None:
        return None, 'Please choose a valid appointment date and time.'

    if status not in VALID_STATUSES:                          # WHAT: reject statuses that are not in the allowed list.
        return None, 'Please choose a valid status.'

    return {
        'name': name, 'age': age, 'contact_number': contact,
        'treatment_type': treatment, 'date_and_time': when, 'status': status,
    }, None


def redirect_to_dashboard():
    """Send the current user to the dashboard that matches their role.

    WHAT: doctor -> /doctor, front desk -> /front-desk, anyone else -> /login.
    WHY : used after login, after blocked actions, and in several other places, so it lives in one spot.
    HOW TO MODIFY: if you add a new role, add another `if` here.
    """
    role = session.get('role')                                # WHAT: .get() returns None (not an error) if not logged in.
    if role == ROLE_DOCTOR:
        return redirect(url_for('doctor_dashboard'))          # url_for takes the FUNCTION name of the route.
    if role == ROLE_FRONT_DESK:
        return redirect(url_for('front_desk'))
    return redirect(url_for('login'))


def login_required(view):
    """Decorator: only let logged-in users reach a route.

    WHAT: put @login_required directly under @app.route(...) to protect a page.
    WHY : without it, anyone could open /doctor by typing the URL.
    HOW TO FIX "I get sent to login all the time": the session cookie is missing - check that
    SECRET_KEY above is not changing between restarts and that cookies are enabled in the browser.
    """
    @wraps(view)                                              # WHAT: keeps the original function name (Flask needs unique names).
    def wrapped(*args, **kwargs):
        if 'user_id' not in session:                          # WHAT: login() stores user_id; no user_id = not logged in.
            flash('Please log in to continue.', 'warning')
            return redirect(url_for('login'))
        return view(*args, **kwargs)                          # WHAT: logged in -> run the real route.
    return wrapped


# =============================================================================
# 4. SEED DEFAULT ACCOUNTS (runs once every time the app starts)
# =============================================================================

with app.app_context():     # WHAT: database commands need an "application context"; this opens one.
    db.create_all()         # WHAT: creates the tables if they do not exist yet. Existing data is NOT touched.
    # HOW TO FIX "no such column ..." after editing a model: db.create_all() never changes existing tables.
    #   Stop the app, delete instance/dental_clinic.db, start again (this wipes all data - fine during development).

    # WHAT: the two accounts required by the spec. Each is created only if it is missing,
    #       so restarting the app never creates duplicates.
    default_accounts = [
        ('frontdesk', 'password123', ROLE_FRONT_DESK),
        ('doctor', 'password123', ROLE_DOCTOR),
    ]
    for username, plain_password, role in default_accounts:
        if User.query.filter_by(username=username).first() is None:     # QUERY: SELECT ... WHERE username = ? LIMIT 1
            db.session.add(User(
                username=username,
                password=generate_password_hash(plain_password),         # WHAT: store the hash, not 'password123'.
                role=role,
            ))
    db.session.commit()     # WHAT: save the new rows permanently. Forgetting commit() = nothing is saved.


# =============================================================================
# 5. ROUTES
# =============================================================================

@app.route('/')
def index():
    """Home URL. WHAT: sends everybody to the login page. WHY: the spec says / redirects to /login."""
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    """Show the login form (GET) and check the credentials (POST).

    WHAT: on success it stores user_id, username and role in the session cookie.
    WHY : every other route reads session['role'] to decide what the user may do (RBAC).
    HOW TO FIX "Invalid username or password" for the defaults: delete instance/dental_clinic.db and restart
    so the seed code above recreates the accounts.
    """
    if request.method == 'POST':                              # WHAT: the form was submitted.
        username = request.form.get('username', '').strip()   # WHAT: value of <input name="username">.
        password = request.form.get('password', '')           # WHAT: value of <input name="password"> (do not strip passwords).

        user = User.query.filter_by(username=username).first()   # QUERY: find the account with that username.

        if user and check_password_hash(user.password, password):   # WHAT: compares typed password with the stored hash.
            session.clear()                                   # WHAT: wipe any old session data first.
            session['user_id'] = user.id                      # WHAT: remember who is logged in...
            session['username'] = user.username               # ...their name (shown in the header)...
            session['role'] = user.role                       # ...and their role (used for access checks).
            flash(f'Welcome, {user.username}!', 'success')
            return redirect_to_dashboard()                    # WHAT: role-based redirect.

        flash('Invalid username or password.', 'danger')      # WHAT: same message for both cases so attackers learn nothing.

    elif 'user_id' in session:                                # WHAT: GET request from someone already logged in.
        return redirect_to_dashboard()                        # WHY: no need to show the login form again.

    return render_template('login.html')                      # WHAT: show the login page (first visit or failed login).


@app.route('/front-desk', methods=['GET', 'POST'])
@login_required
def front_desk():
    """Front desk page: register a patient + book an appointment (POST) and list all records (GET).

    WHAT: one form creates the Patient (if new) AND the Appointment together.
    WHY : reception staff should not have to fill two separate forms.
    NOTE: the doctor may open this page too, because the doctor has full Create rights.
    HOW TO FIX "form saves nothing": make sure each <input name="..."> in front_desk_dashboard.html matches
    the names read in read_and_validate_form() (name, age, contact_number, treatment_type, date_and_time, status).
    """
    if request.method == 'POST':
        values, error = read_and_validate_form(request.form)  # WHAT: read + validate every field.
        if error:
            flash(error, 'danger')
            return redirect(url_for('front_desk'))            # WHY redirect: avoids the "resubmit form?" browser popup.

        # QUERY: is this patient already registered? (same name, ignoring capital letters, AND same phone number)
        patient = Patient.query.filter(
            db.func.lower(Patient.name) == values['name'].lower(),
            Patient.contact_number == values['contact_number'],
        ).first()

        if patient is None:                                   # WHAT: brand-new patient -> create the record.
            patient = Patient(name=values['name'], age=values['age'],
                              contact_number=values['contact_number'])
        else:                                                 # WHAT: returning patient -> just refresh their age.
            patient.age = values['age']

        appointment = Appointment(                            # WHAT: build the new appointment row.
            patient=patient,                                  # WHY: the relationship fills in patient_id for us.
            treatment_type=values['treatment_type'],
            date_and_time=values['date_and_time'],
            status=values['status'],
        )
        db.session.add(appointment)                           # WHAT: stage it (the new patient is saved with it automatically).
        db.session.commit()                                   # WHAT: write to the database.
        flash(f"Record saved for {patient.name}.", 'success')
        return redirect(url_for('front_desk'))

    # ---- GET: show the page ----
    # QUERY: all appointments, newest date first. Each row can reach its patient through appointment.patient.
    appointments = Appointment.query.order_by(Appointment.date_and_time.desc()).all()
    return render_template('front_desk_dashboard.html',
                           appointments=appointments,         # WHAT: the table rows.
                           statuses=VALID_STATUSES)           # WHAT: options for the Status dropdown.

@app.route('/register-patient', methods=['GET', 'POST'])
@login_required
def register_patient():
    """Dedicated page with a centered form to register a new patient and book an appointment."""
    if request.method == 'POST':
        values, error = read_and_validate_form(request.form)
        if error:
            flash(error, 'danger')
            return redirect(url_for('register_patient'))
# 1. Look up the patient by contact number first
        patient = Patient.query.filter_by(contact_number=values['contact_number']).first()

        # 2. Then check if they exist or need to be created/updated
        if patient is None:
            # Brand-new patient
            patient = Patient(
                name=values['name'], 
                age=values['age'],
                contact_number=values['contact_number']
            )
        else:
            # Returning patient: update their name & age to the latest entry
            patient.name = values['name']
            patient.age = values['age']
        appointment = Appointment(
            patient=patient,
            treatment_type=values['treatment_type'],
            date_and_time=values['date_and_time'],
            status=values['status'],
        )
        db.session.add(appointment)
        db.session.commit()
        flash(f"Record saved for {patient.name}.", 'success')
        
        # Redirect back to the correct dashboard based on user role
        back_url = url_for('doctor_dashboard') if session.get('role') == ROLE_DOCTOR else url_for('front_desk')
        return redirect(back_url)

    back_url = url_for('doctor_dashboard') if session.get('role') == ROLE_DOCTOR else url_for('front_desk')
    return render_template('register_patient.html', statuses=VALID_STATUSES, back_url=back_url)


@app.route('/doctor', methods=['GET'])
@login_required
def doctor_dashboard():
    """Doctor dashboard: master schedule, patient list, statistics, calendar and today's agenda.

    WHAT: loads everything the doctor needs in one page.
    WHY : only the doctor role may see it (front desk users are redirected away).
    HOW TO FIX "front desk user can see the doctor page": confirm the role check below is still present.
    """
    if session.get('role') != ROLE_DOCTOR:                    # WHAT: RBAC check.
        flash('Access denied: this page is for the dental doctor only.', 'danger')
        return redirect_to_dashboard()

    
    # QUERY: every appointment, newest first (the "master schedule").
    appointments = Appointment.query.order_by(Appointment.date_and_time.desc()).all()
    # QUERY: every registered patient, alphabetical.
    patients = Patient.query.order_by(Patient.name).all()

    # QUERY: appointments whose date is TODAY -> from 00:00 today up to (but not including) 00:00 tomorrow.
    start_of_today = datetime.combine(date.today(), datetime.min.time())
    start_of_tomorrow = start_of_today + timedelta(days=1)
    todays_appointments = (Appointment.query
                           .filter(Appointment.date_and_time >= start_of_today,
                                   Appointment.date_and_time < start_of_tomorrow)
                           .order_by(Appointment.date_and_time)
                           .all())

    # WHAT: list of "YYYY-MM-DD" strings that have at least one appointment. The calendar widget uses it to draw dots.
    appointment_dates = sorted({a.date_and_time.strftime('%Y-%m-%d') for a in appointments})

    return render_template('doctor_dashboard.html',
                           appointments=appointments,
                           patients=patients,
                           todays_appointments=todays_appointments,
                           appointment_dates=appointment_dates,
                           total_appointments=len(appointments),
                           total_patients=len(patients),
                           statuses=VALID_STATUSES)



@app.route('/add-record', methods=['POST'])
@login_required
def add_record():
    """Save a new patient & appointment, then redirect back to the correct dashboard."""
    values, error = read_and_validate_form(request.form)
    if error:
        flash(error, 'danger')
        return redirect_to_dashboard()

    patient = Patient.query.filter(
        db.func.lower(Patient.name) == values['name'].lower(),
        Patient.contact_number == values['contact_number'],
    ).first()

    if patient is None:
        patient = Patient(name=values['name'], age=values['age'],
                          contact_number=values['contact_number'])
    else:
        patient.age = values['age']

    appointment = Appointment(
        patient=patient,
        treatment_type=values['treatment_type'],
        date_and_time=values['date_and_time'],
        status=values['status'],
    )
    db.session.add(appointment)
    db.session.commit()
    try:
        # Format date for readable SMS message
        formatted_date = appointment.date_and_time.strftime('%b %d, %Y at %I:%M %p')
    except Exception:
        formatted_date = str(appointment.date_and_time)

    send_local_sms(patient.contact_number, patient.name, appointment.treatment_type, formatted_date)

    flash(f"Record saved and SMS sent for {patient.name}.", 'success')
    return redirect_to_dashboard()
    
    



@app.route('/patient/<int:id>', methods=['GET'])
@login_required
def patient_detail(id):
    """Show full profile and treatment history for a specific patient."""
    patient = db.get_or_404(Patient, id)
    back_url = url_for('patients_list')
    return render_template('patient_detail.html', patient=patient, back_url=back_url)



@app.route('/edit-appointment/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_appointment(id):
    """Edit one appointment AND its patient's details. Allowed for BOTH roles.

    WHAT: GET shows the form pre-filled; POST saves the changes.
    WHY : the spec lets front desk EDIT records (but never delete them).
    NOTE: patient details (name/age/contact) belong to the Patient row, so changing them here
          updates that patient on all of their appointments - that is intentional.
    HOW TO FIX "404 Not Found": the appointment id in the URL does not exist (it may have been deleted).
    """
    appointment = db.get_or_404(Appointment, id)              # QUERY: SELECT by primary key, or show a 404 page.

    # WHAT: where the Cancel button and the "after saving" redirect should go, depending on the role.
    back_url = url_for('doctor_dashboard') if session.get('role') == ROLE_DOCTOR else url_for('front_desk')

    if request.method == 'POST':
        values, error = read_and_validate_form(request.form)
        if error:
            flash(error, 'danger')
            return redirect(url_for('edit_appointment', id=id))

        patient = appointment.patient                         # WHAT: the Patient row linked to this appointment.
        patient.name = values['name']                         # WHAT: assigning to attributes marks them as changed...
        patient.age = values['age']
        patient.contact_number = values['contact_number']
        appointment.treatment_type = values['treatment_type']
        appointment.date_and_time = values['date_and_time']
        appointment.status = values['status']
        db.session.commit()                                   # WHAT: ...and commit() writes every change in one go.

        flash(f'Appointment #{appointment.id} updated.', 'success')
        return redirect(back_url)

    return render_template('edit_appointment.html', appointment=appointment, statuses=VALID_STATUSES, back_url=back_url)


@app.route('/delete-appointment/<int:id>', methods=['GET'])
def delete_appointment(id):
    """Delete one appointment. DOCTOR ONLY - this is the backend enforcement of the "no delete" rule.

    WHAT: removes the appointment row (the patient record stays).
    WHY : hiding the Delete button is not enough; a front desk user could type this URL by hand.
          So the server checks the role itself.
    HOW TO FIX "front desk can still delete": make sure the role check below is the FIRST thing
    in this function and that nothing above it can reach db.session.delete().
    SECURITY NOTE: deleting through a GET link (as the spec requires) is fine for a small MVP; for a
    bigger system switch to POST + CSRF tokens so links on other websites cannot trigger deletes.
    """
    if session.get('role') != 'dental_doctor':                # WHAT: required check. Also blocks people who are not logged in (role is None).
        flash('Access denied: only the dental doctor can delete records.', 'danger')
        return redirect_to_dashboard()

    appointment = db.get_or_404(Appointment, id)              # QUERY: find the appointment or show 404.
    db.session.delete(appointment)                            # WHAT: mark the row for deletion...
    db.session.commit()                                       # WHAT: ...and actually remove it.
    flash(f'Appointment #{id} deleted.', 'success')
    return redirect(url_for('doctor_dashboard'))










@app.route('/logout', methods=['GET'])
def logout():
    """Log out. WHAT: clears the session cookie data. WHY: after this, @login_required blocks every page."""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))


# =============================================================================
# 6. START THE DEVELOPMENT SERVER
# =============================================================================
if __name__ == '__main__':      # WHAT: runs only when you type "python app.py" (not when another file imports this one).
    # debug=True auto-reloads on code changes and shows detailed errors in the browser.
    # HOW TO MODIFY: set debug=False (or use a production server such as waitress/gunicorn) for real clinic use.
    # HOW TO FIX "Address already in use": another program uses port 5000 -> use app.run(debug=True, port=5001).
    app.run(debug=True)
