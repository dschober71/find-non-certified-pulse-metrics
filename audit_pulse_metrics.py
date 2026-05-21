import os
import sys
import requests
import pandas as pd
from typing import List, Dict, Any, Optional
from requests.adapters import HTTPAdapter, Retry
from dotenv import load_dotenv

load_dotenv()

# --- Configuration ---
API_VERSION = "3.24"
BASE_URL = os.getenv("TABLEAU_SERVER", "").rstrip("/")
SITE_CONTENT_URL = os.getenv("TABLEAU_SITE")
PAT_NAME = os.getenv("TABLEAU_PAT_NAME")
PAT_SECRET = os.getenv("TABLEAU_PAT_SECRET")

if not all([BASE_URL, SITE_CONTENT_URL, PAT_NAME, PAT_SECRET]):
    print("ERROR: One or more Tableau environment variables are missing.")
    sys.exit(1)

JSON_HEADERS = {"Accept": "application/json", "Content-Type": "application/json"}

# --- Helper Functions ---
def get_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))
    return session

def sign_in(session: requests.Session) -> Dict[str, Any]:
    url = f"{BASE_URL}/api/{API_VERSION}/auth/signin"
    payload = {
        "credentials": {
            "personalAccessTokenName": PAT_NAME,
            "personalAccessTokenSecret": PAT_SECRET,
            "site": {"contentUrl": SITE_CONTENT_URL},
        }
    }
    resp = session.post(url, json=payload, headers=JSON_HEADERS)
    if resp.status_code != 200:
        raise Exception(f"Sign-in failed: {resp.status_code} {resp.text}")
    return resp.json()["credentials"]

def sign_out(session: requests.Session, token: str):
    url = f"{BASE_URL}/api/{API_VERSION}/auth/signout"
    session.post(url, headers={"X-Tableau-Auth": token})

# --- API Wrappers ---
def get_metric_definitions(session, token) -> List[Dict[str, Any]]:
    print("Fetching metric definitions...")
    url = f"{BASE_URL}/api/-/pulse/definitions?page_size=100"
    headers = {"X-Tableau-Auth": token}
    all_defs = []
    while url:
        resp = session.get(url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f"Failed to fetch metric definitions: {resp.status_code} {resp.text}")
        data = resp.json()
        # API returns key as "metric_definitions", "definitions", or "metricDefinitions"
        defs = data.get("metric_definitions") or data.get("definitions") or data.get("metricDefinitions") or []
        all_defs.extend(defs)
        next_token = data.get("next_page_token")
        url = f"{BASE_URL}/api/-/pulse/definitions?page_size=100&page_token={next_token}" if next_token else None
    print(f"Fetched {len(all_defs)} metric definitions.")
    return all_defs

def get_datasource(session, token, site_id, datasource_luid) -> Optional[Dict[str, Any]]:
    url = f"{BASE_URL}/api/{API_VERSION}/sites/{site_id}/datasources/{datasource_luid}"
    headers = {"X-Tableau-Auth": token, **JSON_HEADERS}
    resp = session.get(url, headers=headers)
    if resp.status_code == 404:
        return None
    if resp.status_code != 200:
        raise Exception(f"Datasource fetch error: {resp.status_code} {resp.text}")
    return resp.json().get("datasource")

def get_metrics_for_definition(session, token, definition_id) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/api/-/pulse/definitions/{definition_id}/metrics?page_size=100"
    headers = {"X-Tableau-Auth": token}
    all_metrics = []
    while url:
        resp = session.get(url, headers=headers)
        if resp.status_code != 200:
            raise Exception(f"Failed to fetch metrics for definition {definition_id}: {resp.status_code} {resp.text}")
        data = resp.json()
        all_metrics.extend(data.get("metrics", []))
        next_token = data.get("next_page_token")
        url = f"{BASE_URL}/api/-/pulse/definitions/{definition_id}/metrics?page_size=100&page_token={next_token}" if next_token else None
    return all_metrics

_user_cache: Dict[str, str] = {}

def get_user_email(session, token, site_id, user_id) -> str:
    if not user_id:
        return ""
    if user_id in _user_cache:
        return _user_cache[user_id]
    url = f"{BASE_URL}/api/{API_VERSION}/sites/{site_id}/users/{user_id}"
    resp = session.get(url, headers={"X-Tableau-Auth": token, **JSON_HEADERS})
    if resp.status_code != 200:
        return user_id
    email = resp.json().get("user", {}).get("name", user_id)
    _user_cache[user_id] = email
    return email

def get_subscriptions_for_metric(session, token, metric_id) -> List[Dict[str, Any]]:
    url = f"{BASE_URL}/api/-/pulse/subscriptions?metric_id={metric_id}&page_size=1000"
    headers = {"X-Tableau-Auth": token}
    resp = session.get(url, headers=headers)
    if resp.status_code != 200:
        raise Exception(f"Failed to fetch subscriptions for metric {metric_id}: {resp.status_code} {resp.text}")
    return resp.json().get("subscriptions", [])

def def_id(md: Dict) -> str:
    return md.get("metadata", {}).get("id") or md.get("id", "")

def def_name(md: Dict) -> str:
    return md.get("metadata", {}).get("name") or md.get("name", "")

def def_certified(md: Dict) -> bool:
    return md.get("certification", {}).get("is_certified", False) or md.get("isCertified", False)

def def_datasource_luid(md: Dict) -> str:
    return (
        md.get("specification", {}).get("datasource", {}).get("id")
        or md.get("datasourceLuid", "")
    )

def def_last_modified(md: Dict) -> str:
    return md.get("metadata", {}).get("last_modified_at") or md.get("lastModifiedAt", "")

# --- Main Logic ---
def main():
    session = get_session()
    creds = sign_in(session)
    token = creds["token"]
    site_id = creds["site"]["id"]
    try:
        metric_defs = get_metric_definitions(session, token)

        # Table 1: Certified metrics with non-certified datasource
        table1 = []
        for md in metric_defs:
            if def_certified(md):
                ds_luid = def_datasource_luid(md)
                if ds_luid:
                    ds = get_datasource(session, token, site_id, ds_luid)
                    if ds and not ds.get("isCertified", False):
                        certified_by_id = md.get("certification", {}).get("modified_by")
                        table1.append({
                            "Metric Definition Name": def_name(md),
                            "Metric Definition ID": def_id(md),
                            "Certified By": get_user_email(session, token, site_id, certified_by_id),
                            "Datasource Name": ds.get("name"),
                            "Datasource Project Path": ds.get("project", {}).get("name"),
                            "Datasource Owner Email": ds.get("owner", {}).get("name"),
                        })
        df1 = pd.DataFrame(table1)
        print("\nTable 1: Certified metrics with non-certified datasource")
        print(df1.to_string() if not df1.empty else "(none)")
        df1.to_csv("certified_metrics_with_noncertified_datasource.csv", index=False)

        # Table 2: Metric definitions with no active subscriptions
        table2 = []
        for md in metric_defs:
            metrics = get_metrics_for_definition(session, token, def_id(md))
            total_subs = sum(
                len(get_subscriptions_for_metric(session, token, m.get("id") or m.get("metadata", {}).get("id")))
                for m in metrics
            )
            if total_subs == 0:
                ds_name = ""
                ds_luid = def_datasource_luid(md)
                if ds_luid:
                    ds = get_datasource(session, token, site_id, ds_luid)
                    ds_name = ds.get("name") if ds else "(unreachable)"
                table2.append({
                    "Metric Definition Name": def_name(md),
                    "Metric Definition ID": def_id(md),
                    "Datasource Name": ds_name,
                    "Number of Metrics": len(metrics),
                    "Last Modified": def_last_modified(md),
                })
        df2 = pd.DataFrame(table2)
        print("\nTable 2: Metric definitions with no active subscriptions")
        print(df2.to_string() if not df2.empty else "(none)")
        df2.to_csv("metric_definitions_with_no_active_subscriptions.csv", index=False)

        # Table 3: Metric definitions with dead or unreachable datasources
        table3 = []
        for md in metric_defs:
            ds_luid = def_datasource_luid(md)
            if not ds_luid:
                table3.append({
                    "Metric Definition Name": def_name(md),
                    "Metric Definition ID": def_id(md),
                    "Datasource ID": "",
                    "Failure Reason": "No datasource linked to metric definition",
                })
                continue
            try:
                ds = get_datasource(session, token, site_id, ds_luid)
            except Exception as e:
                table3.append({
                    "Metric Definition Name": def_name(md),
                    "Metric Definition ID": def_id(md),
                    "Datasource ID": ds_luid,
                    "Failure Reason": str(e),
                })
                continue
            if ds is None:
                table3.append({
                    "Metric Definition Name": def_name(md),
                    "Metric Definition ID": def_id(md),
                    "Datasource ID": ds_luid,
                    "Failure Reason": "Datasource not found (404)",
                })
        df3 = pd.DataFrame(table3)
        print("\nTable 3: Metric definitions with dead or unreachable datasources")
        print(df3.to_string() if not df3.empty else "(none)")
        df3.to_csv("metric_definitions_with_dead_or_unreachable_datasources.csv", index=False)

    finally:
        sign_out(session, token)

if __name__ == "__main__":
    main()
