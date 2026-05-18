# Option 3: UiPath RPA — Setup & Workflow Design

End-to-end automation for the ACME Invoice platform.

---

## Part 1: Initial Setup

### Step 1 — Install UiPath Studio Community Edition

1. Go to https://www.uipath.com/start-trial (free, no credit card needed)
2. Create a UiPath account or sign in
3. Download **UiPath Studio Community**
4. Run the installer and choose the **Studio** profile during setup
5. Sign in with your UiPath account when Studio launches

### Step 2 — Create your ACME account

1. Go to https://acme-test.uipath.com/reboot-your-skills
2. Click **Register** and create a free account
3. Note your email and password — the bot will need these as credentials
4. Log in manually once to confirm your account works

### Step 3 — Install required UiPath packages (inside Studio)

Open Studio → **Manage Packages** and install:

| Package | Purpose |
|---|---|
| `UiPath.Excel.Activities` | Read the downloaded invoice report |
| `UiPath.PDF.Activities` | Extract text from PDF invoices |
| `UiPath.WebAPI.Activities` | (Optional) HTTP download fallback |
| `UiPath.DocumentUnderstanding.ML.Activities` | (Optional) AI-based extraction |
| `UiPath.UIAutomation.Activities` | Browser and UI automation |

---

## Part 2: Project Structure

Create a new **Process** project in Studio called `ACME_Invoice_Automation`.

Organize it into three workflows called from `Main.xaml`:

```
ACME_Invoice_Automation/
├── Main.xaml                  ← orchestrates the three steps
├── Workflows/
│   ├── 1_LoginAndDownloadReport.xaml
│   ├── 2_DownloadInvoices.xaml
│   └── 3_ExtractAndSaveData.xaml
├── Data/
│   └── Config.xlsx            ← credentials and settings
└── Output/
    └── (downloaded files go here at runtime)
```

Store credentials in `Config.xlsx` (sheet: "Settings"):

| Key | Value |
|---|---|
| ACME_URL | https://acme-test.uipath.com/reboot-your-skills |
| ACME_Email | your@email.com |
| ACME_Password | yourpassword |
| DownloadFolder | C:\ACME_Invoice_Automation\Output |

---

## Part 3: Workflow Breakdown

### Workflow 1 — Login and Download the Invoice Report

**Goal**: Open the ACME site, log in, and download the full Excel invoice report.

**Steps inside `1_LoginAndDownloadReport.xaml`**:

1. **Read Config** — use `Read Range` to load settings from `Config.xlsx`
2. **Open Browser** — use `Open Browser` activity (Chrome recommended), navigate to `ACME_URL`
3. **Login**:
   - Type email into the email field
   - Type password into the password field  
   - Click the Login button
   - Add a `Wait For Page Load` or `Element Exists` check to confirm login succeeded
4. **Navigate to the invoice report page** — find the "Download Report" link/button and click it
5. **Handle the download dialog** — use `Element Exists` + keyboard shortcut or `Set Download Folder` to save to your `DownloadFolder`
6. **Verify download** — use `Path Exists` to confirm the `.xlsx` file landed in the folder
7. **Output**: return the full path to the downloaded Excel file as an output argument `ReportFilePath`

> **Tip**: Use `Try/Catch` around the login block. If login fails, throw a meaningful `BusinessRuleException` with the message "ACME login failed — check credentials in Config.xlsx."

---

### Workflow 2 — Download All Individual Invoices

**Goal**: Parse the report Excel, then download every invoice file listed.

**Steps inside `2_DownloadInvoices.xaml`**:

1. **Read the Excel report** — use `Read Range` → store as `DataTable dt_Report`
2. **For Each Row** in `dt_Report`:
   a. Read `Vendor` column → `str_Vendor`
   b. Read `Month` column → `str_Month`
   c. Construct the file identifier / URL for that invoice (based on what the ACME site exposes — typically a link in a column or a pattern like `/invoices/{vendor}/{month}`)
   d. Navigate to the invoice page (or click the row link)
   e. Click the download button for that invoice
   f. Wait for the file to appear in `DownloadFolder`
   g. Rename the file to something structured: `{Vendor}_{Month}_invoice.pdf`
3. **Output**: return a `List<String>` of all downloaded file paths as `lst_InvoicePaths`

> **Tip**: Wrap the inner loop body in `Try/Catch` so one failed download doesn't abort the whole run. Log failures with `Log Message` (level: Warning) and continue.

---

### Workflow 3 — Extract Invoice Data and Save Results

**Goal**: For each downloaded invoice PDF, extract the key fields and write to an output Excel.

**Steps inside `3_ExtractAndSaveData.xaml`**:

1. **Create output DataTable** with columns:
   `FileName`, `InvoiceNumber`, `InvoiceDate`, `SupplierName`, `TotalAmount`, `Currency`

2. **For Each** file path in `lst_InvoicePaths`:
   
   **Option A — PDF Activities (rule-based, simpler)**:
   - Use `Read PDF Text` to extract the full text
   - Use `Matches` activity (regex) to pull each field:
     - Invoice number: `(?i)invoice\s*(?:no|number|#)[:\s]*([A-Z0-9\-/]+)`
     - Invoice date: `(?i)(?:invoice\s*date|date)[:\s]*([\d]{1,2}[\/\.\-][\d]{1,2}[\/\.\-][\d]{2,4})`
     - Total amount: `(?i)total[:\s]*([€$£]?\s*[\d,]+\.?\d{0,2})`
     - Supplier: typically the first bold/large text block on page 1
   
   **Option B — Document Understanding (AI-based, more robust)**:
   - Use `Digitize Document` to OCR + parse the PDF
   - Use `Data Extraction Scope` with the pre-built Invoice ML model
   - This handles varied layouts automatically and is the preferred approach for Level 3-style documents

3. **Add Data Row** to output DataTable with extracted values
4. **Write Range** — write the DataTable to `Output/ExtractedInvoices.xlsx`
5. **Log completion** — `Log Message`: "Extracted data from N invoices. Results saved to Output/ExtractedInvoices.xlsx"

---

### Main.xaml — Orchestration

```
Sequence: ACME Invoice Automation
│
├── Log Message: "Starting ACME Invoice Automation"
│
├── Invoke Workflow: 1_LoginAndDownloadReport.xaml
│   └── Out: ReportFilePath
│
├── Invoke Workflow: 2_DownloadInvoices.xaml
│   ├── In:  ReportFilePath
│   └── Out: lst_InvoicePaths
│
├── Invoke Workflow: 3_ExtractAndSaveData.xaml
│   └── In:  lst_InvoicePaths
│
└── Log Message: "Automation complete"
```

---

## Part 4: Error Handling Strategy

| Scenario | Handling |
|---|---|
| Login fails | `BusinessRuleException` → stops run, logs credentials issue |
| One invoice download fails | `Log Message` (Warning) + continue loop |
| PDF extraction returns empty | Log + leave row fields null, flag in `FileName` as "EXTRACTION_FAILED" |
| Excel report not found | `SystemException` → stops run with clear message |

Always use `Try/Catch` at the activity level for network/UI operations and at the workflow level for business logic failures.

---

## Part 5: Running the Bot

1. Open `Main.xaml` in Studio
2. Click **Run** (F5) or **Debug** (F7) for step-through
3. Watch the Output panel for log messages
4. After completion, check `Output/ExtractedInvoices.xlsx` for results

To publish and run via UiPath Orchestrator (optional, more advanced):
- **Publish** the project from Studio
- Create a **Process** in Orchestrator and assign it to your local Robot
- Trigger manually or on a schedule

---

## Notes for the Presentation

- Mention the **modular workflow design** — each step is independently testable
- If asked why UiPath over code-only: built-in retry logic, visual debugging, Orchestrator scheduling, no-code maintenance by non-developers
- If time allows, demo the **Document Understanding** path (Workflow 3 Option B) — it's the most impressive technically and aligns with the AI-heavy theme of the rest of your solution
