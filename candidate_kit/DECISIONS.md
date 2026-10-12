# Technical Decisions

This document records the main implementation choices for the Employee Attendance & Analytics API. It should describe the behavior implemented in `app/main.py` and the contract in `openapi.yaml`. Verify each item against the code before submission; update any item that does not match the final implementation.

## 1. Framework and Database

- **FastAPI** is used to expose the API endpoints and generate interactive API documentation.
- **MongoDB** stores employee and attendance records.
- **PyMongo** is used to query and update MongoDB collections.
- Database connection details are supplied through local configuration/environment variables rather than hard-coded credentials.

## 2. Employee and Attendance Collections

- Employee records are stored in the `employees` collection.
- Attendance records are stored in the `attendance_logs` collection.
- Employee codes are used to identify employees in attendance operations.
- Confirm that the database indexes in the final code match the indexes described in `app/main.py`. Where supported by the data model, indexes should help employee-code lookups and attendance queries.

## 3. API Contract and Validation

- The implementation is documented by `openapi.yaml` and exposed through Swagger UI.
- Request validation should reject missing or invalid fields with clear client errors.
- Attendance status values should follow the contract exactly. The documented values in this project are `PRESENT`, `ABSENT`, `LEAVE`, `WFH`, and `ON_DUTY`; verify the final validator uses this exact set.
- Keep HTTP status codes and response structures consistent with the contract.

## 4. Pagination

- List endpoints may use pagination to avoid returning the entire collection in one response.
- Validate pagination parameters (for example, page number and page size) so invalid values are rejected rather than producing confusing database queries.
- Where a response includes a total count, calculate it using the same filter as the returned page.
- Verify the exact parameter names, defaults, limits, and response shape against the final implementation and `openapi.yaml`.

## 5. Attendance Time and Time Zones

- Attendance calculations must use a consistent time-zone policy.
- Keep stored timestamps and displayed/local attendance dates consistent with the assignment contract.
- Late arrival and overtime calculations should use the shift schedule and thresholds defined by the assignment, not assumptions introduced by the documentation.
- Verify the final code's handling of overnight shifts, minute precision, and daylight/time-zone conversions before claiming those edge cases are fully supported.

## 6. Punch-In, Punch-Out, and Regularization

- Punch-in should validate that the employee exists and that an attendance record can be created for the relevant date.
- Punch-out should validate that a matching punch-in record exists and that a record has not already been punched out.
- Regularization should validate the target employee/date and the requested update, and should preserve any required history/audit information.
- Confirm that duplicate attendance records are prevented by the final database constraints or update logic, including under concurrent requests.

## 7. Analytics

The API includes routes for employee monthly analytics, department summaries, a late-arrival leaderboard, and department trends. Analytics calculations should be consistent with the attendance records and the contract's definitions of totals, percentages, and late arrivals.

## 8. Query Explain Endpoint

The admin explain endpoint should only accept supported endpoint identifiers and return query-plan information without exposing credentials or other sensitive configuration.

## 9. Error Handling and Security

- Return clear client errors for invalid input and missing records.
- Do not expose MongoDB connection strings, passwords, or internal secrets in API responses.
- Keep `.env` and other local secret files out of version control.
- Do not disable TLS certificate verification to work around MongoDB connection problems.

## 10. Verification Before Submission

Before submitting, verify the following against the final code and tests:

- [ ] All documented routes exist and match `openapi.yaml`.
- [ ] Request/response schemas and status codes match the API contract.
- [ ] Pagination and total counts behave as documented.
- [ ] Attendance status values and date/time behavior match the contract.
- [ ] Punch-in, punch-out, and regularization handle invalid and repeated operations.
- [ ] Database indexes and uniqueness constraints are present where required.
- [ ] Analytics results are checked against known test data.
- [ ] The full test suite passes.
- [ ] No credentials or `.env` files are committed.

This file documents design intent and verification points; it is not a claim that every listed edge case has been independently tested.
"""
