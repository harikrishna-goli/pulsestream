from fastapi import APIRouter, Response

router = APIRouter(tags=["Health & Metrics"])

@router.get("/healthz")
async def healthz():
    return {"status": "ok", "service": "PulseStream Event Engine"}

@router.get("/readyz")
async def readyz():
    return {"status": "ready", "database": "connected", "worker": "active"}

@router.get("/metrics")
async def metrics():
    # Prometheus plain-text exposition
    sample_metrics = """# HELP pulsestream_events_ingested_total Total events ingested
# TYPE pulsestream_events_ingested_total counter
pulsestream_events_ingested_total 42

# HELP pulsestream_request_duration_seconds Latency histogram
# TYPE pulsestream_request_duration_seconds histogram
pulsestream_request_duration_seconds_bucket{le="0.01"} 38
pulsestream_request_duration_seconds_bucket{le="0.05"} 41
pulsestream_request_duration_seconds_bucket{le="+Inf"} 42
"""
    return Response(content=sample_metrics, media_type="text/plain")
