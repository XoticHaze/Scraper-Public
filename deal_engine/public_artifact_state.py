"""Read bounded state from this public repository's own workflow artifacts."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import tempfile

REPOSITORY = "XoticHaze/Scraper-Public"
ALLOWED = {
    "macbid-deal-engine": "market-values.runtime.json",
    "macbid-public-observations": "macbid-public-observations.json",
    "macbid-public-history-state": "macbid-public-history-state.json",
}

def prior_public_artifacts(name):
    if name not in ALLOWED or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RuntimeError("owning public repository and registered artifact required")
    raw = subprocess.check_output(["gh","api",f"repos/{REPOSITORY}/actions/artifacts?name={name}&per_page=20"],
                                  text=True,timeout=30)
    rows = json.loads(raw).get("artifacts",[])
    current_run = os.environ.get("GITHUB_RUN_ID")
    return sorted([a for a in rows if a.get("name")==name and not a.get("expired")
           and (a.get("workflow_run") or {}).get("head_branch")=="main"
           and str((a.get("workflow_run") or {}).get("id","")).isdigit()
           and str(a["workflow_run"]["id"])!=current_run],
           key=lambda a:a.get("created_at",""),reverse=True)

def read_public_artifact_json(artifact, *, name, max_bytes=30_000_000):
    if name not in ALLOWED or os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise RuntimeError("artifact route not admitted")
    rid=str((artifact.get("workflow_run") or {}).get("id",""))
    if (artifact.get("name")!=name or artifact.get("expired") or not rid.isdigit()
         or rid==os.environ.get("GITHUB_RUN_ID") or (artifact.get("workflow_run") or {}).get("head_branch")!="main"):
        raise RuntimeError("artifact identity not admitted")
    if not 0 < int(artifact.get("size_in_bytes") or 0) <= 25_000_000:
        raise RuntimeError("artifact archive outside bound")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["gh","run","download",rid,"--repo",REPOSITORY,"--name",name,"--dir",tmp],
                       check=True,capture_output=True,timeout=60)
        path=Path(tmp)/ALLOWED[name]
        if not path.is_file() or path.stat().st_size>max_bytes:
            raise RuntimeError("artifact file missing or oversized")
        doc=json.loads(path.read_text())
    if not isinstance(doc,dict):
        raise RuntimeError("artifact must contain JSON object")
    return doc
