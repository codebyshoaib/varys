---
name: Taleemabad Oxbridge Training Feature
description: Backend architecture and integration points for Oxbridge vendor training levels with certificates
type: project
---

## Context: Training System Architecture

**TeacherProfile Levels** (in `users/models.py:483-489`):
- `levels` = ArrayField with choices: PRIMARY, MIDDLE, HIGH
- Multiple levels per teacher profile supported
- Used to filter/display appropriate training

**Existing Training Model Hierarchy**:
1. **Level** (vendor-aware model at `teacher_training/models.py:42`)
   - `vendor` field: VendorLabel choices → TALEEMABAD, others extensible
   - `name`, `description`, `order`, `passing_score`, `max_attempts`, `time_limit`
   - Has grand quiz (id based: Level 0→GQ1, Level 1→GQ2, etc.)
   
2. **Course** (child of Level)
   - Per-level courses with status, quiz titles, instructions
   
3. **Training** (child of Course)
   - Single training with media asset, duration, content, status
   - Has associated quiz questions (NOT grand quiz)
   
4. **GrandQuiz** (separate model, per-level)
   - Different from training quizzes (Training → Question)
   - Required to pass level and unlock next level
   
5. **Question** (MCQ, MSQ, open-ended, poll)
   - Can belong to: training, grand_quiz, or course
   - Constraint: must belong to exactly one parent
   
6. **Assessment** (tracks performance)
   - Tracks: score, total_score, attempt_number, is_passed, completed_at
   - Linked to: profile, training/grand_quiz/course

**Related Models**:
- `TeacherTrainingStatus` — tracks progress per training
- `Submission` — individual question answers
- `Assessment` — quiz/grand quiz completion records

## Oxbridge Feature Requirements

**Levels**: 
- Primary Level Training (name: "Professional Training in Game-Based Teaching, Learning & Assessment")
- Middle/High Level Training (same name)

**Vendor Flow**:
1. Teacher profile contains level(s) → FE shows matching vendor cards
2. Teacher clicks level → FE shows vendor options (Oxbridge, Beconhouse)
3. For Oxbridge: Training → Quiz → Certificate (NO diagnostic, NO grand quiz)
4. Certificate on FE side (offline-first app)

**Certificate Requirements**:
- Teacher name, training name, completion date, unique code
- Oxbridge branding (Navy #2E4A83, Black, White)
- Issuer: Oxbridge Innovative Solutions (Pvt.) Ltd.
- Signatory: Manzil e Maqsood, CEO Oxbridge

**Key Differences from Existing Training**:
- NO grand quiz (only training + course quiz)
- Certificate auto-issued on quiz completion
- FE-generated certificates (not backend-stored)

## Database Considerations

- New Level records with vendor=OXBRIDGE
- CourseQuiz (or reuse course_quiz_instructions) for the single quiz per level
- No new models needed yet — reuse Assessment/Submission for tracking
- Future: Certificate model if backend storage needed later

## Future Vendors

- Beconhouse (same structure, different branding)
- Pattern: Extensible via vendor field on Level
