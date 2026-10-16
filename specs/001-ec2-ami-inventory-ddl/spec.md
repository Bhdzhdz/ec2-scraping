# Feature Specification: EC2 and AMI Inventory Schema (Initial DDL)

**Feature Branch**: `001-ec2-ami-inventory-ddl`

**Created**: 2026-10-16

**Status**: Draft

**Input**: User description: "define the initial DDL for the ec2 and ami inventory"

## Clarifications

### Session 2026-10-16

- Q: Which SQL database engine should the DDL target? → A: MySQL / MariaDB
- Q: Keep change history or only latest state? → A: Latest state only (v1)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Store an EC2 instance inventory (Priority: P1)

An operator runs the scraper against one or more AWS accounts/regions and needs a persistent, queryable record of every EC2 instance found, including identity, state, placement, sizing, networking, tags, and the AMI it was launched from.

**Why this priority**: The instance inventory is the core purpose of the project; nothing else is useful without it.

**Independent Test**: Apply the schema to an empty database, load sample instance records, and query them by account, region, state, and tag.

**Acceptance Scenarios**:

1. **Given** an empty database, **When** the schema is applied, **Then** an instance inventory structure exists that can hold one row per instance per account and region.
2. **Given** an instance already stored, **When** the same instance is loaded again with changed state, **Then** the existing record is updated rather than duplicated.
3. **Given** an instance with multiple tags, **When** it is stored, **Then** all tags can be retrieved and filtered by key and value.

---

### User Story 2 - Store an AMI inventory linked to instances (Priority: P1)

An operator needs a record of AMIs (owned, or referenced by instances) with their metadata, and wants to see which instances run from which AMI.

**Why this priority**: Linking instances to AMIs enables image-age, deprecation, and ownership reporting.

**Independent Test**: Load AMI and instance records, then list all instances for a given AMI and all AMIs with no instances.

**Acceptance Scenarios**:

1. **Given** stored AMIs and instances, **When** querying by AMI identifier, **Then** all instances launched from it are returned.
2. **Given** an instance referencing an AMI that is not visible/owned by the account, **When** loaded, **Then** the instance is still stored and the AMI link remains resolvable once the AMI is later discovered.

---

### User Story 3 - Track history of scrapes (Priority: P2)

An operator wants to know when each record was first seen, last seen, and from which scrape run, so terminated instances and deregistered AMIs can be identified.

**Why this priority**: Enables lifecycle and drift reporting but is not required for a first usable inventory.

**Independent Test**: Run two loads where one instance disappears in the second; verify it can be identified as no longer observed.

**Acceptance Scenarios**:

1. **Given** two scrape runs, **When** an instance is absent from the second, **Then** its last-seen time predates the second run and it is identifiable as missing.

---

### Edge Cases

- Instances or AMIs with no tags, no name, or no public IP.
- Same instance/AMI identifier appearing in different accounts or regions (identifiers are only unique within a region).
- Instances with multiple network interfaces, volumes, or security groups.
- AMIs that are deprecated, deregistered, or shared from another account.
- Missing optional attributes (e.g. platform, key pair, IAM profile) must be storable as absent.
- Schema applied twice must not fail or destroy data.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The schema MUST define an instance inventory structure identified uniquely by account, region, and instance ID.
- **FR-002**: Instances MUST record: instance type, lifecycle state, launch time, availability zone, architecture, platform, private/public IPs, VPC and subnet IDs, key pair name, IAM instance profile, and monitoring state.
- **FR-003**: The schema MUST define an AMI inventory structure identified uniquely by account (owner context), region, and image ID.
- **FR-004**: AMIs MUST record: name, description, owner ID, creation date, state, architecture, platform, root device type, virtualization type, public/private visibility, and deprecation time when set.
- **FR-005**: Each instance MUST reference the AMI it was launched from, by image ID and region, without requiring the AMI record to exist beforehand.
- **FR-006**: The schema MUST store tags for instances and AMIs as key/value pairs, supporting many tags per resource and lookup by key/value.
- **FR-007**: The schema MUST store instance attachments needed for inventory: security groups, block device mappings (volume ID, device name, size/type), and network interfaces.
- **FR-008**: The schema MUST store AMI block device mappings (snapshot ID, device name, size).
- **FR-009**: Every inventory record MUST carry first-seen and last-seen timestamps and a reference to the scrape run that last observed it.
- **FR-010**: The schema MUST define a scrape-run structure recording start time, end time, status, and the accounts/regions covered.
- **FR-011**: Re-loading an existing resource MUST update it in place (no duplicates), enforced by uniqueness constraints.
- **FR-012**: Deleting a parent record MUST remove its dependent tags and attachments.
- **FR-013**: The DDL MUST be re-runnable safely (idempotent) and include indexes supporting lookups by state, instance type, AMI ID, and tag key/value.
- **FR-014**: The DDL MUST be stored in the repository as versioned, plain SQL files targeting MySQL/MariaDB (InnoDB, utf8mb4).
- **FR-015**: The schema MUST be normalized to Third Normal Form (3NF): every non-key attribute depends only on its table's key; no repeating groups or multi-valued columns; no attribute that is determined by another non-key attribute.
- **FR-016**: Repeated descriptive values MUST live in reference tables referenced by key rather than duplicated as free text on each row: account, region, availability zone, instance type (with vCPU/memory/architecture facts), key pair, IAM instance profile, VPC, subnet, and security group.
- **FR-017**: Tags MUST be stored once in a single tag table per resource kind (instance, AMI) as (resource key, tag key, tag value), not as columns or serialized blobs.
- **FR-018**: Many-to-many relationships (instance to security group) MUST use association tables with a composite unique key.
- **FR-019**: Referential integrity MUST be enforced with foreign keys, except the instance-to-AMI link, which is deliberately soft (see FR-005) and resolved by a join on region and image ID.
- **FR-020**: Deliberate denormalization MUST be limited to first-seen/last-seen timestamps and the last-seen scrape run on each record, and documented in the plan.

### Key Entities *(3NF)*

- **Account**: AWS account ID, optional alias.
- **Region**: Region code; parent of availability zones.
- **Availability Zone**: Zone name, belongs to a region.
- **Instance Type**: Type name with vCPU, memory, architecture (one row per type).
- **Key Pair / IAM Instance Profile / VPC / Subnet / Security Group**: Reference records scoped by account and region; subnet belongs to a VPC and zone; security group belongs to a VPC.
- **Scrape Run**: One scraper execution; start/end time, status; linked to the account/region pairs it covered via a scope association.
- **Instance**: Keyed by account, region, instance ID; references instance type, zone, subnet, key pair, profile; holds state, launch time, IPs, platform, monitoring, AMI image ID, lifecycle timestamps.
- **Instance Security Group**: Association of instance to security group.
- **Instance Volume**: Instance attachment (device name, volume ID, size/type).
- **Instance Network Interface**: Interface ID, subnet, private/public IPs; belongs to an instance.
- **AMI**: Keyed by account, region, image ID; descriptive attributes, owner, visibility, deprecation, lifecycle timestamps.
- **AMI Block Device Mapping**: Device name, snapshot ID, size; belongs to an AMI.
- **Instance Tag / AMI Tag**: Key/value pairs belonging to one resource.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The schema applies cleanly to an empty database with zero errors, and applying it a second time also succeeds with no data loss.
- **SC-002**: 100% of the attributes listed in FR-002 and FR-004 can be stored and retrieved in a round-trip test.
- **SC-003**: Loading the same instance twice results in exactly one record in 100% of tested cases.
- **SC-004**: "All instances for a given AMI" and "all instances with tag key=value" queries return correct results on a 100,000-instance dataset in under 2 seconds.
- **SC-005**: Instances missing from a later scrape run can be listed with a single query.

## Assumptions

- Target database is MySQL/MariaDB (see Clarifications); DDL may use engine-specific syntax and types.
- Data is gathered from multiple AWS accounts and regions, so identifiers are scoped by account and region.
- Only the schema (DDL) is in scope; the scraping/loading code, migrations tooling, and reporting are out of scope.
- Schema targets 3NF; further forms (BCNF/4NF) are not required unless a violation is found during planning.
- Only the latest state is stored (see Clarifications); history of state changes is out of scope for v1, and only first-seen/last-seen are kept.
- Other resource types (EBS volumes, snapshots as standalone inventory, etc.) are out of scope.
