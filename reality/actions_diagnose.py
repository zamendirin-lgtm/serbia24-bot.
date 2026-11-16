"""Diagnostic of scheduled GitHub workflow runs using job-scoped read-only token."""
import os
import requests

repo=os.environ.get("GITHUB_REPOSITORY","zamendirin-lgtm/serbia24-bot.")
token=os.environ.get("GH_TOKEN","")
base="https://api.github.com/repos/"+repo
headers={"Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
if token:
    headers["Authorization"]="Bearer "+token
try:
    r=requests.get(base+"/actions/workflows/reality.yml/runs",
                   params={"event":"schedule","per_page":20},headers=headers,timeout=25)
    print("ACTIONS_SCHEDULE_API_STATUS",r.status_code)
    r.raise_for_status()
    data=r.json()
    print("ACTIONS_SCHEDULE_TOTAL",data.get("total_count"))
    runs=data.get("workflow_runs",[])
    for run in runs[:12]:
        print("ACTIONS_SCHEDULE_RUN",run.get("id"),run.get("created_at"),
              run.get("status"),run.get("conclusion"),run.get("html_url"))
    for run in runs[:3]:
        rr=requests.get(base+"/actions/runs/"+str(run["id"])+"/jobs",
                        headers=headers,timeout=20)
        print("ACTIONS_JOBS_HTTP",run["id"],rr.status_code)
        if rr.ok:
            for job in rr.json().get("jobs",[])[:3]:
                print("ACTIONS_SCHEDULE_JOB",job.get("id"),job.get("name"),
                      job.get("conclusion"),job.get("html_url"))
except (requests.RequestException,ValueError) as exc:
    print("ACTIONS_DIAGNOSTIC_ERROR",type(exc).__name__,str(exc)[:150])
