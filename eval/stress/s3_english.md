# Software Requirements Specification

## Loan Pre-Approval API for Partner Marketplaces

**Organisation:** Teniz Bank JSC, Retail Lending Division
**Author:** M. Ospanova, Senior Business Analyst
**Reviewer:** T. Karimov, Head of Lending Platforms
**Version:** 0.9 (draft)
**Date:** 2026-11-03

## 1. Introduction

### 1.1 Purpose

This document specifies the requirements for a REST API that lets partner marketplaces (online electronics and furniture stores) request a non-binding pre-approval of a consumer loan for their customers before checkout. The pre-approval tells the customer the maximum amount, term and indicative rate the bank is likely to offer.

### 1.2 Scope

In scope: the pre-approval endpoint, eligibility checks, credit bureau lookup, decisioning, offer generation, partner authentication, audit logging.

Out of scope: final loan approval, contract signing, disbursement, collateral loans, mortgages, loans to legal entities.

### 1.3 Definitions

| Term | Definition |
|---|---|
| Partner | A marketplace that has signed a partnership agreement with the bank and received API credentials |
| Applicant | An individual, resident of the Republic of Kazakhstan, for whom the partner requests a pre-approval |
| IIN | Individual Identification Number, 12 digits |
| Pre-approval | A non-binding indicative offer returned by the API |
| DTI | Debt-to-income ratio: total monthly debt payments, including the requested loan, divided by declared monthly net income |
| Credit bureau | The external credit bureau the bank uses to obtain the applicant's credit history and existing obligations |
| Offer | A set of maximum amount, term options and indicative annual rate |

## 2. Actors

- **Partner system** calls the API on behalf of the applicant.
- **Applicant** gives consent on the partner's website and sees the result.
- **Decision engine** is the bank's internal rules engine that evaluates eligibility and calculates the offer.
- **Credit bureau** returns credit history and existing obligations.
- **Risk analyst** maintains decision rules and thresholds in the decision engine.

## 3. Functional Requirements

### 3.1 Request

**REQ-001.** The API shall expose the endpoint `POST /v1/preapprovals` that accepts a JSON body with the fields: `iin`, `phone`, `declared_monthly_income_kzt`, `requested_amount_kzt`, `requested_term_months`, `consent_id`, `partner_order_id`.

**REQ-002.** The API shall validate that `iin` contains exactly 12 digits and that its check digit is valid. Invalid IINs shall be rejected with HTTP 400 and error code `INVALID_IIN`.

**REQ-003.** The API shall validate that `phone` is in the format +7XXXXXXXXXX.

**REQ-004.** `requested_amount_kzt` shall be an integer between 50,000 and 5,000,000 inclusive.

**REQ-005.** `requested_term_months` shall be one of 3, 6, 12, 24, 36.

**REQ-006.** `consent_id` shall reference a consent record for credit bureau access that the partner registered through `POST /v1/consents` no earlier than 30 days before the pre-approval request.

**REQ-007.** Duplicate requests should be handled appropriately.

### 3.2 Eligibility

**REQ-010.** The applicant shall be between 21 and 65 years old on the date of the request. Age is derived from the IIN.

**REQ-011.** The applicant shall be a resident of the Republic of Kazakhstan.

**REQ-012.** The applicant shall not have any overdue obligation of more than 30 days in the last 12 months according to the credit bureau.

**REQ-013.** Thin-file applicants shall be routed to the alternative scoring model.

**REQ-014.** Applicants who already have an active consumer loan with Teniz Bank with an outstanding balance above 3,000,000 KZT shall be declined with reason code `EXISTING_EXPOSURE`.

### 3.3 Scoring and Decision

**REQ-020.** For each eligible applicant the API shall request the credit report from the credit bureau using the IIN and the `consent_id`.

**REQ-021.** The decision engine shall calculate DTI using declared income and the monthly payments reported by the credit bureau plus the estimated monthly payment of the requested loan.

**REQ-022.** If DTI is below 50%, the applicant is approved. If DTI is above 50%, the applicant is declined with reason code `HIGH_DTI`.

**REQ-023.** The maximum pre-approved amount shall be the largest amount for which DTI stays below 50%, capped at 5,000,000 KZT, and rounded.

**REQ-024.** The indicative annual rate shall be taken from the rate table maintained by the Risk analyst in the decision engine for the applicant's score band and term.

**REQ-025.** The pre-approval shall be valid for TBD days from the moment of issue.

**REQ-026.** Applicants aged 18 and over who pass the credit bureau check may receive a pre-approval with a reduced maximum amount of 500,000 KZT.

### 3.4 Response

**REQ-030.** On success the API shall return HTTP 200 with: `preapproval_id`, `decision` (`APPROVED` or `DECLINED`), `max_amount_kzt`, `term_options_months`, `indicative_rate_percent`, `valid_until`, `reason_codes`.

**REQ-031.** For declined applications `max_amount_kzt`, `term_options_months` and `indicative_rate_percent` shall be null and `reason_codes` shall contain at least one code.

**REQ-032.** Reason codes returned to the partner shall be from the published list: `HIGH_DTI`, `AGE`, `NON_RESIDENT`, `OVERDUE_HISTORY`, `EXISTING_EXPOSURE`, `OTHER`. Internal rule identifiers shall never be returned.

**REQ-033.** The response shall not contain the applicant's credit history, income or existing obligations.

### 3.5 Errors

**REQ-040.** Requests without a valid partner access token shall be rejected with HTTP 401.

**REQ-041.** Requests with an expired or missing consent shall be rejected with HTTP 422 and error code `CONSENT_INVALID`.

**REQ-042.** Validation errors shall return HTTP 400 with a list of field names and error codes.

**REQ-043.** Each partner shall be limited to 100 requests per minute. Requests above the limit shall receive HTTP 429.

## 4. Non-Functional Requirements

**REQ-050.** The API shall return a response within 3 seconds for 95% of requests, measured at the bank's API gateway over a calendar day.

**REQ-051.** The API shall be available 99.5% of the time per calendar month, excluding announced maintenance windows.

**REQ-052.** The API shall sustain 1,000 requests per minute per partner without degradation.

**REQ-053.** All traffic shall use TLS 1.2 or higher. Partners authenticate with OAuth 2.0 client credentials; access tokens are valid for 15 minutes.

**REQ-054.** Request and response payloads shall be stored for as long as necessary for audit purposes.

**REQ-055.** IIN and phone shall be masked in application logs (first 4 and last 2 digits visible).

**REQ-056.** The API documentation shall be user-friendly.

## 5. External Interfaces

**REQ-060.** Credit bureau integration uses the bureau's SOAP service `GetCreditReport` with mutual TLS.

**REQ-061.** The decision engine is invoked synchronously over the internal REST interface `POST /decide`.

## 6. Acceptance Criteria

**AC-01.** A request with a valid IIN, consent and DTI of 30% returns `APPROVED` with a non-null `max_amount_kzt`.

**AC-02.** A request with DTI of 65% returns `DECLINED` with reason code `HIGH_DTI`.

**AC-03.** A request with an IIN whose check digit is wrong returns HTTP 400 and `INVALID_IIN`.

**AC-04.** A request with a consent older than 30 days returns HTTP 422 and `CONSENT_INVALID`.

**AC-05.** The 101st request from the same partner within one minute returns HTTP 429.

**AC-06.** A declined response contains no amount, term or rate and at least one reason code.
