from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .api.main import app
from .run_collect import collect_all
from .run_pipeline import run_pipeline

sched = AsyncIOScheduler(timezone="Asia/Shanghai")


async def harvest_job():
    try:
        stats = await collect_all()
        print(f"[job.collect] {stats}", flush=True)
    except Exception as e:
        print(f"[job.collect.err] {type(e).__name__}: {e}", flush=True)
    try:
        stats = await run_pipeline()
        print(f"[job.pipeline] {stats}", flush=True)
    except RuntimeError as e:
        print(f"[job.pipeline.skip] {e}", flush=True)
    except Exception as e:
        print(f"[job.pipeline.err] {type(e).__name__}: {e}", flush=True)


@app.on_event("startup")
async def _start_sched():
    sched.add_job(harvest_job, "interval", minutes=30, id="harvest", max_instances=1, coalesce=True)
    sched.start()


def run():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
