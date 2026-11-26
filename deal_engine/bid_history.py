"""Compact, bounded longitudinal observations. Not closing outcomes or arrival estimates."""
from __future__ import annotations
import math
import re
from statistics import median
from deal_engine.historical_reconciliation import lot_key

MAX_POINTS=32
MAX_TRACKS=25000
MAX_AGE=90*86400

def normalize_snapshot(snapshot, scope):
    if snapshot.get("schema")!="macbid-public-observation-v1" or not snapshot.get("coverage_complete"):
        return None
    epoch=snapshot.get("source_epoch_utc")
    if not isinstance(epoch,int) or isinstance(epoch,bool) or epoch<=0:
        return None
    actual=snapshot.get("scope")
    if actual is None:
        actual={"filter":re.sub(r"expected_closing_utc:>\d+","expected_closing_utc:>SCAN_EPOCH",str(snapshot.get("filter_by") or "")),
                "locations":sorted({r.get("auction_location") for r in snapshot.get("observations",[]) if r.get("auction_location")})}
    if actual!=scope:
        return None
    return epoch

def update_bid_history(previous, snapshots, *, scope_id, scope, now):
    """Retain the first and newest 31 actual points per lot; explicit sampling."""
    old=previous if previous.get("scope_id")==scope_id else {}
    tracks={k:{**r,"points":[p for p in r["points"] if p[0]>=now-MAX_AGE]}
            for k,r in old.get("tracks",{}).items()}
    tracks={k:r for k,r in tracks.items() if r["points"]}
    conflicts={k:v for k,v in old.get("conflicts",{}).items() if v>=now-MAX_AGE}
    epochs=sorted({e for e in old.get("snapshot_epochs",[]) if e>=now-MAX_AGE})
    point_drops=int(old.get("point_drops",0))
    track_drops=int(old.get("track_drops",0))
    observations_added=int(old.get("observations_added",0))
    ordered=sorted(((e,s) for s in snapshots if (e:=normalize_snapshot(s,scope)) is not None),key=lambda x:x[0])
    for epoch,snapshot in ordered:
        if epoch>now or epoch<now-MAX_AGE or epoch in epochs or (epochs and epoch<epochs[-1]):
            continue
        seen=set()
        for row in snapshot.get("observations",[]):
            key=lot_key(row)
            ident=[str(row.get(k) or "") for k in ("inventory_id","identity","condition","auction_location")]
            bid=row.get("current_bid")
            if (not all(key) or not all(ident) or not key[0].isdigit() or not re.fullmatch(r"[A-Z0-9-]{1,24}",key[1])
                    or not isinstance(bid,(int,float)) or isinstance(bid,bool) or not math.isfinite(bid) or bid<0 or bid>1_000_000
                    or row.get("source_epoch_utc",epoch)!=epoch):
                continue
            k=":".join(key)
            if k in conflicts:
                continue
            track=tracks.get(k)
            if k in seen or (track and track["identity_fields"]!=ident):
                conflicts[k]=epoch
                tracks.pop(k,None)
                continue
            seen.add(k)
            if track is None:
                track=tracks[k]={"identity_fields":ident,"points":[],"hunt_ids":[]}
            track["hunt_ids"]=sorted(set(row.get("hunt_ids") or []))
            track["points"].append([epoch,round(bid*100)])
            observations_added+=1
            if len(track["points"])>MAX_POINTS:
                track["points"]=track["points"][:1]+track["points"][-(MAX_POINTS-1):]
                point_drops+=1
        epochs.append(epoch)
        if len(tracks)>MAX_TRACKS:
            ordered_keys=sorted(tracks,key=lambda k:(tracks[k]["points"][-1][0],k),reverse=True)
            track_drops+=len(tracks)-MAX_TRACKS
            tracks={k:tracks[k] for k in ordered_keys[:MAX_TRACKS]}
    return {"schema":"macbid-public-bid-history-v1","scope_id":scope_id,
            "snapshot_epochs":epochs,"tracks":tracks,"conflicts":conflicts,
            "point_drops":point_drops,"track_drops":track_drops,"observations_added":observations_added}

def track_summary(track):
    points=track["points"]
    return {"retained_points":len(points),"first_observed_epoch_utc":points[0][0],
            "latest_observed_epoch_utc":points[-1][0],"first_observed_hammer":points[0][1]/100,
            "latest_observed_hammer":points[-1][1]/100,
            "observed_hammer_change":(points[-1][1]-points[0][1])/100,
            "recent_points":[[p[0],p[1]/100] for p in (points if len(points)<=8 else points[:1]+points[-7:])],
            "display_is_sampled":len(points)>8}

def aggregate_tracks(tracks):
    rows=list(tracks)
    changes=[r["points"][-1][1]-r["points"][0][1] for r in rows if len(r["points"])>1]
    return {"distinct_lots":len(rows),"repeated_lots":len(changes),"increased":sum(v>0 for v in changes),
            "unchanged":sum(v==0 for v in changes),"decreased":sum(v<0 for v in changes),
            "median_observed_hammer_change":median(changes)/100 if changes else None}
