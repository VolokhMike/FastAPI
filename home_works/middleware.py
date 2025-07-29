import time
import logging
from datetime import datetime
from uuid import uuid4
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

LOG_FORMAT = "%(trace_id)s - %(asctime)s - %(name)s - %(funcName)s - %(levelname)s - %(message)s"
LOG_LEVEL = logging.INFO

trace_id_var = {}

class TraceIdFilter(logging.Filter):
    def filter(self, record):
        record.trace_id = trace_id_var.get("trace_id", "no-trace")
        return True

logger = logging.getLogger("api_service_logger")
logger.setLevel(LOG_LEVEL)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter(LOG_FORMAT))
console_handler.addFilter(TraceIdFilter())
logger.addHandler(console_handler)

app = FastAPI()

@app.middleware("http")
async def add_trace_id(request: Request, call_next):
    trace_id = str(uuid4())
    trace_id_var["trace_id"] = trace_id
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response

@app.middleware("http")
async def log_and_check_header(request: Request, call_next):
    method = request.method
    url = request.url.path
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"Incoming request: {method} {url} at {now}")
    
    if "X-Auth-Token" not in request.headers:
        return JSONResponse(
            status_code=400,
            content={"detail": "Missing 'X-Auth-Token' in request headers."},
        )
    
    return await call_next(request)

@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    process_time = time.perf_counter() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.6f}"
    return response

@app.get("/api/secure-endpoint")
async def secure_endpoint():
    return {"message": "Authentication successful! Access granted to secure resource."}

@app.get("/api/public-endpoint")
async def public_endpoint():
    return {"message": "This endpoint should be protected by authentication middleware."}

if __name__ == "__main__":
    uvicorn.run("middleware:app", reload=True)