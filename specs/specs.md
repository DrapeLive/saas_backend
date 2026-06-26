# Garment Wholesale SaaS — AI Agent Specification

> **Purpose:** This document provides structured, machine-readable specifications for AI agents building, testing, or extending the Garment Wholesale SaaS platform. Each section defines module objectives, entities, business rules, data contracts, and acceptance criteria.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Constraints](#2-architecture-constraints)
3. [Module Specifications](#3-module-specifications)
    - 3.1 Super Admin
    - 3.2 Admin (Business Owner)
    - 3.3 Agent Management
    - 3.4 Customer Management
    - 3.5 Product & Inventory
    - 3.6 Order Creation (Agent)
    - 3.7 Order Processing
    - 3.8 Tally Integration
    - 3.9 Outstanding Management
    - 3.10 Commission Management
    - 3.11 Sub Admin (RBAC)
    - 3.12 Analytics & Reporting
4. [Cross-Cutting Concerns](#4-cross-cutting-concerns)
5. [Integration Contracts](#5-integration-contracts)
6. [Implementation Phases](#6-implementation-phases)
7. [Glossary](#7-glossary)

---

## 1. System Overview

| Attribute               | Value                                                                                                                                       |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| **Product type**        | Multi-tenant B2B SaaS                                                                                                                       |
| **Primary market**      | Indian garment wholesale sector                                                                                                             |
| **User personas**       | Super Admin, Admin (Business Owner), Sub Admin, Sales Agent, (read-only) Customer                                                           |
| **Key differentiators** | Multi-company agent switcher, QR-first order creation, bi-directional Tally sync, GST-verified customer directory, tiered commission engine |

### 1.1 Tenancy Model

- **Tenant** = one garment wholesale company (business).
- **Super Admin** operates above all tenants (platform operator).
- All database queries MUST be scoped by `tenant_id` except Super Admin queries.
- Schema strategy: shared database, tenant-ID column filtering.

### 1.2 Subscription Tiers

| Tier         | Price (₹/month) | Agents    | Customers | Storage |
| ------------ | --------------- | --------- | --------- | ------- |
| Starter      | 1,999           | ≤ 3       | ≤ 100     | 50 GB   |
| Professional | 4,999           | ≤ 10      | ≤ 500     | 200 GB  |
| Enterprise   | 9,999           | Unlimited | Unlimited | 1 TB    |

**Trial logic:**

- Default trial: **14 days** (not 6 months — shorter trials yield 15–20% higher conversion).
- Engagement-based extension: up to **90 days** (triggers: ≥ 1 order placed, ≥ 3 customers added).
- Grace period after expiry: **7 days** full access + data export enabled.
- Post-grace: read-only lockout.

---

## 2. Architecture Constraints

### 2.1 Must-Have Technical Requirements

| Concern              | Requirement                                                                            |
| -------------------- | -------------------------------------------------------------------------------------- |
| Auth                 | OAuth 2.0 / JWT; refresh token rotation                                                |
| Encryption (transit) | TLS 1.2+ on all endpoints                                                              |
| Encryption (rest)    | AES-256 for sensitive fields (GSTIN, bank details, commission data)                    |
| RBAC                 | Role-based; permission matrix per module × action                                      |
| Audit log            | Immutable log of all financial transactions and permission changes                     |
| Multi-tenancy        | All queries filtered by `tenant_id`; cross-tenant queries only via Super Admin service |
| Offline support      | Agent mobile app: offline-first with local SQLite; background sync on reconnect        |
| Integration queue    | Message queue (RabbitMQ or Kafka) for Tally sync, WhatsApp, GST API, email             |
| Mobile target        | PWA or React Native / Flutter                                                          |

### 2.2 Naming Conventions

- Invoice series: `INV-{YYYY}-{00001}` — resets on April 1 (Indian FY).
- Purchase Order series: `PO-{YYYY}-{00001}`.
- SKU: auto-generated as `{StyleCode}-{ColorCode}-{SizeCode}`.
- `tenant_id` present on every tenant-scoped entity.

---

## 3. Module Specifications

---

### 3.1 Super Admin Module

**Role:** Platform operator controlling all tenants.

#### 3.1.1 Dashboard KPIs (read, no write)

| Metric              | Description                       |
| ------------------- | --------------------------------- |
| `total_companies`   | All registered tenants            |
| `active_companies`  | Tenants with active subscription  |
| `trial_companies`   | Tenants in trial period           |
| `expired_companies` | Tenants post-grace                |
| `mrr`               | Monthly Recurring Revenue (₹)     |
| `arr`               | Annual Recurring Revenue (₹)      |
| `churn_rate`        | % companies churned this month    |
| `ltv`               | Average Lifetime Value per tenant |

#### 3.1.2 Company Management Actions

| Action         | Trigger / Rule                                                                                  |
| -------------- | ----------------------------------------------------------------------------------------------- |
| Create company | Generates `tenant_id`, initialises trial                                                        |
| Suspend        | Blocks all logins for tenant; data preserved                                                    |
| Activate       | Restores access                                                                                 |
| Extend trial   | Admin-only; logs reason + duration                                                              |
| Impersonate    | Super Admin can view tenant as Admin for support; session flagged as impersonation in audit log |
| Delete         | Soft-delete only; data retained 90 days                                                         |

#### 3.1.3 Notification Schedule (subscription lifecycle)

| Days before/after expiry | Channel                          |
| ------------------------ | -------------------------------- |
| 60 days before           | Email                            |
| 30 days before           | Email + WhatsApp                 |
| 15 days before           | Email + WhatsApp + In-app banner |
| 7 days before            | Email + WhatsApp + In-app banner |
| 1 day before             | WhatsApp + In-app banner         |
| Day 0 (expiry)           | Email + In-app alert             |
| Day 7 (grace end)        | Email + WhatsApp (final warning) |

#### 3.1.4 Business Rules

- A company cannot be deleted during an active subscription.
- Impersonation sessions expire after 30 minutes.
- Storage overage blocks new file uploads; does not break existing features.

---

### 3.2 Admin (Business Owner) Module

**Role:** Manages all operations within one tenant.

#### 3.2.1 Company Setup Wizard (one-time, 5 steps)

1. Business profile (name, logo, GST number → auto-verify via API).
2. Bank details (for commission payouts).
3. Invoice settings (prefix, starting number, terms, footer).
4. Tax settings (GST rate defaults, HSN code library).
5. Notification preferences (WhatsApp, email).

#### 3.2.2 Dashboard KPIs

| Metric                  | Description                                          |
| ----------------------- | ---------------------------------------------------- |
| `orders_today`          | Count of orders submitted today                      |
| `sales_today`           | ₹ value of confirmed/dispatched orders today         |
| `outstanding_total`     | Total receivable outstanding                         |
| `overdue_total`         | Outstanding > 30 days                                |
| `avg_order_value`       | Rolling 30-day average                               |
| `agent_response_time`   | Avg time from order submission to admin confirmation |
| `order_conversion_rate` | Orders confirmed / orders submitted                  |

#### 3.2.3 Analytics Charts

| Chart                       | Data                                             |
| --------------------------- | ------------------------------------------------ |
| Sales trend                 | Line chart, 6 / 12-month toggle                  |
| Top products by revenue     | Bar chart, top 10                                |
| Agent comparison            | Bar chart, MTD sales per agent                   |
| Outstanding aging           | Stacked bar: 0–30, 31–60, 61–90, 90+ days        |
| Customer acquisition funnel | Stage counts: invited → registered → first order |

#### 3.2.4 Business Rules

- Financial year resets invoice/PO counters on April 1.
- Admin receives push notifications for: new order submitted, low stock threshold breach, payment received.

---

### 3.3 Agent Management Module

#### 3.3.1 Entity: Agent

```
Agent {
  agent_id        UUID PK
  tenant_id       UUID FK (one per company relationship)
  user_id         UUID FK (shared across companies)
  name            string
  phone           string (unique)
  email           string
  status          enum(pending, active, suspended)
  invitation_method enum(whatsapp, email, qr_code)
  joined_at       timestamp
  commission_tier UUID FK → CommissionTier
}
```

#### 3.3.2 Invitation Flow

1. Admin generates invitation (WhatsApp link / email / QR code).
2. Agent installs app and claims invitation token.
3. Status: `pending` → Admin (or Sub Admin) approves → `active`.
4. Two-step approval optional: Sub Admin reviews → Admin approves.

#### 3.3.3 Multi-Company Support

- One user account can belong to **multiple tenants** simultaneously.
- Company switcher UI: bottom sheet listing all companies with logo, pending order count, and unread notification count.
- Each company context is **data-isolated** (separate `tenant_id` scope).
- Active company stored in session; switching does not log out.

#### 3.3.4 Agent Performance Data

| Field                | Description                                    |
| -------------------- | ---------------------------------------------- |
| `orders_this_month`  | Count                                          |
| `sales_this_month`   | ₹ value                                        |
| `commission_earned`  | ₹ MTD                                          |
| `commission_preview` | Estimated commission on cart before submission |
| `leaderboard_rank`   | Among all agents in this tenant                |
| `target_vs_actual`   | % achievement against monthly target           |

#### 3.3.5 Business Rules

- Agent cannot view other agents' customers or orders.
- Suspended agent's orders remain in system.
- Offline orders queued locally; synced FIFO on reconnect.
- Commission preview is approximate; final calculation on order confirmation.

---

### 3.4 Customer Management Module

#### 3.4.1 Entity: Customer

```
Customer {
  customer_id     UUID PK
  tenant_id       UUID FK
  legal_name      string (auto-filled from GST API)
  trade_name      string
  gstin           string (15 chars, validated)
  gst_status      enum(active, cancelled, suspended, unverified)
  address         Address
  phone           string
  email           string
  assigned_agent  UUID FK → Agent
  credit_limit    decimal
  credit_used     decimal (computed)
  is_credit_blocked boolean
  tags            string[]
  created_at      timestamp
}
```

#### 3.4.2 GST Auto-Verification

- On GSTIN entry: call GST Verification API (Gridlines / SurePass / SurePass).
- Auto-populate: `legal_name`, `address`, `gst_status`, taxpayer type, jurisdiction.
- Display verification badge: ✅ Active / ⚠️ Suspended / ❌ Cancelled.
- Bulk import: validate each GSTIN row before committing; return per-row error report.

#### 3.4.3 Bulk Import Flow

1. Admin downloads Excel template.
2. Uploads filled template.
3. System maps columns (with override option).
4. Validation run: GSTIN format check → GST API verification.
5. Preview table: valid rows (green) + error rows (red) with reasons.
6. Confirm import of valid rows; download error report for failed rows.

#### 3.4.4 Customer Detail Tabs

| Tab           | Content                                                           |
| ------------- | ----------------------------------------------------------------- |
| Summary       | Contact info, GST badge, credit limit bar, outstanding with aging |
| Orders        | Order history, status, value                                      |
| Payments      | Payment history, receipts                                         |
| Ledger        | Running balance statement                                         |
| Documents     | GST certificate, PAN, KYC uploads                                 |
| Communication | WhatsApp/email log, visit notes                                   |

#### 3.4.5 Auto-Segmentation Rules

| Segment    | Criteria                                |
| ---------- | --------------------------------------- |
| High Value | MTD orders > ₹1L                        |
| At Risk    | No order in 60 days                     |
| Overdue    | Outstanding > credit limit or > 30 days |
| New        | First order within 30 days              |

#### 3.4.6 Business Rules

- New orders MUST be blocked when `credit_used >= credit_limit` AND `is_credit_blocked = true`.
- Only the assigned agent (or Admin/Sub Admin) can view a customer's full profile.
- GSTIN must be unique per tenant.

---

### 3.5 Product & Inventory Module

#### 3.5.1 Entity: Product

```
Product {
  product_id    UUID PK
  tenant_id     UUID FK
  name          string
  category      enum(mens, kids, ladies, accessories, other)
  description   string
  hsn_code      string
  gst_rate      decimal (%)
  images        string[] (URLs, max 10)
  variants      Variant[]
  is_active     boolean
  created_at    timestamp
}

Variant {
  variant_id    UUID PK
  product_id    UUID FK
  color         string
  color_code    string
  sizes         SizeStock[]
  qr_code_url   string (generated)
  sku           string (auto: {StyleCode}-{ColorCode})
}

SizeStock {
  size          string  (e.g., S, M, L, XL, 32, 34)
  sku           string  (auto: {StyleCode}-{ColorCode}-{Size})
  price         decimal
  stock_qty     integer
  reserved_qty  integer (orders in progress)
  available_qty integer (computed: stock_qty - reserved_qty)
  low_stock_threshold integer
  qr_code_url   string
}
```

#### 3.5.2 QR Code Specification

- One QR code per **variant-size combination**.
- QR payload: `{ tenant_id, product_id, variant_id, size, sku }`.
- Batch print: generate A4 sticker sheet PDF (multiple QR codes per page).
- QR codes tolerate up to 30% physical damage (error correction level H).
- Scanning with any smartphone camera must resolve product + open order entry.

#### 3.5.3 Stock Operations

| Operation         | Rule                                                                      |
| ----------------- | ------------------------------------------------------------------------- |
| Stock entry       | Manual per row OR bulk Excel import                                       |
| Stock adjustment  | Requires reason (received, damaged, returned, correction)                 |
| Reserve stock     | On order submission: `reserved_qty += ordered_qty`                        |
| Release stock     | On order cancellation: `reserved_qty -= ordered_qty`                      |
| Confirm stock out | On dispatch: `stock_qty -= ordered_qty`, `reserved_qty -= ordered_qty`    |
| Low stock alert   | Triggered when `available_qty <= low_stock_threshold` (in-app + WhatsApp) |

#### 3.5.4 Business Rules

- Agents CANNOT oversell: `ordered_qty` must not exceed `available_qty` at time of cart submission.
- `available_qty` is computed; never stored directly.
- Product duplication: clone product + variants; new `product_id` and `variant_id`; stock reset to 0.
- Image uploads: compress to max 800 KB per image; store CDN URL.

---

### 3.6 Order Creation Module (Agent)

#### 3.6.1 Order Entity

```
Order {
  order_id        UUID PK
  tenant_id       UUID FK
  po_number       string (e.g., PO-2026-00042)
  agent_id        UUID FK
  customer_id     UUID FK
  items           OrderItem[]
  subtotal        decimal
  discount_amount decimal
  gst_amount      decimal (CGST + SGST or IGST)
  total_amount    decimal
  notes           string
  status          enum(draft, submitted, confirmed, processing, packed, ready, dispatched, delivered, cancelled)
  created_offline boolean
  created_at      timestamp
  submitted_at    timestamp
}

OrderItem {
  item_id         UUID PK
  order_id        UUID FK
  product_id      UUID FK
  variant_id      UUID FK
  size            string
  sku             string
  qty             integer
  unit_price      decimal
  line_total      decimal
}
```

#### 3.6.2 Order Creation Flow

1. Agent selects / confirms active company context.
2. Select customer (search or pick from assigned list).
3. Add products via **QR scan** (primary) or manual search (fallback).
    - QR scan resolves `variant_id` + `size`; opens size-quantity picker.
    - Size grid shows `available_qty` per size; out-of-stock sizes are disabled.
4. Cart: edit quantities, remove items, apply discount (if permitted by role).
5. Review screen: itemised list, GST breakdown, total, optional note.
6. Signature capture (optional, configurable per tenant).
7. Submit → status changes to `submitted`.
8. System immediately generates PO PDF and offers: View / Download / Share via WhatsApp.

#### 3.6.3 QR Scan Requirements

- Flashlight toggle available in scanner.
- Batch scan mode: scan multiple products without leaving scanner.
- Scan any QR code on garment sample → resolves correct variant.

#### 3.6.4 Offline Requirements

- Full order creation available offline.
- Local storage: SQLite (encrypted).
- On reconnect: auto-sync queued orders FIFO.
- Conflict resolution: if stock exhausted during offline period, alert agent and request re-confirmation.

#### 3.6.5 PO PDF Contents

| Section     | Fields                                                                 |
| ----------- | ---------------------------------------------------------------------- |
| Header      | Company logo, legal name, address, GSTIN                               |
| Bill To     | Customer legal name, address, GSTIN                                    |
| Items table | SKU, product name, color, size, qty, unit price, HSN, GST%, line total |
| Tax summary | CGST / SGST (intra-state) or IGST (inter-state) per GST slab           |
| Total       | Subtotal, discount, tax, grand total (figures + words)                 |
| Footer      | Terms, bank details, authorised signature                              |

---

### 3.7 Order Processing Module

#### 3.7.1 Status Workflow

```
submitted → confirmed → processing → packed → ready → dispatched → delivered
                                                              ↓
                                                         cancelled (from any pre-dispatch state)
```

- Status transitions are sequential; no skipping except cancellation.
- Each transition logs: `changed_by`, `changed_at`, `reason` (optional).

#### 3.7.2 Kanban Board

- One column per status.
- Order cards display: PO number, customer name, agent name, total amount, time in current status.
- Drag-and-drop to advance status.
- Bulk action: select multiple orders → bulk status update / bulk dispatch.

#### 3.7.3 Dispatch Entry Fields

| Field             | Required                                    |
| ----------------- | ------------------------------------------- |
| LR number         | Yes                                         |
| Transport company | Yes                                         |
| Dispatch date     | Yes                                         |
| Vehicle number    | No                                          |
| Driver contact    | No                                          |
| E-way bill number | No (auto-link if e-way integration enabled) |
| Tracking link     | No                                          |

#### 3.7.4 Post-Dispatch Automation

On status → `dispatched`:

1. Auto-generate **Sales Invoice** (INV-series PDF).
2. Push invoice to Tally via API (queued if Tally unavailable).
3. Send WhatsApp notification to customer: LR number, transport, estimated delivery, tracking link.
4. Send in-app notification to Admin and Agent.
5. Update `stock_qty` (deduct dispatched quantities).

#### 3.7.5 Business Rules

- Order quantities can be edited before `dispatched` status; edit requires reason log.
- Cancelled orders release reserved stock.
- Invoice number assigned at `dispatched` (not at `confirmed`).

---

### 3.8 Tally Integration Module

#### 3.8.1 Integration Topology

```
SaaS ──[HTTP/XML]──► Tally ERP (local or cloud)
SaaS ◄──[HTTP/XML]── Tally ERP
```

- Protocol: Tally XML/HTTP API over TCP/IP (port 9000 default).
- Auth: token-based + SSL/TLS.
- Sync queued via message queue; retry on failure.

#### 3.8.2 Push: SaaS → Tally

| Event in SaaS             | Tally action                                   |
| ------------------------- | ---------------------------------------------- |
| Order dispatched          | Create Sales Invoice (with GST ledger entries) |
| Customer created/updated  | Create/update Customer Ledger                  |
| Product created/updated   | Create/update Stock Item                       |
| Payment recorded manually | Create Receipt Voucher                         |

#### 3.8.3 Pull: Tally → SaaS

| Data from Tally      | Used in SaaS                                |
| -------------------- | ------------------------------------------- |
| Payment receipts     | Update outstanding, show in payment history |
| Customer outstanding | Display in customer profile and dashboard   |
| Ledger summaries     | Outstanding aging, collection reports       |

#### 3.8.4 Sync Schedule

| Trigger      | Behaviour                                             |
| ------------ | ----------------------------------------------------- |
| Event-driven | Webhook on dispatch / payment immediately queues sync |
| Scheduled    | Every 15 minutes for pull sync                        |
| Manual       | Admin can trigger full sync from integration settings |

#### 3.8.5 Error Handling

- Failed sync → entry added to `sync_error_log` with payload + HTTP status + error message.
- Retry: exponential backoff (1 min, 5 min, 30 min, 2 hr, 24 hr).
- After 5 failures: alert Admin in-app + email.
- Admin can view error log, resolve manually, and re-trigger.

#### 3.8.6 Business Rules

- Tally ledger mapping: default = customer legal name; Admin can override per customer.
- Invoice format: Tax Invoice (registered GSTIN) or Bill of Supply (unregistered / exempted).
- All API calls logged in immutable audit log.

---

### 3.9 Outstanding Management Module

#### 3.9.1 Aging Buckets

| Bucket     | Range                |
| ---------- | -------------------- |
| Current    | Not yet due          |
| 1–30 days  | 1–30 days overdue    |
| 31–60 days | 31–60 days overdue   |
| 61–90 days | 61–90 days overdue   |
| 90+ days   | Over 90 days overdue |

#### 3.9.2 Payment Entry (Manual)

- Fields: customer, amount, date, payment mode (cash / NEFT / UPI / cheque), reference number, receipt upload.
- Generates UPI payment link / QR for the outstanding amount (optional).
- Syncs to Tally as Receipt Voucher.

#### 3.9.3 Automated Payment Reminders

| Days overdue | Channel                                    |
| ------------ | ------------------------------------------ |
| 15 days      | WhatsApp template message                  |
| 30 days      | WhatsApp + Email                           |
| 45 days      | WhatsApp + Email + In-app alert to Admin   |
| 60 days      | WhatsApp + Email + In-app + agent notified |

#### 3.9.4 Monthly Account Statement

- PDF: opening balance, all invoices, all payments, closing balance.
- Sent to customer email on the 1st of each month (configurable).
- Downloadable on demand.

#### 3.9.5 Business Rules

- New orders blocked when `outstanding > credit_limit` AND `is_credit_blocked = true`.
- Collection funnel: total outstanding → contacted → promised → collected (Admin dashboard widget).
- Agent-wise collection target and achievement tracked monthly.

---

### 3.10 Commission Management Module

#### 3.10.1 Commission Structure

**Tier-based (on monthly sales value per agent):**

| Slab                  | Rate |
| --------------------- | ---- |
| ₹0 – ₹1,00,000        | 2%   |
| ₹1,00,001 – ₹5,00,000 | 3%   |
| Above ₹5,00,000       | 5%   |

**Category-based override (if applicable):**

| Category | Rate |
| -------- | ---- |
| Mens     | 2%   |
| Kids     | 3%   |
| Ladies   | 4%   |

**Category rate takes precedence when configured; otherwise tier rate applies.**

Additional modifiers (optional, configured per tenant):

- Product-specific override rate.
- New product launch bonus (flat ₹ per unit).
- Target achievement accelerator (e.g., +1% if target exceeded by 10%).

#### 3.10.2 Calculation Rules

- Commission calculated per `OrderItem` based on `line_total` and applicable rate.
- Commission preview shown in cart before order submission (approximate).
- Monthly settlement cycle: Admin marks commission as paid → creates Tally payment voucher.
- Agent can raise a dispute; Admin reviews and adjusts with notes.

#### 3.10.3 Commission Entities

```
CommissionRecord {
  record_id       UUID PK
  tenant_id       UUID FK
  agent_id        UUID FK
  order_id        UUID FK
  period_month    string (YYYY-MM)
  gross_sales     decimal
  commission_rate decimal
  commission_amt  decimal
  status          enum(pending, approved, paid, disputed)
  paid_at         timestamp
  payment_ref     string
}
```

#### 3.10.4 Business Rules

- Commission is earned on `dispatched` orders only (not on cancelled).
- Settlement is per calendar month.
- Admin sees liability report: total earned, total paid, total pending across all agents.

---

### 3.11 Sub Admin (RBAC) Module

#### 3.11.1 Permission Matrix

Modules (rows) × Actions (columns):

| Module             | View | Add | Edit | Delete | Export |
| ------------------ | ---- | --- | ---- | ------ | ------ |
| Orders             | ☐    | ☐   | ☐    | ☐      | ☐      |
| Products           | ☐    | ☐   | ☐    | ☐      | ☐      |
| Inventory          | ☐    | ☐   | ☐    | ☐      | ☐      |
| Customers          | ☐    | ☐   | ☐    | ☐      | ☐      |
| Agents             | ☐    | ☐   | ☐    | ☐      | ☐      |
| Commission         | ☐    | ☐   | ☐    | ☐      | ☐      |
| Outstanding        | ☐    | ☐   | ☐    | ☐      | ☐      |
| Reports            | ☐    | —   | —    | —      | ☐      |
| Tally Integration  | ☐    | —   | ☐    | —      | —      |
| Sub Admin Settings | ☐    | ☐   | ☐    | ☐      | —      |

UI: toggle matrix (not checkboxes). Edit requires View to be enabled (enforced automatically).

#### 3.11.2 Pre-Built Role Templates

| Template           | Default permissions                                            |
| ------------------ | -------------------------------------------------------------- |
| Operations Manager | All orders + inventory; no commission; no agent management     |
| Product Manager    | Products + inventory + reports (view/export); no orders        |
| Accountant         | Outstanding + commission + reports + Tally; no orders/products |
| Viewer             | View + export only across all modules                          |

#### 3.11.3 Role Rank

- Rank: 0–100 integer.
- Admin = rank 100 (implicit).
- Sub Admin cannot create or modify roles with rank ≥ own rank.

#### 3.11.4 Data Scope Restrictions (optional per role)

| Scope type       | Description                                                  |
| ---------------- | ------------------------------------------------------------ |
| Agent assignment | Sub Admin sees only orders/customers of assigned agents      |
| Product category | Sub Admin manages only specified categories                  |
| Customer region  | Sub Admin manages only customers in specified regions/states |

#### 3.11.5 Business Rules

- All Sub Admin actions logged in audit log: `{user_id, action, entity, entity_id, timestamp, ip_address}`.
- Approval workflow: orders above configurable ₹ threshold require Admin sign-off, even if Sub Admin approved.
- Sub Admins cannot modify their own permissions.

---

### 3.12 Analytics & Reporting Module

#### 3.12.1 Reports by Role

**Admin:**

- Sales: daily / monthly / yearly; product-wise; category-wise; region-wise.
- Orders: status breakdown; cancelled analysis; average order value trend.
- Customers: top customers; acquisition; retention; outstanding aging.
- Agents: sales comparison; activity log; commission summary.
- Inventory: stock valuation; low stock; slow-moving; fast-moving items.

**Agent (self-only):**

- Personal sales trend; target vs achievement; commission forecast.
- Order history; customer order frequency.
- Leaderboard rank; product availability alerts.

**Super Admin (platform-wide):**

- MRR / ARR; churn; cohort analysis.
- Company growth; feature adoption rates.
- Revenue by tier; peak season analysis.

#### 3.12.2 Export & Delivery

- All reports exportable as **Excel (.xlsx)** and **PDF**.
- Scheduled email delivery: daily / weekly / monthly (configurable per report per user).
- Date range filter on all reports.

#### 3.12.3 GSTR-1 Report

- Auto-generate GSTR-1 compatible report from invoice data.
- Reconcile with data pulled from Tally.
- Exportable in government-prescribed format.

---

## 4. Cross-Cutting Concerns

### 4.1 Notifications

| Event                        | In-app | Push | WhatsApp      | Email |
| ---------------------------- | ------ | ---- | ------------- | ----- |
| Order submitted              | ✅     | ✅   | —             | —     |
| Order confirmed              | ✅     | ✅   | ✅ (customer) | —     |
| Order dispatched             | ✅     | ✅   | ✅ (customer) | ✅    |
| Payment received             | ✅     | ✅   | —             | —     |
| Low stock alert              | ✅     | ✅   | ✅ (admin)    | —     |
| Commission settled           | ✅     | —    | ✅ (agent)    | ✅    |
| Subscription expiry reminder | ✅     | —    | ✅            | ✅    |
| Tally sync failure           | ✅     | —    | —             | ✅    |
| Payment overdue (customer)   | —      | —    | ✅            | ✅    |

WhatsApp: use pre-approved Template Messages for all outbound notifications. SMS fallback if WhatsApp delivery fails.

### 4.2 Audit Log Schema

```
AuditLog {
  log_id        UUID PK
  tenant_id     UUID FK (null for Super Admin actions)
  user_id       UUID FK
  user_role     string
  action        string  (e.g., ORDER_DISPATCHED, PERMISSION_UPDATED)
  entity_type   string
  entity_id     UUID
  diff          jsonb   (before/after for updates)
  ip_address    string
  user_agent    string
  created_at    timestamp
}
```

- Audit log is **immutable** (append-only; no UPDATE or DELETE).
- Retained for minimum 7 years (Indian GST compliance).

### 4.3 File Storage

- All uploads (product images, receipts, GST certs): stored in cloud object storage (S3-compatible).
- CDN delivery for product images.
- Per-tenant storage quota enforced (see subscription tiers).
- Compress images to ≤ 800 KB on upload.

---

## 5. Integration Contracts

### 5.1 GST Verification API

**Trigger:** GSTIN field on customer create / edit.

**Request:**

```json
{ "gstin": "27AAPFU0939F1ZV" }
```

**Expected response fields to consume:**

```
legal_name, trade_name, address (line1, line2, city, state, pincode),
gst_status (Active/Cancelled/Suspended), taxpayer_type, registration_date, jurisdiction
```

**Failure handling:** If API unavailable, save as `gst_status: unverified`; retry on next edit.

### 5.2 WhatsApp Business API

- Provider: Any BSP (AiSensy, Interakt, etc.).
- Message types used: Template Messages (notifications), Interactive Messages (payment links).
- Cost reference: ~₹0.145 per utility message (India).
- SMS fallback on delivery failure.

### 5.3 Tally ERP API

- Protocol: HTTP + XML to Tally Gateway on port 9000.
- Auth: bearer token + TLS.
- Operations: `CreateVoucher` (sales invoice, receipt), `GetLedger`, `GetOutstanding`.
- Audit: all calls logged to `tally_sync_log`.

### 5.4 Payment Link / UPI QR

- Generate UPI payment link for outstanding amount.
- Include in WhatsApp payment reminder template.
- On payment confirmation: auto-record in outstanding management.

---

## 6. Implementation Phases

| Phase        | Months | Modules                                                                                                         | Exit Criteria                                            |
| ------------ | ------ | --------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- |
| **MVP**      | 1–3    | Super Admin, Admin Dashboard, Customer Management, Product & Inventory, Basic Order Creation, Agent App (basic) | End-to-end order flow working; QR scan; PO PDF generated |
| **Growth**   | 4–6    | QR Inventory (batch print), Tally Integration, WhatsApp Notifications, Commission Management                    | Production-ready; accounting sync live                   |
| **Scale**    | 7–9    | Sub Admin RBAC, Advanced Analytics, Offline Mode, Bulk Import/Export, GST Verification API                      | Enterprise features complete                             |
| **Optimize** | 10–12  | Mobile app enhancements, AI recommendations, Advanced Reporting, API platform                                   | Market-ready                                             |

---

## 7. Glossary

| Term           | Definition                                                             |
| -------------- | ---------------------------------------------------------------------- |
| **Tenant**     | One garment wholesale company using the platform                       |
| **Agent**      | Sales representative who creates orders on behalf of customers         |
| **Sub Admin**  | Delegated admin within a tenant with scoped permissions                |
| **GSTIN**      | Goods and Services Tax Identification Number (15-char Indian tax ID)   |
| **HSN Code**   | Harmonised System of Nomenclature code for product tax classification  |
| **LR Number**  | Lorry Receipt number (freight/dispatch tracking)                       |
| **PO**         | Purchase Order (document generated at order submission)                |
| **INV**        | Sales Invoice (document generated at dispatch)                         |
| **MRR**        | Monthly Recurring Revenue                                              |
| **ARR**        | Annual Recurring Revenue                                               |
| **RBAC**       | Role-Based Access Control                                              |
| **SKU**        | Stock Keeping Unit (unique product-variant-size identifier)            |
| **E-way Bill** | Electronic waybill required for GST-compliant goods transport in India |
| **GSTR-1**     | Monthly GST return for outward supplies                                |
| **BSP**        | Business Solution Provider (WhatsApp API reseller)                     |
| **PWA**        | Progressive Web App                                                    |
