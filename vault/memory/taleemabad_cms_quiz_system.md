---
name: Taleemabad CMS Quiz System
description: Generic quiz upload system for adding training quizzes via bash script
type: project
originSessionId: e0f29dd7-5bb1-4377-af4f-c7f25f4a9500
---
# Taleemabad CMS Quiz Upload System

## Quick Reference

**Generic script location:** `repos/taleemabad-cms/scripts/add-quiz.sh`

**Usage:**
```bash
cd /home/oye/Documents/free_work/personal-agent/repos/taleemabad-cms
bash scripts/add-quiz.sh <training_id> <quiz_file.json> [api_key]
```

**Example:**
```bash
bash scripts/add-quiz.sh 920 scripts/quiz_session1_training920.json
```

## API Configuration

**Endpoint:** `https://fde-staging.taleemabad.com/api/v1/internal/training_question/`

**Authentication Header:** `API-KEY: 7aeec18d-1529-4483-8475-607d5a16afa7`

**NOT** `Authorization: Bearer` — use `API-KEY` header instead!

## Quiz JSON Schema

```json
{
  "type": "mcq|msq",
  "question_statement": "Question text here?",
  "options": ["Option A", "Option B", "Option C", "Option D"],
  "answers": [1, 3],
  "hints": ["Hint A", "Hint B", "Hint C", "Hint D"],
  "bloom_level": "remember|understand|apply|analyze|evaluate|create",
  "is_active": true,
  "status": "ReadyForReview",
  "training": TRAINING_ID_HERE,
  "index": 1
}
```

**Important:**
- Replace `TRAINING_ID_HERE` with actual training ID
- Answer indices are 1-based (1, 2, 3, 4, etc.)
- For MSQ, provide array of correct option numbers: `[1, 3, 5]`
- For MCQ, provide single answer: `[2]`

## Completed Sessions

| Session | Training ID | Topic | Questions | Status |
|---------|-------------|-------|-----------|--------|
| 1 | 920 | Foundation of GBTLA | 10 (6 MCQ + 4 MSQ) | ✅ Complete |
| 2 | 921 | Implementation of GBTLA | 10 (6 MCQ + 4 MSQ) | ✅ Complete |
| 3 | 922 | Offline Games in GBTLA | 10 (6 MCQ + 4 MSQ) | ✅ Complete |
| 4 | 923 | Assessment & Feedback | 10 (6 MCQ + 4 MSQ) | ✅ Complete |
| 5 | 924 | Student Engagement & Classroom Management | 10 (6 MCQ + 4 MSQ) | ✅ Complete |
| 6 | 925 | STEM/STEAM & Creativity | 9 (6 MCQ + 3 MSQ) | ⚠️ Need question 10 |

## Files Created

**Scripts:**
- `scripts/add-quiz.sh` — Generic reusable quiz uploader
- `scripts/quiz-template.json` — Template for creating new quizzes

**Quiz Files:**
- `scripts/quiz_session1_training920.json`
- `scripts/quiz_session2_training921.json`
- `scripts/quiz_session3_training922.json`
- `scripts/quiz_session4_training923.json`
- `scripts/quiz_session5_training924.json`
- `scripts/quiz_session6_training925.json`

## Workflow for New Trainings

1. **Get training ID** — Check CMS or API response
2. **Copy template:** `cp scripts/quiz-template.json scripts/quiz_session7_training<ID>.json`
3. **Fill in questions** — Use provided quiz content
4. **Run script:** `bash scripts/add-quiz.sh <ID> scripts/quiz_session7_training<ID>.json`
5. **Verify** — Check CMS for created questions

## Question Bank Reference

**Bloom Levels Used:**
- remember
- understand
- apply
- analyze (in future sessions)
- evaluate (in future sessions)
- create (in future sessions)

**Question Types:**
- MCQ (single answer) — Use `answers: [1]` format
- MSQ (multiple answers) — Use `answers: [1, 2, 3]` format

## CMS Code References

**API Client:** `repos/taleemabad-cms/src/api/client.ts` (line 16: API-KEY header)
**Questions API:** `repos/taleemabad-cms/src/api/questions.ts`
- `createQuestions()` → POST `/api/v1/internal/training_question/`
- `getQuestions()` → GET `/api/v1/training_questions/?is_active=null&training__uuid=<uuid>`

**Question Form:** `repos/taleemabad-cms/src/components/training/QuestionForm.tsx`
- Payload structure: lines 89-100
- Bloom levels: defined in types

## Why:** 
The generic script allows rapid quiz creation across all trainings without duplicating logic. All quiz content is stored in JSON files that can be versioned and reused.

## How to apply:**
Provide training ID + quiz questions → I create JSON file → Run script → Questions uploaded. Takes <1 minute per training.
