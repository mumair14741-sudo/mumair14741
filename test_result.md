#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================
# (protocol preserved)
#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

user_problem_statement: |
  Existing full-stack TrackMaster app. User uploaded updated zip and asked to run it,
  then do full testing of the application and fix any bugs found.

backend:
  - task: "Admin login + JWT"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Default admin creds admin@trackmaster.local / admin123. POST /api/admin/login working via curl."
  - task: "User registration + login"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "POST /api/auth/register creates pending user; POST /api/auth/login after admin activation."
  - task: "Links CRUD + short link redirect"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/links create/list/update/delete; /{short_code} redirect with click tracking, VPN, country/OS filters."
  - task: "Clicks listing + stats"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/clicks, /api/clicks/stats, /api/dashboard."
  - task: "Conversions + postback"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/postback endpoint + /api/conversions list."
  - task: "Proxies upload/list/check"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/proxies CRUD + /api/proxies/check."
  - task: "Admin features (users mgmt, branding, API settings)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/admin/users update/delete, /api/branding, /api/admin/api-settings."
  - task: "Sub-users + profile update + features mapping"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/sub-users CRUD and sub-user login flow."
  - task: "Referrer stats + UA generator + email checker (lightweight utilities)"
    implemented: true
    working: "NA"
    file: "backend/server.py"
    stuck_count: 0
    priority: "low"
    needs_retesting: true
    status_history:
      - working: "NA"
        agent: "main"
        comment: "/api/referrer-stats, /api/ua-generator, /api/email-checker endpoints."

frontend:
  - task: "Overall frontend testing"
    implemented: true
    working: "NA"
    file: "frontend/src"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
      - working: "NA"
        agent: "main"
        comment: "Skip frontend UI testing this round — focus backend smoke test. Will test UI after backend is green."

metadata:
  created_by: "main_agent"
  version: "1.0"
  test_sequence: 1
  run_ui: false

test_plan:
  current_focus:
    - "Admin login + JWT"
    - "User registration + login"
    - "Links CRUD + short link redirect"
    - "Clicks listing + stats"
    - "Conversions + postback"
    - "Proxies upload/list/check"
    - "Admin features (users mgmt, branding, API settings)"
    - "Sub-users + profile update + features mapping"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
  - agent: "main"
    message: |
      Backend running cleanly on :8001. MongoDB local. External preview URL:
      https://check-staging.preview.emergentagent.com
      Admin: admin@trackmaster.local / admin123
      Please do a BACKEND-ONLY smoke test of the main tasks listed. No UI testing this round.
      Use REACT_APP_BACKEND_URL from /app/frontend/.env for external calls.
      If anything fails, report with exact endpoint, payload, and response.
