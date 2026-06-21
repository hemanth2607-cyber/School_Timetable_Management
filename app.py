import os
import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

app = Flask(__name__)
# Reads the environment variable 'SECRET_KEY' or falls back to your development key if not set
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'd39cb20ef82c5f1107bdc86a1104e7b8f9a9bb5b')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///school_management.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# --- DATABASE MODELS ---

class School(db.Model):
    __tablename__ = 'schools'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    
    # Cascade relationships to remove all school associated data automatically
    users = db.relationship('User', backref='school', cascade='all, delete-orphan')
    students = db.relationship('Student', backref='school', cascade='all, delete-orphan')
    subjects = db.relationship('Subject', backref='school', cascade='all, delete-orphan')
    slots = db.relationship('TimetableSlot', backref='school', cascade='all, delete-orphan')
    attendance = db.relationship('AttendanceLog', backref='school', cascade='all, delete-orphan')
    substitutions = db.relationship('SubstitutionLog', backref='school', cascade='all, delete-orphan')
    exams = db.relationship('ExamSchedule', backref='school', cascade='all, delete-orphan')

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(50), nullable=False)  # Owner, Moderator, Admin, Teacher
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=True)

class TeacherProfile(db.Model):
    __tablename__ = 'teacher_profiles'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    school_id = db.Column(db.Integer, nullable=False)
    subject_expertise = db.Column(db.String(250), nullable=False) # Comma-separated
    max_periods_per_day = db.Column(db.Integer, default=5)
    
    user = db.relationship('User', backref=db.backref('teacher_profile', uselist=False, cascade='all, delete'))

class Student(db.Model):
    __tablename__ = 'students'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    grade_level = db.Column(db.String(50), nullable=False)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)

class Subject(db.Model):
    __tablename__ = 'subjects'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    grade_level = db.Column(db.String(50), nullable=False)
    weekly_hours = db.Column(db.Integer, default=4)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)

class TimetableSlot(db.Model):
    __tablename__ = 'timetable_slots'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False) # 0-4
    period = db.Column(db.Integer, nullable=False)      # 1-8
    class_name = db.Column(db.String(50), nullable=False)
    subject_id = db.Column(db.Integer, nullable=True)
    teacher_id = db.Column(db.Integer, nullable=True)
    is_revision = db.Column(db.Boolean, default=False)

class AttendanceLog(db.Model):
    __tablename__ = 'attendance_logs'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    entity_type = db.Column(db.String(50), nullable=False) # 'Teacher' or 'Student'
    entity_id = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(50), nullable=False)      # Strict: Present, Absent, Half-day - Morning, Half-day - Evening

class SubstitutionLog(db.Model):
    __tablename__ = 'substitution_logs'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    period = db.Column(db.Integer, nullable=False)
    original_teacher_id = db.Column(db.Integer, nullable=False)
    substituted_teacher_id = db.Column(db.Integer, nullable=False)
    class_name = db.Column(db.String(50), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)

class ExamSchedule(db.Model):
    __tablename__ = 'exam_schedules'
    id = db.Column(db.Integer, primary_key=True)
    school_id = db.Column(db.Integer, db.ForeignKey('schools.id', ondelete='CASCADE'), nullable=False)
    subject_id = db.Column(db.Integer, nullable=False)
    exam_date = db.Column(db.Date, nullable=False)
    period = db.Column(db.Integer, nullable=False)

# Helper function to pack model class references cleanly
def get_models_dict():
    return {
        'User': User,
        'TeacherProfile': TeacherProfile,
        'Student': Student,
        'Subject': Subject,
        'TimetableSlot': TimetableSlot,
        'AttendanceLog': AttendanceLog,
        'SubstitutionLog': SubstitutionLog,
        'ExamSchedule': ExamSchedule
    }

# --- AUTHORIZATION GUARDS ---

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Authentication required.', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def roles_allowed(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if session.get('role') not in roles:
                flash('Access denied. Insufficient privileges.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return wrapper

# --- AUTH ROUTES ---

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            session['role'] = user.role
            session['school_id'] = user.school_id
            return redirect(url_for('dashboard'))
        
        flash('Invalid credentials. Check your details.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Successfully logged out.', 'info')
    return redirect(url_for('login'))

# --- CORE ROUTING SYSTEM ---

@app.route('/dashboard')
@login_required
def dashboard():
    user_role = session.get('role')
    school_id = session.get('school_id')
    
    schools = []
    moderators = []
    admins = []
    teachers = []
    students = []
    subjects = []
    exams = []
    
    if user_role == 'Owner':
        schools = School.query.all()
        moderators = User.query.filter_by(role='Moderator').all()
        admins = User.query.filter_by(role='Admin').all()
        teachers = User.query.filter_by(role='Teacher').all()
    elif user_role == 'Moderator':
        schools = School.query.all()
        admins = User.query.filter(User.role == 'Admin').all()
        teachers = User.query.filter(User.role == 'Teacher').all()
    elif user_role in ['Admin', 'Teacher']:
        students = Student.query.filter_by(school_id=school_id).all()
        subjects = Subject.query.filter_by(school_id=school_id).all()
        exams = ExamSchedule.query.filter_by(school_id=school_id).all()
        teachers = User.query.filter_by(school_id=school_id, role='Teacher').all()

    all_users_list = []
    if user_role == 'Owner':
        all_users_list = User.query.all()
    elif user_role == 'Moderator':
        all_users_list = User.query.filter(User.role.in_(['Admin', 'Teacher'])).all()
    elif user_role == 'Admin':
        all_users_list = User.query.filter_by(school_id=school_id).all()

    return render_template('dashboard.html', 
                           role=user_role, 
                           schools=schools,
                           moderators=moderators,
                           admins=admins,
                           teachers=teachers,
                           students=students,
                           subjects=subjects,
                           exams=exams,
                           all_users=all_users_list)

# --- GLOBAL OWNER & MODERATOR CONTROLS ---

@app.route('/school/add', methods=['POST'])
@login_required
@roles_allowed('Owner', 'Moderator')
def add_school():
    name = request.form.get('name')
    if name:
        new_school = School(name=name)
        db.session.add(new_school)
        db.session.commit()
        flash('School profile successfully registered.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/school/delete/<int:id>', methods=['POST'])
@login_required
@roles_allowed('Owner', 'Moderator')
def delete_school(id):
    school = School.query.get_or_404(id)
    db.session.delete(school)
    db.session.commit()
    flash('School and all cascading relational objects permanently erased.', 'success')
    return redirect(url_for('dashboard'))

@app.route('/user/create', methods=['POST'])
@login_required
@roles_allowed('Owner', 'Moderator', 'Admin')
def create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role')
    target_school_id = request.form.get('school_id')

    # RBAC constraints validation
    creator_role = session.get('role')
    if creator_role == 'Moderator' and role == 'Owner':
        flash('Unauthorized action.', 'danger')
        return redirect(url_for('dashboard'))
    if creator_role == 'Admin':
        if role in ['Owner', 'Moderator', 'Admin']:
            flash('Unauthorized role hierarchy target.', 'danger')
            return redirect(url_for('dashboard'))
        target_school_id = session.get('school_id')

    # Modification: Moderators are global multi-school managers and have no school affiliation
    if role == 'Moderator':
        target_school_id = None

    if not username or not password or not role:
        flash('Required form inputs missing.', 'danger')
        return redirect(url_for('dashboard'))

    # Verify global username uniqueness
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash('Username already registered globally.', 'danger')
        return redirect(url_for('dashboard'))

    new_user = User(
        username=username,
        password_hash=generate_password_hash(password),
        role=role,
        school_id=target_school_id if target_school_id else None
    )
    db.session.add(new_user)
    db.session.commit()

    # Capture teacher profile variables if roles match
    if role == 'Teacher':
        expertise = request.form.get('subject_expertise', 'General')
        max_periods = int(request.form.get('max_periods_per_day', 5))
        profile = TeacherProfile(
            user_id=new_user.id,
            school_id=new_user.school_id,
            subject_expertise=expertise,
            max_periods_per_day=max_periods
        )
        db.session.add(profile)
        db.session.commit()

    flash(f'Account created successfully: {username} ({role})', 'success')
    return redirect(url_for('dashboard'))

@app.route('/user/delete/<int:id>', methods=['POST'])
@login_required
@roles_allowed('Owner', 'Moderator', 'Admin')
def delete_user(id):
    target_user = User.query.get_or_404(id)
    current_user_role = session.get('role')
    current_user_school = session.get('school_id')

    # RBAC verification
    if current_user_role == 'Admin' and target_user.school_id != current_user_school:
        flash('Forbidden action.', 'danger')
        return redirect(url_for('dashboard'))
    if current_user_role == 'Moderator' and target_user.role in ['Owner', 'Moderator']:
        flash('Forbidden action.', 'danger')
        return redirect(url_for('dashboard'))
    if target_user.username == 'GHEMANTH':
        flash('Cannot remove absolute system administrator.', 'danger')
        return redirect(url_for('dashboard'))

    db.session.delete(target_user)
    db.session.commit()
    flash('User profile record removed.', 'success')
    return redirect(url_for('dashboard'))

# --- SCHOOL ADMIN DATA MANAGEMENT ---

@app.route('/admin/config-school', methods=['POST'])
@login_required
@roles_allowed('Admin')
def config_school():
    school_id = session.get('school_id')
    form_type = request.form.get('form_type')
    
    if form_type == 'student':
        name = request.form.get('name')
        grade = request.form.get('grade_level')
        student = Student(name=name, grade_level=grade, school_id=school_id)
        db.session.add(student)
    elif form_type == 'subject':
        name = request.form.get('name')
        grade = request.form.get('grade_level')
        hours = int(request.form.get('weekly_hours', 4))
        subject = Subject(name=name, grade_level=grade, weekly_hours=hours, school_id=school_id)
        db.session.add(subject)
    elif form_type == 'exam':
        subject_id = int(request.form.get('subject_id'))
        date_str = request.form.get('exam_date')
        period = int(request.form.get('period', 1))
        exam_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
        exam = ExamSchedule(school_id=school_id, subject_id=subject_id, exam_date=exam_date, period=period)
        db.session.add(exam)
        
    db.session.commit()
    flash('Database record updated.', 'success')
    return redirect(url_for('dashboard'))

# --- AI SCHEDULER CONTROLLER ---

@app.route('/scheduler/generate', methods=['POST'])
@login_required
@roles_allowed('Admin')
def trigger_ai_scheduler():
    from scheduler_ai import TimetableGenerator
    school_id = session.get('school_id')
    booster_mode = 'booster_mode' in request.form

    grades_query = db.session.query(Student.grade_level).filter_by(school_id=school_id).distinct().all()
    grades = [g[0] for g in grades_query]
    
    subjects_db = Subject.query.filter_by(school_id=school_id).all()
    subjects = [{"id": s.id, "name": s.name, "grade_level": s.grade_level, "weekly_hours": s.weekly_hours} for s in subjects_db]
    
    teachers_db = TeacherProfile.query.filter_by(school_id=school_id).all()
    teachers = [{"id": t.user_id, "expertise": [e.strip() for e in t.subject_expertise.split(',')], "max_periods_per_day": t.max_periods_per_day} for t in teachers_db]
    
    exams_db = ExamSchedule.query.filter_by(school_id=school_id).all()
    exams = [{"subject_id": e.subject_id, "exam_date": e.exam_date} for e in exams_db]

    if not grades or not subjects or not teachers:
        flash('Incomplete schedule dependencies (Verify Students, Subjects, and Teachers configurations).', 'warning')
        return redirect(url_for('dashboard'))

    generator = TimetableGenerator(school_id, grades, subjects, teachers, exams, booster_mode=booster_mode)
    calculated_timetable = generator.generate()

    db.session.query(TimetableSlot).filter_by(school_id=school_id).delete()

    for (grade, day, period), val in calculated_timetable.items():
        subj_id, t_id, is_revision = val
        slot = TimetableSlot(
            school_id=school_id,
            day_of_week=day,
            period=period,
            class_name=grade,
            subject_id=subj_id,
            teacher_id=t_id,
            is_revision=is_revision
        )
        db.session.add(slot)
    
    db.session.commit()
    flash(f'Timetable generated successfully. (Booster Mode: {"ON" if booster_mode else "OFF"})', 'success')
    return redirect(url_for('dashboard'))

# --- ATTENDANCE & SUBSTITUTION CONTROLLER ---

@app.route('/attendance/mark', methods=['POST'])
@login_required
@roles_allowed('Admin', 'Teacher')
def mark_attendance():
    school_id = session.get('school_id')
    date_str = request.form.get('date')
    entity_type = request.form.get('entity_type')
    entity_id = int(request.form.get('entity_id'))
    status = request.form.get('status')
    
    valid_statuses = ["Present", "Absent", "Half-day - Morning", "Half-day - Evening"]
    if status not in valid_statuses:
        return jsonify({"success": False, "error": "Invalid attendance status value"}), 400
        
    log_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    
    log = AttendanceLog.query.filter_by(
        school_id=school_id, date=log_date, entity_type=entity_type, entity_id=entity_id
    ).first()
    
    if log:
        log.status = status
    else:
        log = AttendanceLog(
            school_id=school_id, date=log_date, entity_type=entity_type, entity_id=entity_id, status=status
        )
        db.session.add(log)
    
    db.session.commit()
    
    if entity_type == 'Teacher':
        from scheduler_ai import SubstitutionEngine
        # Send clean dictionary containing explicit model structures
        SubstitutionEngine.get_substitutions_for_date(db.session, get_models_dict(), school_id, log_date)
        
    return jsonify({"success": True})

# --- DATA FETCH ENDPOINTS ---

@app.route('/api/timetable')
@login_required
def get_timetable_data():
    school_id = session.get('school_id')
    grade = request.args.get('grade_level')
    
    if not grade:
        first_student = Student.query.filter_by(school_id=school_id).first()
        grade = first_student.grade_level if first_student else None
        
    if not grade:
        return jsonify({"slots": []})
        
    slots = TimetableSlot.query.filter_by(school_id=school_id, class_name=grade).all()
    
    result = []
    for s in slots:
        subj = Subject.query.get(s.subject_id) if s.subject_id else None
        teacher = User.query.get(s.teacher_id) if s.teacher_id else None
        result.append({
            "day_of_week": s.day_of_week,
            "period": s.period,
            "subject": subj.name if subj else "Study Period",
            "teacher": teacher.username if teacher else "N/A",
            "is_revision": s.is_revision
        })
    return jsonify({"slots": result, "grade": grade})

@app.route('/api/substitutions')
@login_required
def get_substitutions():
    school_id = session.get('school_id')
    date_str = request.args.get('date', datetime.date.today().isoformat())
    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    
    subs = SubstitutionLog.query.filter_by(school_id=school_id, date=target_date).all()
    results = []
    for s in subs:
        orig = User.query.get(s.original_teacher_id)
        repl = User.query.get(s.substituted_teacher_id)
        subj = Subject.query.get(s.subject_id)
        results.append({
            "period": s.period,
            "original_teacher": orig.username if orig else "Unknown",
            "substitute_teacher": repl.username if repl else "No Cover Found",
            "class_name": s.class_name,
            "subject": subj.name if subj else "General Study"
        })
    return jsonify({"substitutions": results})

@app.route('/api/attendance-list')
@login_required
def get_attendance_list():
    school_id = session.get('school_id')
    entity_type = request.args.get('entity_type', 'Student')
    date_str = request.args.get('date', datetime.date.today().isoformat())
    target_date = datetime.datetime.strptime(date_str, '%Y-%m-%d').date()
    
    results = []
    if entity_type == 'Student':
        items = Student.query.filter_by(school_id=school_id).all()
        for item in items:
            log = AttendanceLog.query.filter_by(
                school_id=school_id, date=target_date, entity_type='Student', entity_id=item.id
            ).first()
            results.append({
                "id": item.id,
                "name": item.name,
                "extra": item.grade_level,
                "status": log.status if log else "Present"
            })
    else:
        items = TeacherProfile.query.filter_by(school_id=school_id).all()
        for item in items:
            usr = User.query.get(item.user_id)
            log = AttendanceLog.query.filter_by(
                school_id=school_id, date=target_date, entity_type='Teacher', entity_id=usr.id
            ).first()
            results.append({
                "id": usr.id,
                "name": usr.username,
                "extra": item.subject_expertise,
                "status": log.status if log else "Present"
            })
            
    return jsonify({"records": results})

# --- DATABASE SEEDING ---

def seed_database():
    db.create_all()
    owner = User.query.filter_by(username='GHEMANTH').first()
    if not owner:
        owner = User(
            username='GHEMANTH',
            password_hash=generate_password_hash('gopi2176susi1182hemu2607achu2612'),
            role='Owner',
            school_id=None
        )
        db.session.add(owner)
        db.session.commit()

with app.app_context():
    seed_database()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)