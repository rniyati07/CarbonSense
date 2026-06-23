from __future__ import annotations

from datetime import timedelta

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from orchestration.temporal.activities.hello_world import greet_activity
    from orchestration.temporal.dto import HelloWorldInput, HelloWorldResult


@workflow.defn
class HelloWorldWorkflow:
    """Two-step workflow proving Temporal durability.

    Step 1: greet activity.
    Step 2: a second greet activity (so recovery tests can verify
    that step 1 is not re-executed after a worker restart).
    """

    @workflow.run
    async def run(self, input: HelloWorldInput) -> HelloWorldResult:
        first = await workflow.execute_activity(
            greet_activity,
            HelloWorldInput(name=f"{input.name}-step1"),
            start_to_close_timeout=timedelta(seconds=30),
        )
        second = await workflow.execute_activity(
            greet_activity,
            HelloWorldInput(name=f"{input.name}-step2"),
            start_to_close_timeout=timedelta(seconds=30),
        )
        return HelloWorldResult(greeting=f"{first.greeting} | {second.greeting}")
