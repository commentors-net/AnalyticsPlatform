"""Explicit, resumable app deletion confined to the analytics namespace.

No automatic worker runs. Each confirmed DELETE handles at most 100 documents.
App/tombstone transaction guards prevent concurrent platform writes/resurrection.
"""
import base64
import hashlib
import hmac
import itertools
import json
import re
import time
import uuid
from datetime import datetime, timezone

from api.app.core.config import settings


def _valid_id(app_id):
    if not re.fullmatch(r"[a-z0-9_-]{3,64}", app_id):
        raise ValueError("Invalid application identifier")


def _valid_namespace(repo):
    if not re.fullmatch(r"analytics_[a-z0-9_]{0,48}", repo.db.prefix):
        raise ValueError("Deletion requires a dedicated analytics_ namespace")


def _token(data):
    encoded = base64.urlsafe_b64encode(json.dumps(data, sort_keys=True).encode()).decode()
    signature = hmac.new(settings.ANALYTICS_JWT_SECRET.encode(), b"app-delete-v1:" + encoded.encode(), hashlib.sha256).hexdigest()
    return encoded + "." + signature


def _verify(token, app_id, created_at):
    try:
        encoded, _ = token.rsplit(".", 1)
        data = json.loads(base64.urlsafe_b64decode(encoded))
        if (not hmac.compare_digest(_token(data), token) or data["app_id"] != app_id
                or data["created_at"] != created_at or data["expires"] < time.time()):
            raise ValueError()
    except Exception:
        raise ValueError("Deletion preview expired or mismatched; load a fresh preview")


def _tree(ref, app_id, scope, depth=0):
    if depth > 16 or not (ref.path == scope or ref.path.startswith(scope + "/")):
        raise ValueError("Unexpected deletion scope; cleanup stopped")
    snap = ref.get()
    if snap.exists and snap.to_dict().get("app_id", app_id) != app_id:
        raise ValueError("Conflicting application ownership; cleanup stopped")
    for collection in ref.collections():
        for child in collection.list_documents(page_size=100):
            yield from _tree(child, app_id, scope, depth + 1)
    if snap.exists:
        yield ref


def inventory(repo, app_id):
    """Yield only known app-owned paths; never enumerate/delete global collections."""
    _valid_id(app_id)
    _valid_namespace(repo)
    for label, collection in (("keys", repo.db.api_keys_col), ("permissions", repo.db.permissions_col), ("idempotency", repo.db.idempotency_col)):
        for snap in collection.where("app_id", "==", app_id).stream():
            for ref in _tree(snap.reference, app_id, snap.reference.path):
                yield label, ref
    for env in ("live", "test"):
        root = repo.db.client.collection(f"{repo.db.prefix}data").document(f"{app_id}_{env}")
        for ref in _tree(root, app_id, root.path):
            label = f"{env}_" + (ref.path[len(root.path) + 1:].split('/')[0] if ref.path != root.path else "root")
            yield label, ref
    root = repo.db.apps_col.document(app_id)
    for collection in root.collections():
        for child in collection.list_documents(page_size=100):
            for ref in _tree(child, app_id, root.path):
                yield "app_subdocuments", ref


def preview(repo, app_id):
    _valid_id(app_id)
    _valid_namespace(repo)
    app = repo.get_app(app_id)
    if not app:
        raise LookupError("Application not found")
    if app.get("app_id") != app_id:
        raise ValueError("Conflicting catalog ownership; preview stopped")
    counts = {}
    # Bound preview work; explicitly report lower-bound counts when larger.
    rows = list(itertools.islice(inventory(repo, app_id), 2001))
    for category, _ in rows[:2000]:
        counts[category] = counts.get(category, 0) + 1
    return {
        "app_id": app_id, "name": app["name"], "status": app["status"],
        "counts": counts, "truncated": len(rows) > 2000,
        "catalog_documents": 1,
        "retained": "Immutable audit logs, account records, backups and a minimal retired-ID marker are retained. Other applications are untouched.",
        "notice": "Counts are a snapshot (at least these counts if truncated). Confirmation deletes this application's LIVE and TEST data, permanently retires its ID and blocks new collection. Partial cleanup can be resumed.",
        "preview_token": _token({"app_id": app_id, "created_at": app["created_at"], "expires": time.time() + 600}),
    }


def delete_step(repo, app_id, confirmation, token, actor_id, limit=100):
    _valid_id(app_id)
    _valid_namespace(repo)
    if confirmation != app_id:
        raise ValueError("Type the exact application identifier to confirm permanent deletion")
    app_ref = repo.db.apps_col.document(app_id)
    job_ref = repo.db.deletions_col.document(app_id)

    def freeze(tx):
        app = app_ref.get(transaction=tx)
        job = job_ref.get(transaction=tx)
        if not app.exists:
            if job.exists and job.to_dict().get("state") == "deleted":
                _verify(token, app_id, job.to_dict()["created_at"])
                return True
            raise LookupError("Application not found")
        data = app.to_dict()
        if data.get("app_id") != app_id:
            raise ValueError("Conflicting catalog ownership; cleanup stopped")
        _verify(token, app_id, data["created_at"])
        if job.exists and (job.to_dict().get("state") != "deleting" or job.to_dict().get("created_at") != data["created_at"]):
            raise ValueError("Application identifier is retired or deletion generation changed")
        if not job.exists:
            tx.create(job_ref, {"app_id": app_id, "created_at": data["created_at"], "state": "deleting"})
        tx.update(app_ref, {"status": "DELETING"})
        return False
    if repo.db.run_transaction(freeze):
        return {"status": "deleted", "deleted_this_request": 0}

    # Validate this entire bounded step before deleting any reference in it.
    rows = list(itertools.islice(inventory(repo, app_id), limit + 1))
    for _, ref in rows[:limit]:
        ref.delete()
    if len(rows) > limit:
        return {"status": "deleting", "deleted_this_request": limit, "message": "Cleanup is not complete. Resume deletion to continue."}

    audit_ref = repo.db.audit_logs_col.document(uuid.uuid4().hex)
    def finish(tx):
        app = app_ref.get(transaction=tx)
        job = job_ref.get(transaction=tx)
        if not app.exists and job.exists and job.to_dict().get("state") == "deleted":
            return  # Another confirmed step completed the same generation.
        if not app.exists or not job.exists or app.to_dict().get("status") != "DELETING":
            raise ValueError("Deletion state changed; cleanup stopped")
        tx.delete(app_ref)
        tx.update(job_ref, {"state": "deleted"})
        tx.set(audit_ref, {"action": "DELETE_APPLICATION", "user_id": actor_id, "resource_type": "application", "resource_id": app_id, "timestamp": datetime.now(timezone.utc).isoformat(), "details": {"environments": ["live", "test"]}})
    repo.db.run_transaction(finish)
    return {"status": "deleted", "deleted_this_request": len(rows)}
