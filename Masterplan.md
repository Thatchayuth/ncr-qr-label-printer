# MASTER PROMPT — NCR QR LABEL PRINTER

## ROLE

You are a Senior Python Desktop Engineer, Microsoft Dynamics AX 4.0 Integration Specialist, TSC Printer Integration Engineer, Software Architect, and Windows Deployment Engineer.

Build a production-ready, maintainable Windows Desktop Application named **NCR QR Label Printer**.

Work incrementally by Phase. Prioritize reliability, maintainability, security, correct printing, and simple installation.

Do not build unnecessary infrastructure.

## 1. PROJECT OVERVIEW

Create a Python Desktop Application that:

1. Connects to Microsoft Dynamics AX 4.0 SQL Server.
2. Retrieves data from configurable, approved custom AX tables or SQL views.
3. Supports dynamic search and configurable data mapping.
4. Generates QR codes using user-configurable fields.
5. Designs and previews custom-sized labels.
6. Prints labels directly to a TSC TE200 printer.
7. Supports USB and network printing.
8. Records print history and supports controlled reprinting.
9. Runs without Python installed on the client.
10. Can be installed using Windows Setup.exe.

### Target Environment

- Platform: Windows 10/11 x64
- Language: Python
- UI: PySide6
- Database Connectivity: pyodbc
- ERP: Microsoft Dynamics AX 4.0
- Local Database: SQLite
- QR: qrcode + Pillow
- Printing: TSPL / TSPL2, pywin32, TCP Socket
- Packaging: PyInstaller
- Installer: Inno Setup
- Version Control: Git

Use supported stable dependency versions and maintain pinned dependencies.

## 2. ARCHITECTURE

Implement a lightweight layered architecture:

- Presentation Layer
- Application / Service Layer
- Domain Models
- Infrastructure Layer
- Database Repositories
- Printer Adapters

Required interfaces:

- IDataSourceRepository
- IQueryProfileRepository
- ILabelTemplateRepository
- IQrPayloadBuilder
- ILabelRenderer
- IPrinterAdapter
- IPrintJobRepository
- IConfigurationService

Do not place database connections, SQL queries, TSPL commands, or print execution directly in UI components.

Use Qt workers or QThreadPool for blocking I/O. All UI changes must occur safely on the GUI thread.

Do not introduce a backend server, REST API, Docker, Redis, Celery, or microservices without an explicit requirement.

## 3. AX 4.0 DATABASE INTEGRATION

Connect to SQL Server using pyodbc and an installed compatible Microsoft ODBC driver.

Support SQL Authentication and Windows Integrated Authentication.

Requirements:

- Read-only access
- Configurable server/database
- Connection test
- Connection timeout
- Query timeout
- Parameterized queries
- DATAAREAID filtering where applicable
- Result limits
- Explicit ordering
- Null handling
- Unicode and decimal precision
- Connection cleanup
- Friendly connection error messages

Never assume the actual custom table schema.

Implement two data-access modes:

**Approved Query Mode**
- DBA-provided SQL views or stored procedures
- Explicit input parameters
- Whitelisted source names
- No arbitrary SQL entered by operators

**Admin Data Profile Mode**
- Select approved tables/views
- Discover allowed columns
- Configure search fields
- Configure display fields
- Configure output fields
- Configure sorting and row limits
- Compile only validated identifiers
- Bind all data values as query parameters

Never concatenate user input directly into SQL identifiers or values.

Avoid changing the AX database schema.

Do not permit UPDATE, INSERT, DELETE, DROP, ALTER, EXEC of arbitrary statements or unsafe SQL expressions.

Support Custom Tables and SQL Views without hardcoding SalesTable or SalesLine.

## 4. DYNAMIC DATA MAPPING

Provide Data Profiles with:

- Profile name
- Source view/table
- DATAAREAID policy
- Searchable fields
- Display fields
- QR fields
- Label text fields
- Field aliases
- Data types
- Required-field rules
- Date/decimal formatting
- Default values
- Template assignment

Support changing profiles without rebuilding the program.

Version data profiles and preserve the profile version used for every print job.

## 5. QR PAYLOAD ENGINE

Implement a configurable QR Builder.

Supported formats:

- Plain text
- Delimited text
- JSON

Requirements:

- Multiple mapped fields
- Configurable delimiter
- Optional fixed prefixes and suffixes
- Ordered fields
- Explicit handling of null values
- Maximum payload validation
- QR version/error correction choices
- Unicode handling
- Deterministic serialization
- Payload preview
- Payload byte-length validation
- Test decoding

Use a structured internal model so QR data and printed label text can have different layouts.

Prevent invalid or unsafe data from corrupting TSPL commands.

Consider native TSPL QRCODE and bitmap-based QR printing. Select and document the reliable default after testing real printer firmware, especially for UTF-8 or Thai text.

## 6. CUSTOM LABEL DESIGNER

Build a Qt Graphics View based designer.

Supported objects:

- Static Text
- Dynamic Text
- QR Code
- Rectangle
- Horizontal/Vertical Line
- Image/Logo

Requirements:

- Custom label width and height in millimeters
- Label gap and media type
- 203 DPI for TSC TE200
- Canvas zoom
- Drag and drop
- Resize
- Alignment
- Grid and snap
- Font size and bold
- Text overflow detection
- QR size
- Object rotation
- Margin and printable-area validation
- Save, duplicate, import, and export templates
- Template versioning

Store coordinates using physical units independent of screen pixels.

Provide accurate Preview rendering and avoid maintaining unrelated layout definitions for preview and printing.

Prefer one shared layout model with separate Qt Preview and TSPL renderers.

Support rasterizing fonts/images when native printer fonts cannot represent the content.

## 7. TSC TE200 PRINTER ENGINE

Target TSC TE200, 203 DPI, TSPL-EZD.

Support:

A. Windows USB Printer Queue
B. Windows Network Shared Printer Queue
C. Optional RAW TCP 9100 Print Server

Do not assume TE200 contains native Ethernet hardware.

Create printer adapters:

- WindowsSpoolerAdapter
- WindowsSharedPrinterAdapter
- TcpPrinterAdapter

Support:

- Printer enumeration
- Printer selection
- Default printer profile
- Connection test where feasible
- Test print
- Label calibration guidance
- Copies
- Printing multiple selected rows
- Print queue
- Cancel pending jobs
- Printer errors
- Retry with duplicate prevention
- Print-job correlation IDs
- Configurable density and speed

Generate TSPL with:

SIZE
GAP / BLINE
DIRECTION
REFERENCE
CLS
TEXT / BITMAP / QRCODE
PRINT

Verify all commands against supported firmware.

Escape and validate dynamic data. Never interpolate untrusted user input directly into TSPL syntax.

Do not automatically resend a job after uncertain delivery without checking the queue or requiring operator confirmation.

Differentiate accepted-by-spooler, submitted-to-device, and physically-confirmed print states.

## 8. UI / UX DESIGN

Use PySide6 with a clean, modern enterprise design.

Theme:
- Light theme
- Smooth visual hierarchy
- Rounded cards
- Soft borders
- Clear spacing
- Consistent icons
- Readable Thai and English text
- High-DPI support
- Responsive to desktop resizing

Pages:

1. Dashboard / Search & Print
2. Data Profiles
3. QR Configuration
4. Label Designer
5. Printer Settings
6. Print History
7. Application Settings
8. Diagnostics

Main workflow:

Choose Data Profile
→ Enter search criteria
→ Query AX
→ Display records
→ Select one/multiple rows
→ Select template
→ Preview
→ Choose copies/printer
→ Print
→ Record job results

Remember the previous non-sensitive user settings.

Disable double-submit while a job is being dispatched.

Provide visible error messages and actionable recovery options.

## 9. CONFIGURATION & SECURITY

Store non-sensitive configuration under:

%LOCALAPPDATA%/NCR/QRLabelPrinter/

Use SQLite for local metadata and history.

Use Windows DPAPI for secrets when SQL Authentication is required.

Support Windows Integrated Authentication when possible.

Requirements:

- No hardcoded credentials
- No passwords in plaintext config
- No secret values in logs
- Least-privilege database access
- Separate admin configuration capability
- Schema-validated JSON
- Safe config import/export
- Config version migration
- Atomic file writes
- Backup before migration

Do not assume local Windows Administrator rights are available.

## 10. PRINT HISTORY & LOGGING

Implement structured logging with rotation.

Log:

- Timestamp
- Windows username
- Application version
- Event category
- Correlation ID
- Print job ID
- Profile/template version
- Document reference
- Printer name
- Copies requested
- Job status
- Error code/message
- Retry/reprint reason

Use SQLite persistence.

Avoid exposing passwords, raw connection strings, or sensitive QR contents.

Required history states:

- Pending
- Submitting
- SpoolerAccepted
- Failed
- Cancelled
- UnknownDelivery
- ConfirmedPrinted (only with reliable confirmation)

Reprint operations must create a new history event linked to the original job.

## 11. PROJECT STRUCTURE

Use a clean structure similar to:

ncr-qr-label-printer/
- src/
  - main.py
  - app/
  - ui/
  - domain/
  - services/
  - repositories/
  - infrastructure/
    - ax/
    - printing/
    - storage/
    - security/
  - templates/
  - resources/
- tests/
  - unit/
  - integration/
  - hardware/
- scripts/
- installer/
- docs/
- pyproject.toml
- requirements.lock or equivalent
- README.md
- CHANGELOG.md

Keep classes modular and easy to test.

## 12. TESTING STRATEGY

Unit Tests:
- Field mapping
- Query parameter handling
- Payload generation
- TSPL command generation
- Label bounds validation
- Template serialization
- Retry decisions

Integration Tests:
- SQLite
- Config persistence
- SQL repository against test database
- Windows Spooler abstraction

Hardware Tests:
- TE200 USB
- Shared printer
- Optional TCP print server
- Media calibration
- QR readability
- Continuous printing
- Thai font handling

Provide a simulated AX Data Source and Mock Printer so development does not require physical hardware at every stage.

Never run destructive tests against the production AX database.

## 13. WINDOWS PACKAGING

Build the application on Windows.

Prefer PyInstaller onedir for reliable dependency packaging and installation.

Create an Inno Setup installer:

- Application name: NCR QR Label Printer
- Application version
- Application icon
- Start Menu shortcut
- Optional Desktop shortcut
- Per-user install where feasible
- Optional admin installation mode
- Uninstaller
- Upgrade preservation of user settings
- Clean removal of program files
- Explicit choice whether to delete user data
- First-run setup wizard

Do not silently install drivers, modify firewall rules, or grant database permissions.

Provide:

- Windows build script
- Installer .iss source
- Build instructions
- Installation guide
- Troubleshooting guide

The final installer must work without separately installing Python.

## 14. DEVELOPMENT PHASES

Phase 0 — Discovery and Hardware Proof of Concept

Phase 1 — Project Foundation and UI Shell

Phase 2 — AX Database Access and Dynamic Data Profiles

Phase 3 — QR Payload Engine and Label Designer

Phase 4 — TSC Printer Adapters and Print History

Phase 5 — Windows Packaging, Installer, and UAT

For every Phase:

1. State objective.
2. Define scope.
3. List files to create or modify.
4. Implement actual working code.
5. Add tests.
6. Run available tests and build verification.
7. Explain manual hardware checks.
8. Update documentation.
9. Summarize the result.
10. Identify any unresolved issues.

Do not claim tests or hardware verification were completed unless actually executed.

## 15. OUT OF SCOPE

Unless requested:

- Web Application
- Mobile Application
- Cloud Infrastructure
- REST API Server
- AX Data Modification
- ERP Business Process Changes
- User Management Server
- Automatic Database Schema Changes
- Distributed Print Server
- Multiple Client Synchronization
- Centralized Web Dashboard
- Automatic Updates
- Printer Firmware Updates

## 16. ACCEPTANCE CRITERIA

The system is acceptable when:

- AX read-only connection works.
- Custom source profiles work.
- Search retrieves correct AX data.
- Dynamic fields can map into QR codes.
- Different custom label sizes can be configured.
- Label Preview matches physical output within agreed tolerances.
- TE200 USB printing works.
- Windows Shared Printer printing works.
- Error handling is reliable.
- Print History records results without misleading success states.
- No Python installation is required on user machines.
- Setup.exe installs and uninstalls the application.
- The application does not modify AX data.
- QR content can be scanned and verified.
- Documentation is complete.

## 17. IMPORTANT EXECUTION INSTRUCTIONS

Start with Phase 0.

First inspect the existing repository, if present, and preserve working code.

If no repository exists, initialize the project properly.

Use mock database data and a simulated printer until real AX schema and TSC printer information are supplied.

Do not invent real AX table names, columns, credentials, or printer capabilities.

Do not block development on unspecified label dimensions or QR fields; make them configurable and use clearly marked sample defaults for development.

Create a PHASES.md file with detailed tasks, dependencies, acceptance tests, and completion criteria.

Implement Phase 0 and prepare Phase 1 foundations. Continue through phases only after their acceptance requirements are met.

Favor simple solutions over unnecessary abstractions.

The final objective is a stable Windows desktop tool that an ordinary operator can install, configure, and use to search AX data and print QR labels with minimal training.