---
name: deploy-service
description: Deploy the service under test to its dedicated TEST namespace by triggering its Azure DevOps pipeline, then wait for the Kubernetes rollout and the health endpoint. Use in Phase C when deployed=no. Deployment only ever happens through the pipeline, never kubectl.
---
# deploy-service

Inputs from `variables.json`: `deploy_pipeline`, `deploy_branch` (default:
branch under test), `k8s_namespace`, `k8s_deployment` (default
`service_name`), `base_url`, `health_path`.

## 1. Record the "before" state (evidence)
```bash
kubectl --context $K8S_CONTEXT_TEST -n <ns> get deploy,pods,svc -o wide > docs/<service>/<run>/deploy/before.txt
kubectl --context $K8S_CONTEXT_TEST -n <ns> get deploy <dep> -o jsonpath='{.spec.template.spec.containers[0].image}'
```

## 2. Trigger the pipeline (ask first — this is a write to Azure DevOps)
Tell the tester: pipeline name/id, project, branch, target namespace. On yes:
- Preferred: `mcp__azure-devops__pipelines_write` action `run_pipeline`
  (project, pipelineId, branch/`refs/heads/<branch>`, template parameters if
  the pipeline needs `environment=test`).
- Fallback: `az pipelines run --org https://dev.azure.com/$ADO_ORG --project $ADO_PROJECT --name <pipeline> --branch <branch>`.
Save the run id and URL to `deploy/pipeline-run.json`.

## 3. Wait for the pipeline
Poll `mcp__azure-devops__pipelines_run` action `get` (or `pipelines_build
get_status`) every 30 s, up to 25 min. On failure: fetch logs
(`pipelines_build_log list` → `get_content`), save to `deploy/pipeline-log.txt`,
STOP the run with a clear message (do not retry automatically).

## 4. Wait for the rollout
```bash
bash scripts/wait_for_ready.sh <ns> <deployment> <base_url><health_path> 600
```
It runs `kubectl rollout status`, then polls the health URL until `UP`, and
saves `deploy/after.txt`, `deploy/describe.txt`, `deploy/events.txt`,
`deploy/startup-log.txt` (first 300 log lines — scan them with
`scripts/scan_logs.py` later; startup logs often leak JDBC passwords).

## 5. Confirm the right build is running
Compare the new image tag/commit with the branch commit (`git rev-parse`
vs image tag or `/actuator/info` `git.commit.id`). Mismatch → WARN in report
and ask whether to continue.

If `deployed = yes`: skip 2–3, run 1 and 4 (health + evidence) and 5.
