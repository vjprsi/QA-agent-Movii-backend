# variables.xlsx — what the repo's `/docs/variables*.xlsx` must contain

Sheet **`variables`** — columns: `key | value | required | category | description`

| key | required | category | notes |
|---|---|---|---|
| service_name | yes | service | matches the deployment/app label in K8s |
| deployed | yes | deploy | `yes` or `no`. `no` ⇒ agent triggers the deploy pipeline |
| deploy_pipeline | if deployed=no | deploy | Azure DevOps pipeline name or id that deploys to TEST |
| deploy_branch | no | deploy | default: the branch under test |
| base_url | yes | service | TEST base URL of the service (via the public LB) |
| health_path | no | service | default `/actuator/health` |
| k8s_namespace | yes | k8s | dedicated TEST namespace of this service |
| k8s_deployment | no | k8s | default = service_name |
| db_host | yes | db | TEST MySQL host |
| db_port | no | db | default 3306 |
| db_schema | yes | db | schema(s) of this service, comma-separated |
| auth_type | yes | auth | `bearer` / `basic` / `apikey` / `oauth2_password` / `none` |
| auth_token_url | if oauth2 | auth | token endpoint |
| client_id / client_secret | if oauth2 | auth | |
| test_msisdn | usually | data | primary test user |
| test_password / test_pin | usually | data | |
| test_otp | no | data | static OTP in TEST if applicable |
| admin_token | no | auth | for privileged endpoints |
| postman_collection | yes | postman | path inside /docs, e.g. `docs/postman/service.postman_collection.json` |
| postman_environment | no | postman | path inside /docs |
| stress_tps_ladder | yes for stress | stress | e.g. `1,3,1,5,2,3` (TPS per step) |
| stress_step_seconds | no | stress | default 60 |
| stress_max_tps | no | stress | default = max of ladder |
| stress_p95_ms | no | stress | SLA, default from environments.json |
| stress_error_rate_max | no | stress | default 0.01 |
| stress_endpoints | no | stress | comma list of Postman request names to load; default: all GETs + listed POSTs |
| log_sensitive_fields | no | security | extra field names to scan for in logs |
| encrypted_db_fields | no | security | `table.column` list that must be ciphertext |
| plaintext_db_fields | no | security | `table.column` list that must be readable |
| public_endpoints | no | security | endpoints allowed without auth |

Sheet **`test_data`** (optional) — one row per test user / entity:
`label | msisdn | password | pin | document_id | account | balance | notes`

Rules the agent follows:
- Missing **required** key → listed in `preflight.md`, tester asked, dependent
  tests marked BLOCKED. The run never aborts because of this.
- Values that look like secrets (`*pass*`, `*pin*`, `*secret*`, `*token*`,
  `*key*`) are masked in every printed output.
- Postman variables (`{{var}}`) in the collection are matched against these
  keys; unresolved `{{var}}` names are reported as missing.
