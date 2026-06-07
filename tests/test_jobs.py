import asyncio

import pytest

from app.jobs import JobCancelled, JobManager


@pytest.mark.asyncio
async def test_job_manager_cancels_active_user_job() -> None:
    manager = JobManager(1)
    started = asyncio.Event()

    async def work(context):
        started.set()
        await asyncio.sleep(0.01)
        context.check_cancelled()

    task = asyncio.create_task(manager.run(42, work))
    await started.wait()
    assert await manager.cancel(42)

    with pytest.raises(JobCancelled):
        await task
