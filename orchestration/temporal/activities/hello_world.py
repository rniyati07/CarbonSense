from __future__ import annotations

from temporalio import activity

from orchestration.temporal.dto import HelloWorldInput, HelloWorldResult


@activity.defn
async def greet_activity(input: HelloWorldInput) -> HelloWorldResult:
    return HelloWorldResult(greeting=f"Hello, {input.name}!")
