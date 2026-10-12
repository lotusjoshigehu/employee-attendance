#### My work starts here ########

## Defect 1: Incorrect Late-Minute Calculation

1. What is the defect?

The `compute_late_minutes()` function converts the time difference into whole minutes before checking the 10-minute grace period. This causes employees arriving slightly more than 10 minutes late to be incorrectly marked as not late.

2. Previous function

```python
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0
```

3. How did we notice it?

We tested the function with a shift starting at 09:30 AM and a punch-in time of 09:40:59 AM. The employee was 10 minutes and 59 seconds late, but the function returned 0 because the time difference was converted to 10 whole minutes before checking the grace period.

4. Updated function

```python
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )
    lseconds = (punch_in - start).total_seconds()

    if lseconds <= 600:
        return 0

    return int(lseconds // 60)
```

This checks the exact elapsed time in seconds before applying the 10-minute grace period and returns the number of complete minutes late.

---

## Defect 2: Incorrect Overnight Shift Handling

1. What is the defect?

The `compute_late_minutes()` function creates the shift start time on the same date as the employee's punch-in. For overnight shifts, this can place the shift start in the future instead of on the previous day, resulting in an incorrect late-minute calculation.

2. Previous function

```python
def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )
    minutes = int((punch_in - start).total_seconds() / 60)
    return minutes if minutes > 10 else 0
```

3. How did we notice it?

We tested an overnight shift starting at 10:00 PM with a punch-in at 05:00 AM the following day. The function incorrectly created the shift start at 10:00 PM on the punch-in date, making the shift start later than the punch-in time and producing an incorrect result.

4. Updated function

```python
from datetime import timedelta

def compute_late_minutes(punch_in: datetime, shift_start: str) -> int:
    h, m = map(int, shift_start.split(":"))
    start = punch_in.replace(
        hour=h, minute=m, second=0, microsecond=0
    )

    if start > punch_in:
        start -= timedelta(days=1)

    lseconds = (punch_in - start).total_seconds()

    if lseconds <= 600:
        return 0

    return int(lseconds // 60)
```

This checks whether the calculated shift start is later than the punch-in time. If so, it moves the shift start to the previous day and then calculates late minutes using the 10-minute grace period.


## Defect 3: Employee Not Found Handling    get-attendence punchin

1. What is the defect?

The `punch_in()` function does not check whether the employee exists before accessing their details. If an invalid employee code is provided, the function may raise an error instead of returning a proper HTTP response.

2. Previous function

```python
emp = db.employees.find_one({"emp_code": body.emp_code})
```

3. How did we notice it?

We tried punching in using an employee code that does not exist in the database. MongoDB returned `None`, and accessing `emp["shift_start"]` caused a `TypeError`, resulting in an HTTP 500 error.

4. Updated function

```python
emp = db.employees.find_one({"emp_code": body.emp_code})

if not emp:
    raise HTTPException(
        status_code=404,
        detail="Employee not found"
    )
```

This checks whether the employee exists and returns HTTP 404 if the employee is not found, preventing an unexpected server error.

---

## Defect 4: Incorrect Employee Pagination and Total Count   -get/employees-page and page-size

1. What is the defect?

The `list_employees()` function calculates the pagination offset incorrectly and counts all employees even when a department filter is applied. This causes incorrect results and an inaccurate total count.

2. Previous function

```python
skip = page * page_size
total = db.employees.count_documents({})
```

3. How did we notice it?

We requested the first page using `page=1` and `page_size=20`. The API skipped the first 20 employees instead of returning them. We also applied a department filter and noticed that the total count included employees from all departments rather than only the selected department.

4. Updated function

```python
skip = (page - 1) * page_size
total = db.employees.count_documents(q)
```

This corrects the pagination offset so the first page starts at the beginning and ensures the total count includes only employees matching the applied filters.

## Defect 5: Missing Pagination Parameter Validation     -get/employees-page and page-size

### 1. What is the defect?

The employee and attendance listing endpoints do not validate pagination parameters. If a user provides a page number less than 1 or a page size less than 1, the API may return incorrect results or behave unexpectedly.

### 2. Previous function

```python
skip = (page - 1) * page_size

items = list(
    db.employees.find(q)
    .skip(skip)
    .limit(page_size)
)
```

### 3. How did we notice it?

We tested the employee endpoint with invalid pagination values, such as `page=0` or `page_size=-1`. The API did not explicitly reject these values with a clear validation error, potentially resulting in incorrect pagination behavior.

### 4. Updated function

```python
if page < 1:
    raise HTTPException(
        status_code=400,
        detail="Page must be greater than or equal to 1"
    )

if page_size < 1:
    raise HTTPException(
        status_code=400,
        detail="Page size must be greater than or equal to 1"
    )

skip = (page - 1) * page_size

items = list(
    db.employees.find(q)
    .skip(skip)
    .limit(page_size)
)
```

This validates pagination parameters before querying MongoDB and returns a clear HTTP 400 response when the values are invalid.

## Defect 6: Missing Validation for Punch-Out      post/attendance-punchin

1. What is the defect?

The `punch_out()` function needs to check whether an attendance record exists before updating it. If an employee tries to punch out without having punched in first, MongoDB returns `None` because no matching attendance record exists. Accessing fields on this missing record can cause a `TypeError` and result in HTTP 500 instead of a meaningful error response.

The function should also prevent an employee from punching out again if they have already punched out for that attendance record.

2. Previous function

```python
record = db.attendance_logs.find_one({
    "emp_code": body.emp_code,
    "date": d
})

record["punch_out"] = ts
```

3. How did we notice it?

We tested the punch-out endpoint using an employee code and date for which no attendance record existed. The database query returned `None`, but the function attempted to update the record anyway. This could cause a `TypeError` and an HTTP 500 response.

We also considered the case where an employee had already punched out and tried to punch out again. Without checking the existing `punch_out` value, the function could overwrite the original punch-out time.

 4. Updated function

```python
record = db.attendance_logs.find_one({
    "emp_code": body.emp_code,
    "date": d
})

if not record:
    raise HTTPException(
        status_code=404,
        detail="Attendance record not found"
    )

if record.get("punch_out") is not None:
    raise HTTPException(
        status_code=409,
        detail="Already punched out"
    )

record["punch_out"] = ts

db.attendance_logs.update_one(
    {"_id": record["_id"]},
    {"$set": {"punch_out": ts}}
)
```
 5. How does the fix work?

- The first condition checks whether the attendance record exists. If it does not, the API returns HTTP 404.
- The second condition checks whether the employee has already punched out. If so, the API returns HTTP 409 Conflict and prevents the original punch-out time from being overwritten.
- If both checks pass, the function updates the punch-out time in MongoDB using `update_one()`.

This prevents updates to nonexistent attendance records and helps preserve the original punch-out time.


## Defect 7: Missing Validation for Date Filters             get/attdenace/date

1. What is the defect?

The attendance listing endpoint may not validate the date range provided by the user. If the start date is later than the end date, the API may return misleading or empty results instead of reporting that the date range is invalid.

2. Previous function

```python
def validate_date_range(start_date=None, end_date=None):
    if start_date and end_date:
        query = {
            "date": {
                "$gte": start_date,
                "$lte": end_date
            }
        }
```

3. How did we notice it?

We tested the attendance listing endpoint with an end date earlier than the start date. The API should reject this invalid date range instead of processing the query.

4. Updated function

```python
from fastapi import HTTPException

def validate_date_range(start_date=None, end_date=None):
    if start_date and end_date and start_date > end_date:
        raise HTTPException(
            status_code=400,
            detail="Start date must not be after end date"
        )
```

This validates the date range and returns HTTP 400 when the start date is later than the end date. The validation should be called inside the attendance endpoint before querying MongoDB.

## Defect 8: Missing Validation for Attendance Status — GET Attendance/status -invalid

1. What is the defect?

The attendance listing endpoint does not validate the supplied status value. An invalid status, such as `INVALID_STATUS`, may be accepted instead of returning a validation error.

2. Previous function

```python
if status:
    q["status"] = status
```

3. How did we notice it?

1. We opened `http://127.0.0.1:8000/docs`.
2. We located the GET attendance listing endpoint.
3. We clicked **Try it out**.
4. We entered `INVALID_STATUS` in the `status` field.
5. We clicked **Execute**.
6. The API returned HTTP 200 OK instead of rejecting the invalid status.

4. Updated function

```python
from fastapi import HTTPException

allowed_statuses = {"Present", "Absent", "Late"}

if status and status not in allowed_statuses:
    raise HTTPException(
        status_code=400,
        detail="Invalid attendance status"
    )

if status:
    q["status"] = status
```

This validates the status before querying MongoDB and returns HTTP 400 when an unsupported status is provided.

## Defect 9 — Incorrect Overtime Calculation

1. What is the defect?
The compute_overtime() function calculates overtime when an employee punches out after their scheduled shift ends. The defect occurs when the function doesn't correctly enforce the 30-minute minimum overtime threshold.
For example, if an employee's shift ends at 6:30 PM, punching out at 6:45 PM should result in 0 overtime minutes, not 15.

2. How did we test it?
We tested a shift ending at 18:30 (6:30 PM) with different punch-out times.
Punch-out time	Expected overtime
18:45	0 minutes
18:59	0 minutes
19:00	30 minutes
19:15	45 minutes
The test identifies whether the function applies the 30-minute threshold correctly.

3. Previous function
This is the original function from your starter app/main.py:


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str
) -> int:
    h, m = map(int, shift_end.split(":"))
    end = datetime.fromisoformat(date_str).replace(
        hour=h, minute=m, tzinfo=IST
    )
    return max(
        0,
        int((punch_out - end).total_seconds() / 60)
    )



What was wrong?
The function calculates the minutes after shift end and returns them immediately if they are positive. It does not enforce the minimum 30-minute threshold.
For example, if an employee punches out at 6:45 PM after a 6:30 PM shift, it returns 15 instead of 0.

4. Updated function
Replace the original function with the following version. This version assumes punch_out is already timezone-aware in IST.


def compute_overtime(
    punch_out: datetime,
    shift_end: str,
    date_str: str
) -> int:
    h, m = map(int, shift_end.split(":"))

    shift_date = datetime.fromisoformat(date_str).date()
    end = datetime.combine(
        shift_date,
        time(hour=h, minute=m),
        tzinfo=IST
    )

    # Handle an overnight shift
    if end > punch_out:
        end -= timedelta(days=1)

    seconds = (punch_out - end).total_seconds()
    minutes = int(seconds // 60)

    return minutes if minutes >= 30 else 0

