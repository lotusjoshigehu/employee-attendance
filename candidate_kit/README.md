

A REST API built with **FastAPI** and **MongoDB** for employee records, attendance tracking, attendance regularization, and analytics.

## Features

- Create and list employees.
- Record employee punch-in and punch-out.
- List attendance records with filtering and pagination.
- Regularize an employee's attendance record for a specific date.
- View monthly attendance analytics for an employee.
- View department attendance summaries and trends.
- View a late-arrival leaderboard.
- Inspect query-plan information through the admin explain endpoint.
- Explore the API through Swagger UI.

## Technology Stack

- Python
- FastAPI
- PyMongo
- MongoDB
- Uvicorn
- python-dotenv (if used by the application's configuration)

## Project Structure

```text
candidate_kit/
├── app/
│   └── main.py
├── requirements.txt
├── README.md
├── REVIEW.md
├── DECISIONS.md
└── openapi.yaml
```

The project may contain additional files. Preserve the assignment's required structure.

## Setup

### 1. Open the project directory

Open a terminal in the folder containing `app/` and `requirements.txt`. For example:

```powershell
cd C:\\Users\\hp\\Downloads\\SDT_candidate_kit\\candidate_kit
```

Adjust the path if your project is stored elsewhere.

### 2. Create and activate a virtual environment

```powershell
python -m venv .venv
.\\.venv\\Scripts\\Activate.ps1
```

### 3. Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure MongoDB

Configure the MongoDB connection variable expected by `app/main.py`. If your application loads a `.env` file, create one locally. For example:

```env
MONGODB_URI=mongodb+srv://<username>:<password>@<cluster-host>/<database-name>?retryWrites=true&w=majority
```

This is an example only. Replace the placeholders with your own connection details, and ensure the environment variable name matches the application code.

For MongoDB Atlas:
- Confirm the cluster is running.
- Add your current public IP under **Security → Network Access**.
- Ensure the database user has the required permissions.
- URL-encode special characters in the password when required.

**Never commit `.env`, database credentials, passwords, or tokens to GitHub.** Add `.env` to `.gitignore`.

## Run the API

From the directory containing the `app` folder:

```powershell
uvicorn app.main:app --reload
```

If your package layout differs, adjust the import path to match your project.

Default local URLs:

- API base URL: `http://127.0.0.1:8000`
- Swagger UI: `http://127.0.0.1:8000/docs`
- ReDoc: `http://127.0.0.1:8000/redoc`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

## API Endpoints

Confirm the exact request fields, query parameters, response schemas, and status codes in `openapi.yaml` and the running Swagger documentation.

### Core endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/employees` | Create an employee |
| `GET` | `/employees` | List employees |
| `POST` | `/attendance/punch-in` | Record punch-in |
| `POST` | `/attendance/punch-out` | Record punch-out |
| `GET` | `/attendance` | List attendance records |

### Additional endpoints implemented for attendance regularization and analytics

| Method | Endpoint | Purpose |
|---|---|---|
| `PATCH` | `/attendance/{emp_code}/{date}` | Regularize an attendance record for an employee and date |
| `GET` | `/analytics/employees/{emp_code}/monthly` | Get monthly attendance analytics for an employee |
| `GET` | `/analytics/departments/summary` | Get an attendance summary by department |
| `GET` | `/analytics/leaderboard/late` | Get a leaderboard of late arrivals |
| `GET` | `/analytics/departments/{department}/trend` | Get attendance trends for a department |
| `GET` | `/admin/explain/{endpoint}` | Get query-plan/explain information for a supported endpoint |

The additional endpoints above are the routes added beyond the core employee and attendance operations. Verify each route against `app/main.py` and `openapi.yaml` before submission.

## Testing

Run the test suite supplied with the project:

```powershell
python -m pytest -q
```

Check Python syntax with:

```powershell
python -m compileall app
```

Configure any required environment variables or test database before running tests. Record only test results you have actually observed.

## Troubleshooting

### MongoDB SSL or connection timeout

If PyMongo reports an SSL handshake failure or `ServerSelectionTimeoutError`:

1. Confirm the Atlas cluster is running.
2. Check **Security → Network Access** and allow your current public IP.
3. Verify the connection string and database user.
4. If needed, update packages:

   ```powershell
   python -m pip install --upgrade pymongo certifi dnspython
   ```

5. Try another trusted network if a firewall, VPN, or proxy may be interfering.

Do not disable TLS certificate verification as a workaround.

## Documentation and Review

- `openapi.yaml` — API contract; keep it aligned with the implementation.
- `REVIEW.md` — identified defects, impact, and proposed or verified fixes.
- `DECISIONS.md` — important implementation decisions and trade-offs.

Distinguish defects that have been reproduced from risks that still need verification.

## Security

- Never commit `.env`, credentials, database passwords, or access tokens.
- Use environment variables for local configuration.
- Use least-privilege database credentials.
- Inspect `git status` and review files before committing.

## Submission Checklist

- [ ] Required application and documentation files are present.
- [ ] `openapi.yaml` matches the implemented endpoints.
- [ ] Tests have been run and results recorded accurately.
- [ ] `README.md`, `REVIEW.md`, and `DECISIONS.md` are complete.
- [ ] Secrets and local environment files are excluded from Git.
- [ ] The public GitHub repository contains the required files.
- [ ] The submitted repository URL is correct.
"""
