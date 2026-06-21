import datetime
import random

class TimetableGenerator:
    def __init__(self, school_id, grades, subjects, teachers, exams=None, booster_mode=False):
        """
        - grades: list of strings, e.g., ["Grade 9", "Grade 10"]
        - subjects: list of dicts, e.g., [{"id": 1, "name": "Math", "grade_level": "Grade 10", "weekly_hours": 4}]
        - teachers: list of dicts, e.g., [{"id": 2, "expertise": ["Math"], "max_periods_per_day": 5}]
        - exams: list of dicts, e.g., [{"subject_id": 1, "exam_date": datetime.date(2026, 6, 15)}]
        - booster_mode: bool, switches to exam revision priority
        """
        self.school_id = school_id
        self.grades = grades
        self.subjects = subjects
        self.teachers = teachers
        self.exams = exams or []
        self.booster_mode = booster_mode
        self.days = [0, 1, 2, 3, 4]  # Mon to Fri
        self.periods = [1, 2, 3, 4, 5, 6, 7, 8]  # 8 Periods per day (Break after period 4)

    def generate(self):
        # Initialize empty schedules: timetable[(grade, day, period)] = (subject_id, teacher_id, is_revision)
        timetable = {}
        
        # Keep track of assignments and limits to respect constraints
        teacher_busy = {}  # (teacher_id, day, period) -> bool
        grade_busy = {}    # (grade, day, period) -> bool
        teacher_daily_load = {}  # (teacher_id, day) -> int count
        
        # Requirements pool: (grade, subject_id, target_hours)
        requirements = []
        for subj in self.subjects:
            target_hours = subj["weekly_hours"]
            # If Exam Booster Mode is active, boost critical subjects nearing exams and inject revision slots
            if self.booster_mode and self._is_exam_near(subj["id"]):
                target_hours += 2  # Boost weight/allocation of exam subjects
            requirements.append({
                "grade": subj["grade_level"],
                "subject_id": subj["id"],
                "subject_name": subj["name"],
                "remaining_hours": target_hours,
                "is_exam_subject": self._is_exam_near(subj["id"])
            })

        # Heuristic optimization passes
        for day in self.days:
            for period in self.periods:
                for grade in self.grades:
                    # Skip if grade already has an assignment this period
                    if grade_busy.get((grade, day, period)):
                        continue
                    
                    # Sort requirements based on remaining hours and exam urgency
                    valid_reqs = [r for r in requirements if r["grade"] == grade and r["remaining_hours"] > 0]
                    if self.booster_mode:
                        # Prioritize active exam subjects
                        valid_reqs.sort(key=lambda r: (r["is_exam_subject"], r["remaining_hours"]), reverse=True)
                    else:
                        valid_reqs.sort(key=lambda r: r["remaining_hours"], reverse=True)
                    
                    assigned = False
                    for req in valid_reqs:
                        # Find a qualifying teacher for this subject
                        candidate_teachers = [
                            t for t in self.teachers 
                            if req["subject_name"] in t["expertise"]
                        ]
                        
                        # Sort teachers by lowest daily workload index (balancing stress thresholds)
                        candidate_teachers.sort(key=lambda t: teacher_daily_load.get((t["id"], day), 0))
                        
                        for teacher in candidate_teachers:
                            t_id = teacher["id"]
                            max_load = teacher["max_periods_per_day"]
                            current_load = teacher_daily_load.get((t_id, day), 0)
                            
                            # Check constraints
                            is_teacher_busy = teacher_busy.get((t_id, day, period), False)
                            below_stress_limit = current_load < max_load
                            
                            # Cognitive load balancing: Avoid consecutive high-intensity revision sessions in booster mode
                            is_cognitive_overload = False
                            if self.booster_mode and req["is_exam_subject"] and period > 1:
                                prev_slot = timetable.get((grade, day, period - 1))
                                if prev_slot and prev_slot[2]:  # If the previous period was also a revision slot
                                    is_cognitive_overload = True
                            
                            if not is_teacher_busy and below_stress_limit and not is_cognitive_overload:
                                # Assign slot
                                is_revision = self.booster_mode and req["is_exam_subject"]
                                timetable[(grade, day, period)] = (req["subject_id"], t_id, is_revision)
                                
                                # Update states
                                teacher_busy[(t_id, day, period)] = True
                                grade_busy[(grade, day, period)] = True
                                teacher_daily_load[(t_id, day)] = current_load + 1
                                req["remaining_hours"] -= 1
                                assigned = True
                                break
                        if assigned:
                            break
                            
                    # Fill idle slots with general study periods if no valid classes were scheduled
                    if not assigned and not grade_busy.get((grade, day, period)):
                        timetable[(grade, day, period)] = (None, None, False)

        return timetable

    def _is_exam_near(self, subject_id):
        # Checks if an exam for this subject is scheduled within 14 days
        today = datetime.date.today()
        for ex in self.exams:
            if ex["subject_id"] == subject_id:
                diff = (ex["exam_date"] - today).days
                if 0 <= diff <= 14:
                    return True
        return False


class SubstitutionEngine:
    @staticmethod
    def get_substitutions_for_date(db_session, models, school_id, target_date):
        """
        - Resolves dynamic substitution paths based on teacher attendance.
        - Strict statuses used: Present, Absent, Half-day - Morning, Half-day - Evening.
        """
        # Delete existing auto-substitutions for this day to allow clean recalibration
        db_session.query(models.SubstitutionLog).filter_by(school_id=school_id, date=target_date).delete()
        db_session.commit()

        day_of_week = target_date.weekday() # 0 = Monday, ..., 4 = Friday
        if day_of_week > 4:
            return [] # No substitutions needed on weekends

        # Fetch scheduled timetable configurations for the day
        timetable_slots = db_session.query(models.TimetableSlot).filter_by(
            school_id=school_id, day_of_week=day_of_week
        ).all()
        
        # Fetch teacher attendance records for the date
        attendance_logs = db_session.query(models.AttendanceLog).filter_by(
            school_id=school_id, date=target_date, entity_type='Teacher'
        ).all()
        
        attendance_map = {log.entity_id: log.status for log in attendance_logs}
        
        # Map out teacher assignments for workload index calculations
        teacher_base_slots = {}
        for slot in timetable_slots:
            if slot.teacher_id:
                teacher_base_slots.setdefault(slot.teacher_id, []).append(slot)
                
        # Resolve replacements needed
        substitutions_made = []
        
        for slot in timetable_slots:
            orig_teacher_id = slot.teacher_id
            if not orig_teacher_id:
                continue
            
            # Identify attendance status of current teacher
            status = attendance_map.get(orig_teacher_id, "Present")
            if status == "Present":
                continue
                
            needs_replacement = False
            # Check period boundaries
            # Morning period = 1 to 4, Evening period = 5 to 8
            if status == "Absent":
                needs_replacement = True
            elif status == "Half-day - Morning" and slot.period <= 4:
                needs_replacement = True
            elif status == "Half-day - Evening" and slot.period >= 5:
                needs_replacement = True
                
            if needs_replacement:
                # Identify substitute teacher candidates from school pool
                all_teachers = db_session.query(models.TeacherProfile).filter_by(school_id=school_id).all()
                candidates = []
                
                for candidate in all_teachers:
                    c_id = candidate.user_id
                    if c_id == orig_teacher_id:
                        continue
                    
                    # Verify candidate attendance for the selected block
                    c_status = attendance_map.get(c_id, "Present")
                    if c_status == "Absent":
                        continue
                    if c_status == "Half-day - Morning" and slot.period <= 4:
                        continue
                    if c_status == "Half-day - Evening" and slot.period >= 5:
                        continue
                        
                    # Verify teacher is not already scheduled in a standard class
                    is_busy = any(s.day_of_week == day_of_week and s.period == slot.period 
                                  for s in teacher_base_slots.get(c_id, []))
                    if is_busy:
                        continue
                        
                    # Verify teacher isn't already assigned a substitution in this period
                    sub_assigned = db_session.query(models.SubstitutionLog).filter_by(
                        school_id=school_id, date=target_date, period=slot.period, substituted_teacher_id=c_id
                    ).first()
                    if sub_assigned:
                        continue
                        
                    # Determine active total load for this specific day (standard slots + substitution count)
                    base_load = len([s for s in teacher_base_slots.get(c_id, []) if s.day_of_week == day_of_week])
                    sub_load = db_session.query(models.SubstitutionLog).filter_by(
                        school_id=school_id, date=target_date, substituted_teacher_id=c_id
                    ).count()
                    
                    total_load = base_load + sub_load
                    if total_load >= candidate.max_periods_per_day:
                        continue
                        
                    # Rate expertise mapping
                    subj_name = db_session.query(models.Subject).get(slot.subject_id).name
                    expertise_list = [exp.strip() for exp in candidate.subject_expertise.split(",")]
                    has_expertise = 1 if subj_name in expertise_list else 0
                    
                    candidates.append({
                        "profile": candidate,
                        "has_expertise": has_expertise,
                        "total_load": total_load
                    })
                
                # Sort candidates: Expertise matches first, then lowest active workload index
                candidates.sort(key=lambda x: (-x["has_expertise"], x["total_load"]))
                
                if candidates:
                    selected_sub = candidates[0]["profile"]
                    sub_log = models.SubstitutionLog(
                        school_id=school_id,
                        date=target_date,
                        period=slot.period,
                        original_teacher_id=orig_teacher_id,
                        substituted_teacher_id=selected_sub.user_id,
                        class_name=slot.class_name,
                        subject_id=slot.subject_id
                    )
                    db_session.add(sub_log)
                    substitutions_made.append(sub_log)
                    
        db_session.commit()
        return substitutions_made