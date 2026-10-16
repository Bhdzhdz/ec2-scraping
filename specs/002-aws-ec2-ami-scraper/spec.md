# Feature Specification: AWS EC2/AMI Scraper

**Feature Branch**: `002-aws-ec2-ami-scraper`
**Created**: 2026-10-16
**Status**: Draft
**Input**: User description: "AWS EC2/AMI scraping via boto3 using SSO profiles, loading results into the inventory schema from 001"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Scrape one account via an SSO profile (Priority: P1)

An operator names an AWS SSO profile and runs a scrape. The tool authenticates with that profile, collects all EC2 instances and the AMIs they use or own in the selected regions, and stores them in the inventory database from feature 001.

**Why this priority**: Core value; without it the schema stays empty.

**Independent Test**: Run against a test account with known instances and AMIs; verify every one appears in the database with its attributes, tags, and attachments.

**Acceptance Scenarios**:

1. **Given** a valid SSO session for a profile, **When** the operator runs a scrape for that profile, **Then** all instances and AMIs in scope are stored and a scrape run is recorded as succeeded.
2. **Given** an expired or missing SSO session, **When** a scrape starts, **Then** it stops before any collection with a message telling the operator to log in again for that profile, and no data is changed.
3. **Given** a previously scraped resource, **When** it is scraped again, **Then** its record is updated in place and its last-seen time and scrape run advance.

---

### User Story 2 - Scrape multiple profiles and regions (Priority: P2)

An operator supplies several profiles and/or regions (or all enabled regions) in one run. Each profile/region combination is scraped and recorded as part of a single scrape run.

**Why this priority**: Real estates span many accounts and regions.

**Independent Test**: Run with two profiles and two regions; verify data for all four combinations and that the run scope lists them.

**Acceptance Scenarios**:

1. **Given** multiple profiles and regions, **When** a scrape runs, **Then** each combination is collected and the run scope records every combination attempted.
2. **Given** one profile fails (expired login, denied access, or region unavailable), **When** the run finishes, **Then** other combinations are still stored, the failure is reported per combination, and the run is marked partial.

---

### User Story 3 - Detect resources that disappeared (Priority: P3)

After a scrape, an operator can tell which previously known resources were not seen in the latest run for the scraped scope.

**Why this priority**: Builds on the history model from 001.

**Independent Test**: Scrape, terminate/deregister a resource, scrape again; verify it is reported as missing from the latest run.

**Acceptance Scenarios**:

1. **Given** a resource absent from a successful run of its scope, **When** the operator queries missing resources, **Then** it is listed and its last-seen time is unchanged.
2. **Given** a failed combination, **When** missing resources are queried, **Then** resources in that combination are not reported missing because of that run.

---

### Edge Cases

- Account with zero instances or AMIs: run succeeds, nothing stored.
- Large result sets spanning multiple pages: all results collected.
- Instance references an AMI that is not visible or no longer exists: instance is stored; no AMI record is required.
- API throttling: collection retries and completes, or the combination is reported failed.
- Region disabled for the account: combination reported failed or skipped, run continues.
- Interrupted run (crash, Ctrl-C): run is not left marked running indefinitely.
- Resources missing optional attributes (no public IP, no tags, no key pair): stored with empty values.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST authenticate to AWS using named SSO profiles supplied by the operator, and MUST NOT require or store long-lived access keys.
- **FR-002**: The tool MUST accept one or more profiles and one or more regions per run, with an option to cover all regions enabled for the account.
- **FR-003**: If a profile's SSO session is invalid or expired, the tool MUST report which profile needs login and skip it without changing data.
- **FR-004**: The tool MUST collect all EC2 instances in scope, including all attributes, tags, security groups, block devices, and network interfaces defined by the 001 schema.
- **FR-005**: The tool MUST collect AMIs owned by the scraped account in scope, and AMIs referenced by scraped instances when visible, with attributes, tags, and block device mappings defined by 001.
- **FR-006**: The tool MUST retrieve complete results regardless of result paging.
- **FR-007**: The tool MUST resolve the account ID from the authenticated profile and record it with each resource.
- **FR-008**: The tool MUST load data into the 001 schema, creating or updating reference records (account, region, AZ, instance type, VPC, subnet, key pair, IAM profile, security group) as needed.
- **FR-009**: Re-scraping MUST update existing records in place without duplicates, and MUST update last-seen time and scrape run reference.
- **FR-010**: Tags removed in AWS MUST be removed from the stored record on the next successful scrape; attachments removed likewise.
- **FR-011**: Each invocation MUST create a scrape run recording start, end, status (succeeded, partial, failed), and every combination that resolves to an account, plus login failures in the run summary
- **FR-012**: A failure in one profile/region combination MUST NOT prevent other combinations from completing; failures MUST be reported per combination with the cause.
- **FR-013**: The tool MUST only perform read-only operations against AWS.
- **FR-014**: The tool MUST handle API throttling by retrying with backoff before reporting failure.
- **FR-015**: Each combination's data MUST be stored atomically: a failed combination leaves its previous stored data unchanged.
- **FR-016**: The tool MUST provide a way to list resources not seen in the latest successful run of their scope.
- **FR-017**: The tool MUST report a summary at the end of a run: counts of instances and AMIs created, updated, and unchanged, plus failures.
- **FR-018**: The tool MUST be runnable non-interactively (suitable for scheduling), with exit status reflecting success, partial, or failure.
- **FR-019**: Database connection settings MUST be supplied via configuration or environment, not hard-coded.

### Key Entities

- **Scrape target**: A profile and region pair to collect; resolves to an account.
- **Scrape run / scope**: Existing 001 entities recording what was attempted and the outcome.
- **Instance, AMI and their attributes, tags, attachments**: Existing 001 entities populated by this feature.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After a scrape of a test account, 100% of its instances and in-scope AMIs are present with all defined attributes and tags.
- **SC-002**: Running the same scrape twice produces zero duplicate records and advances last-seen on all unchanged resources.
- **SC-003**: With one of several profiles failing, 100% of the remaining profiles' data is stored and the failure is identified by profile and region.
- **SC-004**: An expired login is reported with the specific profile name before any data is written.
- **SC-005**: A scrape of 5,000 instances across multiple regions completes within 10 minutes.
- **SC-006**: A resource deleted in AWS appears in the missing-resources listing after the next successful scrape of its scope.
- **SC-007**: The operator can run a scrape end to end from a single command with no interactive prompts when the SSO session is valid.

## Assumptions

- The inventory schema from feature 001 is applied to the target database; this feature does not alter it.
- Operators have already configured SSO profiles locally and log in themselves; the tool does not perform the login flow.
- boto3 is the AWS client library (stated by the requester).
- Profiles grant at least read-only access to EC2 describe operations.
- Only EC2 instances and AMIs (plus their referenced network/reference data) are in scope; EBS volumes, snapshots, and other services are out of scope.
- Public AMIs not owned by or used in the scraped accounts are out of scope.
- Hard deletion of missing resources is out of scope; they are only reported.
- A single run is executed by one process at a time.
