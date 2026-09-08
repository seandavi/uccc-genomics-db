# Cohort discovery tools elsewhere, and what applies here

Written 2026-09-08 as input to `COHORT_TOOL.md` (the design for our cohort
query API, issue #23) and to the identified-data request path (issue #16).

Summary. Genomics portals (cBioPortal, GENIE, GDC) show exact counts of
patients and samples and put all of their privacy work before load: HIPAA
Safe Harbor age caps, day intervals instead of dates, and a controlled tier
for anything that could identify someone. Feasibility tools (TriNetX, i2b2,
SHRINE, Epic Cosmos) do the opposite: they run live on identifiable or
limited data and protect the count itself, with a floor of 3, 10 or 11,
Gaussian noise or rounding, a query log, and in some versions a lockout for
repeated queries. OHDSI sits between the two: ATLAS shows exact person
counts inside the institution and deletes cells of 5 or fewer only from the
results that leave it. The vendor cohort products (FoundationInsights, Caris
CODEai, Tempus Lens, Flatiron CGDB) publish almost nothing about their
suppression rules; Flatiron's "5 or fewer" is the only vendor number found.
For our tool the survey supports patient-level counts as the unit, a hard
floor rather than noise, secondary suppression on every breakdown, a
per-user audit log, cBioPortal's every-chart-is-a-filter interaction, and an
escalation path that stays inside the institution's IRB.

Each claim below links to the page that owns it. Where a primary source
could not be read or does not exist, the text says "not verified" or "no
public documentation found" rather than guessing. Four research passes
against primary sources fed this document; the per-system sections keep
their detail, the summary and final section keep the decisions.

## Comparison

| System | Filters | Count unit | Small-cell protection | Backend | Counts to identified data |
|---|---|---|---|---|---|
| cBioPortal | Any clinical attribute, gene, alteration type, driver/VUS, genomic profile, treatment, custom data; exact protein change only through OQL in the query builder | Patients and samples, both shown | None in the product; data must be de-identified before load | Live, Java over ClickHouse | None in the product; institutional |
| AACR GENIE | cBioPortal study view over the release | Patients and samples | None on counts; Safe Harbor age masking at under 18 and over 89, day intervals not dates, public tier omits birth year and sequencing year | Live cBioPortal plus Synapse download | Contact the coordinating center; no in-product path |
| FoundationInsights | "Genomic criteria", natural-language search; filter set not published | Patients (marketing) | "De-identified"; no method or floor published | Live, cloud | Ordering portal and EMR feed for own patients |
| Caris CODEai | Clinical, pathological, molecular, therapy, survival | Patients or cases (marketing) | "Fully de-identified and HIPAA-compliant"; no method or floor published | Live, web | POA letter of intent; provider portal for own patients |
| Tempus Lens | Diagnosis, variant genes, modality, drug class, temporal logic | Patient records | HIPAA expert determination; no floor published | Live, web, LLM query builder | Feasibility request reviewed by Tempus; Hub and Tempus One for own patients |
| Flatiron CGDB | No self-serve UI; licensed datasets and a trusted research environment | Patients | Expert determination, third-party token linkage, cohorts of 5 or fewer shown as "≤5", birth year adjusted at 85 and over | Periodic refresh, analysis in situ | None by design |
| NCI GDC | Program, project, site, diagnosis, demographics, stage, treatment, biospecimen, mutated gene, specific mutation | Cases; files in the repository | None on counts; ages capped at 90; identifying data in a controlled tier | Live REST API | dbGaP plus eRA Commons plus a data access committee |
| TriNetX | Demographics, diagnoses, procedures, medications, labs, genomic tests, notes | Patients per site and total | Counts of 10 or fewer shown as 10; larger counts rounded up to the nearest 10; expert determination | Live, federated appliances | TriNetX Connect to the site; the site re-identifies locally |
| i2b2 | Ontology concepts, AND across groups, OR within, exclusion, dates, occurrence, values | Patients, patient sets, encounter sets | Role-based: true count of 3 or less returned as 0, Gaussian noise sigma 1.32, lockout after 7 identical queries in 30 days | Live SQL | Role upgrade to DATA_LDS, DATA_DEID or DATA_PROT |
| SHRINE | i2b2 query broadcast to sites | Patients per site plus sum | 4.x: sigma 1.33, "less than 3", no rounding; audit digest to a data steward; rate limits; lockout removed in 2.0 | Live, federated | Site data administrator runs the local query |
| OHDSI ATLAS | Concept sets, entry events, observation windows, inclusion rules, exit | Persons and records, exact | None on interactive counts; Achilles deletes cells of 5 or fewer from Data Sources; study packages carry `minCellCount` 5 | Live WebAPI plus precomputed Achilles | Inside the institution ATLAS reaches person rows; across sites only aggregates travel |
| Epic Cosmos SlicerDicer | Not publicly documented | Patients | Values 1 to 10 shown as "10 or fewer"; limited data set for counts, expert-determination set for line-level in a locked VM | Live | None; line-level never leaves the portal |

## 1. cBioPortal

| | |
|---|---|
| Filters | Every clinical attribute in the study becomes a chart. Defaults are cancer type, detailed cancer type, survival, mutation count versus fraction genome altered, mutated genes, CNA genes, samples per patient, mutation count, sex, age ([study view customization](https://docs.cbioportal.org/deployment/customization/studyview/)). "Add charts" offers Clinical, Genomic, Gene Specific, Custom Data and X vs Y tabs ([tutorial](https://raw.githubusercontent.com/cBioPortal/cbioportal/master/docs/tutorials/cBioPortal%20Tutorial%201%20Single%20Study%20Exploration.pdf)). The backend filter object lists clinical, gene, structural variant, treatment, genomic profile, generic assay, case list, custom data, clinical event and mutation data filters ([StudyViewFilter.java](https://github.com/cBioPortal/cbioportal/blob/master/src/main/java/org/cbioportal/legacy/web/parameter/StudyViewFilter.java)). |
| Exact protein change | Not in the study view. Gene filters carry gene, CNA type and mutation type or driver status only ([MutationOption.java](https://github.com/cBioPortal/cbioportal/blob/master/src/main/java/org/cbioportal/legacy/web/parameter/MutationOption.java)). OQL in the query box does it: `BRAF: MUT = V600E` for one change, `V600` for a position, and classes such as `TRUNC` and `INFRAME` ([OQL](https://docs.cbioportal.org/user-guide/oql/)). |
| Count unit | Both. The header shows N patients and M samples ([StudyViewPage.tsx](https://github.com/cBioPortal/cbioportal-frontend/blob/master/src/pages/studyView/StudyViewPage.tsx)). Filters resolve to sample identifiers; patient-level attributes are joined to samples for counting ([ClickHouse mapper](https://github.com/cBioPortal/cbioportal/blob/master/src/main/resources/mappers/clickhouse/clinical_data/ClickhouseClinicalDataMapper.xml)). A "samples per patient" chart is on by default. |
| Small-cell | None. Counts of 1 render as 1. The docs assume de-identification before load: "The cBioPortal only contains de-identified clinical data" ([Datasets.md](https://github.com/cBioPortal/cbioportal-manual/blob/master/Datasets.md)). Authentication is SAML, LDAP, Keycloak or OAuth2, with study-level authorization in the portal's own tables ([user authorization](https://docs.cbioportal.org/deployment/authorization-and-authentication/user-authorization/)). No "identified portal" documentation exists. |
| Backend | Live. Java REST API over ClickHouse with precomputed derived tables; MySQL was dropped in v7 ([architecture](https://docs.cbioportal.org/architecture-overview/), [deployment](https://docs.cbioportal.org/deployment/)). |
| To identified data | Nothing in the product. MSK and DFCI run internal instances behind institutional SAML ([SAML](https://docs.cbioportal.org/deployment/authorization-and-authentication/authenticating-users-via-saml/)). |

The interaction pattern is the thing to borrow. "Individual charts can be
used to select a subset of the samples. All charts will then update to
reflect the features of that subset" (tutorial above). Filters from
different charts are ANDed; the applier intersects sample sets one filter
at a time ([StudyViewFilterApplier.java](https://github.com/cBioPortal/cbioportal/blob/master/src/main/java/org/cbioportal/legacy/web/util/StudyViewFilterApplier.java)).
Values within one chart are ORed. Each chart has its own clear button, plus
"Clear All Filters". The whole filter state is one JSON object that also
serialises into the URL as `filterJson` ([FAQ](https://docs.cbioportal.org/user-guide/faq/)),
so a shared link is a cohort definition.

## 2. AACR Project GENIE

| | |
|---|---|
| Browsing | A cBioPortal instance at genie.cbioportal.org, behind Google sign-in, plus download from Synapse after accepting terms ([data page](https://aacrprojectgenie.org/data/)). |
| Cadence | Public releases every January and July; consortium releases monthly in between. Release 20.0-public (July 2026) has over 289,000 samples from over 242,000 patients (same page; [data guide 20.0](https://aacrprojectgenie.org/wp-content/uploads/2026/08/20.0-data_guide.pdf)). |
| Terms | "Users will not attempt to identify or contact individual participants" and "will not redistribute the data without express written permission" (data guide). Synapse enforces it as a managed access requirement with no IRB attachment ([access requirement](https://repo-prod.prod.sagebase.org/repo/v1/entity/syn7222066/accessRequirement)). |
| De-identification | "All data has been de-identified via the HIPAA Safe Harbor Method." Ages and dates are masked over 89 and, at a site's discretion, under 18. Masked fields show "<18", ">89", "withheld" or "cannotReleaseHIPAA". No calendar dates: `INT_CONTACT` and `INT_DOD` are days from birth, `YEAR_CONTACT` and `YEAR_DEATH` are years. Germline variants are removed from every release because of re-identification risk (data guide). |
| Public versus consortium | Birth year, secondary and tertiary race, age at sequencing in days, and sequencing year are marked "Not available for public releases" (data guide). Treatment and outcomes live in the separate BPC cohorts. |
| Count unit | Patients and samples, as in any cBioPortal. |
| Small-cell | None. The data guide's sample filters are quality, privacy (age redaction), temporal and retraction. No minimum count rule is stated. |
| To more data | Sponsored projects by contact ([FAQ](https://aacrprojectgenie.org/faq/)). |

GENIE is the clearest precedent for our de-identification choices: age caps
at 89, year granularity for dates, and a clean split between privacy
filtering before release and the UI, which does no suppression at all.

## 3. Foundation Medicine and Caris portals

Public documentation on both is thin. Several first-party pages could not
be read on 2026-09-08: corpsite.foundationmedicine.com failed at TLS, the
FMI academic-research page returned "Access denied", and the Caris MI
Portal returned a 502. Nothing below is inferred from those pages.

### FoundationInsights and the FMI portal

| | |
|---|---|
| Filters | "A cloud-based analytical platform enabling interactive exploration, visualization, and programmatic access" with natural-language search over "complex genomic criteria" and Python and R access ([data solutions](https://www.foundationmedicine.com/biopharma/data-solutions), [Manifold release](https://www.foundationmedicine.com/press-release/manifold-partnership-foundationinsights)). The actual filter list is not published. |
| Count unit | "More than 800,000 patients" in marketing; whether the UI counts patients or reports is not published. |
| Small-cell | "De-identified" only. No method or floor published. |
| Backend | Live, hosted. |
| Institutional view | Insights launched for biopharma in October 2025 "with plans to launch a customized version for healthcare providers and health systems in 2026". No documentation of that provider version, its cohort views or its terms was found. The May 2026 provider announcement covers trial matching and guidelines, not cohorts ([digital solutions](https://www.foundationmedicine.com/press-release/digital-solutions)). |
| To identified data | For an ordering institution: the portal, EMR integrations, and "transfer of genomic data in multiple formats including VCF, JSON, XML, BAM etc. for research purposes" ([EMR integrations](https://www.foundationmedicine.com/info/detail/online-portal-emr-integrations-and-data-transfers)). That is the XML feed this repo already loads. |

Precedent for FMI data in the open: about 18,000 FoundationOne profiles at
GDC, with clinical and biospecimen data open and short variants controlled
through dbGaP ([GDC FMI page](https://gdc.cancer.gov/about-gdc/contributed-genomic-data-cancer-research/foundation-medicine)).

### Caris CODEai and the Precision Oncology Alliance

| | |
|---|---|
| Filters | "Cohort Designer allows users to easily create unique subsets of patients for analysis based on clinical, pathological, molecular features and therapies" ([CODEai](https://www.carislifesciences.com/research/artificial-intelligence/caris-codeai/)); search over profiling results, demographics, diagnosis, treatment and survival ([launch release](https://www.carislifesciences.com/about/news-and-media/caris-life-sciences-launches-codeai-real-world-clinico-genomic-data-platform-powered-by-artificial-intelligence/)). |
| Count unit | "484,000+ patients" in marketing; UI unit not published. |
| Small-cell | "Fully de-identified and HIPAA-compliant" (launch release). No method or floor published. |
| Backend | Live web application. |
| Access | POA members only, through a Caris medical science liaison; "not yet available to international members" ([POA](https://www.carislifesciences.com/partners/caris-precision-oncology-alliance/)). CU Anschutz's own page describes the workflow as explore CODEai, then a letter of intent ([CU Anschutz Caris page](https://medschool.cuanschutz.edu/colorado-cancer-center/research/research-partners/caris-ai)). |
| Institution-scoped view | No public documentation found for a member seeing only its own patients. No peer-reviewed methods paper describing CODEai was found on PubMed. |

Neither vendor documents an institution-scoped cohort view over the
institution's own tested patients. That gap is what this dashboard fills.

## 4. Tempus Lens

| | |
|---|---|
| Filters | "Patient inclusion/exclusion criteria are represented by filters, a group of which constitute a query"; named filters include primary diagnosis, somatic variant genes, DNA, RNA and biopsy modality, and drug class, with "temporal or complex logical relationships between filters" ([ASCO 2025 abstract](https://www.tempus.com/publications/cohort-builder-in-tempus-lens-querying-a-large-oncology-database-with-generative-ai/)). "9M+ real-world patient cases" ([Lens](https://www.tempus.com/solutions/lens/)). |
| Count unit | Patient records. |
| Small-cell | "Tempus employs an expert determination method" ([tech blog](https://www.tempus.com/tech-blog/The-Tempus-data-pipeline-architecting-the-future-of-precision-medicine/)). No floor or count suppression published. |
| Backend | Live web app with an LLM text-to-query builder; 75.9% of 1,596 beta queries rated accurate or mostly accurate (abstract above). |
| Licensing | The 10-K says Lens serves "clinicians interested in exploring data related both to their own patients and to similarly situated patients from the broader Tempus dataset" and is generally free because it "facilitates data licensing opportunities" ([10-K](https://www.sec.gov/Archives/edgar/data/1717115/000119312526066961/tem-20251231.htm)). |
| To identified data | Feasibility requests are "subject to Tempus' internal review and approval" (Lens page). Ordering providers get results and raw files through Hub, and Tempus One in the EHR offers "rapid filtering of patient incidence by alteration, gene, or diagnoses" ([Tempus One](https://www.tempus.com/solutions/one/)). |

Tempus is the only vendor with a primary-source statement that an ordering
institution sees its own patients as a cohort. How that view is
de-identified or suppressed is not published.

## 5. Flatiron Health and Foundation Medicine CGDB

| | |
|---|---|
| Filters | No self-serve UI. Disease-specific de-identified datasets delivered for analysis, increasingly inside a Flatiron-hosted trusted research environment where data "remains in Flatiron's secure environment and is analyzed in situ" ([Lifebit release](https://resources.flatiron.com/press/lifebit-and-flatiron-health-bring-cutting-edge-research-technology-to-japan-advancing-global-cancer-care-through-real-world-data)). |
| Count unit | Patients ([Singal et al., JAMA 2019](https://jamanetwork.com/journals/jama/fullarticle/2730114)). |
| De-identification | HIPAA expert determination ([privacy notice](https://flatironhealth.legal/privacy)). Linkage uses hashed tokens generated by each party and matched by a third party; the linked database "received new deidentified tokens, preventing relinking to internal identified data sets" (JAMA 2019). |
| Small-cell | "Patient cohorts of 5 or fewer patients are described as less than or equal to 5 (≤5) patients" ([database characterization](https://flatiron.com/database-characterization)). Patients 85 and older "may have an adjusted birth year in the dataset or data reported as not available" ([SEER comparison](https://resources.flatiron.com/publications/comparison-population-characteristics-oncology-databases-seer-npcr-flatironhealth)). Date shifting and year-only dates: not published. |
| Backend | Refreshed every 3 to 6 months (JAMA 2019). |
| To identified data | None by design. Studies need IRB approval with a consent waiver (JAMA 2019). |

This is the only vendor number found: a display floor of "≤5" on a
de-identified dataset, plus a birth-year adjustment at 85 rather than the
Safe Harbor 89.

## 6. NCI GDC Data Portal

| | |
|---|---|
| Filters | Program, project, disease type, primary diagnosis, primary site, sex at birth, race, ethnicity, age at diagnosis, vital status, stage, grade, year of diagnosis, treatment, exposure, biospecimen, mutated gene, somatic mutation, data availability, and any indexed property through "Add a Custom Filter" ([cohort_builder.json](https://github.com/NCI-GDC/gdc-frontend-framework/blob/develop/packages/core/src/features/cohort/data/cohort_builder.json), [Cohort Builder](https://docs.gdc.cancer.gov/Data_Portal/Users_Guide/cohort_builder/)). Gene and variant tables show affected cases in the cohort and across GDC ([Mutation Frequency](https://docs.gdc.cancer.gov/Data_Portal/Users_Guide/mutation_frequency/)). |
| Count unit | Cases. Cards sort "by the number of cases based on current filters"; the cohort bar shows cases. The repository counts files ([Repository](https://docs.gdc.cancer.gov/Data_Portal/Users_Guide/Repository/)). |
| Small-cell | None on counts. "Individuals over 89 will all appear as 90 years old" ([age FAQ](https://gdc.cancer.gov/content/i-only-see-patients-ages-90-years-or-less-gdc-why)). Open data is "high level genomic data that is not individually identifiable, as well as most clinical and all biospecimen data elements"; controlled data is raw sequence, germline variants and "certain clinical data elements" ([access processes](https://gdc.cancer.gov/access-data/data-access-processes-and-tools)). |
| Backend | Live REST API; a query-defined cohort grows automatically on the next release (Cohort Builder page). |
| Cohort persistence | Saved cohorts persist in the browser only; export is a list of case UUIDs and "does not preserve the custom queries used to filter for those cases" (Cohort Builder page). |
| To identified data | eRA Commons account, dbGaP authorization per project, data access committee approval, then token download ([controlled access](https://gdc.cancer.gov/access-data/obtaining-access-controlled-data)). |

GDC shows that exact counts over open de-identified data are the norm when
the identifying material sits in a separate controlled tier.

## 7. TriNetX, i2b2 and SHRINE

### TriNetX

| | |
|---|---|
| Filters | Demographics, diagnoses, procedures, medications, labs, and "tumor registry and molecular genomic data" with HGNC genes and HGVS variants ([Topaloglu and Palchuk 2018](https://www.trinetx.com/wp-content/uploads/2018/05/JCO-Clinical-Cancer-Informatics-2018-Topaloglu.pdf), read from a web.archive.org capture because trinetx.com returns 404), plus facts from clinical notes ([features](https://trinetx.com/solutions/live-platform/features/)). |
| Count unit | Patients. "The first action is to count the patients who conform to these criteria"; only "statistical results" leave the site appliance (2018 paper). |
| Small-cell | Quoted from the 2018 paper: "for Pharma-initiated query results, all HCO patient counts are rounded to the next 10"; "total patient counts greater than 10 are rounded up to the nearest 10"; "when a query returns a patient count on a term and the patient count is ≤ 10, results shows the count as 10". The expert determination summary states "a minimum threshold on the number of participants when returning aggregate query results" so "no query directly returns a value smaller than 10" ([Malin 2020](https://trinetx.com/wp-content/uploads/2021/12/TriNetX-Empirical-Summary-by-Brad-Malin-2020.pdf), archived copy). Expert determination refreshed May 2025 ([publication guidelines](https://trinetx.com/real-world-resources/case-studies-publications/trinetx-publication-guidelines/)). |
| Query logging and lockout | The application shows each user's query history (2018 paper). Server-side audit and any repeated-query lockout: not verified. The paper's stated defence against query series is rounding, not lockout. |
| Backend | Live, federated appliances behind each site's firewall. |
| To identified data | TriNetX Connect routes a study to the site; re-identification happens only inside the site (2018 paper). |

### i2b2

| | |
|---|---|
| Filters | Ontology items ORed within a group, groups ANDed, with date ranges, "Occurs > N times", exclusion groups, numeric and text value constraints, and temporal sequences ([Query Tool](https://community.i2b2.org/wiki/display/webclient/3.+Query+Tool), [temporal constraints](https://community.i2b2.org/wiki/display/webclient/Temporal+and+Panel+Timing+Constraints)). |
| Count unit | Patients; patient sets and encounter sets for higher roles. The database keeps both `SET_SIZE` (possibly obfuscated) and `REAL_SET_SIZE` ([CRC architecture](https://www.i2b2.org/software/files/PDF/current/CRC_Architecture.pdf)). |
| Roles | `DATA_OBFSC` gets obfuscated counts and a query limit; `DATA_AGG` exact counts; `DATA_LDS` a limited data set; `DATA_DEID` all de-identified fields; `DATA_PROT` identified data ([user roles](https://community.i2b2.org/wiki/display/ServersideArchitectureHome/User+Roles)). "All queries and retrieval of patient data is stored for auditing purposes" (CRC architecture). |
| Backend | Live SQL over a star schema. |
| To identified data | The same query re-run under a higher role returns patient sets and rows. Role assignment is administrative; the IRB or honest-broker policy sits outside the software. |

The obfuscation parameters, from `crc.properties`
([lockout properties](https://community.i2b2.org/wiki/display/getstarted/10.4.4.2.4+Setfinder+Query+-+Lockout+Properties),
[source](https://github.com/i2b2/i2b2-core-server/blob/master/edu.harvard.i2b2.crc/etc/spring/crc.properties)):

| Property | Default | Meaning |
|---|---|---|
| `lockout.setfinderquery.count` | 7 | attempts at the same query before lockout; -1 disables |
| `lockout.setfinderquery.day` | 30 | window for counting repeats |
| `lockout.setfinderquery.zero.count` | -1 | zero-size results do not count toward lockout |
| `setfinderquery.obfuscation.count.sigma` | 1.323 | Gaussian standard deviation added to the patient count |
| `setfinderquery.obfuscation.breakdowncount.sigma` | 1.6 | same for breakdown counts (sex, race, age) |
| `setfinderquery.obfuscation.minimum.value` | 3 | "if the real set size is 3 or less then a count of zero will be returned" |

The noise is Box-Muller Gaussian from `SecureRandom`, rounded and added to
the true count, forced non-negative
([GaussianBoxMuller.java](https://github.com/i2b2/i2b2-core-server/blob/master/edu.harvard.i2b2.crc/src/server/edu/harvard/i2b2/crc/dao/setfinder/GaussianBoxMuller.java)).
The web client shows "+/- 3" next to every obfuscated count; that string is
hard-coded in the client.

### SHRINE

SHRINE adds a second layer at each site's adapter and has changed its mind
about lockout. Version 1.22 (2017) rounded counts to the nearest 5 with a
"+/- 10" clamp, raised sigma to 6.5, added an audit digest to a data steward
"once every 30 queries per researcher or 30 days", rate-limited a researcher
to 10 queries per minute and 200 per workday, and warned that lockout would
be removed ([1.22.8](https://open.catalyst.harvard.edu/wiki/display/SHRINE/SHRINE+1.22.8)).
The upgrade guide states the rationale: "The default values force a
nefarious researcher to run about 30 queries to identify an individual
patient, and an additional 30 queries per fact they wish to verify"
([1.22.8 upgrade](https://open.catalyst.harvard.edu/wiki/pages/viewpage.action?pageId=23986702)).
Version 2.0 removed count-based lockout and stopped recording the true count
([2.0.0 notes](https://harvardcatalyst.atlassian.net/wiki/spaces/SHRINE/pages/166887745/2.0.0+Release+Notes)).

Current defaults ([4.5 webclient help](https://harvardcatalyst.atlassian.net/wiki/spaces/SHRINE/pages/904298497/SHRINE+4.5+Webclient+Help)):

| Parameter | Default | Display |
|---|---|---|
| `setSizeObfuscation` | on | |
| `sigma` | 1.33 | |
| `binSize` | 1 | no rounding |
| `Clamp` | 3 | "+/-3" beside each count |
| `lowLimit` | 3 | "Less than 3 patients" |

The escalation path is organisational: a site data administrator runs the
identified i2b2 query locally, and ACT Phase Two requires `DATA_LDS` "to
generate a table of patients to review" ([ACT Phase Two](https://community.i2b2.org/wiki/display/ACT/Phase+Two+Software)).

## 8. OHDSI ATLAS

| | |
|---|---|
| Definition model | A cohort is "a set of persons who satisfy one or more inclusion criteria for a duration of time". Concept sets, an entry event, continuous observation before index, inclusion rules phrased as inclusion, an exit strategy, and era collapse ([Book of OHDSI, Cohorts](https://ohdsi.github.io/TheBookOfOhdsi/Cohorts.html)). Definitions are Circe JSON rendered to SQL per source. |
| Count unit | Persons and records side by side, with an attrition report per inclusion rule ([cohort manager](https://raw.githubusercontent.com/OHDSI/Atlas/master/js/pages/cohort-definitions/cohort-definition-manager.html)). |
| Small-cell | Achilles `smallCellCount` default 5: "cells with small counts (<= smallCellCount) are deleted" ([Achilles reference](https://ohdsi.github.io/Achilles/reference/achilles.html)); the SQL keeps `count_value > @smallCellCount` ([merge SQL](https://raw.githubusercontent.com/OHDSI/Achilles/main/inst/sql/sql_server/analyses/merge_achilles_tables.sql)). Cohort pathways have a `minCellCount` (UI default 0, options 1 to 10) ([PathwayAnalysis.js](https://raw.githubusercontent.com/OHDSI/Atlas/master/js/pages/pathways/PathwayAnalysis.js)). CohortDiagnostics `minCellCount` default 5 ([executeDiagnostics](https://ohdsi.github.io/CohortDiagnostics/reference/executeDiagnostics.html)). Interactive cohort generation counts are exact, even 1. |
| Backend | Achilles results are precomputed; cohort generation, incidence and characterization run live in WebAPI ([Data Quality](https://ohdsi.github.io/TheBookOfOhdsi/DataQuality.html)). |
| Network model | "Data remains at the site behind a firewall. No patient-level data pooling occurs across network sites. Only aggregate results are shared." Thresholds are the site's job: each analyst must "review these thresholds and ensure it follows local governance policies" ([Network Research](https://ohdsi.github.io/TheBookOfOhdsi/NetworkResearch.html)). Strategus packages the analysis as JSON and modules write CSV results; it did not change the trust model ([Strategus](https://ohdsi.github.io/Strategus/articles/IntroductionToStrategus.html)). |
| Genomics | The OMOP Genomic vocabulary aggregates CGI, CIViC, ClinVar, JAX, NCIt and OncoKB. Mapping 5,466 FoundationOne significant short variants at Northwestern reached 15% coverage by name and 5% by HGVS ([Gurley 2022 poster](https://www.ohdsi.org/wp-content/uploads/2022/10/25-Michael-Gurley_Mapping-variants-of-known-significance-to-the-OMOP-Genomic_2022-symposium-Asieh-Golozar.pdf)). The Oncology WG genomics page is under construction ([OncologyWG](https://ohdsi.github.io/OncologyWG/genomics.html)). |

Two lessons. The floor is applied where data leaves the institution, not in
the analyst's own tool. And OMOP Genomic is not ready as a vocabulary layer
for vendor reports; the 15% figure was measured on the same FMI feed we load.

## 9. Epic Cosmos and small-cell policy

### Epic Cosmos and SlicerDicer

Epic UserWeb is behind a customer login, so the SlicerDicer manual could
not be checked. Two Epic-authored papers state the rule. Cosmos research
runs "on the HIPAA limited data set via a secure web portal that includes
data query and visualization tools that mask data for any cell counts under
11" ([Noel and Bartelt 2023](https://www.jscdm.org/article/id/246/)). SlicerDicer
"reports values 1 to 10 as '10 or fewer,' and does not permit access to
line-level data" ([Howat et al. 2026](https://pmc.ncbi.nlm.nih.gov/articles/PMC13404524/)).
Line-level work happens on an expert-determination dataset in a locked
virtual machine from which "raw data is programmatically prevented from
being exported" (Noel and Bartelt). "All actions in Cosmos are audited"
([governance](https://cosmos.epic.com/governance/)). So Epic uses a hard
floor of 11 with a fixed display string, no noise, on a live query.

### Where the thresholds come from

| Policy | Rule | Source |
|---|---|---|
| CMS cell suppression | No cell "with a size of 1-10 will be used in publication", no percentages that let a 1 to 10 cell be derived, zero allowed; complementary suppression of another cell is required | [CMS LDS DUA](https://www.cms.gov/files/document/lds-dua-terms-and-conditions.pdf), [ResDAC](https://www.resdac.org/articles/cms-cell-size-suppression-policy) |
| NCHS Research Data Center | "Collapse variable categories if any category has a frequency of less than 5"; otherwise asterisk cells under 5 | [NCHS RDC output](https://www.cdc.gov/rdc/output/index.html) |
| NCHS proportions standard | Reliability, not confidentiality: suppress on denominators under 30 or wide confidence intervals | [Series 2 No. 175](https://www.cdc.gov/nchs/data/series/sr_02/sr02_175.pdf) |
| HIPAA Safe Harbor | Dates to year, ages over 89 to "90 or older", ZIP to three digits; no numeric cell threshold anywhere in the rule | [45 CFR 164.514](https://www.govinfo.gov/content/pkg/CFR-2023-title45-vol2/xml/CFR-2023-title45-vol2-sec164-514.xml) |
| FCSM Working Paper 22 | "Some agencies require at least 5 respondents in a cell, while others require 3"; linear sensitivity rules on counts reduce to a threshold of 3 | [WP22](https://nces.ed.gov/FCSM/pdf/SPWP22_rev.pdf) |
| US Census FSRDC | Cell sizes "must be at least three"; 10, 20 and 100 for IRS data by geography | [Disclosure avoidance handbook](https://www2.census.gov/adrm/FSRDC/Resources/FSRDC-Disclosure-Avoidance-Methods-Handbook.pdf) |
| UK GSS administrative tables | Counts of 1 or 2 "ought to be considered potentially disclosive"; threshold of 3 | [GSS guidance 2014](https://gss.civilservice.gov.uk/wp-content/uploads/2018/03/Guidance-for-tables-produced-from-administrative-sources-4.pdf) |
| ONS births and deaths | Suppress under 3, round to base 3 or 5; for online extraction tools "a minimum cell count equal to five is suggested"; "small numbers, even unique cases, are not necessarily disclosive" | [ONS policy](https://www.ons.gov.uk/methodology/methodologytopicsandstatisticalconcepts/disclosurecontrol/policyonprotectingconfidentialityintablesofbirthanddeathstatistics) |
| ONS Secure Research Service | Outputs checked against "a low count threshold of 10"; zero permitted | [DfE SDC policy](https://assets.publishing.service.gov.uk/media/69dcee3aeb7e7bc5651702be/Statistical_disclosure_control_policy_for_DfE_data_-_Office_for_National_Statistics_Secure_Research_Service.pdf) |
| NHS England HES | 1 to 7 shown as "*", the rest rounded to 5 | not verified; the page returned 403 |
| Statistics Canada census | Random rounding to base 5; statistics on fewer than 4 records suppressed; areas under 40 people suppressed | [2011 confidentiality](https://www12.statcan.gc.ca/census-recensement/2011/ref/DQ-QD/conf-eng.cfm) |
| NAACCR CiNA public use | "Automatically suppressed for counts less than 6 based on potentially linkable variables (registry, sex, age, race, race/ethnicity, year of diagnosis and site)" | [CiNA](https://www.naaccr.org/cina-public-use-data-set/) |
| SEER and US Cancer Statistics | Statistics on fewer than 16 cases not shown, for reliability and "to protect the confidentiality of patients" | [USCS suppression](https://www.cdc.gov/united-states-cancer-statistics/technical-notes/suppression.html), [SEER FAQ](https://seer.cancer.gov/data/faqs.html) |
| NIH Genomic Data Sharing | Aggregate allele frequencies moved to controlled access in 2008 after Homer et al., and back to unrestricted for most studies in 2019 unless a study is designated sensitive; no numeric threshold | [NOT-OD-19-023](https://grants.nih.gov/grants/guide/notice-files/NOT-OD-19-023.html), [NHGRI FAQ](https://www.genome.gov/about-nhgri/Policies-Guidance/Data-Sharing-Policies-and-Expectations/GSR-update-FAQs) |

Reading the table: the rules cluster at "hide 1 to 4 or 1 to 5" (statistical
agencies, Achilles, NCHS, NAACCR, Flatiron) and "hide 1 to 10" (CMS, Epic,
TriNetX, ONS SRS). No policy uses 10 as a floor in the sense "10 shown, 9
hidden". Every real policy with a hard floor also demands complementary
suppression, because a floor alone is defeated by subtracting two cells.
HIPAA itself sets no cell threshold; the number is always an agency or
vendor choice.

## What applies to us

Each item names the precedent and states a recommendation for the cohort
API in `COHORT_TOOL.md` and the dashboard pages.

**Count patients, show reports beside them.** cBioPortal's header shows
patients and samples together, GDC counts cases, TriNetX and i2b2 count
patients, ATLAS shows persons and records. Nobody counts reports as the
headline. Keep `patients` as the primary number and `reports` as the second
card, as the design already says.

**Floor at 5, not 11, and say why.** The 5 floor has direct precedents in
Achilles (`smallCellCount` 5), NCHS RDC, NAACCR (under 6), ONS's advice for
online tools, and Flatiron's "≤5". The 11 floor is CMS and Epic Cosmos and
would be the choice if the data were Medicare claims or if Cosmos were the
benchmark reviewers expect. Our data are vendor reports under DUAs, the
audience is authenticated institutional staff, and at 5,400 patients an 11
floor would hide most of the per-year and protein-change cells the
feasibility question needs (`COHORT_TOOL.md` section b shows disease by
gene by year already keeps only 30% at 5). Keep 5, cite the precedents in
the page footnote, and keep `min_cell` in the response `meta` so a later
change is one setting.

**Hard floor, not noise.** i2b2 and SHRINE add Gaussian noise because they
run on identified data and serve outside users. SHRINE moved from tight
noise to heavy noise plus rounding and back to light noise, and dropped
lockout, which shows how hard the setting is to get right. Epic, CMS,
Flatiron, Achilles and GDC use a hard floor or plain deletion. Our data are
already de-identified with shifted dates, so a floor is the norm for our
tier. Keep exact counts at 5 and above; leave `COHORT_ROUND` available but
default to 1.

**Secondary suppression on every breakdown.** CMS requires it explicitly,
ResDAC's worked example shows it, and Achilles sidesteps it by deleting rows
rather than masking. The design's rule (null the next-smallest cell when
exactly one cell is hidden and the total is shown) is the CMS complementary
rule. Keep it, and keep the test that no integer 1 to 4 appears in any
response.

**Log every query with the user, keep the true count, review by digest.**
i2b2 stores `REAL_SET_SIZE` and audits every query. SHRINE emails a data
steward after 30 queries or 30 days per researcher and rate-limits to 10 per
minute and 200 per day. Epic audits all Cosmos actions. Our design's JSON
line per request with email, parameters and pre-suppression count matches
i2b2. Add a monthly `journalctl` summary per email to Sean, which is
SHRINE's digest at zero cost.

**Do not build a repeated-query lockout.** i2b2's lockout after 7 identical
queries in 30 days is the only one still shipping, and SHRINE removed its
own in 2.0 in favour of audit and rate limits. TriNetX never had one and
relies on rounding. With an audience that authenticates by email and could
read the chart directly, the audit log plus Traefik's rate limit is the
SHRINE 2.0 position and is enough. `COHORT_TOOL.md` should stop citing
TriNetX as a lockout precedent; its defence is round-up-to-10.

**Year granularity for dates, age capped at 89, no calendar dates in any
response.** GENIE ships intervals in days from birth and years only, masks
ages over 89, and omits sequencing year from the public tier. GDC caps age
at 90. Flatiron adjusts birth year at 85. Our per-patient date shift of
plus or minus 182 days plus year-only output is stronger than GENIE's public
tier on dates and equal on age. Keep year as the only time unit the API
returns, and keep the sentence on the page that dates are shifted.

**No allele frequencies.** NIH moved aggregate genomic summary results to
controlled access in 2008 because they can reveal participation. Our
responses return patient counts per gene and per protein change, not per
allele, so the Homer attack does not apply. Do not add VAF distributions or
per-variant read-level summaries to the cohort API; those stay on the
Biomarkers page as suppressed aggregates built at load time.

**Borrow cBioPortal's study view for the page.** Every breakdown chart is
also a filter; clicking a bar narrows the cohort and every other chart
redraws; filters from different charts AND, values within one chart OR;
each chart has its own clear control; the whole filter state is one JSON
object that is also the URL. The design's "copy link" button already makes
the query string the cohort definition. Go one step further on the Cohort
page: make the disease, vendor and class, sex and age bars clickable so
they append to the query, with a chip row showing active filters and a
clear-all. Keep the per-year chart as display only, since clicking a year
would create sub-floor cells. GDC's lesson is the negative one: its export
is a case list that "does not preserve the custom queries", so users lose
their definition. Ours is the URL.

**Exact protein change belongs in the query, not the chart.** cBioPortal
does not offer G12C as a study-view chart; it is OQL in the query builder.
That matches the design: `aa` is a parameter that appears only once one
gene is chosen, and the Genes page (#18) handles the static view with
sub-floor changes pooled as "other".

**Escalation from counts to identified data stays inside the institution
and goes through the IRB.** No system in the survey moves a user from a
count to identified rows inside the tool. i2b2 changes the user's role,
SHRINE and TriNetX hand the query to the site's data administrator, GDC
uses dbGaP and a data access committee, Flatiron makes relinking
impossible. The phase 2 "Request this cohort" button, which mails Sean the
filter definition as the entry to issue #16, is the i2b2 and SHRINE
pattern: the honest broker re-runs the same definition against the PHI file
under an IRB protocol. Record the API's query string in the request so the
identified pull is the same cohort the user saw.

**Reject a static bigger cube and reject OMOP Genomic as a vocabulary
layer.** ATLAS keeps its precomputed Achilles layer only for data
characterisation and runs cohorts live; that is the same split the design
reached from the 2.6% measurement. OMOP Genomic mapped 15% of FoundationOne
significant variants at Northwestern, so vendor gene and HGVS strings
remain the vocabulary here.

**Name the vendor gap on the page.** No public documentation shows Caris or
Foundation Medicine giving an institution a cohort view of its own tested
patients, and Tempus documents the idea but not its suppression. A one-line
"why this exists" note on the Overview page is cheap and true.

## Not verified

Items the survey could not confirm against a primary source, so they should
not be cited as fact:

- Any minimum count rule inside FoundationInsights, Caris CODEai or Tempus
  Lens.
- A provider-facing FoundationInsights with institution-scoped cohorts; FMI
  said "2026" in October 2025 and nothing since.
- TriNetX server-side audit or repeated-query lockout.
- SHRINE's old `adapterLockoutAttemptsThreshold` default of 10.
- NHS England's "1 to 7 plus round to 5" rule; the page returned 403.
- Epic SlicerDicer's filter model; UserWeb is not public.
- The OCR de-identification guidance text; hhs.gov returned 403, so the
  regulation text at govinfo was used instead.
- The original 2008 NIH notice moving aggregate genomic data to controlled
  access; only the 2019 notice that recounts it was read.
