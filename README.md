# Credit Union Kiosk Queue & Member Details Application

## 1. Overview

This Flask-based web application serves as a staff-facing dashboard to manage member check-ins from a kiosk system. It provides a real-time view of the waiting queue, detailed member information by integrating with core systems (DNA) and loan servicing platforms (MeridianLink), and tools for staff to manage interactions. The application is designed with performance and usability in mind, incorporating caching, background data pre-fetching, and a clear user interface.

## 2. Key Features

*   **Real-time Kiosk Queue:** Displays members currently waiting and those already handled.
*   **Comprehensive Member Details:**
    *   Integrates with DNA API for core member data, account details, balances, and transaction history.
    *   Integrates with MeridianLink API for loan application information.
    *   Displays AI-generated insights based on member's financial activity.
*   **Manual Member Number Entry:**
    *   If a member does not enter their member number at the kiosk, staff can manually input it on the member details page to fetch their information from DNA and MeridianLink.
*   **Reversal of Manual Entry:** Staff can clear a manually entered member number, resetting the profile to its previous state (typically requiring re-entry if details are still needed).
*   **Improved Partial Data Display:** When a member number is not provided or validated, the application gracefully displays available check-in information from the SQL database, clearly indicating why full details are missing.
*   **Performance Optimization:**
    *   **Caching:** Time-based caching for DNA data (1 hour TTL), transaction data (10 minutes TTL), and AI insights (10 minutes TTL) to reduce redundant API calls and speed up page loads.
    *   **Background Pre-fetching:** Proactively fetches DNA and transaction data for members in the "Waiting" queue.
    *   **API Call Management:** Includes logic to prevent redundant API calls if a fetch for a member is already in progress or was recently completed.
*   **Logging:** Detailed application logging (`logs/waiting_app.log`) and full XML response logging for DNA API calls (`DNA_response_logs/`) for troubleshooting.

## 3. Setup Instructions

### 3.1. Prerequisites
*   Python 3.8+
*   Access to a Microsoft SQL Server database.
*   Credentials and endpoint information for DNA API and MeridianLink API.
*   ODBC Driver 18 for SQL Server (or compatible) installed on the machine running the application.

### 3.2. Installation
1.  **Clone the repository (if applicable).**
2.  **Create a virtual environment:**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    (`requirements.txt` includes: Flask, python-dotenv, cachetools, pyodbc, requests)

### 3.3. Configuration (Environment Variables)
Create a `.env` file in the root directory of the project and populate it with the following environment variables:

```ini
# Flask Configuration
FLASK_SECRET_KEY=your_very_strong_random_secret_key # Used for session management
FLASK_DEBUG=False # Set to True for development (enables debug mode, auto-reloader)
WAITING_PORT=8082 # Port on which the Flask app will run

# SSL Verification for External APIs (set to true in production if certs are valid)
DNA_VERIFY_SSL=false
ML_VERIFY_SSL=false

# Database Configuration (Microsoft SQL Server)
DB_SERVER=your_sql_server_address_or_hostname
DB_NAME=your_database_name
DB_USERNAME=your_db_username
DB_PASSWORD=your_db_password
DB_KIOSK_TABLE=NameOfTheFacingMembersTable # Table storing kiosk check-ins (e.g., FacingMembers)
# DB_TABLE was present in old README but seems unused by current app.py features for kiosk queue.
# If another table is used for other visitor types, add its variable here.

# DNA API Client Configuration
PIE_ENDPOINT=https://your_dna_pie_endpoint.com/PIE/PrimaryInterfaceExternal.asmx # Full URL for DirectSignon and WhoIs
DNA_ENDPOINT=https://your_dna_api_endpoint.com/DNA/CoreApiService.svc # Full URL for SubmitRequest
DEVICE_ID=your_dna_device_id
PROD_ENV_CD=your_dna_prod_env_cd
PROD_DEF_CD=your_dna_prod_def_cd
USER_ID=your_dna_api_user_id
PASSWORD=your_dna_api_password
APPLICATION_ID=your_dna_application_id
NTWK_NODE_NAME=your_dna_network_node_name # Often the machine name or identifier

# MeridianLink API Client Configuration
ML_API_USER_ID=your_meridianlink_api_user_id
ML_API_PASSWORD=your_meridianlink_api_password
ML_API_URL=https://your_meridianlink_search_query_api_url.com # URL for SEARCH_QUERY
ML_API_GET_LOAN_URL=https://your_meridianlink_get_loan_api_url.com # URL for GET_LOAN

# AI Insights Configuration
INSIGHTS_TRANSACTION_DAYS=30 # Number of past days of transactions to consider for insights
# INSIGHT_GENERATOR_URL (If applicable, if insight_generator.py calls an external service)
```

**Note on `DB_KIOSK_TABLE`:** This table must have columns like `FacingMemberID`, `Name`, `HelpTopic`, `SubIssue`, `CreatedDate`, `UpdatedDate`, `Status`, `MemberNumber` (for kiosk-entered number), `ManuallyEnteredMemberNumber` (for staff-entered number), and `MemberNumberSource`.

### 3.4. Running the Application
1.  Ensure your `.env` file is correctly configured.
2.  Activate your virtual environment (`source venv/bin/activate`).
3.  Run the Flask application:
    ```bash
    python app.py
    ```
4.  The application will be available at `http://localhost:<WAITING_PORT>` (e.g., `http://localhost:8082` by default).

## 4. Logging

*   **Application Logs:** General application events, errors, and warnings are logged in `logs/waiting_app.log`. This file is rotated to keep its size manageable.
*   **DNA API Response Logs:** Full XML responses from the DNA API are stored in the `DNA_response_logs/` directory. This is useful for debugging DNA integration issues. Each response is saved in a separate timestamped XML file.
*   The logging level can be adjusted in `app.py` if needed (currently `DEBUG` for file handler).

## 5. Dockerization (Future Plan)

The application is planned to be deployed in a Docker container. A `Dockerfile` and `docker-compose.yml` would need to be created, considering:
*   Python base image.
*   Copying application code.
*   Installing `requirements.txt`.
*   Exposing the `WAITING_PORT`.
*   Managing environment variables securely (e.g., via Docker Compose environment files or secrets).
*   Ensuring ODBC drivers are available within the container image.

## 6. Key Application Components

*   **`app.py`:** Main Flask application file containing routes, request handling, caching logic, and background task initiation.
*   **`database.py`:** Handles all database interactions (connecting, querying, updating) with the SQL Server.
*   **`dna_client.py`:** Client for interacting with the DNA API (authentication, fetching member details, transactions).
*   **`meridian_link_client.py`:** Client for interacting with the MeridianLink API (querying loan information).
*   **`insight_generator.py`:** (Assumed) Contains logic for generating AI insights from transaction data.
*   **`templates/`:** Contains Jinja2 HTML templates for rendering web pages.
    *   `dashboard.html`: The main staff-facing dashboard.
    *   `member_details.html`: View for detailed member information.
    *   `base.html`: Base layout template.
*   **`static/`:** Contains static assets like CSS and images.

## 7. Basic Troubleshooting

*   **Application Not Starting:**
    *   Ensure all dependencies in `requirements.txt` are installed in your virtual environment.
    *   Verify that the `.env` file exists and all required environment variables are set correctly.
    *   Check for syntax errors in `app.py` or other Python files.
*   **Database Connection Issues:**
    *   Confirm `DB_SERVER`, `DB_NAME`, `DB_USERNAME`, `DB_PASSWORD` are correct.
    *   Ensure the SQL Server is running and accessible from where the application is running.
    *   Verify ODBC drivers are correctly installed and configured.
    *   Check `logs/waiting_app.log` for specific database error messages.
*   **API Integration Problems (DNA/MeridianLink):**
    *   Double-check all API related environment variables (`PIE_ENDPOINT`, `DNA_ENDPOINT`, `ML_API_URL`, etc.) and credentials.
    *   For DNA issues, inspect the XML requests/responses in `DNA_response_logs/`.
    *   Ensure `DNA_VERIFY_SSL` and `ML_VERIFY_SSL` are set appropriately (usually `false` for dev/test unless you have valid certs).
*   **Data Not Appearing or Incorrect:**
    *   Check `logs/waiting_app.log` for any errors during data fetching or processing.
    *   Verify the member number being used is correct.
    *   If caching is suspected, consider temporarily reducing TTLs or clearing cache (requires code modification or app restart) for testing.
*   **"Internal Server Error":**
    *   If `FLASK_DEBUG=True`, you should see a detailed traceback in your browser.
    *   Otherwise, check `logs/waiting_app.log` for the error stack trace.
