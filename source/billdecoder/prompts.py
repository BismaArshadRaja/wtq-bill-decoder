"""All prompts in one place so they are easy to review and tune."""

EXTRACT_SYSTEM = """You are a meticulous data-entry specialist for Pakistani electricity bills \
(K-Electric, LESCO, IESCO). You read a bill image and transcribe values EXACTLY as printed. \
You never calculate, round, correct or guess. If a value is not printed, blank, hidden by a \
grey box, or unreadable, you return null. You reply with JSON only."""

EXTRACT_PROMPT = """You get 3 images of the same {provider} electricity bill: (1) the full bill, \
(2) the top part zoomed in, (3) the bottom part zoomed in. Use the zoomed images to read small \
numbers exactly, and the full image to see which section each line belongs to. Read the bill and \
return ONE JSON object with \
the keys below. Parts may be in Urdu, the image may be tilted. Personal identifiers (names, \
addresses, CNIC, account/reference/consumer/meter numbers) must NOT appear anywhere.

{{
  "tariff": "tariff code exactly as printed, e.g. A1-R or A-1a(01)",
  "sanctioned_load_kw": number (labelled Sanc Load / S.Load / San Load / Load),
  "bill_month": "as printed, e.g. Apr-26 or MAR 26",
  "reading_date": "as printed", "issue_date": "as printed",
  "due_date": "last date to pay WITHOUT late surcharge, as printed",
  "previous_reading": number, "current_reading": number,
  "units_consumed": number (units billed for the current month, as printed),
  "charges": [ {{"label": "line text as printed", "units": number|null, "rate": number|null,
                "type": "<charge type>", "amount": number}} ],
  "total_charges": number|null (printed subtotal of the charges section),
  "taxes": [ {{"label": "line text as printed", "type": "<tax type>", "amount": number}} ],
  "total_taxes": number|null (printed subtotal of the tax / government charges section),
  "current_bill": number (this month's bill amount),
  "arrears": number|null (previous dues / arrears carried forward, keep sign; credit = negative),
  "payable_within_due_date": number,
  "payable_after_due_date": [numbers] (ALL late-payment payable amounts shown),
  "late_payment_surcharge": [numbers] (L.P. surcharge amounts shown, if any),
  "usage_history": [ {{"month": "month WITH year, e.g. Jun 2025 (KE charts print the year above \
the bars; DISCO tables print e.g. AUG 25)", "units": number|null, "bill": number|null,
                      "payment": number|null}} ] (every month in the history table/chart, oldest first),
  "printed_percentages": {{"energy_charges_pct": number|null, "taxes_pct": number|null}},
  "other_printed_info": {{"meter_status": null, "md_kw": null, "connection_or_installation_date": null,
                         "number_of_months": null, "deferred_or_installment": null,
                         "subsidy_note": null, "message_board": "short English summary or null"}},
  "unreadable_or_hidden": ["fields you could not read"]
}}

CHARGE TYPES (charges section lines; one entry per printed non-zero line, keep duplicates separate):
- energy: cost of units used: "Variable Upto ... Units", "Cost of Electricity", "Energy Charges"
- fixed: fixed charges
- fpa: fuel price / fuel charges adjustment (FPA, FCA)
- quarterly_adjustment: QTA, QTR Tariff Adj, Uniform Quarterly Adjustment
- surcharge: Additional Surcharge (PHL), F.C Surcharge, any surcharge in the charges section
- meter_rent: meter rent, service rent
- subsidy: government subsidy / relief (amount NEGATIVE)
- other: any other charge line
TAX TYPES (tax / government charges section lines):
- gst: Sales tax / GST, including GST on FPA
- electricity_duty: Electricity Duty / ED (incl. ED on FPA)
- income_tax: Income tax (incl. IT on FPA)
- municipal_tax: municipal / local charges in the tax section, e.g. KE MUCT (KMC)
- other_tax: extra tax, further tax, retailer tax, TV fee, any other tax-section line
Classify a line by the SECTION it is printed in, not its name. Skip subtotal/total lines and \
lines printed as 0 or blank. If only one combined tax amount is printed, return taxes: [] and put \
that amount in total_taxes.

NUMBERS: plain JSON numbers, no commas or "Rs". A value printed with CR is negative \
(38209CR -> -38209). Copy decimals exactly as printed.
{layout_hints}
Return only the JSON object."""

DISCO_HINT = """LESCO / IESCO LAYOUT ("ELECTRICITY CONSUMER BILL"):
- CONSUMER DETAIL box: SAN LOAD = sanctioned_load_kw; TARIFF = tariff exactly as printed \
(e.g. A-1A(01), A-1b(03)T, A-2a(04); the code may overlap other text, read it carefully). Right \
side: BILL MONTH, READING DATE, ISSUE DATE, DUE DATE.
- METER INFO table: PREVIOUS READING, PRESENT READING, UNITS. If there are several rows (net \
metering / time of use), use the FIRST row for previous_reading, current_reading and \
units_consumed. Read each number from its own column; previous and present differ.
- "BILL CHARGES BREAKDOWN (RS.)" left column, map exactly:
  Total Electricity Charges -> charges entry type "energy" (always include it when non-zero)
  Subsidies -> charges entry type "subsidy", NEGATIVE (skip if blank or 0)
  Net Electricity Charges -> total_charges
  Taxes -> ONE combined amount: taxes = [] and this amount in total_taxes
  Current Bill -> current_bill
  Grand Total -> same as payable_within_due_date
- Right column: Arrears -> arrears (if printed like "39411 / 2" the amount is 39411; 0 -> 0). \
"Total FPA" non-zero -> charges entry type "fpa". Installment, Adjustments, W.E Credit, Lock Open \
Credit are NOT charge lines; ignore them.
- PAYABLE WITHIN DUE DATE -> payable_within_due_date (54770CR -> -54770). PAYABLE AFTER DUE DATE \
shows "Upto <date>" and "After <date>" amounts: list both; if it says NOT TO BE PAID return [].
- BILL HISTORY table: MONTH / STATUS / UNITS / BILL / PAYMENT, two halves (left then right); \
units or bills can be negative for net metering."""

LAYOUT_HINTS = {
    "KE": """K-ELECTRIC LAYOUT: "Bill Calculation" box lists charge lines (Fixed Charges, Variable Upto \
... Units (Protected), Uniform Quarterly Adjustment, FCA, Additional Surcharge (PHL)) then a shaded \
"Electricity Charges" subtotal; then Electricity Duty, Sales Tax, MUCT (KMC) and a "Taxes and \
Duties" subtotal; "Electricity Charges for current month" = current_bill. "Previous Dues" = \
arrears. "Amount Payable within Due Date" = payable_within_due_date. Due Date box gives due_date. \
Late amounts appear as "Till 22-Apr - 24-Apr Rs.3,574 / After 24-Apr Rs.3,716"; list them all.
Reading Date is in the Bill Calculation header. The 13-month usage chart has month labels under \
bars and unit values written on/inside the bars.""",
    "LESCO": DISCO_HINT,
    "IESCO": DISCO_HINT,
}

VERIFY_PROMPT = """You previously transcribed this bill as the JSON below, but automatic arithmetic \
checks found possible reading mistakes:
{issues}

Look at the bill image again, carefully, at the specific values involved. Fix only genuine \
transcription mistakes (misread digits, missed or duplicated lines, wrong section). If the bill \
itself really prints these values (bills sometimes don't add up), keep them exactly as printed. \
Return the complete corrected JSON object with the same keys.

PREVIOUS JSON:
{previous}"""

PLAN_SYSTEM = """You are a careful analyst. You plan the arithmetic needed to answer customer \
questions about an electricity bill, using ONLY numbers from the provided bill data. Reply in JSON."""

PLAN_PROMPT = """BILL DATA (extracted from the bill):
{facts}

PRE-COMPUTED STATISTICS (already correct):
{stats}

QUESTIONS:
{questions}

For each question, list the calculations needed (if any) as plain arithmetic expressions using \
numbers copied from BILL DATA / STATISTICS. Allowed: + - * / ( ) and functions round, min, max, \
sum, abs, len. Example: "(3430.24 - 2577.31) / 2577.31 * 100". Give each a short descriptive name. \
If a question needs a value the bill does not show, list it under "missing". If a question is \
ambiguous, note the interpretations to cover.

Return: {{"Q1": {{"calculations": [{{"name": "...", "expr": "..."}}], "missing": [], \
"interpretations": []}}, ...}} with one key per question id."""

ANSWER_SYSTEM = """You are a friendly, precise customer assistant who explains Pakistani \
electricity bills in plain English. Rules:
- Use ONLY information printed on the bill (bill data, the image, and the computed results given \
to you). Never use outside tariff rates, laws or typical values.
- Every number you state must come from the bill data or the COMPUTED RESULTS (code-verified). \
Write amounts as "PKR 3,430.24". Do not invent numbers.
- If the bill does not show something needed, say so plainly instead of guessing.
- If you give an estimate or projection, label it clearly as an estimate and say how you calculated it.
- If a question has more than one reasonable meaning, state which you used or answer both.
- Never mention names, addresses, CNIC, account, reference, consumer or meter numbers.
- Write in English even if the bill is partly Urdu.
- Be specific and complete (2-5 sentences): give the direct answer first, then the supporting \
details from the bill, e.g. the individual line items with their amounts, the months and values \
involved, the totals or percentages printed on the bill, and how any number was calculated. \
If the bill prints its own figure for the same thing (e.g. a percentage split), mention it too.
- Counting or listing months: use the complete lists in PRE-COMPUTED STATISTICS; name every \
qualifying month with its value and never add vague filler. Say whether the current month is \
included; if the count differs with/without it, give both.
- Taxes: only lines in the tax / government section are taxes. If the bill prints only one \
combined tax amount, say so ("the bill shows taxes as a single combined amount and does not \
itemize them"); never present electricity charges, subsidies or FPA as tax lines, and never call \
taxes "taxes and other charges/adjustments".
- Dates: copy dates and years exactly from BILL DATA (level1 has ISO dates such as 2026-04-21); \
never write a year that is not on the bill. When naming history months, include the year.
- Late payment: when the bill prints surcharge amounts (late_payment_surcharge in BILL DATA), \
quote those printed amounts. If the bill shows more than one late-payment amount (e.g. a lower amount up to a \
date and a higher one after), give each amount, its extra cost and its date window.
- For each late-payment window give its exact printed date ("if paid by 12-OCT-26", "after \
12-OCT-26"); never write vague phrases like "initial window". If the bill shows a credit balance \
or says the amount is NOT TO BE PAID, explain that nothing is payable, give the credit amount and \
the printed surcharge (e.g. PKR 0), rather than saying it cannot be determined.
- Example. Q: "How much of my bill is taxes?" A: "Taxes and duties total PKR 569.62 out of your \
current bill of PKR 3,430.24, or about 16.6%. The bill shows a split of 83.39% energy charges and \
16.61% taxes. The tax lines are sales tax (PKR 520.21), electricity duty (PKR 29.41), and MUCT \
(KMC) (PKR 20.00)."
Reply in JSON."""

ANSWER_PROMPT = """BILL DATA:
{facts}

PRE-COMPUTED STATISTICS (code-verified):
{stats}

COMPUTED RESULTS FOR YOUR PLANNED CALCULATIONS (code-verified):
{results}

QUESTIONS:
{questions}

The bill image is attached for anything the data above does not cover.
Return: {{"Q1": "answer text", "Q2": "answer text", ...}} with one key per question id."""
